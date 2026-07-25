"""CLI: `flow` runs the daemon; subcommands exercise the pipeline directly."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, config as config_mod
from .config import load
from .language import decide


def _cmd_run(args) -> int:
    from .daemon import run

    run(load())
    return 0


def _cmd_text(args) -> int:
    """Run the language decision + polish pass on a typed transcript (no audio)."""
    from .daemon import Snapshot, Stores, run_pipeline
    from .context import Focus, contact_from_window

    cfg = load()
    stores = Stores(cfg)
    focus = None
    if args.app:
        focus = Focus(
            app=args.app,
            window=args.contact or "",
            contact=args.contact or contact_from_window(args.app, args.contact or ""),
        )
    preferred = stores.prefs.resolve(args.app, args.contact) if args.app else None
    snapshot = Snapshot(focus=focus, preferred_script=preferred)
    final, target = run_pipeline(args.transcript, snapshot, cfg, stores)
    print(f"target: {target.describe()}  (via {target.source})", file=sys.stderr)
    print(final)
    return 0


def _cmd_wav(args) -> int:
    from .daemon import Snapshot, Stores, run_pipeline
    from .transcribe import transcribe

    cfg = load()
    wav = Path(args.path).read_bytes()
    transcript = transcribe(wav, cfg)
    print(f"transcript: {transcript.text}", file=sys.stderr)
    snapshot = Snapshot(focus=None, preferred_script=None)
    final, target = run_pipeline(transcript.text, snapshot, cfg, Stores(cfg))
    print(f"target: {target.describe()}", file=sys.stderr)
    print(final)
    return 0


def _cmd_decide(args) -> int:
    target = decide(args.transcript)
    print(json.dumps(target.__dict__, ensure_ascii=False))
    return 0


def _cmd_history(args) -> int:
    from .context import HistoryStore

    store = HistoryStore(config_mod.flow_dir() / "history.jsonl")
    for e in store.recent(n=args.n):
        where = e.get("app") or "?"
        who = f" -> {e['contact']}" if e.get("contact") else ""
        print(f"[{where}{who}] {e.get('text', '')}")
    return 0


def _cmd_doctor(args) -> int:
    cfg = load()
    ok = True

    def check(label: str, good: bool, hint: str = "") -> None:
        nonlocal ok
        mark = "ok " if good else "MISSING"
        print(f"{mark:8} {label}" + (f"  — {hint}" if (hint and not good) else ""))
        ok = ok and good

    check("python 3.10+", sys.version_info >= (3, 10))
    check(
        "ASR key (Groq or OpenAI)",
        bool(cfg.asr_api_key),
        "export GROQ_API_KEY=... (console.groq.com, free tier works)",
    )
    check(
        "ANTHROPIC_API_KEY (polish pass)",
        bool(os.environ.get("ANTHROPIC_API_KEY")),
        "without it flow falls back to basic cleanup",
    )
    for mod, hint in [
        ("sounddevice", "pip install sounddevice  (brew install portaudio first)"),
        ("pynput", "pip install pynput"),
        ("requests", "pip install requests"),
        ("anthropic", "pip install anthropic"),
    ]:
        try:
            __import__(mod)
            check(f"module {mod}", True)
        except Exception:
            check(f"module {mod}", False, hint)
    if sys.platform == "darwin":
        print(
            "\nmacOS permissions (System Settings -> Privacy & Security):\n"
            "  Microphone, Accessibility, and Input Monitoring for your terminal app."
        )
    else:
        print("\nnote: not macOS — capture/paste are stubbed, pipeline commands still work.")
    print(f"\nconfig dir: {config_mod.flow_dir()}")
    print(f"ASR: {cfg.asr_model or 'unset'} @ {cfg.asr_base_url or 'unset'}")
    print(f"polish model: {cfg.polish_model}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flow", description=__doc__)
    parser.add_argument("--version", action="version", version=f"flow {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="start the push-to-talk daemon (default)")

    p_text = sub.add_parser("text", help="run the pipeline on a typed transcript")
    p_text.add_argument("transcript")
    p_text.add_argument("--app", default=None)
    p_text.add_argument("--contact", default=None)

    p_wav = sub.add_parser("wav", help="transcribe + polish an audio file")
    p_wav.add_argument("path")

    p_decide = sub.add_parser("decide", help="show the language/script decision only")
    p_decide.add_argument("transcript")

    p_hist = sub.add_parser("history", help="show recent dictations")
    p_hist.add_argument("-n", type=int, default=10)

    sub.add_parser("doctor", help="check keys, deps, and permissions")

    args = parser.parse_args(argv)
    handlers = {
        None: _cmd_run,
        "run": _cmd_run,
        "text": _cmd_text,
        "wav": _cmd_wav,
        "decide": _cmd_decide,
        "history": _cmd_history,
        "doctor": _cmd_doctor,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
