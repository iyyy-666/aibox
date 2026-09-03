#!/usr/bin/env python3
"""Test one WAV with a selected local ASR backend."""
from __future__ import annotations

import argparse
import os
import sys
import wave
from pathlib import Path


def wav_info(path: str) -> dict[str, int | str | float]:
    with wave.open(path, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        return {
            "path": path,
            "sample_rate": rate,
            "channels": channels,
            "sample_width": width,
            "duration_sec": frames / rate if rate else 0.0,
        }


def read_wav(path: str) -> bytes:
    with wave.open(path, "rb") as wf:
        if wf.getframerate() != 16000 or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise SystemExit("WAV must be 16000 Hz, mono, 16-bit PCM for a fair backend test.")
        return wf.readframes(wf.getnframes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    parser.add_argument("--backend", choices=["vosk", "sherpa_onnx", "sherpa", "whisper"], default="vosk")
    parser.add_argument("--grammar", choices=["free", "commands"], default="free")
    args = parser.parse_args()

    os.environ["VOICE_BACKEND"] = args.backend
    from speech_context import correct_text
    from voice_engine import VoiceEngine

    info = wav_info(args.wav)
    print("AUDIO FORMAT")
    for key, value in info.items():
        print(f"{key}: {value}")

    engine = VoiceEngine()
    engine.use_command_grammar = args.grammar == "commands"
    if args.grammar == "commands":
        engine.set_commands({"直立": None, "放平": None, "抓取": None, "搬运": None, "停止": None, "张开": None, "闭合": None, "复位": None})
    if not engine.load():
        print(f"load failed: {engine.last_error}", file=sys.stderr)
        return 2

    audio = read_wav(args.wav)
    raw = engine._recognize_raw(audio)
    normalized = correct_text(raw, "robot", strict=False)
    print("\nASR BACKEND")
    print(engine.status().get("backend"))
    print("\nRAW ASR RESULT")
    print(raw)
    print("\nNORMALIZED RESULT")
    print(normalized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
