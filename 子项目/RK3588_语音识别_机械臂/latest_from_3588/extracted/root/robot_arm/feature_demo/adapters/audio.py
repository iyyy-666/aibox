"""Audio resources owned by unified feature-demo workers."""
from __future__ import annotations

import os
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Callable


VOICE_INPUT_DEVICE = "dsnoop:CARD=XFMDPV0018,DEV=0"
AUDIO_OUTPUT_DEVICE = "plughw:CARD=Device,DEV=0"


def deployment_environment() -> dict[str, str]:
    """Return the device defaults used by all Chinese voice modules."""
    return {
        "VOICE_INPUT_DEVICE": os.getenv("VOICE_INPUT_DEVICE", VOICE_INPUT_DEVICE),
        "AUDIO_OUTPUT_DEVICE": os.getenv("AUDIO_OUTPUT_DEVICE", AUDIO_OUTPUT_DEVICE),
        "VOICE_LANGUAGE": os.getenv("VOICE_LANGUAGE", "zh"),
        "VOICE_BACKEND": os.getenv("VOICE_BACKEND", "sensevoice"),
        "PARAFORMER_MODEL_DIR": os.getenv("PARAFORMER_MODEL_DIR", "/root/sherpa_models/paraformer-large-int8"),
        "SHERPA_ASR_DIR": os.getenv(
            "SHERPA_ASR_DIR", "/root/sherpa_models/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01"
        ),
        "SHERPA_TTS_DIR": os.getenv("SHERPA_TTS_DIR", "/root/sherpa_models/vits-melo-tts-zh_en"),
        "LLM_MODEL": os.getenv("LLM_MODEL", "/root/llm_models/qwen2.5-3b-instruct-q4_k_m.gguf"),
    }


class PlaybackController:
    """Own one aplay child process; never discover or kill foreign processes."""

    def __init__(
        self,
        *,
        device: str | None = None,
        popen_factory: Callable[..., object] = subprocess.Popen,
    ) -> None:
        self._device = device or deployment_environment()["AUDIO_OUTPUT_DEVICE"]
        self._popen_factory = popen_factory
        self._process = None
        self._cleanup_path: str | None = None

    @property
    def active(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def play(self, path: str, *, cleanup: bool = False) -> None:
        self.stop()
        self._cleanup_path = path if cleanup else None
        self._process = self._popen_factory(
            ["aplay", "-q", "-D", self._device, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        process = self._process
        self._process = None
        cleanup_path = self._cleanup_path
        self._cleanup_path = None
        if process is None or process.poll() is not None:
            if cleanup_path:
                with suppress(FileNotFoundError):
                    Path(cleanup_path).unlink()
            return
        with suppress(Exception):
            process.terminate()
        with suppress(Exception):
            process.wait(timeout=0.5)
        if process.poll() is None:
            with suppress(Exception):
                process.kill()
            with suppress(Exception):
                process.wait(timeout=0.5)
        if cleanup_path:
            with suppress(FileNotFoundError):
                Path(cleanup_path).unlink()
