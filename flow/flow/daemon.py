"""The daemon: hold a key, speak, release, and the right thing happens.

Two hotkeys, three behaviors:

  hotkey (hold)      — dictate: speak, release, polished text lands in the
                       frontmost app. A quick TAP instead of a hold locks
                       recording hands-free; tap again to stop.
  edit key (hold)    — edit: select text first, hold, say what to change
                       ("make that two sentences"), release; the selection
                       is replaced.

Every dictation routes through the shortcut engine before the polish pass:

  raw transcript -> whole-utterance command match (deterministic)
                 -> LLM paraphrase match (gated; flow.intent)
                 -> inline snippet expansion (deterministic splice)
                 -> polish -> paste

A matched command runs its block Plan (type text, open things, press keys)
instead of being typed as prose. Nothing about ordinary dictation changes
when no shortcut matches — the shortcut layer is invisible until invoked.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from . import config as config_mod
from .actions import run_plan
from .audio import Recorder
from .config import Config
from .context import Focus, HistoryStore, PrefStore, frontmost
from .insert import notify, paste, read_clipboard
from .intent import smart_match
from .language import ENGLISH, TargetStyle, decide
from .polish import polish
from .shortcuts import (
    Plan,
    RunContext,
    Shortcut,
    ShortcutStore,
    execute,
    expand_inline,
    find_command_match,
    uses_block,
)
from .style import profile
from .transcribe import TranscribeError, transcribe


@dataclass
class Snapshot:
    """Everything about the moment the user started talking."""

    focus: Focus | None
    preferred_script: str | None
    recent: list[str] = field(default_factory=list)

    @property
    def app(self) -> str | None:
        return self.focus.app if self.focus else None

    @property
    def contact(self) -> str | None:
        return self.focus.contact if self.focus else None


class Stores:
    def __init__(self, cfg: Config):
        base = config_mod.flow_dir()
        self.history = HistoryStore(base / "history.jsonl", limit=cfg.history_limit)
        self.prefs = PrefStore(base / "prefs.json")
        self.shortcuts = ShortcutStore(config_mod.shortcuts_dir())


def take_snapshot(cfg: Config, stores: Stores) -> Snapshot:
    focus = frontmost()
    preferred = None
    recent: list[str] = []
    if focus:
        preferred = stores.prefs.resolve(focus.app, focus.contact)
        recent = [
            e.get("text", "")
            for e in stores.history.recent(focus.app, focus.contact, n=cfg.context_recent)
            if e.get("text") and e.get("kind") != "shortcut"
        ]
    return Snapshot(focus=focus, preferred_script=preferred, recent=recent)


def run_pipeline(
    raw: str,
    snapshot: Snapshot,
    cfg: Config,
    stores: Stores,
    *,
    verbatim: list[str] | None = None,
    dry: bool = False,
) -> tuple[str, TargetStyle]:
    """Transcript -> final dictation text. The dictation leg of route()."""
    target = decide(
        raw,
        preferred_script=snapshot.preferred_script,
        policy=cfg.hindi_script_policy,
    )
    final = polish(
        raw,
        target,
        cfg,
        app=snapshot.app,
        contact=snapshot.contact,
        recent=snapshot.recent,
        style_hints=profile(snapshot.recent).hints(),
        verbatim=verbatim,
    )
    if final and not dry:
        stores.history.append(
            {
                "app": snapshot.app,
                "contact": snapshot.contact,
                "raw": raw,
                "text": final,
                "language": target.language,
                "script": target.hindi_script,
            }
        )
        if target.language != ENGLISH and target.hindi_script and snapshot.app:
            stores.prefs.record(snapshot.app, snapshot.contact, target.hindi_script)
    return final, target


@dataclass
class Routed:
    """What a transcript turned out to be, and what should happen."""

    kind: str                     # "command" | "dictation"
    final: str                    # text to type ("" when a command types nothing)
    target: TargetStyle | None    # set for dictation
    plan: Plan | None             # the command's Plan, or inline extra actions
    via: str = ""                 # deterministic | model, for command matches


def _run_context(shortcut: Shortcut, slots: dict, snapshot: Snapshot, stores: Stores) -> RunContext:
    """Context for one shortcut execution; expensive reads only when used."""
    clipboard = read_clipboard() if uses_block(shortcut.blocks, "clipboard") else ""
    last = ""
    if uses_block(shortcut.blocks, "last_dictation"):
        entries = [e for e in stores.history.entries() if e.get("kind") != "shortcut"]
        last = entries[-1].get("text", "") if entries else ""
    return RunContext(
        app=snapshot.app,
        contact=snapshot.contact,
        slots=slots,
        clipboard=clipboard,
        last_dictation=last,
    )


def route(
    raw: str,
    snapshot: Snapshot,
    cfg: Config,
    stores: Stores,
    *,
    shortcuts: list[Shortcut] | None = None,
    dry: bool = False,
) -> Routed:
    """Decide what a transcript is and produce the full outcome, executing nothing."""
    if shortcuts is None:
        shortcuts, problems = stores.shortcuts.load_all()
        for p in problems:
            notify(f"shortcut skipped: {p}")

    match = find_command_match(raw, shortcuts)
    if match is None:
        match = smart_match(raw, shortcuts, cfg)
    if match is not None:
        ctx = _run_context(match.shortcut, match.slots, snapshot, stores)
        plan = execute(match.shortcut, ctx)
        if not dry:
            stores.history.append(
                {
                    "app": snapshot.app,
                    "contact": snapshot.contact,
                    "raw": raw,
                    "kind": "shortcut",
                    "shortcut": match.shortcut.name,
                    "text": plan.text,
                }
            )
        return Routed("command", plan.text, None, plan, via=match.via)

    inline_ctx = RunContext(app=snapshot.app, contact=snapshot.contact)
    if any(sc.inline and sc.enabled and uses_block(sc.blocks, "clipboard") for sc in shortcuts):
        inline_ctx.clipboard = read_clipboard()
    expanded, extra_actions, expansions = expand_inline(raw, shortcuts, inline_ctx)

    final, target = run_pipeline(
        expanded, snapshot, cfg, stores, verbatim=expansions or None, dry=dry
    )
    plan = Plan(shortcut="inline", text="", actions=extra_actions) if extra_actions else None
    return Routed("dictation", final, target, plan)


class HoldOrLock:
    """Push-to-talk state machine: hold to talk, tap to lock, tap to stop.

    Pure logic with injected timestamps so it can be unit-tested. Returns the
    action the daemon should take: "start", "stop", "lock", or None.
    """

    IDLE, HELD, LOCKED, STOPPING = "idle", "held", "locked", "stopping"

    def __init__(self, tap_threshold: float = 0.35, tap_lock: bool = True):
        self.tap_threshold = tap_threshold
        self.tap_lock = tap_lock
        self.state = self.IDLE
        self._pressed_at: float | None = None

    def press(self, t: float) -> str | None:
        if self.state == self.IDLE:
            self.state = self.HELD
            self._pressed_at = t
            return "start"
        if self.state == self.LOCKED:
            self.state = self.STOPPING
            return "stop"
        return None  # key auto-repeat while held

    def release(self, t: float) -> str | None:
        if self.state == self.HELD:
            held_for = t - (self._pressed_at if self._pressed_at is not None else t)
            if self.tap_lock and held_for < self.tap_threshold:
                self.state = self.LOCKED
                return "lock"
            self.state = self.IDLE
            return "stop"
        if self.state == self.STOPPING:
            self.state = self.IDLE
        return None


def _parse_hotkey(name: str):
    from pynput import keyboard

    name = name.strip()
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    try:
        return getattr(keyboard.Key, name)
    except AttributeError as e:
        raise SystemExit(
            f"Unknown hotkey {name!r}. Use a pynput key name like alt_r, cmd_r, ctrl_r, f13."
        ) from e


def run(cfg: Config) -> None:
    import time as _time

    from pynput import keyboard

    hotkey = _parse_hotkey(cfg.hotkey)
    edit_key = _parse_hotkey(cfg.edit_hotkey) if cfg.edit_hotkey else None
    if edit_key == hotkey:
        edit_key = None

    stores = Stores(cfg)
    recorder = Recorder(cfg.sample_rate)
    ptt = HoldOrLock(cfg.tap_threshold, cfg.tap_lock)
    state_lock = threading.Lock()
    snapshot_holder: dict = {}
    edit_holder: dict = {}
    mode_holder = {"mode": None}  # "dictate" | "edit" while recording

    def start_recording(mode: str) -> bool:
        try:
            recorder.start()
        except Exception as e:  # no mic permission, no device, ...
            notify(f"mic error: {e}")
            return False
        mode_holder["mode"] = mode
        return True

    def grab_snapshot() -> None:
        snapshot_holder.pop("snap", None)  # never reuse the previous context

        def grab() -> None:
            snapshot_holder["snap"] = take_snapshot(cfg, stores)

        t = threading.Thread(target=grab, daemon=True)
        t.start()
        snapshot_holder["thread"] = t

    def current_snapshot() -> Snapshot:
        t = snapshot_holder.get("thread")
        if t is not None:
            t.join(timeout=3)
        return snapshot_holder.get("snap") or Snapshot(focus=None, preferred_script=None)

    def handle_dictation(wav: bytes, seconds: float, snapshot: Snapshot) -> None:
        if seconds < cfg.min_seconds:
            return
        try:
            transcript = transcribe(wav, cfg, preferred_script=snapshot.preferred_script)
        except TranscribeError as e:
            notify(str(e))
            return
        if not transcript.text:
            return
        routed = route(transcript.text, snapshot, cfg, stores)
        if routed.kind == "command":
            run_plan(routed.plan, cfg)
            print(f"[shortcut {routed.plan.shortcut} via {routed.via}] {routed.plan.describe()}")
            return
        if routed.final:
            paste(routed.final)
            if routed.plan:  # inline snippet side-effects
                run_plan(routed.plan, cfg)
            print(f"[{routed.target.describe()}] {routed.final}")

    def handle_edit(wav: bytes, seconds: float, selection: str, app: str | None) -> None:
        from .editmode import run_edit

        if seconds < cfg.min_seconds:
            return
        try:
            transcript = transcribe(wav, cfg)
        except TranscribeError as e:
            notify(str(e))
            return
        if not transcript.text:
            return
        if run_edit(selection, transcript.text, cfg, app):
            print(f"[edit] {transcript.text}")
        else:
            notify("edit didn't change anything")

    def stop_and_process() -> None:
        seconds = recorder.seconds
        wav = recorder.stop()
        mode = mode_holder["mode"]
        mode_holder["mode"] = None
        if mode == "edit":
            sel = edit_holder.pop("selection", None)
            app = edit_holder.pop("app", None)
            if sel:
                threading.Thread(
                    target=handle_edit, args=(wav, seconds, sel, app), daemon=True
                ).start()
            return
        snapshot = current_snapshot()
        threading.Thread(
            target=handle_dictation, args=(wav, seconds, snapshot), daemon=True
        ).start()

    def on_press(key) -> None:
        now = _time.monotonic()
        if key == hotkey:
            with state_lock:
                action = ptt.press(now)
                if action == "start":
                    if recorder.recording or not start_recording("dictate"):
                        ptt.state = HoldOrLock.IDLE
                        return
                    grab_snapshot()
                elif action == "stop":
                    if recorder.recording:
                        stop_and_process()
        elif edit_key is not None and key == edit_key:
            with state_lock:
                if recorder.recording:
                    return
                from .editmode import read_selection

                selection = read_selection()
                if not selection:
                    notify("select some text, then hold the edit key and speak")
                    return
                if not start_recording("edit"):
                    return
                focus = frontmost()
                edit_holder["selection"] = selection
                edit_holder["app"] = focus.app if focus else None

    def on_release(key) -> None:
        now = _time.monotonic()
        if key == hotkey:
            with state_lock:
                action = ptt.release(now)
                if action == "lock":
                    notify("listening — tap again to stop")
                elif action == "stop" and recorder.recording:
                    stop_and_process()
        elif edit_key is not None and key == edit_key:
            with state_lock:
                if recorder.recording and mode_holder["mode"] == "edit":
                    stop_and_process()

    if cfg.asr_is_local():
        from .local_asr import ensure_server

        if ensure_server(cfg):
            print("local ASR is up — audio stays on this machine.")
        else:
            notify("local ASR isn't ready — run `flow local setup`")

    extra = f", hold {cfg.edit_hotkey} on a selection to edit" if edit_key else ""
    print(f"flow is listening — hold {cfg.hotkey} to dictate (tap to lock){extra}, Ctrl-C to quit.")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()
