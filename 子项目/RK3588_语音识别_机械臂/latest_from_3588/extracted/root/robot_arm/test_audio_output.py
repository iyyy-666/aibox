#!/usr/bin/env python3
"""Play a simple test tone through AUDIO_OUTPUT_DEVICE."""
from __future__ import annotations

import argparse
import math
import struct
import subprocess
import tempfile
import wave
from contextlib import suppress

from audio_config import audio_output_device, print_audio_devices


def make_tone(path: str, seconds: float = 1.2, rate: int = 16000, volume: float = 0.35) -> None:
    total = int(seconds * rate)
    data = bytearray()
    for i in range(total):
        sample = int(32767 * volume * math.sin(2 * math.pi * 440 * i / rate))
        data.extend(struct.pack("<h", sample))
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(data))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default=None)
    parser.add_argument("--wav", default=None)
    args = parser.parse_args()

    device = args.device or audio_output_device()
    print_audio_devices("test_audio_output")
    wav_path = args.wav
    temp_path = None
    if not wav_path:
        fd, temp_path = tempfile.mkstemp(prefix="audio_output_test_", suffix=".wav")
        with suppress(OSError):
            import os
            os.close(fd)
        wav_path = temp_path
        make_tone(wav_path)

    print(f"playing device={device} wav={wav_path}")
    result = subprocess.run(["aplay", "-D", device, wav_path], text=True, capture_output=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if temp_path:
        with suppress(OSError):
            import os
            os.remove(temp_path)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
