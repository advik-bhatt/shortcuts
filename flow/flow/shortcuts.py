"""Smart shortcuts: the block language, the matcher, and the interpreter.

A shortcut is a small program the user assembles from Scratch-style blocks
(in the visual editor, `flow blocks`) or writes as JSON by hand. It fires
from SPEECH: say the trigger phrase — or something close enough — and the
blocks run: text is composed and typed, URLs open, keys are pressed.

Design laws, in priority order:

1. **Never misfire on ordinary dictation.** A command shortcut fires only
   when the WHOLE utterance matches its trigger (after normalization), so
   "email Sam about the launch" fires, while "I should email Sam about the
   launch when I land" is just dictation. Inline snippets expand only when
   marked `inline` and only on an exact phrase span.
2. **Deterministic first.** This module decides everything it can without a
   model, and is dependency-free and unit-tested. The LLM assist
   (flow.intent) runs only when this layer found nothing, only on
   command-shaped utterances, and its answer is re-validated here before
   anything executes.
3. **The user authored every word.** Blocks compose text the user wrote
   (templates) or spoke (slots). No block generates content on its own —
   flow types for you; it never talks for you.

Trigger phrases support slots and optional words:

    "email <person> about <topic>"      slots capture the spoken words
    "open (the) calendar"               parenthesized words are optional

In a command trigger the final slot is greedy (it takes the rest of the
utterance); earlier slots are lazy, so multi-slot phrases split where the
literal words sit. Inline snippet slots are always lazy — they grab as few
words as possible so an expansion never eats the rest of the sentence.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Words dropped from BOTH the utterance and the trigger during command
# matching, so "um, please email Sam about the launch" still hits
# "email <person> about <topic>". Kept tiny and closed-class: a bigger list
# would eat real words.
FILLERS = frozenset("um uh umm uhh hmm please pls kindly hey ok okay so".split())

_ANY_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
_SLOT = re.compile(r"<([a-zA-Z_][a-zA-Z0-9_]*)>")
_OPTIONAL = re.compile(r"\(([^()<>]+)\)")
_TEMPLATE_REF = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_PHRASE_TOKEN = re.compile(r"<[a-zA-Z_][a-zA-Z0-9_]*>|\([^()<>]+\)|[^\W_]+(?:'[^\W_]+)?")

CONDITION_KINDS = ("app", "contact", "hour_before", "hour_after", "weekday", "slot_present")
TRANSFORM_OPS = ("upper", "lower", "title", "sentence", "trim")
BLOCK_TYPES = (
    "text", "slot", "date", "time", "clipboard", "last_dictation",
    "if", "transform", "open_url", "open_app", "keys", "shell", "pause",
)
# Side-effect blocks; everything else composes text.
ACTION_TYPES = ("open_url", "open_app", "keys", "shell", "pause")


def normalize_words(text: str, *, drop_fillers: bool = True) -> list[str]:
    """Utterance -> lowercase word list, punctuation gone, fillers optional."""
    words = [w.lower() for w in _ANY_WORD.findall(text)]
    if drop_fillers:
        words = [w for w in words if w not in FILLERS]
    return words


def _parse_phrase(phrase: str) -> list[tuple]:
    """Phrase -> ordered parts: ("WORD", w) | ("SLOT", name) | ("OPT", [words])."""
    parts: list[tuple] = []
    for tok in _PHRASE_TOKEN.findall(phrase):
        slot_m = _SLOT.fullmatch(tok)
        opt_m = _OPTIONAL.fullmatch(tok)
        if slot_m:
            parts.append(("SLOT", slot_m.group(1)))
        elif opt_m:
            inner = [w.lower() for w in _ANY_WORD.findall(opt_m.group(1)) if w.lower() not in FILLERS]
            if inner:
                parts.append(("OPT", inner))
        else:
            word = tok.lower()
            if word not in FILLERS:
                parts.append(("WORD", word))
    return parts


def _render_pattern(parts: list[tuple], *, sep: str, word_rx: str, greedy_last_slot: bool) -> str:
    """Build one regex from phrase parts.

    sep — what separates words in the text being matched (" " for the
    normalized form, r"\\W+" for raw text). word_rx — what one word looks
    like there. The final slot may be greedy (command triggers) so trailing
    content lands in it; every other slot is lazy.
    """
    last_slot = max((i for i, p in enumerate(parts) if p[0] == "SLOT"), default=-1)
    rx: list[str] = []
    first = True
    for i, part in enumerate(parts):
        kind = part[0]
        if kind == "OPT":
            inner = sep.join(re.escape(w) for w in part[1])
            if first:
                rx.append(f"(?:{inner}{sep})?")
            else:
                rx.append(f"(?:{sep}{inner})?")
            continue  # optional: carries its own separator, doesn't end "first"
        piece: str
        if kind == "SLOT":
            greedy = greedy_last_slot and i == last_slot
            tail = f"(?:{sep}{word_rx})*" + ("" if greedy else "?")
            piece = f"(?P<{part[1]}>{word_rx}{tail})"
        else:
            piece = re.escape(part[1])
        if not first:
            rx.append(sep)
        rx.append(piece)
        first = False
    return "".join(rx)


@dataclass
class Trigger:
    """One trigger phrase, compiled two ways: command form and inline form."""

    phrase: str
    slots: list[str]
    command_rx: re.Pattern  # fullmatch over the normalized utterance
    inline_rx: re.Pattern   # search over the raw text, punctuation-tolerant

    @classmethod
    def compile(cls, phrase: str) -> "Trigger":
        parts = _parse_phrase(phrase)
        if not parts:
            raise ValueError(f"trigger {phrase!r} has no matchable words")
        slots = [p[1] for p in parts if p[0] == "SLOT"]
        if len(set(slots)) != len(slots):
            raise ValueError(f"trigger {phrase!r} repeats a slot name")
        command = _render_pattern(parts, sep=" ", word_rx=r"\S+", greedy_last_slot=True)
        inline = r"\b" + _render_pattern(parts, sep=r"[^\w']+", word_rx=r"[\w']+", greedy_last_slot=False) + r"\b"
        return cls(
            phrase=phrase,
            slots=slots,
            command_rx=re.compile(command),
            inline_rx=re.compile(inline, re.IGNORECASE),
        )

    def match_command(self, utterance: str) -> dict | None:
        """Whole-utterance match on the normalized form. {slot: words} or None."""
        normalized = " ".join(normalize_words(utterance))
        if not normalized:
            return None
        m = self.command_rx.fullmatch(normalized)
        if not m:
            return None
        return {name: m.group(name).strip() for name in self.slots}

    def match_inline(self, raw: str) -> tuple[dict, tuple[int, int]] | None:
        """Search the RAW text; returns (slots, char span) so the caller can splice."""
        m = self.inline_rx.search(raw)
        if not m:
            return None
        return {name: m.group(name).strip() for name in self.slots}, (m.start(), m.end())


@dataclass
class Shortcut:
    """One user-defined shortcut: triggers plus a block program."""

    name: str
    triggers: list[Trigger]
    blocks: list[dict]
    inline: bool = False       # expand inside dictation instead of replacing it
    enabled: bool = True
    description: str = ""
    path: Path | None = None   # where it lives on disk, when loaded from a file

    @classmethod
    def from_dict(cls, data: dict, path: Path | None = None) -> "Shortcut":
        problems = validate(data)
        if problems:
            raise ValueError(f"invalid shortcut {data.get('name', '?')!r}: " + "; ".join(problems))
        phrases = data["trigger"]["phrases"]
        return cls(
            name=data["name"],
            triggers=[Trigger.compile(p) for p in phrases],
            blocks=data["blocks"],
            inline=bool(data.get("inline", False)),
            enabled=bool(data.get("enabled", True)),
            description=data.get("description", ""),
            path=path,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "inline": self.inline,
            "trigger": {"phrases": [t.phrase for t in self.triggers]},
            "blocks": self.blocks,
        }


def validate(data) -> list[str]:
    """Structural validation with human-readable problems; [] when valid."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["shortcut must be a JSON object"]
    if not data.get("name") or not isinstance(data.get("name"), str):
        problems.append("missing name")
    trig = data.get("trigger")
    if not isinstance(trig, dict) or not isinstance(trig.get("phrases"), list) or not trig.get("phrases"):
        problems.append("trigger.phrases must be a non-empty list")
    else:
        for p in trig["phrases"]:
            if not isinstance(p, str):
                problems.append(f"trigger phrase must be a string: {p!r}")
                continue
            try:
                Trigger.compile(p)
            except (ValueError, re.error) as e:
                problems.append(str(e))
                continue
            # A phrase whose only guaranteed words are slots would fire on
            # anything: require at least one literal, non-optional, non-filler word.
            literal = _SLOT.sub(" ", _OPTIONAL.sub(" ", p))
            if _SLOT.search(p) and not normalize_words(literal):
                problems.append(f"trigger {p!r} needs at least one literal word beside its slots")
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        problems.append("blocks must be a non-empty list")
    else:
        problems.extend(_validate_blocks(blocks))
    return problems


