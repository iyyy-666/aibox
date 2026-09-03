"""Shared audio playback helpers for RK3588 apps."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import wave
from contextlib import suppress
from pathlib import Path

import numpy as np


PLAYBACK_RATE = int(os.getenv("AUDIO_PLAYBACK_RATE", "48000"))
PLAYBACK_CHANNELS = int(os.getenv("AUDIO_PLAYBACK_CHANNELS", "2"))
PLAYBACK_FORMAT = os.getenv("AUDIO_PLAYBACK_FORMAT", "s16le")


def _convert_with_ffmpeg(src: str, dst: str) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        src,
        "-ar",
        str(PLAYBACK_RATE),
        "-ac",
        str(PLAYBACK_CHANNELS),
        "-acodec",
        "pcm_s16le",
        dst,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    return proc.returncode == 0 and Path(dst).exists() and Path(dst).stat().st_size > 1024


def normalize_playback_wav(src_path: str, gain: float = 1.0, target_rate: int | None = None, target_channels: int | None = None) -> str:
    target_rate = int(target_rate or PLAYBACK_RATE)
    target_channels = int(target_channels or PLAYBACK_CHANNELS)
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(src_path)
    fd, dst = tempfile.mkstemp(prefix="rk3588_play_", suffix=".wav")
    os.close(fd)
    dst_path = Path(dst)
    try:
        if not _convert_with_ffmpeg(str(src), str(dst_path)):
            with wave.open(str(src), "rb") as wf:
                params = wf.getparams()
                data = wf.readframes(wf.getnframes())
            audio = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if gain and abs(gain - 1.0) > 1e-3 and audio.size:
                audio = np.clip(audio * gain, -32768, 32767)
            audio = audio.astype(np.int16)
            channels = params.nchannels
            if channels != target_channels and audio.size:
                if channels == 1 and target_channels == 2:
                    audio = np.repeat(audio.reshape(-1, 1), 2, axis=1).reshape(-1)
                elif channels == 2 and target_channels == 1:
                    audio = audio.reshape(-1, 2).mean(axis=1).astype(np.int16)
                channels = target_channels
            with wave.open(str(dst_path), "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(target_rate)
                wf.writeframes(audio.tobytes())
        return str(dst_path)
    except Exception:
        with suppress(FileNotFoundError):
            dst_path.unlink()
        raise


def play_blocking(device: str, wav_path: str, timeout: int = 60) -> tuple[int, float, str]:
    start = time.perf_counter()
    proc = subprocess.run(
        ["aplay", "-q", "-D", device, wav_path],
        capture_output=True,
        text=True,
        timeout=timeout,
        errors="replace",
    )
    elapsed = time.perf_counter() - start
    stderr = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, elapsed, stderr
