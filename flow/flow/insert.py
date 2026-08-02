"""Deliver the final text into the frontmost app.

Paste-via-clipboard is the only method that handles Devanagari (and emoji,
and everything else) reliably, so that's the primary path: save the clipboard,
put the text on it, synthesize Cmd-V, restore the clipboard. Off macOS the
text goes to stdout so the pipeline stays usable everywhere.
"""

from __future__ import annotations

import subprocess
import sys
import time


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=10, **kw)


def paste(text: str) -> None:
    if not text:
        return
    if sys.platform != "darwin":
        print(text)
        return

    old = _run(["pbpaste"]).stdout
    _run(["pbcopy"], input=text.encode("utf-8"))
    _run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ]
    )
    # give the paste a beat to land before restoring the clipboard
    time.sleep(0.5)
    if old:
        _run(["pbcopy"], input=old)


def read_clipboard() -> str:
    """Current clipboard text; '' off macOS or on failure."""
    if sys.platform != "darwin":
        return ""
    try:
        return _run(["pbpaste"]).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def notify(message: str, title: str = "flow") -> None:
    if sys.platform != "darwin":
        print(f"[{title}] {message}")
        return
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    _run(["osascript", "-e", f'display notification "{safe}" with title "{safe_title}"'])
