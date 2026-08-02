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


def shortcuts_dir() -> Path:
    return flow_dir() / "shortcuts"


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

    # Local ASR (whisper.cpp; the $0/month mode — see flow/local_asr.py)
    #   auto   — hosted when a key is set, local when the model is downloaded
    #   local  — always local
    #   hosted — never local
    asr_mode: str = "auto"
    local_asr_port: int = 8586
    local_asr_model: str = "large-v3-turbo-q5_0"

    # Polish pass (Claude)
    polish_model: str = "claude-haiku-4-5"
    polish_max_tokens: int = 1000
    polish_timeout: float = 30.0

    # Hindi script when no per-contact preference exists yet:
    #   mirror     — keep the script the utterance was transcribed in
    #   devanagari — always Devanagari
    #   latin      — always romanized (Hinglish spelling)
    hindi_script_policy: str = "mirror"

    # Smart shortcuts
    smart_match: str = "conservative"  # off | conservative | eager (LLM assist)
    allow_shell: bool = False          # shell blocks stay dead until this is true
    tap_lock: bool = True              # tap the hotkey (instead of holding) to lock recording
    tap_threshold: float = 0.35        # seconds; shorter presses count as taps
    edit_hotkey: str = "cmd_r"         # hold + speak an instruction to edit the selection
    editor_port: int = 7739            # `flow blocks` local editor

    history_limit: int = 500
    context_recent: int = 4
    dictionary: list[str] = field(default_factory=list)

    def resolve_asr(self) -> None:
        """Fill in ASR endpoint/key from the environment when not set explicitly."""
        mode = os.environ.get("FLOW_ASR_MODE", self.asr_mode)
        self.asr_mode = mode
        if not self.asr_api_key and mode != "local":
            if os.environ.get("GROQ_API_KEY"):
                self.asr_api_key = os.environ["GROQ_API_KEY"]
                self.asr_base_url = self.asr_base_url or GROQ_BASE_URL
                self.asr_model = self.asr_model or "whisper-large-v3-turbo"
            elif os.environ.get("OPENAI_API_KEY"):
                self.asr_api_key = os.environ["OPENAI_API_KEY"]
                self.asr_base_url = self.asr_base_url or OPENAI_BASE_URL
                self.asr_model = self.asr_model or "whisper-1"
        if not self.asr_api_key and mode in ("local", "auto"):
            # local mode: explicit, or automatic when the model is downloaded
            from .local_asr import model_path

            if mode == "local" or model_path(self.local_asr_model).exists():
                self.asr_base_url = self.asr_base_url or f"http://127.0.0.1:{self.local_asr_port}/v1"
                self.asr_model = self.asr_model or self.local_asr_model
                self.asr_api_key = "local"
        # explicit base url / key via env always wins
        self.asr_base_url = os.environ.get("FLOW_ASR_BASE_URL", self.asr_base_url)
        self.asr_model = os.environ.get("FLOW_ASR_MODEL", self.asr_model)
        self.asr_api_key = os.environ.get("FLOW_ASR_API_KEY", self.asr_api_key)

    def asr_is_local(self) -> bool:
        return self.asr_api_key == "local" or self.asr_base_url.startswith(
            f"http://127.0.0.1:{self.local_asr_port}"
        )


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
    if os.environ.get("FLOW_EDIT_HOTKEY"):
        cfg.edit_hotkey = os.environ["FLOW_EDIT_HOTKEY"]
    if os.environ.get("FLOW_SMART_MATCH"):
        cfg.smart_match = os.environ["FLOW_SMART_MATCH"]
    if os.environ.get("FLOW_ALLOW_SHELL"):
        cfg.allow_shell = os.environ["FLOW_ALLOW_SHELL"].lower() in ("1", "true", "yes")

    dict_path = flow_dir() / "dictionary.txt"
    if dict_path.exists():
        words = [w.strip() for w in dict_path.read_text(encoding="utf-8").splitlines()]
        cfg.dictionary = [w for w in words if w and not w.startswith("#")]

    cfg.resolve_asr()
    return cfg
