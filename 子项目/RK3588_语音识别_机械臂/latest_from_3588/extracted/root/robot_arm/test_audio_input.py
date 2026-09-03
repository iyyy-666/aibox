#!/usr/bin/env python3
"""Record a short WAV from VOICE_INPUT_DEVICE."""
from __future__ import annotations

import argparse
import time
import wave

import alsaaudio

from audio_config import print_audio_devices, voice_input_device


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--out", default="/tmp/voice_debug/input_test.wav")
    parser.add_argument("--device", default=None)
    args = parser.parse_args()

    device = args.device or voice_input_device()
    print_audio_devices("test_audio_input")
    print(f"recording device={device} rate=16000 channels=1 format=s16le seconds={args.seconds}")

    pcm = alsaaudio.PCM(
        alsaaudio.PCM_CAPTURE,
        alsaaudio.PCM_NORMAL,
        device,
        channels=1,
        rate=16000,
        format=alsaaudio.PCM_FORMAT_S16_LE,
        periodsize=160,
    )
    frames: list[bytes] = []
    deadline = time.time() + max(0.1, args.seconds)
    while time.time() < deadline:
        length, data = pcm.read()
        if length > 0 and data:
            frames.append(data)

    with wave.open(args.out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"".join(frames))
    print(f"saved={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
