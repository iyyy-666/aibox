#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import wave
from pathlib import Path

import numpy as np

from audio_config import voice_input_device
from speech_context import correct_text
from voice_engine import VoiceEngine


SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = "S16_LE"
OUT_DIR = Path("/tmp/voice_chain_doctor")


def record_wav(path: Path, seconds: float, device: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "arecord",
        "-D",
        device,
        "-r",
        str(SAMPLE_RATE),
        "-c",
        str(CHANNELS),
        "-f",
        FORMAT,
        "-d",
        str(max(1, int(seconds))),
        str(path),
    ]
    subprocess.run(cmd, check=True)


def read_audio(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        return wf.readframes(wf.getnframes())


def metrics(audio: bytes) -> dict[str, float]:
    if not audio:
        return {"seconds": 0.0, "rms": 0.0, "peak": 0.0, "clip_ratio": 0.0}
    samples = np.frombuffer(audio, dtype=np.int16)
    if samples.size == 0:
        return {"seconds": 0.0, "rms": 0.0, "peak": 0.0, "clip_ratio": 0.0}
    abs_samples = np.abs(samples.astype(np.int32))
    return {
        "seconds": float(samples.size / SAMPLE_RATE),
        "rms": float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)) / 32768.0),
        "peak": float(np.max(abs_samples) / 32768.0),
        "clip_ratio": float(np.count_nonzero(abs_samples >= 32760) / samples.size),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Record and inspect the RK3588 voice input chain.")
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--device", default=voice_input_device())
    parser.add_argument("--expected", default="")
    args = parser.parse_args()

    path = OUT_DIR / f"doctor_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    print(f"INPUT_DEVICE={args.device}")
    print(f"FORMAT={SAMPLE_RATE}Hz mono {FORMAT}")
    print(f"WAV={path}")
    record_wav(path, args.seconds, args.device)
    audio = read_audio(path)
    stat = metrics(audio)

    engine = VoiceEngine()
    engine.use_command_grammar = False
    if not engine.load():
        raise SystemExit(f"voice engine load failed: {engine.last_error}")
    raw, normalized = engine._recognize_pair(audio)
    result = {
        "wav": str(path),
        "input_device": args.device,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "format": FORMAT,
        "metrics": stat,
        "backend": engine._backend,
        "raw_asr": raw,
        "normalized": normalized,
        "expected": args.expected,
        "expected_normalized": correct_text(args.expected, "robot", strict=True) if args.expected else "",
    }
    json_path = OUT_DIR / "last_result.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