def _validate_blocks(blocks: list, depth: int = 0) -> list[str]:
    problems: list[str] = []
    if depth > 8:
        return ["blocks nested deeper than 8 levels"]
    for b in blocks:
        if not isinstance(b, dict) or b.get("type") not in BLOCK_TYPES:
            problems.append(f"unknown block: {b!r}")
            continue
        t = b["type"]
        if t == "text" and not isinstance(b.get("value"), str):
            problems.append("text block needs a string value")
        if t == "slot" and not b.get("name"):
            problems.append("slot block needs a name")
        if t == "transform":
            if b.get("op") not in TRANSFORM_OPS:
                problems.append(f"transform op must be one of {TRANSFORM_OPS}")
            problems.extend(_validate_blocks(b.get("children") or [], depth + 1))
        if t == "if":
            cond = b.get("cond") or {}
            if cond.get("kind") not in CONDITION_KINDS:
                problems.append(f"if condition kind must be one of {CONDITION_KINDS}")
            problems.extend(_validate_blocks(b.get("then") or [], depth + 1))
            problems.extend(_validate_blocks(b.get("else") or [], depth + 1))
        if t == "open_url" and not b.get("url"):
            problems.append("open_url block needs a url")
        if t == "open_app" and not b.get("app"):
            problems.append("open_app block needs an app")
        if t == "keys" and not b.get("combo"):
            problems.append("keys block needs a combo like cmd+shift+4")
        if t == "shell" and not b.get("cmd"):
            problems.append("shell block needs a cmd")
        if t == "pause" and not isinstance(b.get("seconds"), (int, float)):
            problems.append("pause block needs numeric seconds")
    return problems


