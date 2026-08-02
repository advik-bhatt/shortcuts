"""CLI: `flow` runs the daemon; subcommands exercise every layer directly."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, config as config_mod
from .config import load
from .language import decide


def _snapshot_for(args, cfg, stores):
    from .context import Focus, contact_from_window
    from .daemon import Snapshot

    focus = None
    app = getattr(args, "app", None)
    contact = getattr(args, "contact", None)
    if app:
        focus = Focus(
            app=app,
            window=contact or "",
            contact=contact or contact_from_window(app, contact or ""),
        )
    preferred = stores.prefs.resolve(app, contact) if app else None
    return Snapshot(focus=focus, preferred_script=preferred)


def _print_routed(routed) -> None:
    if routed.kind == "command":
        print(f"shortcut: {routed.plan.shortcut}  (via {routed.via})", file=sys.stderr)
        if routed.plan.slots:
            print(f"slots: {json.dumps(routed.plan.slots, ensure_ascii=False)}", file=sys.stderr)
        print(f"would: {routed.plan.describe()}", file=sys.stderr)
        if routed.plan.text:
            print(routed.plan.text)
    else:
        print(f"target: {routed.target.describe()}  (via {routed.target.source})", file=sys.stderr)
        if routed.plan:
            print(f"inline actions: {routed.plan.actions}", file=sys.stderr)
        print(routed.final)


def _cmd_run(args) -> int:
    from .daemon import run

    run(load())
    return 0


def _cmd_text(args) -> int:
    """Run the full routing (shortcuts + polish) on a typed transcript."""
    from .daemon import Stores, route

    cfg = load()
    stores = Stores(cfg)
    routed = route(args.transcript, _snapshot_for(args, cfg, stores), cfg, stores)
    _print_routed(routed)
    return 0


def _cmd_try(args) -> int:
    """Like `text` but a dry run: no history writes, nothing executed."""
    from .daemon import Stores, route

    cfg = load()
    stores = Stores(cfg)
    routed = route(args.utterance, _snapshot_for(args, cfg, stores), cfg, stores, dry=True)
    _print_routed(routed)
    return 0


def _cmd_wav(args) -> int:
    from .daemon import Stores, route
    from .transcribe import transcribe

    cfg = load()
    wav = Path(args.path).read_bytes()
    transcript = transcribe(wav, cfg)
    print(f"transcript: {transcript.text}", file=sys.stderr)
    stores = Stores(cfg)
    routed = route(transcript.text, _snapshot_for(args, cfg, stores), cfg, stores)
    _print_routed(routed)
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
        kind = " [shortcut]" if e.get("kind") == "shortcut" else ""
        print(f"[{where}{who}]{kind} {e.get('text', '')}")
    return 0


def _cmd_blocks(args) -> int:
    from .editor import serve

    cfg = load()
    if args.port:
        cfg.editor_port = args.port
    serve(cfg, open_browser=not args.no_open)
    return 0


def _cmd_shortcuts(args) -> int:
    from .shortcuts import ShortcutStore

    store = ShortcutStore(config_mod.shortcuts_dir())
    shortcuts, problems = store.load_all()
    if not shortcuts and not problems:
        print("no shortcuts yet — run `flow blocks` to build one")
        return 0
    for sc in shortcuts:
        mode = "inline" if sc.inline else "command"
        state = "" if sc.enabled else "  (disabled)"
        print(f"{sc.name}  [{mode}]{state}")
        for t in sc.triggers:
            print(f'    "{t.phrase}"')
    for p in problems:
        print(f"BROKEN  {p}", file=sys.stderr)
    return 1 if problems else 0


def _cmd_local(args) -> int:
    from . import local_asr

    cfg = load()
    if args.action == "setup":
        return local_asr.setup(cfg)
    # status
    print(f"mode: {cfg.asr_mode}" + ("  (active)" if cfg.asr_is_local() else ""))
    print(f"binary: {local_asr.binary() or 'MISSING — brew install whisper-cpp'}")
    mp = local_asr.model_path(cfg.local_asr_model)
    print(f"model: {mp}" + ("" if mp.exists() else "  MISSING — flow local setup"))
    up = local_asr.server_running(cfg.local_asr_port)
    print(f"server: {'up' if up else 'down'} (port {cfg.local_asr_port})")
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
    if cfg.asr_is_local():
        from . import local_asr

        check("whisper-server (local ASR)", bool(local_asr.binary()), "brew install whisper-cpp")
        check(
            f"local model {cfg.local_asr_model}",
            local_asr.model_path(cfg.local_asr_model).exists(),
            "flow local setup",
        )
    else:
        check(
            "ASR key (Groq or OpenAI)",
            bool(cfg.asr_api_key),
            "export GROQ_API_KEY=... (console.groq.com), or `flow local setup` for the $0 local mode",
        )
    check(
        "ANTHROPIC_API_KEY (polish + smart shortcuts + edit mode)",
        bool(os.environ.get("ANTHROPIC_API_KEY")),
        "without it: basic cleanup, exact-phrase shortcuts only, no edit mode",
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

    from .shortcuts import ShortcutStore

    shortcuts, problems = ShortcutStore(config_mod.shortcuts_dir()).load_all()
    check(f"shortcuts ({len(shortcuts)} loaded)", not problems, "; ".join(problems))

    if sys.platform == "darwin":
        print(
            "\nmacOS permissions (System Settings -> Privacy & Security):\n"
            "  Microphone, Accessibility, and Input Monitoring for your terminal app."
        )
    else:
        print("\nnote: not macOS — capture/paste are stubbed, pipeline commands still work.")
    print(f"\nconfig dir: {config_mod.flow_dir()}")
    print(f"ASR: {cfg.asr_model or 'unset'} @ {cfg.asr_base_url or 'unset'}"
          + ("  [local]" if cfg.asr_is_local() else ""))
    print(f"polish model: {cfg.polish_model}")
    print(f"hotkeys: dictate={cfg.hotkey} (tap to lock), edit={cfg.edit_hotkey}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flow", description=__doc__)
    parser.add_argument("--version", action="version", version=f"flow {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="start the push-to-talk daemon (default)")

    p_text = sub.add_parser("text", help="run shortcuts + polish on a typed transcript")
    p_text.add_argument("transcript")
    p_text.add_argument("--app", default=None)
    p_text.add_argument("--contact", default=None)

    p_try = sub.add_parser("try", help="dry-run: what would this utterance do?")
    p_try.add_argument("utterance")
    p_try.add_argument("--app", default=None)
    p_try.add_argument("--contact", default=None)

    p_wav = sub.add_parser("wav", help="transcribe + route + polish an audio file")
    p_wav.add_argument("path")

    p_decide = sub.add_parser("decide", help="show the language/script decision only")
    p_decide.add_argument("transcript")

    p_hist = sub.add_parser("history", help="show recent dictations")
    p_hist.add_argument("-n", type=int, default=10)

    p_blocks = sub.add_parser("blocks", help="open the visual shortcut editor")
    p_blocks.add_argument("--port", type=int, default=None)
    p_blocks.add_argument("--no-open", action="store_true")

    sub.add_parser("shortcuts", help="list shortcuts and their triggers")

    p_local = sub.add_parser("local", help="the $0/month local ASR mode (whisper.cpp)")
    p_local.add_argument("action", choices=["setup", "status"], nargs="?", default="status")

    sub.add_parser("doctor", help="check keys, deps, and permissions")

    args = parser.parse_args(argv)
    handlers = {
        None: _cmd_run,
        "run": _cmd_run,
        "text": _cmd_text,
        "try": _cmd_try,
        "wav": _cmd_wav,
        "decide": _cmd_decide,
        "history": _cmd_history,
        "blocks": _cmd_blocks,
        "shortcuts": _cmd_shortcuts,
        "local": _cmd_local,
        "doctor": _cmd_doctor,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
