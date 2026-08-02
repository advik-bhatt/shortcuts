"""Execute a shortcut Plan: type the text, then run the side-effect actions.

The interpreter (flow.shortcuts.execute) is pure and returns a Plan; this
module is the only place a Plan touches the machine. macOS does the real
work; anywhere else the plan is printed, so the pipeline stays testable.

Shell blocks are OFF by default (`allow_shell` in config). A shortcut file
someone hands you should not be able to run commands until you have said,
once, that you want that.
"""

from __future__ import annotations

import subprocess
import sys
import time

from .config import Config
from .insert import notify, paste
from .shortcuts import Plan

# osascript key codes for non-character keys
_KEY_CODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51,
    "esc": 53, "escape": 53, "left": 123, "right": 124, "down": 125, "up": 126,
}
_MODIFIERS = {
    "cmd": "command down", "command": "command down",
    "shift": "shift down",
    "alt": "option down", "option": "option down",
    "ctrl": "control down", "control": "control down",
}


def press_keys(combo: str) -> bool:
    """Synthesize a key combo like cmd+shift+4 via System Events."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        return False
    mods = [_MODIFIERS[p] for p in parts[:-1] if p in _MODIFIERS]
    if len(mods) != len(parts) - 1:
        return False  # an unknown modifier — refuse rather than mis-press
    key = parts[-1]
    using = f" using {{{', '.join(mods)}}}" if mods else ""
    if key in _KEY_CODES:
        script = f'tell application "System Events" to key code {_KEY_CODES[key]}{using}'
    elif len(key) == 1:
        safe = key.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{safe}"{using}'
    else:
        return False
    if sys.platform != "darwin":
        print(f"[keys] {combo}")
        return True
    return subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10).returncode == 0


def run_plan(plan: Plan, cfg: Config) -> None:
    """Type the composed text, then perform the actions in order."""
    if plan.text:
        paste(plan.text)
    for action in plan.actions:
        kind = action["type"]
        if kind == "pause":
            time.sleep(min(float(action["seconds"]), 10.0))
        elif kind == "open_url":
            _open(["open", action["url"]], f"open {action['url']}")
        elif kind == "open_app":
            _open(["open", "-a", action["app"]], f"launch {action['app']}")
        elif kind == "keys":
            press_keys(action["combo"])
        elif kind == "shell":
            if not cfg.allow_shell:
                notify("shell block skipped — enable allow_shell in ~/.flow/config.json")
                continue
            try:
                subprocess.run(action["cmd"], shell=True, capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired) as e:
                notify(f"shell block failed: {e}")


def _open(cmd: list[str], describe: str) -> None:
    if sys.platform != "darwin":
        print(f"[action] {describe}")
        return
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        notify(f"{describe} failed: {e}")
