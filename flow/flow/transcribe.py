"""Speech-to-text against any OpenAI-compatible /audio/transcriptions endpoint.

Default provider is Groq's hosted Whisper (whisper-large-v3-turbo), because it
is the cheapest serious ASR going — fractions of a cent per hour of speech —
and Whisper large-v3 handles Hindi, English, and code-switched Hinglish in one
model with automatic language detection. Set OPENAI_API_KEY instead and it
uses OpenAI's endpoint; point FLOW_ASR_BASE_URL anywhere else that speaks the
same API.

The style_hint matters: Whisper's `prompt` parameter biases the decoder toward
the style of the prompt text, so when we already know this conversation is
written in romanized Hinglish (or in Devanagari), we prime the transcription
in that direction before the LLM pass ever runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config

# Style primers for the ASR prompt. Whisper tends to continue in the script
# and register of its prompt, which nudges Hindi speech toward the script the
# conversation actually uses.
STYLE_PRIMERS = {
    "latin": "Haan theek hai, kal milte hain. Mixing Hindi and English casually.",
    "devanagari": "हाँ ठीक है, कल मिलते हैं। Mixing Hindi and English casually.",
}


class TranscribeError(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    language: str | None = None  # ISO-ish language guess from the ASR model


def build_asr_prompt(
    dictionary: list[str] | None = None,
    preferred_script: str | None = None,
) -> str:
    parts = []
    if preferred_script in STYLE_PRIMERS:
        parts.append(STYLE_PRIMERS[preferred_script])
    if dictionary:
        parts.append("Names and terms: " + ", ".join(dictionary[:40]) + ".")
    return " ".join(parts)[:800]


def transcribe(
    wav: bytes,
    cfg: Config,
    *,
    preferred_script: str | None = None,
) -> Transcript:
    if not cfg.asr_api_key:
        raise TranscribeError(
            "No ASR key. Set GROQ_API_KEY (recommended, cheapest) or OPENAI_API_KEY."
        )
    try:
        import requests
    except ImportError as e:
        raise TranscribeError("pip install requests") from e

    url = cfg.asr_base_url.rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": f"Bearer {cfg.asr_api_key}"}
    data = {"model": cfg.asr_model, "temperature": "0", "response_format": "verbose_json"}
    prompt = build_asr_prompt(cfg.dictionary, preferred_script)
    if prompt:
        data["prompt"] = prompt

    def _post(payload):
        return requests.post(
            url,
            headers=headers,
            data=payload,
            files={"file": ("audio.wav", wav, "audio/wav")},
            timeout=60,
        )

    resp = _post(data)
    if resp.status_code == 400 and "response_format" in resp.text:
        # some providers/models only accept plain json
        data = {**data, "response_format": "json"}
        resp = _post(data)
    if resp.status_code != 200:
        raise TranscribeError(f"ASR HTTP {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    text = (body.get("text") or "").strip()
    return Transcript(text=text, language=body.get("language"))
