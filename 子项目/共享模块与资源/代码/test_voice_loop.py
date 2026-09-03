#!/usr/bin/env python3
"""Independent closed-loop voice test tool for RK3588.

Flow:
local TTS -> speaker playback -> mic capture -> WAV save -> local ASR -> compare -> repeat
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import importlib
import json
import math
import os
import subprocess
import sys
import time
import wave
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from audio_config import audio_output_device, print_audio_devices, voice_input_device
from speech_context import correct_text


VOICE_INPUT_DEVICE = voice_input_device()
AUDIO_OUTPUT_DEVICE = audio_output_device()
SAMPLE_RATE = 16000
CHANNELS = 1
PCM_FORMAT = "S16_LE"
EXPECTED_TEXT = "机械臂请搬运一下物块"
DEFAULT_TTS_DIR = os.getenv("SHERPA_TTS_DIR", "/root/sherpa_models/vits-melo-tts-zh_en")
DEFAULT_TTS_SPEED = float(os.getenv("VOICE_LOOP_TTS_SPEED", "0.8"))
DEFAULT_TTS_LENGTH_SCALE = float(os.getenv("VOICE_LOOP_TTS_LENGTH_SCALE", "1.05"))
DEFAULT_TTS_SID = int(os.getenv("VOICE_LOOP_TTS_SID", "0"))
DEFAULT_TTS_GAIN = float(os.getenv("VOICE_LOOP_TTS_GAIN", "1.65"))
DEFAULT_BACKENDS = ("vosk", "sherpa", "whisper")


@dataclasses.dataclass
class BackendResult:
    backend: str
    model: str
    raw_asr: str
    normalized: str
    similarity: float
    recognized: bool
    asr_sec: float
    error: str = ""


def normalize_text(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isalnum() or "\u4e00" <= ch <= "\u9fff").lower()


def similarity_percent(expected: str, actual: str) -> float:
    exp = normalize_text(expected)
    act = normalize_text(actual)
    if not exp and not act:
        return 100.0
    return round(difflib.SequenceMatcher(None, exp, act).ratio() * 100.0, 2)


def wav_info(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        data = wf.readframes(frames)
    samples = np.frombuffer(data, dtype=np.int16) if data else np.array([], dtype=np.int16)
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))) / 32768.0) if samples.size else 0.0
    peak = float(np.max(np.abs(samples)) / 32768.0) if samples.size else 0.0
    return {
        "path": str(path),
        "sample_rate": rate,
        "channels": channels,
        "sample_width": width,
        "duration_sec": round(frames / rate, 3) if rate else 0.0,
        "rms": round(rms, 6),
        "peak": round(peak, 6),
    }


def read_pcm16(wav_path: Path) -> bytes:
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getframerate() != SAMPLE_RATE or wf.getnchannels() != CHANNELS or wf.getsampwidth() != 2:
            raise ValueError("WAV must be 16000 Hz, mono, 16-bit PCM")
        return wf.readframes(wf.getnframes())


def write_pcm16(path: Path, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def apply_gain_to_wav(src: Path, dst: Path, gain: float) -> None:
    with wave.open(str(src), "rb") as wf:
        params = wf.getparams()
        data = wf.readframes(wf.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        write_pcm16(dst, b"", params.framerate)
        return
    scaled = np.clip(samples * gain, -32768, 32767).astype(np.int16)
    write_pcm16(dst, scaled.tobytes(), params.framerate)


def run_cmd(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def probe_devices(outdir: Path) -> dict[str, str]:
    probes = {
        "cards": ["cat", "/proc/asound/cards"],
        "arecord_l": ["arecord", "-l"],
        "arecord_L": ["arecord", "-L"],
        "aplay_l": ["aplay", "-l"],
        "aplay_L": ["aplay", "-L"],
    }
    out = {}
    chunks = []
    for name, cmd in probes.items():
        rc, text = run_cmd(cmd, timeout=30)
        out[name] = text
        chunks.append(f"$ {' '.join(cmd)}\nrc={rc}\n{text}\n")
    (outdir / "devices.txt").write_text("\n".join(chunks), encoding="utf-8")
    return out


def build_tts(text: str, out_wav: Path, gain: float) -> dict[str, Any]:
    try:
        import sherpa_onnx
    except Exception as exc:
        raise RuntimeError(f"sherpa_onnx TTS unavailable: {exc}") from exc

    base = Path(DEFAULT_TTS_DIR)
    model = base / "model.onnx"
    tokens = base / "tokens.txt"
    lexicon = base / "lexicon.txt"
    if not model.exists() or not tokens.exists() or not lexicon.exists():
        raise FileNotFoundError(f"TTS model files missing in {base}")

    rule_fsts = ",".join(str(p) for p in [base / "phone.fst", base / "date.fst", base / "number.fst"] if p.exists())
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(model),
                tokens=str(tokens),
                lexicon=str(lexicon),
                data_dir="",
                length_scale=DEFAULT_TTS_LENGTH_SCALE,
            ),
            num_threads=4,
            provider="cpu",
        ),
        rule_fsts=rule_fsts,
        max_num_sentences=1,
    )
    tts = sherpa_onnx.OfflineTts(cfg)
    audio = tts.generate(text.strip(), sid=DEFAULT_TTS_SID, speed=DEFAULT_TTS_SPEED)
    raw_wav = out_wav.with_name("tts_raw.wav")
    sherpa_onnx.write_wave(str(raw_wav), audio.samples, audio.sample_rate)
    if gain and abs(gain - 1.0) > 1e-3:
        apply_gain_to_wav(raw_wav, out_wav, gain)
    else:
        out_wav.write_bytes(raw_wav.read_bytes())
    info = wav_info(out_wav)
    info.update(
        {
            "tts_model_dir": str(base),
            "tts_speed": DEFAULT_TTS_SPEED,
            "tts_length_scale": DEFAULT_TTS_LENGTH_SCALE,
            "tts_gain": gain,
            "tts_sid": DEFAULT_TTS_SID,
        }
    )
    return info


def capture_with_playback(
    input_device: str,
    output_device: str,
    tts_wav: Path,
    capture_wav: Path,
    lead_sec: float,
    tail_sec: float,
) -> tuple[dict[str, Any], str, str]:
    play_info = wav_info(tts_wav)
    total_sec = max(play_info["duration_sec"] + lead_sec + tail_sec, 3.0)
    total_dur = int(math.ceil(total_sec))
    capture_cmd = [
        "arecord",
        "-D",
        input_device,
        "-f",
        PCM_FORMAT,
        "-c",
        str(CHANNELS),
        "-r",
        str(SAMPLE_RATE),
        "-d",
        str(total_dur),
        str(capture_wav),
    ]
    capture_proc = subprocess.Popen(capture_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    time.sleep(max(0.0, lead_sec))
    play_cmd = ["aplay", "-D", output_device, str(tts_wav)]
    play_proc = subprocess.Popen(play_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    play_out, play_err = play_proc.communicate(timeout=total_dur + 20)
    cap_out, cap_err = capture_proc.communicate(timeout=total_dur + 20)
    if play_proc.returncode != 0:
        raise RuntimeError(f"aplay failed rc={play_proc.returncode}: {(play_out or '') + (play_err or '')}")
    if capture_proc.returncode != 0:
        raise RuntimeError(f"arecord failed rc={capture_proc.returncode}: {(cap_out or '') + (cap_err or '')}")
    if not capture_wav.exists() or capture_wav.stat().st_size < 44:
        raise RuntimeError(f"capture wav missing or empty: {capture_wav}")
    capture_info = wav_info(capture_wav)
    capture_info.update(
        {
            "lead_sec": lead_sec,
            "tail_sec": tail_sec,
            "record_seconds_requested": total_dur,
            "play_cmd": " ".join(play_cmd),
            "capture_cmd": " ".join(capture_cmd),
            "play_returncode": play_proc.returncode,
            "capture_returncode": capture_proc.returncode,
        }
    )
    return capture_info, (play_out or "") + (play_err or ""), (cap_out or "") + (cap_err or "")


def load_voice_engine(backend: str):
    backend = backend.strip().lower()
    if backend == "sherpa_onnx":
        backend = "sherpa"
    os.environ["VOICE_BACKEND"] = backend
    os.environ["ASR_BACKEND"] = backend
    if "voice_engine" in sys.modules:
        module = importlib.reload(sys.modules["voice_engine"])
    else:
        module = importlib.import_module("voice_engine")
    engine = module.VoiceEngine()
    if not engine.load():
        raise RuntimeError(engine.last_error or f"failed to load backend {backend}")
    return engine


class AsrRunner:
    def __init__(self, backends: list[str]):
        self.backends = [self._normalize_backend(b) for b in backends]
        self.cache: dict[str, Any] = {}

    @staticmethod
    def _normalize_backend(backend: str) -> str:
        backend = backend.strip().lower()
        if backend in {"sherpa_onnx", "sherpa-onnx"}:
            return "sherpa"
        return backend

    def recognize(self, wav_path: Path, backend: str) -> BackendResult:
        backend = self._normalize_backend(backend)
        if backend not in self.cache:
            self.cache[backend] = load_voice_engine(backend)
        engine = self.cache[backend]
        with wave.open(str(wav_path), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())
        start = time.perf_counter()
        raw = engine._recognize_raw(pcm)
        asr_sec = time.perf_counter() - start
        normalized = correct_text(raw, "robot", strict=False)
        model = str(engine.status().get("model") or "")
        return BackendResult(
            backend=backend,
            model=model,
            raw_asr=raw,
            normalized=normalized,
            similarity=similarity_percent(EXPECTED_TEXT, raw),
            recognized=normalize_text(raw) == normalize_text(EXPECTED_TEXT),
            asr_sec=round(asr_sec, 4),
        )


def parse_csv_floats(text: str) -> list[float]:
    values = []
    for part in (text or "").split(","):
        part = part.strip()
        if part:
            values.append(float(part))
    return values


def summarize(results: list[dict[str, Any]], outdir: Path, meta: dict[str, Any]) -> str:
    by_backend: dict[str, list[BackendResult]] = defaultdict(list)
    for item in results:
        for backend, result in item["backend_results"].items():
            by_backend[backend].append(BackendResult(**result))

    lines = []
    lines.append(f"总测试次数：{len(results)}")
    lines.append(f"标准文本：{EXPECTED_TEXT}")
    lines.append("")
    for backend, items in by_backend.items():
        correct = sum(1 for r in items if r.recognized)
        avg_similarity = sum(r.similarity for r in items) / max(len(items), 1)
        avg_asr = sum(r.asr_sec for r in items) / max(len(items), 1)
        lines.append(f"[{backend}] 正确次数：{correct}/{len(items)}")
        lines.append(f"[{backend}] 平均文本相似度：{avg_similarity:.2f}%")
        lines.append(f"[{backend}] 平均识别耗时：{avg_asr:.3f} 秒")
        lines.append("")
    if results:
        best_item = max(
            (
                (backend, item, BackendResult(**result))
                for item in results
                for backend, result in item["backend_results"].items()
            ),
            key=lambda row: row[2].similarity,
        )
        lines.append(
            f"最佳单次结果：test={best_item[1]['id']} backend={best_item[0]} "
            f"gain={best_item[1]['gain']} lead={best_item[1]['lead_sec']} tail={best_item[1]['tail_sec']} "
            f"similarity={best_item[2].similarity:.2f}% raw={best_item[2].raw_asr!r}"
        )
    lines.append("最终推荐配置请以 results.json 中最高相似度的测试组为准。")
    summary = "\n".join(lines).strip() + "\n"
    (outdir / "summary.txt").write_text(summary, encoding="utf-8")
    return summary


def run_cases(args: argparse.Namespace) -> int:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "captures").mkdir(exist_ok=True)
    (outdir / "processed").mkdir(exist_ok=True)

    print_audio_devices("voice_loop")
    probe_devices(outdir)

    tts_wav = outdir / "tts.wav"
    print(f"[voice_loop] generating TTS: {EXPECTED_TEXT}")
    tts_info = build_tts(EXPECTED_TEXT, tts_wav, args.tts_gain)
    print(f"[voice_loop] tts saved: {tts_wav}")

    backends = [b.strip().lower() for b in args.backends.split(",") if b.strip()]
    if "all" in backends:
        backends = list(DEFAULT_BACKENDS)
    runner = AsrRunner(backends)

    if args.sweep:
        gain_list = parse_csv_floats(args.gains)
        lead_list = parse_csv_floats(args.leads)
        tail_list = parse_csv_floats(args.tails)
        test_plan = [(gain, lead, tail) for gain in gain_list for lead in lead_list for tail in tail_list]
        repeat = max(1, int(args.repeat))
    else:
        test_plan = [(float(args.voice_gain), float(args.lead_sec), float(args.tail_sec))]
        repeat = max(1, int(args.runs))

    results: list[dict[str, Any]] = []
    capture_idx = 1
    for combo_idx, (gain, lead_sec, tail_sec) in enumerate(test_plan, start=1):
        for rep in range(repeat):
            capture_path = outdir / "captures" / f"capture_{capture_idx:03d}.wav"
            processed_path = outdir / "processed" / f"capture_{capture_idx:03d}_gain{gain:.2f}.wav"
            print(f"[voice_loop] test {capture_idx:03d} combo={combo_idx} rep={rep + 1} gain={gain} lead={lead_sec} tail={tail_sec}")
            capture_info = {}
            processed_info = {}
            backend_results: dict[str, BackendResult] = {}
            try:
                capture_info, play_text, cap_text = capture_with_playback(
                    VOICE_INPUT_DEVICE,
                    AUDIO_OUTPUT_DEVICE,
                    tts_wav,
                    capture_path,
                    lead_sec,
                    tail_sec,
                )
                if play_text.strip():
                    (outdir / f"play_{capture_idx:03d}.log").write_text(play_text, encoding="utf-8")
                if cap_text.strip():
                    (outdir / f"record_{capture_idx:03d}.log").write_text(cap_text, encoding="utf-8")

                apply_gain_to_wav(capture_path, processed_path, gain)
                processed_info = wav_info(processed_path)
                for backend in backends:
                    try:
                        backend_results[backend] = runner.recognize(processed_path, backend)
                    except Exception as exc:
                        backend_results[backend] = BackendResult(
                            backend=backend,
                            model="",
                            raw_asr="",
                            normalized="",
                            similarity=0.0,
                            recognized=False,
                            asr_sec=0.0,
                            error=str(exc),
                        )
            except Exception as exc:
                backend_results = {
                    backend: BackendResult(
                        backend=backend,
                        model="",
                        raw_asr="",
                        normalized="",
                        similarity=0.0,
                        recognized=False,
                        asr_sec=0.0,
                        error=str(exc),
                    )
                    for backend in backends
                }

            result = {
                "id": capture_idx,
                "expected_text": EXPECTED_TEXT,
                "input_device": VOICE_INPUT_DEVICE,
                "output_device": AUDIO_OUTPUT_DEVICE,
                "sample_rate": SAMPLE_RATE,
                "channels": CHANNELS,
                "format": PCM_FORMAT,
                "gain": gain,
                "lead_sec": lead_sec,
                "tail_sec": tail_sec,
                "tts": tts_info,
                "capture": capture_info,
                "processed": processed_info,
                "backend_results": {
                    backend: dataclasses.asdict(value) for backend, value in backend_results.items()
                },
            }
            results.append(result)
            capture_idx += 1

    json_path = outdir / "results.json"
    json_path.write_text(
        json.dumps(
            {
                "expected_text": EXPECTED_TEXT,
                "input_device": VOICE_INPUT_DEVICE,
                "output_device": AUDIO_OUTPUT_DEVICE,
                "sample_rate": SAMPLE_RATE,
                "channels": CHANNELS,
                "format": PCM_FORMAT,
                "voice_gain": args.voice_gain,
                "tts_gain": args.tts_gain,
                "tts_backend": "sherpa_onnx",
                "tts_model_dir": DEFAULT_TTS_DIR,
                "backends": backends,
                "tests": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = summarize(results, outdir, {})
    print(summary)
    print(f"[voice_loop] results: {json_path}")
    print(f"[voice_loop] summary: {outdir / 'summary.txt'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RK3588 local voice closed-loop test tool")
    parser.add_argument("--outdir", default="/tmp/voice_loop")
    parser.add_argument("--backends", default="vosk,sherpa,whisper", help="comma list, or all")
    parser.add_argument("--runs", type=int, default=10, help="repeat count for a single config")
    parser.add_argument("--voice-gain", type=float, default=3.0, help="gain applied to capture before ASR")
    parser.add_argument("--lead-sec", type=float, default=0.5, help="recording lead time before playback")
    parser.add_argument("--tail-sec", type=float, default=0.8, help="recording tail time after playback")
    parser.add_argument("--tts-gain", type=float, default=DEFAULT_TTS_GAIN, help="output gain applied to generated TTS wav")
    parser.add_argument("--sweep", action="store_true", help="enable parameter sweep mode")
    parser.add_argument("--gains", default="1.0,1.5,2.0,2.5,3.0,4.0")
    parser.add_argument("--leads", default="0.2,0.5,1.0")
    parser.add_argument("--tails", default="0.3,0.5,0.8,1.0")
    parser.add_argument("--repeat", type=int, default=3, help="repeat count per sweep combination")
    args = parser.parse_args()
    return run_cases(args)


if __name__ == "__main__":
    raise SystemExit(main())
