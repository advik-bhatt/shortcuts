"""One place that talks to Claude. polish, intent, and edit mode all call this.

Centralizes the per-tier request shape: Haiku takes neither thinking nor
effort params; Fable/Mythos tiers accept effort only; Sonnet/Opus tiers take
thinking disabled + low effort (what a sub-second formatting call wants).
Returns None on ANY failure — every caller has a deterministic fallback, and
dictation must never die mid-thought.
"""

from __future__ import annotations

import os

from .config import Config


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def complete(system: str, user: str, cfg: Config, *, max_tokens: int | None = None) -> str | None:
    """One system+user round trip. Text out, or None on any failure."""
    if not available():
        return None
    try:
        import anthropic
    except ImportError:
        return None

    kwargs: dict = dict(
        model=cfg.polish_model,
        max_tokens=max_tokens or cfg.polish_max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    model = cfg.polish_model
    if model.startswith(("claude-fable", "claude-mythos")):
        kwargs["output_config"] = {"effort": "low"}
    elif not model.startswith("claude-haiku"):
        kwargs["thinking"] = {"type": "disabled"}
        kwargs["output_config"] = {"effort": "low"}

    try:
        client = anthropic.Anthropic(timeout=cfg.polish_timeout)
        response = client.messages.create(**kwargs)
        if getattr(response, "stop_reason", None) == "refusal":
            return None
        parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
        text = "".join(parts).strip()
        return text or None
    except Exception:
        return None