@dataclass
class RunContext:
    """Everything the interpreter may read. All optional; blocks degrade to ''."""

    app: str | None = None
    contact: str | None = None
    slots: dict = field(default_factory=dict)
    clipboard: str = ""
    last_dictation: str = ""
    now: _dt.datetime | None = None  # injectable for tests

    def moment(self) -> _dt.datetime:
        return self.now or _dt.datetime.now()


@dataclass
class Plan:
    """What executing a shortcut should do. Pure data; flow.actions runs it."""

    shortcut: str
    text: str                      # composed text to type ('' if none)
    actions: list[dict] = field(default_factory=list)
    slots: dict = field(default_factory=dict)

    @property
    def has_effects(self) -> bool:
        return bool(self.text) or bool(self.actions)

    def describe(self) -> str:
        bits = []
        if self.text:
            preview = self.text if len(self.text) <= 60 else self.text[:57] + "..."
            bits.append(f"type {preview!r}")
        for a in self.actions:
            label = {
                "open_url": lambda a: f"open {a['url']}",
                "open_app": lambda a: f"launch {a['app']}",
                "keys": lambda a: f"press {a['combo']}",
                "shell": lambda a: f"run `{a['cmd']}`",
                "pause": lambda a: f"wait {a['seconds']}s",
            }[a["type"]](a)
            bits.append(label)
        return "; ".join(bits) or "(nothing)"


