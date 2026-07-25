"""Configuration: ~/.flow/config.json overlaid with environment variables.

Everything has a working default. The only thing flow *needs* to go fully
live is an ASR key (GROQ_API_KEY or OPENAI_API_KEY) and, for the polish pass,
ANTHROPIC_API_KEY. With no polish key it still works — it falls back to a
deterministic cleanup instead of the LLM pass.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"


def flow_dir() -> Path:
    d = Path(os.environ.get("FLOW_DIR", "~/.flow")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Config:
    # Push-to-talk key (pynput key name: alt_r, cmd_r, ctrl_r, f13, ...)
    hotkey: str = "alt_r"
    sample_rate: int = 16_000
    min_seconds: float = 0.3

    # ASR (any OpenAI-compatible /audio/transcriptions endpoint)
    asr_base_url: str = ""
    asr_model: str = ""
    asr_api_key: str = ""

    # Polish pass (Claude)
    polish_model: str = "claude-haiku-4-5"
    polish_max_tokens: int = 1000
    polish_timeout: float = 30.0

    # Hindi script when no per-contact preference exists yet:
    #   mirror     — keep the script the utterance was transcribed in
    #   devanagari — always Devanagari
    #   latin      — always romanized (Hinglish spelling)
    hindi_script_policy: str = "mirror"

    history_limit: int = 500
    context_recent: int = 4
    dictionary: list[str] = field(default_factory=list)

    def resolve_asr(self) -> None:
        """Fill in ASR endpoint/key from the environment when not set explicitly."""
        if not self.asr_api_key:
            if os.environ.get("GROQ_API_KEY"):
                self.asr_api_key = os.environ["GROQ_API_KEY"]
                self.asr_base_url = self.asr_base_url or GROQ_BASE_URL
                self.asr_model = self.asr_model or "whisper-large-v3-turbo"
            elif os.environ.get("OPENAI_API_KEY"):
                self.asr_api_key = os.environ["OPENAI_API_KEY"]
                self.asr_base_url = self.asr_base_url or OPENAI_BASE_URL
                self.asr_model = self.asr_model or "whisper-1"
        # explicit base url / key via env always wins
        self.asr_base_url = os.environ.get("FLOW_ASR_BASE_URL", self.asr_base_url)
        self.asr_model = os.environ.get("FLOW_ASR_MODEL", self.asr_model)
        self.asr_api_key = os.environ.get("FLOW_ASR_API_KEY", self.asr_api_key)


def load() -> Config:
    cfg = Config()
    path = flow_dir() / "config.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)

    if os.environ.get("FLOW_HOTKEY"):
        cfg.hotkey = os.environ["FLOW_HOTKEY"]
    if os.environ.get("FLOW_MODEL"):
        cfg.polish_model = os.environ["FLOW_MODEL"]
    if os.environ.get("FLOW_HINDI_SCRIPT"):
        cfg.hindi_script_policy = os.environ["FLOW_HINDI_SCRIPT"]

    dict_path = flow_dir() / "dictionary.txt"
    if dict_path.exists():
        words = [w.strip() for w in dict_path.read_text(encoding="utf-8").splitlines()]
        cfg.dictionary = [w for w in words if w and not w.startswith("#")]

    cfg.resolve_asr()
    return cfg
