"""Microphone capture: hold-to-talk recording into in-memory WAV bytes."""

from __future__ import annotations

import io
import wave


def wav_bytes(frames: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM frames in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)
    return buf.getvalue()


class Recorder:
    """Start on key-down, stop on key-up, hand back WAV bytes."""

    def __init__(self, sample_rate: int = 16_000):
        self.sample_rate = sample_rate
        self._chunks: list[bytes] = []
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd  # lazy: needs PortAudio, only on the daemon path

        self._chunks = []
        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            callback=self._on_audio,
        )
        self._stream.start()

    def _on_audio(self, indata, frames, time_info, status) -> None:
        self._chunks.append(bytes(indata))

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def seconds(self) -> float:
        total = sum(len(c) for c in self._chunks)
        return total / (2 * self.sample_rate)

    def stop(self) -> bytes:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        return wav_bytes(b"".join(self._chunks), self.sample_rate)
