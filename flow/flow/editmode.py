"""Edit mode: select text anywhere, hold the edit key, say what to change.

"make that three bullet points", "drop the second sentence", "same thing
but as a question" — the selection is replaced in place.

This edits YOUR text under YOUR spoken instruction. The prompt binds the
model to executing the instruction on the given text — it never composes
new content beyond what the instruction itself dictates, and if the
instruction isn't an edit at all, the text comes back untouched.

Selection capture is the clipboard round-trip (set a sentinel, synthesize
Cmd-C, read, restore) — the one method that works across native apps,
browsers, and Electron alike, using the same machinery insert.py already
uses to paste. No ANTHROPIC_API_KEY means edit mode says so and does
nothing: there is no deterministic fallback that can execute an arbitrary
spoken instruction.
"""

from __future__ import annotations

import subprocess
import sys
import time
import uuid

from . import llm
from .config import Config
from .insert import notify, paste

SYSTEM_PROMPT = """You are the edit engine inside a dictation tool. The user selected text they wrote and spoke an instruction for how to change it. Apply the instruction to the text. Output ONLY the revised text — it replaces the selection directly, so no commentary, no surrounding quotes, no markdown fences unless the text itself had them.

Rules:
1. Execute exactly what the instruction asks. Leave everything the instruction does not address unchanged — same wording, same casing, same line breaks.
2. Never add content of your own. New words appear only when the instruction itself supplies or clearly dictates them ("add a line that says X", "turn this into a question").
3. Preserve the text's language and script. Hindi stays Hindi, in its current script, unless the instruction says otherwise.
4. If the instruction is unintelligible, empty, or not an edit instruction, output the original text exactly as received."""


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=10, **kw)


def read_selection() -> str | None:
    """Copy of the current selection, clipboard preserved. None when nothing
    is selected (or off macOS)."""
    if sys.platform != "darwin":
        return None
    old = _run(["pbpaste"]).stdout
    sentinel = f"flow-sel-{uuid.uuid4().hex[:12]}"
    _run(["pbcopy"], input=sentinel.encode("utf-8"))
    _run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "c" using command down',
        ]
    )
    time.sleep(0.2)
    grabbed = _run(["pbpaste"]).stdout
    if old:
        _run(["pbcopy"], input=old)
    else:
        _run(["pbcopy"], input=b"")
    text = grabbed.decode("utf-8", errors="replace")
    if not text or text == sentinel:
        return None  # Cmd-C copied nothing: no selection
    return text


def build_user_message(selection: str, instruction: str, app: str | None = None) -> str:
    lines = ["<context>", f"app: {app or 'unknown'}", "</context>"]
    lines += ["<selected_text>", selection, "</selected_text>"]
    lines += ["<instruction>", instruction.strip(), "</instruction>"]
    return "\n".join(lines)


def apply_edit(selection: str, instruction: str, cfg: Config, app: str | None = None) -> str | None:
    """Revised text per the instruction, or None when the model is unavailable."""
    if not instruction.strip():
        return None
    return llm.complete(
        SYSTEM_PROMPT,
        build_user_message(selection, instruction, app),
        cfg,
        max_tokens=max(cfg.polish_max_tokens, 400 + len(selection) // 2),
    )


def run_edit(selection: str, instruction: str, cfg: Config, app: str | None = None) -> bool:
    """Apply and paste over the still-active selection. True when it landed."""
    if not llm.available():
        notify("edit mode needs ANTHROPIC_API_KEY")
        return False
    revised = apply_edit(selection, instruction, cfg, app)
    if revised is None or revised == selection:
        return False
    paste(revised)
    return True
