"""The LLM assist for shortcut matching: say roughly the thing, it still fires.

The deterministic matcher (flow.shortcuts) requires the trigger words. This
layer catches the paraphrase — "shoot an email over to Sam re the launch"
firing "email <person> about <topic>" — under three hard gates:

1. It only runs when the deterministic matcher found NOTHING.
2. It only runs on command-shaped utterances that share at least one literal
   trigger word with some shortcut (mode "conservative", the default; mode
   "eager" drops the shared-word gate; "off" disables the layer).
3. Its answer is re-validated here — the named shortcut must exist and the
   slots must be that shortcut's slots — and anything below the confidence
   floor falls through to ordinary dictation.

A wrong expansion is worse than no expansion: every gate fails CLOSED into
plain dictation, which is always a correct outcome.
"""

from __future__ import annotations

import json

from . import llm
from .config import Config
from .shortcuts import (
    MatchResult,
    Shortcut,
    _parse_phrase,
    command_shaped,
    normalize_words,
)

CONFIDENCE_FLOOR = 0.8

# Words too common to indicate a shortcut is being invoked. The conservative
# gate ignores these when checking whether an utterance shares vocabulary
# with any trigger — otherwise a trigger like "open (the) calendar" would
# send every sentence containing "the" to the model.
_STOPWORDS = frozenset(
    "a an the to of for in on at with and or but my your his her their me you it is are was be this that".split()
)

SYSTEM_PROMPT = """You route spoken utterances inside a dictation tool. You receive the user's utterance and a list of their voice shortcuts (name, trigger phrases, slot names). Decide whether the utterance IS an invocation of exactly one shortcut — same intent as a trigger phrase, allowing paraphrase — or is ordinary dictation.

Output ONLY a JSON object, no prose:
{"shortcut": "<name>" | null, "slots": {"<slot>": "<spoken words>"}, "confidence": 0.0-1.0}

Rules:
- null unless the WHOLE utterance is the invocation. If the utterance contains the command plus other content to type, it is dictation: return null.
- Slot values must be words the user actually spoke (case may be normalized). Never invent slot content.
- confidence is your honest probability that the user meant to invoke this shortcut. When torn, go lower: a missed shortcut costs one retry, a false fire types the wrong thing."""


def _vocabulary(shortcuts: list[Shortcut]) -> set[str]:
    words: set[str] = set()
    for sc in shortcuts:
        for trig in sc.triggers:
            for kind, val in _parse_phrase(trig.phrase):
                if kind == "WORD":
                    words.add(val)
                elif kind == "OPT":
                    words.update(val)
    return words


def gate(utterance: str, shortcuts: list[Shortcut], mode: str) -> bool:
    """Should the LLM assist run at all for this utterance?"""
    if mode == "off" or not shortcuts:
        return False
    if not command_shaped(utterance):
        return False
    if mode == "eager":
        return True
    # conservative: the utterance must share a meaningful literal trigger word
    vocabulary = _vocabulary(shortcuts) - _STOPWORDS
    return bool(set(normalize_words(utterance)) & vocabulary)


def _catalog(shortcuts: list[Shortcut]) -> str:
    entries = []
    for sc in shortcuts:
        entries.append(
            {
                "name": sc.name,
                "phrases": [t.phrase for t in sc.triggers],
                "slots": sorted({s for t in sc.triggers for s in t.slots}),
                "description": sc.description or None,
            }
        )
    return json.dumps(entries, ensure_ascii=False)


def smart_match(utterance: str, shortcuts: list[Shortcut], cfg: Config) -> MatchResult | None:
    """LLM paraphrase match. None unless confident and re-validated."""
    active = [sc for sc in shortcuts if sc.enabled and not sc.inline]
    if not gate(utterance, active, cfg.smart_match):
        return None

    user = (
        "<shortcuts>\n" + _catalog(active) + "\n</shortcuts>\n"
        "<utterance>\n" + utterance.strip() + "\n</utterance>"
    )
    raw = llm.complete(SYSTEM_PROMPT, user, cfg, max_tokens=300)
    if not raw:
        return None
    try:
        # tolerate a fenced or prefixed reply, then parse strictly
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start : end + 1])
    except (ValueError, json.JSONDecodeError):
        return None

    name = data.get("shortcut")
    if not name:
        return None
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if confidence < CONFIDENCE_FLOOR:
        return None
    target = next((sc for sc in active if sc.name == name), None)
    if target is None:
        return None
    allowed = {s for t in target.triggers for s in t.slots}
    slots_in = data.get("slots") or {}
    if not isinstance(slots_in, dict):
        return None
    slots = {
        k: str(v).strip()
        for k, v in slots_in.items()
        if k in allowed and isinstance(v, (str, int, float)) and str(v).strip()
    }
    return MatchResult(shortcut=target, slots=slots, via="model")