def _apply_transform(op: str, text: str) -> str:
    if op == "upper":
        return text.upper()
    if op == "lower":
        return text.lower()
    if op == "title":
        return text.title()
    if op == "sentence":
        stripped = text.strip()
        return stripped[:1].upper() + stripped[1:] if stripped else stripped
    if op == "trim":
        return text.strip()
    return text


def _check_condition(cond: dict, ctx: RunContext) -> bool:
    kind = cond.get("kind")
    value = str(cond.get("value", ""))
    if kind == "app":
        return bool(ctx.app) and value.lower() in ctx.app.lower()
    if kind == "contact":
        return bool(ctx.contact) and value.lower() in ctx.contact.lower()
    if kind == "hour_before":
        return ctx.moment().hour < int(value or 0)
    if kind == "hour_after":
        return ctx.moment().hour >= int(value or 0)
    if kind == "weekday":
        # value: "mon tue ..." — any-of, case-insensitive
        days = {d[:3].lower() for d in value.split()}
        return ctx.moment().strftime("%a").lower() in days
    if kind == "slot_present":
        return bool(ctx.slots.get(value, "").strip())
    return False


def _fill_template(template: str, ctx: RunContext) -> str:
    """Substitute {slot} references in urls/commands with captured words."""
    return _TEMPLATE_REF.sub(lambda m: ctx.slots.get(m.group(1), ""), template)


# A safe strftime subset: portable across macOS/Linux, no locale surprises.
_DATE_FORMATS = {
    "long": "%A, %B %d",        # Sunday, August 02
    "iso": "%Y-%m-%d",
    "short": "%b %d",
    "day": "%A",
}
_TIME_FORMATS = {
    "12h": "%I:%M %p",
    "24h": "%H:%M",
}


def execute(shortcut: Shortcut, ctx: RunContext) -> Plan:
    """Run the block program. Pure: returns a Plan, performs nothing."""
    actions: list[dict] = []

    def walk(blocks: list[dict]) -> str:
        local: list[str] = []
        for b in blocks:
            t = b["type"]
            if t == "text":
                local.append(b["value"])
            elif t == "slot":
                local.append(ctx.slots.get(b["name"], b.get("fallback", "")))
            elif t == "date":
                fmt = _DATE_FORMATS.get(b.get("format", "long"), _DATE_FORMATS["long"])
                local.append(ctx.moment().strftime(fmt).replace(" 0", " "))
            elif t == "time":
                fmt = _TIME_FORMATS.get(b.get("format", "12h"), _TIME_FORMATS["12h"])
                local.append(ctx.moment().strftime(fmt).lstrip("0"))
            elif t == "clipboard":
                local.append(ctx.clipboard)
            elif t == "last_dictation":
                local.append(ctx.last_dictation)
            elif t == "transform":
                local.append(_apply_transform(b["op"], walk(b.get("children") or [])))
            elif t == "if":
                branch = b.get("then") if _check_condition(b.get("cond") or {}, ctx) else b.get("else")
                local.append(walk(branch or []))
            elif t == "open_url":
                actions.append({"type": "open_url", "url": _fill_template(b["url"], ctx)})
            elif t == "open_app":
                actions.append({"type": "open_app", "app": b["app"]})
            elif t == "keys":
                actions.append({"type": "keys", "combo": b["combo"]})
            elif t == "shell":
                actions.append({"type": "shell", "cmd": _fill_template(b["cmd"], ctx)})
            elif t == "pause":
                actions.append({"type": "pause", "seconds": float(b["seconds"])})
        return "".join(local)

    text = walk(shortcut.blocks)
    return Plan(shortcut=shortcut.name, text=text, actions=actions, slots=dict(ctx.slots))


