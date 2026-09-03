"""Audio device configuration for RK3588 voice apps."""
from __future__ import annotations

import os
import subprocess


DEFAULT_INPUT_DEVICE = "dsnoop:CARD=XFMDPV0018,DEV=0"
DEFAULT_OUTPUT_DEVICE = "plughw:CARD=Device,DEV=0"


def voice_input_device() -> str:
    return (
        os.getenv("VOICE_INPUT_DEVICE")
        or os.getenv("VOICE_DEVICE")
        or DEFAULT_INPUT_DEVICE
    )


def audio_output_device() -> str:
    return (
        os.getenv("AUDIO_OUTPUT_DEVICE")
        or os.getenv("TTS_DEVICE")
        or os.getenv("PLAY_DEVICE")
        or DEFAULT_OUTPUT_DEVICE
    )


def print_audio_devices(prefix: str = "audio") -> None:
    print(
        f"[{prefix}] VOICE_INPUT_DEVICE={voice_input_device()} "
        f"AUDIO_OUTPUT_DEVICE={audio_output_device()}",
        flush=True,
    )


def command_output(command: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        return f"{command!r} failed: {exc}"
