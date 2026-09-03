#!/usr/bin/env python3
"""System-level audio diagnosis for RK3588."""
from __future__ import annotations

import argparse
import os
import subprocess
import time
import wave
from pathlib import Path

from audio_config import audio_output_device, print_audio_devices, voice_input_device


def run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def wav_info(path: Path) -> dict[str, object]:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return {
            "path": str(path),
            "rate": rate,
            "channels": wf.getnchannels(),
            "width": wf.getsampwidth(),
            "duration": round(frames / rate, 3) if rate else 0.0,
        }


def record(device: str, rate: int, seconds: int, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "arecord",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-c",
        "1",
        "-r",
        str(rate),
        "-d",
        str(seconds),
        str(out),
    ]
    rc, text = run(cmd, timeout=seconds + 10)
    return f"rc={rc}\n{text}"


def play(device: str, wav: Path) -> str:
    rc, text = run(["aplay", "-D", device, str(wav)], timeout=30)
    return f"rc={rc}\n{text}"


def dump_hw() -> str:
    parts = []
    for cmd in [
        ["arecord", "--dump-hw-params", "-D", "hw:CARD=XFMDPV0018,DEV=0", "-f", "S16_LE", "-c", "1", "-r", "16000", "-d", "1", "/dev/null"],
        ["aplay", "--dump-hw-params", "-D", "hw:CARD=Device,DEV=0", "/tmp/audio_diag_20260827/16000.wav"],
    ]:
        rc, text = run(cmd, timeout=20)
        parts.append(f"$ {' '.join(cmd)}\nrc={rc}\n{text}")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--outdir", default="/tmp/audio_diag_20260827")
    args = parser.parse_args()

    in_dev = voice_input_device()
    out_dev = audio_output_device()
    print_audio_devices("audio_system")
    print(f"INPUT={in_dev}")
    print(f"OUTPUT={out_dev}")
    print("\n--- DEVICE LIST ---")
    for cmd in [["cat", "/proc/asound/cards"], ["arecord", "-l"], ["arecord", "-L"], ["aplay", "-l"], ["aplay", "-L"]]:
        rc, text = run(cmd, timeout=30)
        print(f"$ {' '.join(cmd)}")
        print(text)
        if rc != 0:
            print(f"rc={rc}")

    outdir = Path(args.outdir)
    print("\n--- HW PARAMS ---")
    print(dump_hw())
    print("\n--- RECORD + PLAY ---")
    for rate in (16000, 44100, 48000):
        wav = outdir / f"{rate}.wav"
        print(f"\nRATE={rate}")
        print("RECORDING prompt: 打开机械臂，关闭机械臂，机械臂回到原点")
        print(record(in_dev, rate, args.seconds, wav))
        print(wav_info(wav))
        print(play(out_dev, wav))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
