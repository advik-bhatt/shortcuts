"""The polish pass: turn a raw ASR transcript into the text a human would type.

This is the layer that does what Wispr Flow's formatting engine does — infer
punctuation and quotes nobody spoke aloud, honor "scratch that" self-edits,
drop filler — plus the part it doesn't: render Hindi in the right script for
the conversation, chosen by flow.language and the per-contact memory.

Runs on Claude (default claude-haiku-4-5 — the cheapest tier, and a short
formatting task is squarely inside what it does well). If no ANTHROPIC_API_KEY
is available, or the API call fails, fall back to a deterministic cleanup so
dictation never dies mid-thought.
"""

from __future__ import annotations

import re

from . import llm
from .config import Config
from .language import ENGLISH, TargetStyle

SYSTEM_PROMPT = """You are the formatting engine inside a dictation tool. The user spoke out loud; a speech-recognition model produced the transcript you receive. Your only job is to produce the exact text the user meant to type. Your output is pasted directly into the frontmost app, so output ONLY the final text — no commentary, no explanations, no surrounding quotes.

Rules:
1. Punctuate the way the speaker implied: sentence breaks, commas, question marks, apostrophes, and quotation marks around quoted speech ("she said 'I'm done'" gets real quote marks) — even though none of it was spoken.
2. Honor spoken self-editing: "scratch that", "no wait", "actually make that X" — keep only the corrected version, never the false start or the command itself.
3. Remove pure disfluencies (um, uh, filler repeats) but keep the speaker's tone, slang, and meaning exactly. Never summarize, expand, translate, or ANSWER the content — you are typing it, not replying to it.
4. Fix obvious ASR mistakes using the context block (the app, the person, recent dictations, the user's dictionary of proper nouns). Prefer the dictionary spelling of any name that sounds similar.
5. Language and script: the target block says what the final text should be.
   - english: plain English.
   - hindi or hinglish with hindi_script=devanagari: render Hindi words in Devanagari (देवनागरी). English words and names stay in Latin script.
   - hindi or hinglish with hindi_script=latin: render Hindi words in standard romanized Hinglish spelling (hai, nahi, theek, kyun). Never output Devanagari in this mode.
   - Transliterate between scripts when the transcript's script differs from the target. Transliterate, never translate — "कल मिलते हैं" with target latin becomes "kal milte hain", not "see you tomorrow".
   - If the transcript clearly contains Hindi the target missed (or vice versa), trust the transcript for WHAT was said and the target only for WHICH SCRIPT Hindi is written in.
6. Numbers: use digits for quantities, times, and amounts ("meet at 5 30" -> "meet at 5:30") unless clearly spoken as a deliberate word.
7. Match the destination: in code editors and terminals use plain ASCII punctuation and no smart quotes; in chat apps keep it casual and don't force capitalization onto lowercase-style messages the user has been sending. Obey any style lines in the context block — they are measured from this exact conversation.
8. If the transcript is empty, pure noise, or only filler, output nothing at all.
9. Strings listed in the <verbatim> block were inserted by the user's own snippet expansions: each must appear in your output EXACTLY as given, character for character — never rephrase, re-punctuate, or re-case them."""


def build_user_message(
    raw: str,
    target: TargetStyle,
    *,
    app: str | None = None,
    contact: str | None = None,
    recent: list[str] | None = None,
    dictionary: list[str] | None = None,
    style_hints: list[str] | None = None,
    verbatim: list[str] | None = None,
) -> str:
    lines = ["<context>"]
    lines.append(f"app: {app or 'unknown'}")
    if contact:
        lines.append(f"talking to: {contact}")
    if recent:
        lines.append("recent dictations in this context (oldest first):")
        for r in recent:
            lines.append(f"- {r}")
    if dictionary:
        lines.append("user dictionary (proper nouns, preferred spellings): " + ", ".join(dictionary))
    for hint in style_hints or []:
        lines.append(hint)
    lines.append("</context>")
    if verbatim:
        lines.append("<verbatim>")
        for v in verbatim:
            lines.append(v)
        lines.append("</verbatim>")
    lines.append("<target>")
    lines.append(f"language: {target.language}")
    if target.language != ENGLISH:
        lines.append(f"hindi_script: {target.hindi_script}")
    lines.append(f"decided by: {target.source}")
    lines.append("</target>")
    lines.append("<transcript>")
    lines.append(raw.strip())
    lines.append("</transcript>")
    return "\n".join(lines)


def fallback_cleanup(raw: str) -> str:
    """Deterministic no-LLM cleanup so dictation still works with zero keys."""
    text = re.sub(r"\s+", " ", raw).strip()
    if not text:
        return ""
    # drop leading fillers
    text = re.sub(r"^(um|uh|umm|uhh|hmm)[,\s]+", "", text, flags=re.IGNORECASE)
    # lone "i" is always "I" in English
    text = re.sub(r"\bi\b", "I", text)
    if text and text[0].isalpha() and text[0].islower():
        text = text[0].upper() + text[1:]
    if len(text.split()) > 3 and text[-1].isalnum():
        text += "."
    return text


def polish(
    raw: str,
    target: TargetStyle,
    cfg: Config,
    *,
    app: str | None = None,
    contact: str | None = None,
    recent: list[str] | None = None,
    style_hints: list[str] | None = None,
    verbatim: list[str] | None = None,
) -> str:
    """LLM polish; falls back to deterministic cleanup on any failure."""
    if not raw.strip():
        return ""
    message = build_user_message(
        raw,
        target,
        app=app,
        contact=contact,
        recent=recent,
        dictionary=cfg.dictionary or None,
        style_hints=style_hints,
        verbatim=verbatim,
    )
    text = llm.complete(SYSTEM_PROMPT, message, cfg)
    return text if text else fallback_cleanup(raw)