class ShortcutStore:
    """Shortcuts on disk: one JSON file each under ~/.flow/shortcuts/."""

    def __init__(self, directory: Path):
        self.directory = directory

    def load_all(self) -> tuple[list[Shortcut], list[str]]:
        """All valid shortcuts, plus human-readable problems for broken files."""
        shortcuts: list[Shortcut] = []
        problems: list[str] = []
        if not self.directory.exists():
            return shortcuts, problems
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                shortcuts.append(Shortcut.from_dict(data, path=path))
            except (json.JSONDecodeError, ValueError, OSError) as e:
                problems.append(f"{path.name}: {e}")
        return shortcuts, problems

    def save(self, data: dict) -> Path:
        problems = validate(data)
        if problems:
            raise ValueError("; ".join(problems))
        self.directory.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-") or "shortcut"
        path = self.directory / f"{slug}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path

    def delete(self, name: str) -> bool:
        for sc in self.load_all()[0]:
            if sc.name == name and sc.path:
                sc.path.unlink(missing_ok=True)
                return True
        return False


@dataclass
class MatchResult:
    shortcut: Shortcut
    slots: dict
    span: tuple[int, int] | None = None  # raw-text span, set for inline matches
    via: str = "deterministic"


def find_command_match(utterance: str, shortcuts: list[Shortcut]) -> MatchResult | None:
    """Whole-utterance command match. Most specific trigger wins.

    Sorting by literal word count (descending) makes the most specific
    trigger win when several could match — "email <person> about <topic>"
    beats "email <person>".
    """
    candidates: list[tuple[int, Shortcut, Trigger]] = []
    for sc in shortcuts:
        if not sc.enabled or sc.inline:
            continue
        for trig in sc.triggers:
            specificity = len([p for p in _parse_phrase(trig.phrase) if p[0] == "WORD"])
            candidates.append((specificity, sc, trig))
    for _, sc, trig in sorted(candidates, key=lambda c: -c[0]):
        hit = trig.match_command(utterance)
        if hit is not None:
            return MatchResult(shortcut=sc, slots=hit)
    return None


def find_inline_matches(raw: str, shortcuts: list[Shortcut]) -> list[MatchResult]:
    """Inline snippet hits inside a dictation, non-overlapping, left to right."""
    hits: list[MatchResult] = []
    taken: list[tuple[int, int]] = []
    for sc in shortcuts:
        if not sc.enabled or not sc.inline:
            continue
        for trig in sc.triggers:
            got = trig.match_inline(raw)
            if got is None:
                continue
            slots, span = got
            if any(not (span[1] <= s or span[0] >= e) for s, e in taken):
                continue
            taken.append(span)
            hits.append(MatchResult(shortcut=sc, slots=slots, span=span))
            break
    return sorted(hits, key=lambda h: h.span or (0, 0))


def expand_inline(
    raw: str, shortcuts: list[Shortcut], ctx: RunContext
) -> tuple[str, list[dict], list[str]]:
    """Replace inline snippet spans in the raw transcript with their expansions.

    Returns (new_text, actions, expansion_texts). Deterministic splice on the
    raw text — the polish pass runs afterwards and is told to keep each
    expansion text verbatim.
    """
    matches = find_inline_matches(raw, shortcuts)
    if not matches:
        return raw, [], []
    out: list[str] = []
    actions: list[dict] = []
    expansions: list[str] = []
    cursor = 0
    for m in matches:
        span = m.span or (0, 0)
        run_ctx = RunContext(
            app=ctx.app, contact=ctx.contact, slots=m.slots,
            clipboard=ctx.clipboard, last_dictation=ctx.last_dictation, now=ctx.now,
        )
        plan = execute(m.shortcut, run_ctx)
        out.append(raw[cursor:span[0]])
        out.append(plan.text)
        actions.extend(plan.actions)
        if plan.text:
            expansions.append(plan.text)
        cursor = span[1]
    out.append(raw[cursor:])
    return "".join(out), actions, expansions


def uses_block(blocks: list[dict], block_type: str) -> bool:
    """Does this block program contain a block of the given type anywhere?"""
    for b in blocks:
        if b.get("type") == block_type:
            return True
        for key in ("children", "then", "else"):
            if b.get(key) and uses_block(b[key], block_type):
                return True
    return False


def command_shaped(utterance: str, max_words: int = 12) -> bool:
    """Cheap gate for the LLM assist: short utterances only."""
    words = normalize_words(utterance)
    return 0 < len(words) <= max_words
