"""The daemon: hold the hotkey, speak, release, and the text appears.

Pipeline per dictation:

  key down  -> snapshot context (frontmost app, contact, learned script
               preference, recent dictations) + start recording
  key up    -> stop recording
  worker    -> ASR (primed with the preferred script and the user dictionary)
            -> language/script decision (deterministic, flow.language)
            -> polish pass (Claude) -> paste into the frontmost app
            -> remember: history log + script preference for this conversation
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from . import config as config_mod
from .audio import Recorder
from .config import Config
from .context import Focus, HistoryStore, PrefStore, frontmost
from .insert import notify, paste
from .language import ENGLISH, TargetStyle, decide
from .polish import polish
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


def take_snapshot(cfg: Config, stores: Stores) -> Snapshot:
    focus = frontmost()
    preferred = None
    recent: list[str] = []
    if focus:
        preferred = stores.prefs.resolve(focus.app, focus.contact)
        recent = [
            e.get("text", "")
            for e in stores.history.recent(focus.app, focus.contact, n=cfg.context_recent)
            if e.get("text")
        ]
    return Snapshot(focus=focus, preferred_script=preferred, recent=recent)


def run_pipeline(raw: str, snapshot: Snapshot, cfg: Config, stores: Stores) -> tuple[str, TargetStyle]:
    """Transcript -> final text. Shared by the daemon and the `flow text` CLI."""
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
    )
    if final:
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
    from pynput import keyboard

    hotkey = _parse_hotkey(cfg.hotkey)
    stores = Stores(cfg)
    recorder = Recorder(cfg.sample_rate)
    state_lock = threading.Lock()
    snapshot_holder: dict = {}

    def handle_audio(wav: bytes, seconds: float, snapshot: Snapshot) -> None:
        if seconds < cfg.min_seconds:
            return
        try:
            transcript = transcribe(wav, cfg, preferred_script=snapshot.preferred_script)
        except TranscribeError as e:
            notify(str(e))
            return
        if not transcript.text:
            return
        final, target = run_pipeline(transcript.text, snapshot, cfg, stores)
        if final:
            paste(final)
            print(f"[{target.describe()}] {final}")

    def on_press(key) -> None:
        if key != hotkey:
            return
        with state_lock:
            if recorder.recording:
                return
            try:
                recorder.start()
            except Exception as e:  # no mic permission, no device, ...
                notify(f"mic error: {e}")
                return
        # context lookup happens while you talk, off the hot path
        def grab() -> None:
            snapshot_holder["snap"] = take_snapshot(cfg, stores)

        t = threading.Thread(target=grab, daemon=True)
        t.start()
        snapshot_holder["thread"] = t

    def on_release(key) -> None:
        if key != hotkey:
            return
        with state_lock:
            if not recorder.recording:
                return
            seconds = recorder.seconds
            wav = recorder.stop()
        t = snapshot_holder.get("thread")
        if t is not None:
            t.join(timeout=3)
        snapshot = snapshot_holder.get("snap") or Snapshot(focus=None, preferred_script=None)
        threading.Thread(
            target=handle_audio, args=(wav, seconds, snapshot), daemon=True
        ).start()

    print(f"flow is listening — hold {cfg.hotkey} to dictate, Ctrl-C to quit.")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()
