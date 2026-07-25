"""The language brain: decide what language and script the final text should be.

Two facts make this decidable without asking the speaker:

1. Whisper-class ASR models render Hindi speech in Devanagari and English in
   Latin script, so the transcript itself carries a strong signal about what
   was spoken.
2. The *script* the output should use (Devanagari vs romanized Hinglish) is a
   property of the conversation, not the utterance — you write to your mother
   in Devanagari and to your college group chat in Latin letters. That is
   learnable per (app, contact) and sticky.

This module is deliberately deterministic and dependency-free so it can be
unit-tested to death. The LLM polish pass downstream treats its output as a
strong default, not a straitjacket: if the transcript obviously contains Hindi
that this layer missed, the polish prompt tells the model to keep the Hindi
and use the chosen script anyway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ENGLISH = "english"
HINDI = "hindi"
HINGLISH = "hinglish"

DEVANAGARI_SCRIPT = "devanagari"
LATIN_SCRIPT = "latin"

# High-precision list of common Hindi words as they are typically romanized.
# Deliberately excludes anything that collides with ordinary English tokens
# (the, do, is, us, me, to, no, main, so, are, gay, ...). Precision over
# recall: a miss here is cheap (the polish model still sees the real words);
# a false positive would flip an English sentence into "Hinglish".
ROMAN_HINDI_WORDS = frozenset(
    """
    hai hain hoon nahi nahin kya kyu kyun kaise kab kahan kaun kisko kisne
    aur lekin magar phir fir toh tha thi hui hua hoga hogi honge
    raha rahi rahe karo karna karke kiya kijiye gaya gayi jao jaana jaunga
    aao aaya aayi acha accha achha theek thik bas bhai yaar haan
    ji aap tum tera teri tere mera meri mere apna apni hamara tumhara
    kuch sab log baat bolo bola batao bataya dekho dekha suno suna
    chalo chal milte milta milna hona wala wale wali
    shayad zaroor zarur bilkul abhi kal aaj raat subah shaam
    ghar paisa paise kaam sahi galat pata chahiye mein mujhe tujhe usko
    matlab samajh samjha padhai khana paani thoda bahut bohot zyada kam
    jaldi der baad pehle andar bahar upar neeche saath bina sirf
    """.split()
)

_LATIN_WORD = re.compile(r"[A-Za-z']+")


def _devanagari_count(text: str) -> int:
    return sum(1 for ch in text if "ऀ" <= ch <= "ॿ")


def _latin_tokens(text: str) -> list[str]:
    return [t.lower() for t in _LATIN_WORD.findall(text)]


@dataclass
class ScriptMix:
    devanagari_chars: int
    latin_words: int
    roman_hindi_hits: int

    @property
    def roman_hindi_score(self) -> float:
        if not self.latin_words:
            return 0.0
        return self.roman_hindi_hits / self.latin_words


def script_mix(text: str) -> ScriptMix:
    tokens = _latin_tokens(text)
    hits = sum(1 for t in tokens if t in ROMAN_HINDI_WORDS)
    return ScriptMix(
        devanagari_chars=_devanagari_count(text),
        latin_words=len(tokens),
        roman_hindi_hits=hits,
    )


@dataclass
class TargetStyle:
    language: str  # english | hindi | hinglish
    hindi_script: str | None  # devanagari | latin | None when language == english
    source: str  # why this decision was made (for logs and debugging)

    def describe(self) -> str:
        if self.language == ENGLISH:
            return "english"
        return f"{self.language} ({self.hindi_script})"


def decide(
    transcript: str,
    *,
    preferred_script: str | None = None,
    policy: str = "mirror",
) -> TargetStyle:
    """Decide the target language and Hindi script for a transcript.

    preferred_script — learned preference for the current (app, contact),
    or None when nothing is known yet.
    policy — what to do about Hindi script when there is no preference:
    "mirror" (follow the utterance), "devanagari", or "latin".
    """
    mix = script_mix(transcript)

    has_devanagari = mix.devanagari_chars >= 2
    # Romanized Hindi needs at least two distinct dictionary hits and a
    # third of the words matching before we believe it — precision first.
    has_roman_hindi = mix.roman_hindi_hits >= 2 and mix.roman_hindi_score >= 0.3

    if not has_devanagari and not has_roman_hindi:
        return TargetStyle(ENGLISH, None, "no hindi detected")

    # Hindi is present. Pure Hindi vs code-switched Hinglish: how much of the
    # Latin content is English (i.e. not in the romanized-Hindi list)?
    english_words = mix.latin_words - mix.roman_hindi_hits
    if has_devanagari and english_words <= 1:
        language = HINDI
    elif not has_devanagari and english_words == 0:
        language = HINDI
    else:
        language = HINGLISH

    if preferred_script in (DEVANAGARI_SCRIPT, LATIN_SCRIPT):
        return TargetStyle(language, preferred_script, "contact preference")

    if policy in (DEVANAGARI_SCRIPT, LATIN_SCRIPT):
        return TargetStyle(language, policy, "configured policy")

    # mirror: follow the script the Hindi actually arrived in
    if has_devanagari and mix.devanagari_chars >= mix.roman_hindi_hits * 4:
        return TargetStyle(language, DEVANAGARI_SCRIPT, "mirrored transcript")
    return TargetStyle(language, LATIN_SCRIPT, "mirrored transcript")
