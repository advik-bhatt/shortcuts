"""Tone matching: read how you already write in this conversation, and say so.

Wispr Flow calls this "tone matching": your Slack messages stay lowercase and
loose, your emails stay full sentences. flow derives it from evidence — the
recent dictations in THIS (app, contact) — with plain counting, no model.
The result is a couple of extra lines in the polish prompt; the polish model
applies them. Deterministic, so it is unit-testable and never surprising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
_LETTER = re.compile(r"[A-Za-z]")


@dataclass
class StyleProfile:
    samples: int
    lowercase: bool       # sentences start lowercase in this conversation
    light_punctuation: bool  # messages usually end without . ! ?
    uses_emoji: bool

    def hints(self) -> list[str]:
        """Prompt lines for the polish pass; [] when there's nothing to say."""
        if self.samples < 3:
            return []
        out: list[str] = []
        if self.lowercase:
            out.append(
                "style: this conversation is lowercase-casual — do not capitalize "
                "sentence starts unless it's a proper noun or 'I'"
            )
        if self.light_punctuation:
            out.append(
                "style: messages here usually end without a period — don't add one "
                "to the final sentence"
            )
        if self.uses_emoji:
            out.append("style: emoji are at home in this conversation — keep any the speaker implies")
        return out


def profile(recent: list[str]) -> StyleProfile:
    """Distill a register from recent final texts in one conversation."""
    texts = [t.strip() for t in recent if t and t.strip()]
    n = len(texts)
    if n == 0:
        return StyleProfile(0, False, False, False)

    lower_starts = 0
    unpunctuated_ends = 0
    emoji = 0
    for t in texts:
        first = _LETTER.search(t)
        if first and first.group(0).islower():
            lower_starts += 1
        if t[-1].isalnum():
            unpunctuated_ends += 1
        if _EMOJI.search(t):
            emoji += 1

    return StyleProfile(
        samples=n,
        lowercase=lower_starts / n >= 0.7,
        light_punctuation=unpunctuated_ends / n >= 0.7,
        uses_emoji=emoji / n >= 0.5,
    )
