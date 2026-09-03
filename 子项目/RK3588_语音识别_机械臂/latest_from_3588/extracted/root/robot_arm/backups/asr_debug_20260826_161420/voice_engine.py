"""语音引擎 - 命令识别 + 实时电平"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import wave
from collections import deque
from contextlib import suppress
from pathlib import Path

import numpy as np

from audio_config import audio_output_device, print_audio_devices, voice_input_device
from speech_context import correct_text, match_command, normalize_text as _normalize_text

WHISPER_BIN = os.getenv("WHISPER_BIN", "/tmp/whisper.cpp/build/bin/whisper-cli")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "/tmp/whisper.cpp/models/ggml-tiny.bin")
VOICE_BACKEND = os.getenv("VOICE_BACKEND", "sherpa").strip().lower()
SHERPA_ASR_DIR = os.getenv(
    "SHERPA_ASR_DIR",
    "/root/sherpa_models/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01",
)
VOSK_MODEL_DIR = os.getenv("VOSK_MODEL_DIR", "/root/robot_arm/voice/vosk-model-small-cn-0.22")
SENSEVOICE_MODEL = os.getenv(
    "SENSEVOICE_MODEL",
    "/home/ztl/.cache/modelscope/models/iic--SenseVoiceSmall/snapshots/master",
)
SENSEVOICE_FALLBACK = os.getenv("VOICE_SENSEVOICE_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
VOICE_INPUT_DEVICE = voice_input_device()
AUDIO_OUTPUT_DEVICE = audio_output_device()
VOICE_DEVICE = VOICE_INPUT_DEVICE
SAMPLE_RATE = int(os.getenv("VOICE_SAMPLE_RATE", "16000"))
FRAME_SIZE = int(os.getenv("VOICE_FRAME_SIZE", "160"))
GAIN = float(os.getenv("VOICE_GAIN", "3.0"))
TRIGGER_PEAK = float(os.getenv("VOICE_TRIGGER_PEAK", "0.085"))
SILENCE_PEAK = float(os.getenv("VOICE_SILENCE_PEAK", "0.052"))
MIN_RECORD_SEC = float(os.getenv("VOICE_MIN_RECORD_SEC", "0.22"))
MAX_RECORD_SEC = float(os.getenv("VOICE_MAX_RECORD_SEC", "2.20"))
POST_SILENCE_SEC = float(os.getenv("VOICE_POST_SILENCE_SEC", "0.48"))
COOLDOWN_SEC = float(os.getenv("VOICE_COOLDOWN_SEC", "0.08"))
PRE_ROLL_FRAMES = int(os.getenv("VOICE_PRE_ROLL_FRAMES", "8"))
SHERPA_FINAL_PAD_SEC = float(os.getenv("VOICE_SHERPA_FINAL_PAD_SEC", "0.28"))
SHERPA_FALLBACK = os.getenv("VOICE_SHERPA_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
TIMING_LOG = os.getenv("VOICE_TIMING_LOG", "/tmp/robot_voice_timing.log")
DEBUG_WAV_DIR = Path(os.getenv("VOICE_DEBUG_WAV_DIR", "/tmp/voice_debug"))

COMMAND_ALIASES = {
    "直立": ("直立", "直", "立", "竖", "站", "起", "起来", "直起", "立起", "站立", "竖立", "竖直", "立正", "抬起", "升起", "立起来", "竖起来", "竖直起来", "之力", "直力", "支立", "之立", "只立", "智力", "治理", "实力", "纸币", "指令"),
    "放平": ("放平", "放", "平", "平放", "放下", "放低", "下放", "躺平", "摆平", "铺平", "摊平", "展开", "前倾", "放倒", "倒下", "手臂放平", "机械臂放平", "方平", "防平", "放屏", "放瓶", "放坪", "访评"),
    "抓取": ("抓取", "抓", "取", "抓起", "抓紧", "抓住", "抓起来", "拿取", "拿起", "拿起来", "夹取", "夹住", "夹紧", "夹起来", "取物", "抓物", "抓东西", "拿东西", "抓去", "爪取", "早取", "找取", "他取", "它取", "夹去", "抓举", "格局", "各取", "搁取"),
    "搬运": ("搬运", "搬", "搬过去", "移过去", "挪动", "挪过去", "拿过去", "放过去", "移动", "迁移", "转移", "转过去", "转一", "转椅"),
    "停止": ("停止", "停", "停下", "停住", "别动", "不要动", "暂停", "急停", "停止动作", "停下来", "停一停", "别转", "别抓", "别动了"),
    "张开": ("张开", "开", "打开", "松开", "放开", "打开夹子", "松开夹子", "开夹", "开爪", "夹爪打开", "张开夹爪", "张凯", "章开", "张卡", "张夹", "张爪", "张家"),
    "闭合": ("闭合", "合", "合上", "闭上", "关", "关闭", "夹紧", "夹住", "关夹", "合爪", "闭爪", "夹爪闭合", "夹爪合上", "并合", "闭盒"),
    "复位": ("复位", "回", "回位", "归位", "回中", "回正", "回原点", "回到原点", "恢复", "重置", "复原", "归中", "回到中间", "付位", "腹位"),
}

VOSK_GRAMMAR_ALIASES = {
    "直立": ("直立", "立", "站", "站立", "立正"),
    "放平": ("放平", "放", "平", "放下"),
    "抓取": ("抓取", "抓", "取", "抓住", "抓紧"),
    "搬运": ("搬运", "搬", "移动", "转移"),
    "停止": ("停止", "停", "停下", "暂停"),
    "张开": ("张开", "开", "打开", "松开", "放开"),
    "闭合": ("闭合", "合", "关", "关闭", "夹紧", "夹住"),
    "复位": ("复位", "回", "回位", "归位", "恢复", "重置"),
}


COMMAND_ALIASES.update({
    "\u53f3\u8f6c\u79fb": (
        "\u53f3\u8f6c\u79fb", "\u5411\u53f3\u8f6c\u79fb", "\u5411\u53f3\u8f6c",
        "\u53f3\u8f6c", "\u53f3\u8fb9\u8f6c\u79fb", "\u642c\u5230\u53f3\u8fb9",
    ),
    "\u5de6\u8f6c\u79fb": (
        "\u5de6\u8f6c\u79fb", "\u5411\u5de6\u8f6c\u79fb", "\u5411\u5de6\u8f6c",
        "\u5de6\u8f6c", "\u5de6\u8fb9\u8f6c\u79fb", "\u642c\u5230\u5de6\u8fb9",
    ),
})
VOSK_GRAMMAR_ALIASES.update({
    "\u53f3\u8f6c\u79fb": ("\u53f3\u8f6c\u79fb", "\u53f3\u8f6c", "\u5411\u53f3\u8f6c"),
    "\u5de6\u8f6c\u79fb": ("\u5de6\u8f6c\u79fb", "\u5de6\u8f6c", "\u5411\u5de6\u8f6c"),
})

_BANYUN_ALIASES = (
    "\u642c\u8fd0", "\u822c\u8fd0", "\u534a\u8fd0", "\u73ed\u8fd0", "\u5e2e\u8fd0",
    "\u642c\u4e91", "\u642c\u6655", "\u642c\u97f5", "\u642c\u7528", "\u642c\u5b55",
    "\u642c", "\u8fd0", "\u8fd0\u8f93", "\u8fd0\u9001", "\u8f6c\u8fd0",
    "\u642c\u4e00\u4e0b", "\u642c\u4e00\u642c", "\u5f00\u59cb\u642c",
    "\u5f00\u59cb\u642c\u8fd0", "\u6267\u884c\u642c\u8fd0", "\u642c\u8fc7\u53bb",
    "\u642c\u5230", "\u642c\u8d70", "\u642c\u8d27", "\u642c\u7269",
    "\u79fb\u8fc7\u53bb", "\u79fb\u52a8", "\u632a\u52a8", "\u62ff\u8fc7\u53bb",
    "\u653e\u8fc7\u53bb", "\u8f6c\u79fb", "\u8f6c\u8fc7\u53bb",
)
COMMAND_ALIASES["\u642c\u8fd0"] = tuple(dict.fromkeys(COMMAND_ALIASES.get("\u642c\u8fd0", ()) + _BANYUN_ALIASES))
VOSK_GRAMMAR_ALIASES["\u642c\u8fd0"] = tuple(dict.fromkeys(VOSK_GRAMMAR_ALIASES.get("\u642c\u8fd0", ()) + _BANYUN_ALIASES))


def timing_log(message: str) -> None:
    try:
        with open(TIMING_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.time():.3f} {message}\n")
    except Exception:
        pass

class VoiceEngine:
    def __init__(self):
        print_audio_devices("voice")
        self.running = False
        self._thread = None
        self._loaded = False
        self._busy = False
        self._backend = VOICE_BACKEND
        self._sherpa_model = None
        self._sensevoice_model = None
        self._vosk_model = None
        self._vosk_grammar: str | None = "[]"
        self.use_command_grammar = True
        self.command_queue: queue.Queue[str] = queue.Queue()
        self.commands = {}
        self._device = VOICE_DEVICE or self._find_mic()
        self.last_peak = 0.0
        self.last_text = ""
        self.last_raw_text = ""
        self.last_normalized_text = ""
        self.last_debug_wav = ""
        self.last_audio_sec = 0.0
        self.last_asr_sec = 0.0
        self.last_command = ""
        self.last_error = ""
        self._last_recog_time = 0.0
        self._robot = None

    def load(self, device=None):
        if device:
            self._device = device
        elif VOICE_DEVICE:
            self._device = VOICE_DEVICE
        else:
            self._device = self._find_mic()

        self._backend = self._pick_backend()
        if self._backend == "sherpa":
            if not self._load_sherpa_model():
                self._backend = "vosk" if self._find_vosk_model() else "whisper"
            elif SENSEVOICE_FALLBACK:
                self._load_sensevoice_model()

        if self._backend == "vosk":
            if not self._load_vosk_model():
                self._backend = "whisper"
            elif SHERPA_FALLBACK and self._sherpa_model is None:
                self._load_sherpa_model()

        if self._backend == "whisper":
            if not Path(WHISPER_BIN).exists():
                print("[语音] whisper.cpp未找到")
                return False
            if not Path(WHISPER_MODEL).exists():
                print("[语音] 模型未找到")
                return False

        self._loaded = True
        self.last_error = ""
        print(f"[语音] {self._backend}就绪 ({self._device})")
        return True

    def _pick_backend(self) -> str:
        if VOICE_BACKEND in {"sherpa", "sherpa_onnx", "auto"} and self._find_sherpa_model():
            return "sherpa"
        if VOICE_BACKEND in {"vosk", "auto"} and self._find_vosk_model():
            return "vosk"
        return "whisper"

    def _find_sherpa_model(self) -> str | None:
        model = Path(SHERPA_ASR_DIR) / "model.int8.onnx"
        tokens = Path(SHERPA_ASR_DIR) / "tokens.txt"
        return SHERPA_ASR_DIR if model.exists() and tokens.exists() else None

    def _find_vosk_model(self) -> str | None:
        candidates = [
            os.getenv("VOSK_MODEL_DIR", ""),
            VOSK_MODEL_DIR,
            "/root/robot_arm/voice/vosk-model-cn-0.22",
            "/root/robot_arm/voice/vosk-model-small-cn-0.22",
        ]
        for path in candidates:
            if path and Path(path).exists():
                return path
        return None

    def _find_sensevoice_model(self) -> str | None:
        model_path = Path(SENSEVOICE_MODEL)
        if model_path.exists():
            return str(model_path)
        return None

    def _command_aliases(self) -> list[str]:
        aliases: list[str] = []
        keys = list(self.commands.keys()) or list(VOSK_GRAMMAR_ALIASES.keys())
        for kw in keys:
            aliases.append(kw)
            aliases.extend(VOSK_GRAMMAR_ALIASES.get(kw, (kw,)))
            aliases.extend(COMMAND_ALIASES.get(kw, ()))
        return sorted(set(alias for alias in aliases if alias))

    def _build_vosk_grammar(self) -> str:
        if not self.use_command_grammar:
            return ""
        phrases = self._command_aliases()
        return json.dumps(phrases, ensure_ascii=False)

    def _load_vosk_model(self) -> bool:
        try:
            from vosk import Model

            model_dir = self._find_vosk_model()
            if not model_dir:
                self.last_error = "vosk model not found"
                return False
            self._vosk_model = Model(model_dir)
            self._vosk_grammar = self._build_vosk_grammar()
            print(f"[语音] Vosk模型就绪 ({model_dir})")
            return True
        except Exception as e:
            self.last_error = str(e)
            print(f"[语音] Vosk加载失败:{e}")
            return False

    def _load_sherpa_model(self) -> bool:
        try:
            model_dir = self._find_sherpa_model()
            if not model_dir:
                self.last_error = "sherpa model not found"
                return False
            import sherpa_onnx

            self._sherpa_model = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
                tokens=str(Path(model_dir) / "tokens.txt"),
                model=str(Path(model_dir) / "model.int8.onnx"),
                num_threads=3,
                sample_rate=SAMPLE_RATE,
                feature_dim=80,
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=0.8,
                rule2_min_trailing_silence=0.25,
                rule3_min_utterance_length=6.0,
                decoding_method="greedy_search",
                provider="cpu",
            )
            print(f"[语音] sherpa模型就绪 ({model_dir})")
            return True
        except Exception as e:
            self.last_error = str(e)
            print(f"[语音] sherpa加载失败:{e}")
            return False

    def _load_sensevoice_model(self) -> bool:
        try:
            model_dir = self._find_sensevoice_model()
            if not model_dir:
                self.last_error = "sensevoice model not found"
                return False
            from funasr import AutoModel

            self._sensevoice_model = AutoModel(
                model=model_dir,
                trust_remote_code=True,
                disable_update=True,
            )
            print(f"[语音] SenseVoice兜底就绪 ({model_dir})")
            return True
        except Exception as e:
            self._sensevoice_model = None
            self.last_error = str(e)
            print(f"[语音] SenseVoice加载失败:{e}")
            return False

    def _find_mic(self):
        try:
            with open("/proc/asound/cards", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if "XFM" in line:
                        return "dsnoop:CARD=XFMDPV0018,DEV=0"
        except Exception:
            pass
        return "dsnoop:CARD=XFMDPV0018,DEV=0"

    def set_commands(self, cmds):
        self.commands = dict(cmds or {})
        if self._loaded and self._backend == "vosk":
            self._vosk_grammar = self._build_vosk_grammar()

    def start(self):
        if self.running:
            return True
        if not self._loaded:
            self.last_error = "voice model not loaded"
            return False
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[语音] 监听中")
        return True

    def stop(self):
        self.running = False
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._busy = False
        self.last_peak = 0.0

    def _open_pcm(self):
        import alsaaudio

        return alsaaudio.PCM(
            alsaaudio.PCM_CAPTURE,
            alsaaudio.PCM_NORMAL,
            self._device,
            channels=1,
            rate=SAMPLE_RATE,
            format=alsaaudio.PCM_FORMAT_S16_LE,
            periodsize=FRAME_SIZE,
        )

    def _robot_busy(self) -> bool:
        if not self._robot:
            return False
        try:
            return bool(getattr(self._robot, "is_moving", False) or getattr(self._robot, "is_rotating", False))
        except Exception:
            return False

    def _drain_pcm(self, inp, limit: int = 8) -> None:
        for _ in range(limit):
            try:
                length, _data = inp.read()
            except Exception:
                return
            if length <= 0:
                return

    def _close_pcm(self, inp) -> None:
        close = getattr(inp, "close", None)
        if callable(close):
            with suppress(Exception):
                close()

    def _loop(self):
        while self.running:
            try:
                inp = self._open_pcm()
                break
            except Exception as e:
                self.last_error = str(e)
                print(f"[语音] ALSA重试:{e}")
                time.sleep(2)
        else:
            return

        busy_seen = False
        consecutive_misses = 0
        while self.running:
            try:
                if self._robot_busy():
                    busy_seen = True
                    self._drain_pcm(inp, 4)
                    time.sleep(0.05)
                    continue

                if busy_seen:
                    self._close_pcm(inp)
                    time.sleep(0.18)
                    inp = self._open_pcm()
                    busy_seen = False
                    consecutive_misses = 0

                t_record = time.time()
                audio, peak = self._record_utterance(inp)
                record_sec = time.time() - t_record
                self.last_peak = peak
                if not audio or peak < TRIGGER_PEAK:
                    continue
                if time.time() - self._last_recog_time < COOLDOWN_SEC:
                    continue

                self._busy = True
                t_asr = time.time()
                raw_text, normalized_text = self._recognize_pair(audio)
                asr_sec = time.time() - t_asr
                self._busy = False
                debug_wav = self._save_debug_wav(audio)
                if not normalized_text:
                    timing_log(
                        f"miss record={record_sec:.3f} asr={asr_sec:.3f} "
                        f"audio={len(audio) / 2 / SAMPLE_RATE:.3f} peak={peak:.3f} "
                        f"backend={self._backend} device={self._device} wav={debug_wav} raw={raw_text!r}"
                    )
                    consecutive_misses += 1
                    if consecutive_misses >= 4:
                        timing_log("pcm_reopen reason=consecutive_misses")
                        self._close_pcm(inp)
                        time.sleep(0.12)
                        inp = self._open_pcm()
                        consecutive_misses = 0
                    continue

                self.last_raw_text = raw_text
                self.last_normalized_text = normalized_text
                self.last_text = normalized_text
                self.last_audio_sec = len(audio) / 2 / SAMPLE_RATE
                self.last_asr_sec = asr_sec
                self.last_debug_wav = debug_wav
                consecutive_misses = 0
                self.last_error = ""
                timing_log(
                    f"hit record={record_sec:.3f} asr={asr_sec:.3f} "
                    f"audio={self.last_audio_sec:.3f} peak={peak:.3f} backend={self._backend} "
                    f"device={self._device} rate={SAMPLE_RATE} channels=1 format=s16le "
                    f"wav={debug_wav} raw={raw_text!r} normalized={normalized_text!r}"
                )
                print(f"[语音] {self.last_text}", flush=True)
                self._match(self.last_text)
            except Exception as e:
                self._busy = False
                self.last_error = str(e)
                print(f"[语音] 错误:{e}")
                time.sleep(1)

    def _record_utterance(self, inp):
        pre_roll = deque(maxlen=PRE_ROLL_FRAMES)
        frames = []
        speaking = False
        silence_frames = 0
        peak = 0.0
        started_at = time.monotonic()
        min_samples = max(1, int(MIN_RECORD_SEC * SAMPLE_RATE))
        max_samples = max(min_samples, int(MAX_RECORD_SEC * SAMPLE_RATE))
        post_silence_samples = max(1, int(POST_SILENCE_SEC * SAMPLE_RATE))
        captured_samples = 0
        silence_samples = 0

        while self.running:
            try:
                length, data = inp.read()
            except Exception as e:
                self.last_error = str(e)
                break

            if length <= 0:
                time.sleep(0.01)
                continue

            raw = np.frombuffer(data, dtype=np.int16)
            if raw.size == 0:
                continue

            boosted = np.clip(raw.astype(np.float32) * GAIN, -32768, 32767).astype(np.int16)
            frame_peak = float(np.max(np.abs(boosted))) / 32768.0
            self.last_peak = frame_peak
            pre_roll.append(boosted.tobytes())

            if frame_peak >= TRIGGER_PEAK:
                if not speaking:
                    speaking = True
                    frames.extend(pre_roll)
                    captured_samples += sum(len(frame) // 2 for frame in pre_roll)
                    pre_roll.clear()
                else:
                    frames.append(boosted.tobytes())
                    captured_samples += boosted.size
                silence_frames = 0
                silence_samples = 0
                peak = max(peak, frame_peak)
            elif speaking:
                frames.append(boosted.tobytes())
                captured_samples += boosted.size
                peak = max(peak, frame_peak)
                if frame_peak < SILENCE_PEAK:
                    silence_frames += 1
                    silence_samples += boosted.size
                else:
                    silence_frames = 0
                    silence_samples = 0
                if captured_samples >= min_samples and silence_samples >= post_silence_samples:
                    break

            if speaking and captured_samples >= max_samples:
                break
            if not speaking and time.monotonic() - started_at > 0.35:
                pre_roll.clear()

        return (b"".join(frames) if speaking else b""), peak

    def _save_debug_wav(self, audio: bytes) -> str:
        if not audio:
            return ""
        try:
            DEBUG_WAV_DIR.mkdir(parents=True, exist_ok=True)
            path = DEBUG_WAV_DIR / f"voice_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.wav"
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio)
            return str(path)
        except Exception as exc:
            self.last_error = f"save debug wav failed: {exc}"
            return ""

    def _normalize_asr_text(self, text: str) -> str:
        return correct_text(text, "robot", strict=True)

    def _recognize_pair(self, audio: bytes) -> tuple[str, str]:
        raw = self._recognize_raw(audio)
        normalized = self._normalize_asr_text(raw)
        return raw, normalized

    def _recognize(self, audio: bytes) -> str:
        return self._recognize_pair(audio)[1]

    def _recognize_raw(self, audio: bytes) -> str:
        if self._backend == "sherpa":
            text = self._recognize_sherpa(audio)
            if text and match_command(text, tuple(self.commands.keys())):
                return text
            if self._sensevoice_model is not None:
                reviewed = self._recognize_sensevoice(audio)
                if reviewed:
                    timing_log(f"sensevoice_fallback primary={text!r} reviewed={reviewed!r}")
                    return reviewed
            return text
        if self._backend == "vosk":
            text = self._recognize_vosk(audio)
            if text:
                return text
            if SHERPA_FALLBACK and self._sherpa_model is not None:
                timing_log("fallback_sherpa reason=vosk_empty")
                return self._recognize_sherpa(audio)
            return ""

        fd, wav_path = tempfile.mkstemp(prefix="whisper_live_", suffix=".wav")
        os.close(fd)
        try:
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio)

            result = subprocess.run(
                [
                    WHISPER_BIN,
                    "-m",
                    WHISPER_MODEL,
                    "-l",
                    "zh",
                    "-f",
                    wav_path,
                    "--no-timestamps",
                    "-t",
                    "6",
                    "--best-of",
                    "1",
                    "--beam-size",
                    "1",
                    "--no-fallback",
                    "-ac",
                    "512",
                    "-np",
                    "--prompt",
                    "直立。放平。抓取。搬运。停止。张开。闭合。复位。",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            return self._extract_text(result.stdout)
        except subprocess.TimeoutExpired:
            self.last_error = "whisper timeout"
            return ""
        finally:
            with suppress(FileNotFoundError):
                os.remove(wav_path)

    def _recognize_vosk(self, audio: bytes) -> str:
        if self._vosk_model is None:
            return ""
        try:
            from vosk import KaldiRecognizer

            if self._vosk_grammar:
                rec = KaldiRecognizer(self._vosk_model, SAMPLE_RATE, self._vosk_grammar)
            else:
                rec = KaldiRecognizer(self._vosk_model, SAMPLE_RATE)
            rec.SetWords(True)
            chunk = 4000
            for idx in range(0, len(audio), chunk):
                rec.AcceptWaveform(audio[idx : idx + chunk])
            result = json.loads(rec.FinalResult())
            return result.get("text", "").strip()
        except Exception as e:
            self.last_error = str(e)
            return ""

    def _recognize_sherpa(self, audio: bytes) -> str:
        if self._sherpa_model is None:
            return ""
        try:
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            stream = self._sherpa_model.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            stream.accept_waveform(SAMPLE_RATE, np.zeros(int(SHERPA_FINAL_PAD_SEC * SAMPLE_RATE), dtype=np.float32))
            stream.input_finished()
            while self._sherpa_model.is_ready(stream):
                self._sherpa_model.decode_stream(stream)
            result = self._sherpa_model.get_result_all(stream)
            return (result.text or "").strip()
        except Exception as e:
            self.last_error = str(e)
            return ""

    def _recognize_sensevoice(self, audio: bytes) -> str:
        if self._sensevoice_model is None:
            return ""
        fd, wav_path = tempfile.mkstemp(prefix="robot_sensevoice_", suffix=".wav")
        os.close(fd)
        try:
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio)
            res = self._sensevoice_model.generate(
                input=wav_path,
                cache={},
                language="zh",
                use_itn=True,
            )
            if not res:
                return ""
            text = str(res[0].get("text", ""))
            text = re.sub(r"<\|.*?\|>", "", text).strip()
            return text
        except Exception as e:
            self.last_error = str(e)
            return ""
        finally:
            with suppress(FileNotFoundError):
                os.remove(wav_path)

    def _extract_text(self, stdout: str) -> str:
        ignored = ("whisper_", "system_", "main:", "read_audio", "WARNING")
        for line in stdout.splitlines():
            text = line.strip().strip("()[]{} \t")
            if text and not text.startswith(ignored):
                return text
        return ""

    def _match(self, text):
        if not text:
            return
        self._last_recog_time = time.time()
        matched = match_command(text, tuple(self.commands.keys()))

        for kw, cb in self.commands.items():
            if kw == matched:
                self.last_command = kw
                self.last_error = ""
                print(f"[语音] 匹配:{kw}")
                self.command_queue.put(kw)
                if callable(cb):
                    try:
                        cb(kw)
                    except Exception as e:
                        self.last_error = str(e)
                        print(f"[语音] 回调:{e}")
                return

    def get_command(self, timeout=0.0):
        try:
            return self.command_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def status(self):
        if self._backend == "sherpa":
            model_name = Path(self._find_sherpa_model() or "").name
            if self._sensevoice_model is not None:
                model_name += "+SenseVoice"
        elif self._backend == "whisper":
            model_name = Path(WHISPER_MODEL).name
        else:
            model_name = Path(self._find_vosk_model() or "").name
        return {
            "running": self.running,
            "loaded": self._loaded,
            "busy": self._busy,
            "backend": self._backend,
            "device": self._device,
            "input_device": self._device,
            "output_device": AUDIO_OUTPUT_DEVICE,
            "model": model_name,
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "pcm_format": "s16le",
            "peak": float(self.last_peak if self.running else 0.0),
            "text": self.last_text,
            "last_text": self.last_text,
            "raw_asr": self.last_raw_text,
            "normalized_text": self.last_normalized_text,
            "last_debug_wav": self.last_debug_wav,
            "last_audio_sec": self.last_audio_sec,
            "last_asr_sec": self.last_asr_sec,
            "last_command": self.last_command,
            "last_error": self.last_error,
            "cooldown": COOLDOWN_SEC,
        }
