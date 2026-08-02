"""Local ASR: the $0/month mode. whisper.cpp on your own machine, no cloud.

whisper.cpp ships `whisper-server`, an HTTP transcription server with an
OpenAI-like API whose endpoint path is configurable (`--inference-path`).
Pointed at /v1/audio/transcriptions, it becomes a drop-in target for flow's
existing OpenAI-compatible client — the rest of the pipeline cannot tell the
difference. Audio never leaves the machine.

The model is Whisper large-v3-turbo (quantized q5_0, ~574 MB), the same
family the hosted default uses, so Hindi + English code-switching keeps
working. flow's recorder already produces the 16 kHz mono WAV whisper.cpp
wants, so no ffmpeg conversion is needed on the daemon path.

Setup is one command: `flow local setup` (checks the binary, downloads the
model, flips config). The daemon starts and reuses the server automatically
when local mode is active.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import config as config_mod
from .config import Config

MODEL_FILES = {
    # name -> (filename, approx download size) from the canonical ggml conversions
    "large-v3-turbo-q5_0": ("ggml-large-v3-turbo-q5_0.bin", "~574 MB"),
    "large-v3-turbo": ("ggml-large-v3-turbo.bin", "~1.6 GB"),
    "large-v3-q5_0": ("ggml-large-v3-q5_0.bin", "~1.1 GB"),
}
MODEL_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"


def models_dir() -> Path:
    d = config_mod.flow_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_path(name: str) -> Path:
    filename = MODEL_FILES.get(name, (f"ggml-{name}.bin", ""))[0]
    return models_dir() / filename


def binary() -> str | None:
    """Path to whisper-server, or None when it isn't installed."""
    return shutil.which("whisper-server")


def server_running(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def start_server(cfg: Config) -> subprocess.Popen | None:
    """Spawn whisper-server detached; returns the process or None on failure."""
    exe = binary()
    model = model_path(cfg.local_asr_model)
    if not exe or not model.exists():
        return None
    cmd = [
        exe,
        "--host", "127.0.0.1",
        "--port", str(cfg.local_asr_port),
        "--inference-path", "/v1/audio/transcriptions",
        "-m", str(model),
    ]
    log = (config_mod.flow_dir() / "whisper-server.log").open("ab")
    try:
        return subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)
    except OSError:
        return None


def ensure_server(cfg: Config, wait: float = 20.0) -> bool:
    """Server up (starting it if needed). False when local mode can't run."""
    if server_running(cfg.local_asr_port):
        return True
    proc = start_server(cfg)
    if proc is None:
        return False
    deadline = time.monotonic() + wait  # large models take a beat to load
    while time.monotonic() < deadline:
        if server_running(cfg.local_asr_port):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.3)
    return False


def download_model(name: str) -> Path | None:
    """Fetch the ggml model with a progress line; returns the path or None."""
    filename, size = MODEL_FILES.get(name, (None, None))
    if filename is None:
        print(f"unknown model {name!r}; known: {', '.join(MODEL_FILES)}")
        return None
    dest = models_dir() / filename
    if dest.exists():
        return dest
    url = MODEL_BASE_URL + filename
    print(f"downloading {filename} ({size}) ...")
    tmp = dest.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, tmp.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done * 100 // total}% of {total >> 20} MB", end="", flush=True)
        print()
        tmp.replace(dest)
        return dest
    except OSError as e:
        print(f"\ndownload failed: {e}")
        tmp.unlink(missing_ok=True)
        return None


def setup(cfg: Config) -> int:
    """`flow local setup`: binary, model, config — then it just works."""
    ok = True
    if binary():
        print("ok       whisper-server found")
    else:
        ok = False
        hint = "brew install whisper-cpp" if sys.platform == "darwin" else "build ggml-org/whisper.cpp and put whisper-server on PATH"
        print(f"MISSING  whisper-server  — {hint}")
    model = model_path(cfg.local_asr_model)
    if model.exists():
        print(f"ok       model {model.name}")
    elif download_model(cfg.local_asr_model):
        print(f"ok       model {model.name} downloaded")
    else:
        ok = False
        print(f"MISSING  model {model.name}")
    if ok:
        cfg_path = config_mod.flow_dir() / "config.json"
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        except (json.JSONDecodeError, OSError):
            data = {}
        data["asr_mode"] = "local"
        cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print("\nlocal mode is ON (asr_mode=local in ~/.flow/config.json).")
        print("Audio now stays on this machine. `flow` will start the server itself.")
    else:
        print("\nfix the missing pieces above, then run `flow local setup` again.")
    return 0 if ok else 1
