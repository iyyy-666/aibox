#!/usr/bin/env python3
"""RK3588 playback-chain diagnostics for Chinese WAVs.

Checks:
- original WAV integrity
- direct aplay playback across devices
- repeated playback stability
- playback duration vs WAV duration
- stderr for underrun/xrun/broken pipe
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from audio_config import audio_output_device, print_audio_devices


SAMPLE_TEXTS = [
    "你好",
    "今天天气很好",
    "机械臂请搬运一下物块",
    "请把桌子上的红色方块移动到指定位置",
]


@dataclasses.dataclass
class WavMeta:
    path: str
    sample_rate: int
    channels: int
    sample_width: int
    duration_sec: float
    rms: float
    peak: float


def run_cmd(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def wav_meta(path: Path) -> WavMeta:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        data = wf.readframes(frames)
    arr = np.frombuffer(data, dtype=np.int16) if data else np.array([], dtype=np.int16)
    rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)) / 32768.0) if arr.size else 0.0
    peak = float(np.max(np.abs(arr)) / 32768.0) if arr.size else 0.0
    return WavMeta(
        path=str(path),
        sample_rate=rate,
        channels=channels,
        sample_width=width,
        duration_sec=round(frames / rate, 3) if rate else 0.0,
        rms=round(rms, 6),
        peak=round(peak, 6),
    )


def wav_summary(path: Path) -> dict[str, Any]:
    meta = wav_meta(path)
    return dataclasses.asdict(meta)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def find_tts_model_dir() -> Path:
    return Path(os.getenv("SHERPA_TTS_DIR", "/root/sherpa_models/vits-melo-tts-zh_en"))


def generate_tts(text: str, out_wav: Path, *, speed: float, gain: float) -> dict[str, Any]:
    import sherpa_onnx

    base = find_tts_model_dir()
    model = base / "model.onnx"
    tokens = base / "tokens.txt"
    lexicon = base / "lexicon.txt"
    if not model.exists() or not tokens.exists() or not lexicon.exists():
        raise FileNotFoundError(f"missing TTS model files in {base}")
    rule_fsts = ",".join(str(p) for p in [base / "phone.fst", base / "date.fst", base / "number.fst"] if p.exists())
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(model),
                tokens=str(tokens),
                lexicon=str(lexicon),
                data_dir="",
                length_scale=float(os.getenv("VOICE_LOOP_TTS_LENGTH_SCALE", "1.05")),
            ),
            num_threads=4,
            provider="cpu",
        ),
        rule_fsts=rule_fsts,
        max_num_sentences=1,
    )
    tts = sherpa_onnx.OfflineTts(cfg)
    audio = tts.generate(text.strip(), sid=int(os.getenv("VOICE_LOOP_TTS_SID", "0")), speed=speed)
    raw_path = out_wav.with_name(out_wav.stem + "_raw.wav")
    sherpa_onnx.write_wave(str(raw_path), audio.samples, audio.sample_rate)
    if abs(gain - 1.0) > 1e-3:
        import wave as pywave

        with pywave.open(str(raw_path), "rb") as wf:
            params = wf.getparams()
            data = wf.readframes(wf.getnframes())
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        samples = np.clip(samples * gain, -32768, 32767).astype(np.int16)
        with pywave.open(str(out_wav), "wb") as wf:
            wf.setparams(params)
            wf.writeframes(samples.tobytes())
    else:
        out_wav.write_bytes(raw_path.read_bytes())
    return {
        "text": text,
        "tts_model_dir": str(base),
        "speed": speed,
        "gain": gain,
        "wav": wav_summary(out_wav),
    }


def convert_wav(src: Path, dst: Path, rate: int, channels: int) -> dict[str, Any]:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-ac",
        str(channels),
        "-ar",
        str(rate),
        "-acodec",
        "pcm_s16le",
        str(dst),
    ]
    rc, text = run_cmd(cmd, timeout=120)
    if rc != 0:
        raise RuntimeError(f"ffmpeg convert failed: {text}")
    return wav_summary(dst)


def direct_info(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"path": str(path)}
    for tool, cmd in [
        ("file", ["file", str(path)]),
        ("soxi", ["soxi", str(path)]),
    ]:
        try:
            rc, text = run_cmd(cmd, timeout=20)
            info[tool] = {"rc": rc, "text": text}
        except FileNotFoundError:
            info[tool] = {"rc": -1, "text": "not found"}
    return info


def play_once(device: str, wav_path: Path, timeout: int = 120) -> dict[str, Any]:
    start = time.perf_counter()
    proc = subprocess.run(
        ["aplay", "-D", device, str(wav_path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        errors="replace",
    )
    elapsed = time.perf_counter() - start
    return {
        "device": device,
        "wav": str(wav_path),
        "returncode": proc.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def detect_card_locks() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cmd in [
        ["fuser", "-v", "/dev/snd/*"],
        ["lsof", "/dev/snd"],
    ]:
        try:
            rc, text = run_cmd(cmd, timeout=20)
            result[" ".join(cmd)] = {"rc": rc, "text": text}
        except FileNotFoundError:
            result[" ".join(cmd)] = {"rc": -1, "text": "not found"}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="RK3588 audio playback diagnostics")
    parser.add_argument("--outdir", default="/tmp/audio_playback_diag")
    parser.add_argument("--repeat", type=int, default=50)
    parser.add_argument("--formats", default="16000_mono,44100_mono,48000_mono,44100_stereo,48000_stereo")
    parser.add_argument("--devices", default="hw:CARD=Device,DEV=0;plughw:CARD=Device,DEV=0;default")
    parser.add_argument("--tts-speed", type=float, default=float(os.getenv("VOICE_LOOP_TTS_SPEED", "0.8")))
    parser.add_argument("--tts-gain", type=float, default=float(os.getenv("VOICE_LOOP_TTS_GAIN", "1.65")))
    parser.add_argument("--continuous-only", action="store_true")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    ensure_dir(outdir)
    ensure_dir(outdir / "tts")
    ensure_dir(outdir / "formats")
    ensure_dir(outdir / "logs")

    print_audio_devices("playback_diag")
    device = audio_output_device()
    print(f"OUTPUT_DEVICE={device}")

    devices_info = {}
    for cmd in [
        ["cat", "/proc/asound/cards"],
        ["aplay", "-l"],
        ["aplay", "-L"],
    ]:
        rc, text = run_cmd(cmd, timeout=30)
        devices_info[" ".join(cmd)] = {"rc": rc, "text": text}
    (outdir / "devices.json").write_text(json.dumps(devices_info, ensure_ascii=False, indent=2), encoding="utf-8")

    raw_wavs: list[Path] = []
    tts_meta: list[dict[str, Any]] = []
    for idx, text in enumerate(SAMPLE_TEXTS, start=1):
        wav_path = outdir / "tts" / f"src_{idx:02d}.wav"
        meta = generate_tts(text, wav_path, speed=args.tts_speed, gain=args.tts_gain)
        raw_wavs.append(wav_path)
        tts_meta.append(meta)

    all_results: dict[str, Any] = {
        "devices": devices_info,
        "tts": tts_meta,
        "locks": detect_card_locks(),
        "runs": [],
    }

    fmt_specs = {
        "16000_mono": (16000, 1),
        "44100_mono": (44100, 1),
        "48000_mono": (48000, 1),
        "44100_stereo": (44100, 2),
        "48000_stereo": (48000, 2),
    }
    selected_formats = [x.strip() for x in args.formats.split(",") if x.strip()]
    selected_devices = [x.strip() for x in args.devices.split(";") if x.strip()]

    # direct aplay sanity on original files
    for idx, wav in enumerate(raw_wavs, start=1):
        entry = {
            "kind": "direct_original",
            "source": str(wav),
            "meta": wav_summary(wav),
            "file_info": direct_info(wav),
            "plays": [],
        }
        for dev in selected_devices:
            play = play_once(dev, wav)
            entry["plays"].append(play)
        all_results["runs"].append(entry)

    if not args.continuous_only:
        for fmt_name in selected_formats:
            if fmt_name not in fmt_specs:
                continue
            rate, ch = fmt_specs[fmt_name]
            for idx, wav in enumerate(raw_wavs, start=1):
                conv_path = outdir / "formats" / f"src_{idx:02d}_{fmt_name}.wav"
                meta = convert_wav(wav, conv_path, rate, ch)
                entry = {
                    "kind": "format_test",
                    "format": fmt_name,
                    "source": str(wav),
                    "converted": str(conv_path),
                    "meta": meta,
                    "file_info": direct_info(conv_path),
                    "plays": [],
                }
                for dev in selected_devices:
                    run_stats = []
                    for i in range(max(1, args.repeat // 5)):
                        play = play_once(dev, conv_path)
                        run_stats.append(play)
                    entry["plays"].append({"device": dev, "runs": run_stats})
                all_results["runs"].append(entry)

    # continuous playback test with original WAVs
    continuous_log = []
    total = max(1, args.repeat)
    for i in range(total):
        wav = raw_wavs[i % len(raw_wavs)]
        for dev in selected_devices:
            play = play_once(dev, wav)
            continuous_log.append(play)
    (outdir / "logs" / "continuous.json").write_text(
        json.dumps(continuous_log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    all_results["continuous"] = continuous_log

    summary_lines = []
    summary_lines.append(f"devices={selected_devices}")
    summary_lines.append(f"formats={selected_formats}")
    summary_lines.append(f"repeat={total}")
    xruns = 0
    underruns = 0
    broken = 0
    bad = 0
    for item in continuous_log:
        stderr = (item.get("stderr") or "").lower()
        if item.get("returncode") != 0:
            bad += 1
        if "underrun" in stderr:
            underruns += 1
        if "xrun" in stderr:
            xruns += 1
        if "broken pipe" in stderr:
            broken += 1
    summary_lines.append(f"bad_runs={bad}")
    summary_lines.append(f"underruns={underruns}")
    summary_lines.append(f"xruns={xruns}")
    summary_lines.append(f"broken_pipe={broken}")
    (outdir / "results.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n".join(summary_lines))
    print(f"results: {outdir / 'results.json'}")
    print(f"summary: {outdir / 'summary.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
