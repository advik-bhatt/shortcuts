"""Context: what app is in front, who you're talking to, what you said before.

Three pieces:

- frontmost() asks macOS which app and window are focused (osascript; returns
  None cleanly anywhere else).
- contact_from_window() turns a window title into a person/channel name for
  the messaging apps where the title actually carries one.
- HistoryStore / PrefStore persist, under ~/.flow/, what you dictated and
  which Hindi script each conversation ended up using — that is the memory
  that makes script choice automatic the second time you talk to someone.

Everything stays on disk, local, plain files you can read and delete.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

MESSAGING_APPS = {
    "whatsapp": "whole-title",
    "messages": "whole-title",
    "telegram": "whole-title",
    "signal": "whole-title",
    "slack": "first-segment",
    "discord": "first-segment",
}

_TITLE_NOISE = {"", "whatsapp", "messages", "telegram", "signal", "slack", "discord", "new message"}

_FRONTMOST_SCRIPT = """
tell application "System Events"
    set p to first application process whose frontmost is true
    set appName to name of p
    set winTitle to ""
    try
        set winTitle to name of front window of p
    end try
end tell
return appName & linefeed & winTitle
"""


@dataclass
class Focus:
    app: str
    window: str
    contact: str | None


def frontmost() -> Focus | None:
    """Frontmost app + window title on macOS; None elsewhere or on failure."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["osascript", "-e", _FRONTMOST_SCRIPT],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    lines = out.stdout.rstrip("\n").split("\n")
    app = lines[0].strip() if lines else ""
    window = lines[1].strip() if len(lines) > 1 else ""
    if not app:
        return None
    return Focus(app=app, window=window, contact=contact_from_window(app, window))


def contact_from_window(app: str, title: str) -> str | None:
    """Extract the person/channel from a window title, for apps where it's real."""
    mode = MESSAGING_APPS.get(app.strip().lower())
    if mode is None:
        return None
    # strip invisible directionality marks WhatsApp likes to embed
    cleaned = "".join(ch for ch in title if ch.isprintable()).strip()
    if mode == "first-segment":
        cleaned = cleaned.split(" - ")[0].strip()
        # Slack DMs render as "Name (DM)"
        if cleaned.endswith("(DM)"):
            cleaned = cleaned[: -len("(DM)")].strip()
        cleaned = cleaned.lstrip("@").strip()
    if cleaned.lower() in _TITLE_NOISE:
        return None
    return cleaned or None


def _pref_key(app: str, contact: str | None) -> str:
    return f"{app.strip().lower()}\x1f{(contact or '').strip().lower()}"


class PrefStore:
    """Learned Hindi-script preference per (app, contact), with app-level fallback."""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def record(self, app: str, contact: str | None, script: str) -> None:
        for key in {_pref_key(app, contact), _pref_key(app, None)}:
            entry = self._data.setdefault(key, {"devanagari": 0, "latin": 0})
            entry[script] = entry.get(script, 0) + 1
            entry["last"] = script
            entry["updated"] = time.time()
        self._save()

    def resolve(self, app: str, contact: str | None) -> str | None:
        """Best known script for this conversation, or None if we don't know yet."""
        for key in (_pref_key(app, contact), _pref_key(app, None)):
            entry = self._data.get(key)
            if not entry:
                continue
            dev, lat = entry.get("devanagari", 0), entry.get("latin", 0)
            if dev + lat < 2:
                continue  # one sample isn't a preference yet
            if dev == lat:
                return entry.get("last")
            return "devanagari" if dev > lat else "latin"
        return None


class HistoryStore:
    """Append-only JSONL log of dictations; feeds recent context to the polish pass."""

    def __init__(self, path: Path, limit: int = 500):
        self.path = path
        self.limit = limit

    def append(self, entry: dict) -> None:
        entry = {"ts": time.time(), **entry}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._trim()

    def _trim(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) > self.limit * 2:
            self.path.write_text("\n".join(lines[-self.limit :]) + "\n", encoding="utf-8")

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def recent(self, app: str | None = None, contact: str | None = None, n: int = 4) -> list[dict]:
        """Last n dictations for this conversation; falls back to global recency."""
        entries = self.entries()
        if app:
            scoped = [
                e
                for e in entries
                if e.get("app", "").lower() == app.lower()
                and (not contact or (e.get("contact") or "").lower() == contact.lower())
            ]
            if scoped:
                return scoped[-n:]
        return entries[-n:]
