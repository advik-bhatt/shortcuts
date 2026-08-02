"""`flow blocks`: the visual editor for shortcuts, served on localhost.

A stdlib HTTP server (no dependencies, binds 127.0.0.1 only) serving one
self-contained HTML page (flow/blocks.html — no CDN, no build step, works
offline) plus a tiny JSON API over ~/.flow/shortcuts/:

    GET  /                   the editor
    GET  /api/shortcuts      every shortcut + problems for broken files
    POST /api/shortcuts      save one shortcut (validated first)
    POST /api/delete         {"name": ...}
    POST /api/try            {"utterance", "shortcut"?, "app"?, "contact"?}
                             dry-run the matcher/interpreter, execute nothing

Every API request must carry the `X-Flow: 1` header. Browsers refuse to
attach custom headers cross-origin without a CORS preflight (which this
server never answers), so a malicious web page can't drive the API through
DNS rebinding or CSRF — the classic localhost-tool hole, closed.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from . import config as config_mod
from .config import Config
from .shortcuts import (
    RunContext,
    Shortcut,
    ShortcutStore,
    execute,
    find_command_match,
    find_inline_matches,
    validate,
)


def _try_route(payload: dict, store: ShortcutStore) -> dict:
    """Dry-run: what would this utterance do? Executes nothing."""
    utterance = str(payload.get("utterance") or "")
    if not utterance.strip():
        return {"fires": False, "reason": "empty utterance"}

    shortcuts: list[Shortcut] = []
    candidate = payload.get("shortcut")
    if isinstance(candidate, dict):
        problems = validate(candidate)
        if problems:
            return {"fires": False, "problems": problems}
        shortcuts.append(Shortcut.from_dict(candidate))
    else:
        shortcuts = store.load_all()[0]

    ctx = RunContext(
        app=payload.get("app") or None,
        contact=payload.get("contact") or None,
        clipboard="(clipboard)",
        last_dictation="(last dictation)",
    )
    m = find_command_match(utterance, shortcuts)
    if m is not None:
        plan = execute(m.shortcut, RunContext(
            app=ctx.app, contact=ctx.contact, slots=m.slots,
            clipboard=ctx.clipboard, last_dictation=ctx.last_dictation,
        ))
        return {
            "fires": True, "kind": "command", "shortcut": m.shortcut.name,
            "slots": m.slots, "text": plan.text, "actions": plan.actions,
            "describe": plan.describe(),
        }
    inline = find_inline_matches(utterance, shortcuts)
    if inline:
        m = inline[0]
        plan = execute(m.shortcut, RunContext(
            app=ctx.app, contact=ctx.contact, slots=m.slots,
            clipboard=ctx.clipboard, last_dictation=ctx.last_dictation,
        ))
        return {
            "fires": True, "kind": "inline", "shortcut": m.shortcut.name,
            "slots": m.slots, "text": plan.text, "actions": plan.actions,
            "describe": f"expands in place: {plan.text!r}",
        }
    return {
        "fires": False,
        "reason": "no trigger matches this as a whole utterance (commands) or phrase (inline)",
    }


def make_handler(store: ShortcutStore):
    page = resources.files("flow").joinpath("blocks.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: dict) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

        def _guarded(self) -> bool:
            if self.headers.get("X-Flow") != "1":
                self._json(403, {"error": "missing X-Flow header"})
                return False
            return True

        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/index"):
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                return
            if self.path == "/api/shortcuts":
                if not self._guarded():
                    return
                loaded, problems = store.load_all()
                self._json(200, {"shortcuts": [sc.to_dict() for sc in loaded], "problems": problems})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._guarded():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "bad json"})
                return
            if self.path == "/api/shortcuts":
                problems = validate(payload)
                if problems:
                    self._json(400, {"problems": problems})
                    return
                path = store.save(payload)
                self._json(200, {"ok": True, "file": path.name})
                return
            if self.path == "/api/delete":
                ok = store.delete(str(payload.get("name") or ""))
                self._json(200 if ok else 404, {"ok": ok})
                return
            if self.path == "/api/try":
                self._json(200, _try_route(payload, store))
                return
            self._json(404, {"error": "not found"})

    return Handler


def serve(cfg: Config, *, open_browser: bool = True) -> None:
    store = ShortcutStore(config_mod.shortcuts_dir())
    server = ThreadingHTTPServer(("127.0.0.1", cfg.editor_port), make_handler(store))
    url = f"http://127.0.0.1:{cfg.editor_port}/"
    print(f"flow blocks — edit your shortcuts at {url}  (Ctrl-C to stop)")
    if open_browser:
        import subprocess
        import sys

        if sys.platform == "darwin":
            subprocess.run(["open", url], capture_output=True, timeout=10)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
