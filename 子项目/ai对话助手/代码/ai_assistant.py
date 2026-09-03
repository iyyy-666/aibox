"""AI voice assistant for RK3588.

Fast interruptible ASR -> local LLM -> Mandarin TTS pipeline.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time
import wave
from collections import deque
from contextlib import suppress
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import ttk

from audio_config import audio_output_device, print_audio_devices, voice_input_device
from audio_playback import normalize_playback_wav, play_blocking
from speech_context import correct_text
from voice_engine import adaptive_threshold, prefer_reviewed_asr, trim_audio_edges


WHISPER_BIN = os.getenv("WHISPER_BIN", "/tmp/whisper.cpp/build/bin/whisper-cli")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "/tmp/whisper.cpp/models/ggml-base.bin")
ASR_BACKEND = os.getenv("ASR_BACKEND", "auto").strip().lower()
PARAFORMER_ASR_DIR = os.getenv("PARAFORMER_ASR_DIR", "/root/sherpa_models/paraformer-large-int8")
SHERPA_ASR_DIR = os.getenv(
    "SHERPA_ASR_DIR",
    "/root/sherpa_models/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01",
)
SHERPA_TTS_DIR = os.getenv("SHERPA_TTS_DIR", "/root/sherpa_models/vits-melo-tts-zh_en")
SENSEVOICE_LOCAL = "/home/ztl/.cache/modelscope/models/iic--SenseVoiceSmall/snapshots/master"
SENSEVOICE_MODEL = os.getenv(
    "SENSEVOICE_MODEL",
    SENSEVOICE_LOCAL if Path(SENSEVOICE_LOCAL).exists() else "iic/SenseVoiceSmall",
)
LLM_MODEL = os.getenv("LLM_MODEL", "/root/llm_models/qwen2.5-3b-instruct-q4_k_m.gguf")
LLM_PRELOAD = os.getenv("AI_LLM_PRELOAD", "0").strip().lower() in {"1", "true", "yes", "on"}
LLM_MIN_AVAILABLE_MB = int(os.getenv("AI_LLM_MIN_AVAILABLE_MB", "3600"))
TTS_MODEL = os.getenv("TTS_MODEL", "/root/piper_voices/zh_CN-huayan-medium.onnx")
TTS_CONFIG = os.getenv("TTS_CONFIG", "/root/piper_voices/zh_CN-huayan-medium.onnx.json")
VOICE_DEVICE = voice_input_device()
TTS_DEVICE = audio_output_device()
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
EDGE_TTS_ENABLED = os.getenv("AI_EDGE_TTS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}

SAMPLE_RATE = 16000
FRAME_SIZE = int(os.getenv("AI_FRAME_SIZE", "160"))
GAIN = float(os.getenv("AI_VOICE_GAIN", "3.0"))
MANUAL_MAX_RECORD_SEC = float(os.getenv("AI_MANUAL_MAX_RECORD_SEC", "20.0"))
MANUAL_EDGE_TRIM_SEC = float(os.getenv("AI_MANUAL_EDGE_TRIM_SEC", "0.20"))
MANUAL_MIN_PEAK = float(os.getenv("AI_MANUAL_MIN_PEAK", "0.015"))
MANUAL_MIN_RMS = float(os.getenv("AI_MANUAL_MIN_RMS", "0.003"))
TRIGGER_PEAK = float(os.getenv("AI_TRIGGER_PEAK", "0.038"))
BARGE_IN_TRIGGER_PEAK = float(os.getenv("AI_BARGE_IN_TRIGGER_PEAK", "0.095"))
BARGE_IN_ENABLED = os.getenv("AI_BARGE_IN_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
SILENCE_PEAK = float(os.getenv("AI_SILENCE_PEAK", "0.022"))
MIN_RECORD_SEC = float(os.getenv("AI_MIN_RECORD_SEC", "0.56"))
MAX_RECORD_SEC = float(os.getenv("AI_MAX_RECORD_SEC", "5.2"))
POST_SILENCE_SEC = float(os.getenv("AI_POST_SILENCE_SEC", "0.86"))
FAST_POST_SILENCE_SEC = float(os.getenv("AI_FAST_POST_SILENCE_SEC", "0.72"))
INTERRUPT_MIN_SEC = float(os.getenv("AI_INTERRUPT_MIN_SEC", "0.25"))
NOISE_CALIBRATE_SEC = float(os.getenv("AI_NOISE_CALIBRATE_SEC", "0.35"))
NOISE_TRIGGER_MULT = float(os.getenv("AI_NOISE_TRIGGER_MULT", "1.25"))
NOISE_SILENCE_MULT = float(os.getenv("AI_NOISE_SILENCE_MULT", "1.05"))
MAX_DYNAMIC_TRIGGER = float(os.getenv("AI_MAX_DYNAMIC_TRIGGER", "0.22"))
MAX_DYNAMIC_SILENCE = float(os.getenv("AI_MAX_DYNAMIC_SILENCE", "0.14"))
MIN_VALID_PEAK_MARGIN = float(os.getenv("AI_MIN_VALID_PEAK_MARGIN", "0.003"))
MIN_VALID_AUDIO_SEC = float(os.getenv("AI_MIN_VALID_AUDIO_SEC", "0.12"))
TTS_OUTPUT_GAIN = float(os.getenv("AI_TTS_OUTPUT_GAIN", "1.45"))
TTS_TARGET_PEAK = float(os.getenv("AI_TTS_TARGET_PEAK", "0.72"))
TTS_MAX_GAIN = float(os.getenv("AI_TTS_MAX_GAIN", "2400"))
SHERPA_TTS_SID = int(os.getenv("AI_SHERPA_TTS_SID", "0"))
SHERPA_TTS_SPEED = float(os.getenv("AI_SHERPA_TTS_SPEED", "0.8"))
SHERPA_TTS_LENGTH_SCALE = float(os.getenv("AI_SHERPA_TTS_LENGTH_SCALE", "1.05"))
SHERPA_TTS_WAIT_SEC = float(os.getenv("AI_SHERPA_TTS_WAIT_SEC", "12.0"))
TIMING_LOG = os.getenv("AI_TIMING_LOG", "/tmp/ai_assistant_timing.log")
SECOND_PASS_ASR = os.getenv("AI_SECOND_PASS_ASR", "1").strip().lower() in {"1", "true", "yes", "on"}
SECOND_PASS_MIN_SEC = float(os.getenv("AI_SECOND_PASS_MIN_SEC", "0.45"))

SYSTEM_PROMPT = (
    "你是运行在本地设备上的中文语音对话助手，和用户像日常聊天一样交流。"
    "用户喜欢你称呼他为“小帅”，开场、确认和合适的时候可以自然这样叫他，但不要每句话都重复。"
    "回答先给结论，再补一两句关键原因；不要机械复述用户问题，不要说空泛套话。"
    "用户的语音识别文本可能有同音错字，你要结合上下文猜真实意图；如果不确定，就用一句话追问确认。"
    "默认用普通话中文回答，语气自然、聪明、简洁。英文、数字、代码或算式保留原义，但朗读时不要逐个念标点。"
    "除非用户要求详细解释，否则控制在一到四句话；能直接办的事就直接说怎么做。"
)

PUNCT_TABLE = str.maketrans({
    "，": " ", "。": " ", "？": " ", "！": " ", "；": " ", "：": " ",
    ",": " ", ".": " ", "?": " ", "!": " ", ";": " ", ":": " ",
    "“": " ", "”": " ", "‘": " ", "’": " ", "\"": " ", "'": " ",
    "（": " ", "）": " ", "(": " ", ")": " ", "[": " ", "]": " ",
    "{": " ", "}": " ", "《": " ", "》": " ", "<": " ", ">": " ",
    "#": " ", "@": " ", "$": " ", "%": " ", "&": " ", "*": " ",
    "_": " ", "|": " ", "\\": " ", "/": " ", "~": " ", "`": " ",
})


def write_wav(path: str, audio: bytes, rate: int = SAMPLE_RATE) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(audio)


def boost_wav_file(path: str, gain: float) -> None:
    try:
        with wave.open(path, "rb") as wf:
            params = wf.getparams()
            data = wf.readframes(wf.getnframes())
        if params.sampwidth != 2:
            return
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return
        peak = float(np.max(np.abs(samples)))
        scale = max(gain, 1.0)
        if peak > 0 and TTS_TARGET_PEAK > 0:
            target = max(1000.0, min(32767.0, TTS_TARGET_PEAK * 32767.0))
            scale = max(scale, min(TTS_MAX_GAIN, target / peak))
        if scale <= 1.01:
            return
        boosted = np.clip(samples * scale, -32768, 32767).astype(np.int16)
        out_channels = params.nchannels
        if params.nchannels == 1:
            boosted = np.repeat(boosted.reshape(-1, 1), 2, axis=1).reshape(-1)
            out_channels = 2
        with wave.open(path, "wb") as wf:
            wf.setnchannels(out_channels)
            wf.setsampwidth(params.sampwidth)
            wf.setframerate(params.framerate)
            wf.setcomptype(params.comptype, params.compname)
            wf.writeframes(boosted.tobytes())
    except Exception:
        pass


def timing_log(message: str) -> None:
    try:
        with open(TIMING_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.time():.3f} {message}\n")
    except Exception:
        pass


def clean_asr_text(text: str) -> str:
    text = re.sub(r"<\|.*?\|>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.strip().strip("()[]{} \t\r\n")
    text = re.sub(r"^\[[^\]]+\]", "", text).strip()
    noise = ("字幕", "谢谢观看", "感谢观看", "请不吝点赞", "转发", "订阅")
    if any(x in text for x in noise):
        return ""
    return text[:160]


def normalize_common_asr(text: str) -> str:
    compact = re.sub(r"[\s，。！？,.!?]+", "", text)
    latin = re.sub(r"[^A-Za-z]+", "", text or "").lower()
    if latin in {"nihao", "ninhao", "hello", "hi", "hey"}:
        return "你好"
    fixes = {
        "泥好": "你好",
        "你号": "你好",
        "您好": "你好",
        "小衰": "小帅",
        "小率": "小帅",
        "小水": "小帅",
        "小睡": "小帅",
        "小谁": "小帅",
        "肖帅": "小帅",
        "晓帅": "小帅",
        "小心星": "小星星",
        "小猩猩": "小星星",
        "两只老": "两只老虎",
        "杨知老": "两只老虎",
        "梁只老虎": "两只老虎",
    }
    for wrong, right in fixes.items():
        if wrong in compact:
            return right if len(compact) <= len(wrong) + 3 else text.replace(wrong, right)
    return correct_text(text, "assistant")


def is_fast_greeting(text: str) -> bool:
    compact = re.sub(r"[\s。！!,.，]+", "", text or "")
    latin = re.sub(r"[^A-Za-z]+", "", text or "").lower()
    if latin in {"nihao", "ninhao", "hello", "hi", "hey"}:
        return True
    return bool(re.fullmatch(r"(你好|您好|哈喽|hello|hi|hey|喂|小帅)", compact, flags=re.IGNORECASE))


def available_memory_mb() -> int:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def is_incomplete_asr(text: str) -> bool:
    compact = re.sub(r"[\s，。！？!?,.]+", "", text or "")
    if not compact:
        return True
    if is_fast_greeting(compact):
        return False
    if re.fullmatch(r"[\d+\-*/×÷=]+", compact):
        return False
    return compact in {"你", "我", "他", "她", "它", "嗯", "啊", "喂", "比", "那", "这", "的"}


def audio_seconds(audio: bytes) -> float:
    return len(audio) / 2 / SAMPLE_RATE if audio else 0.0


def format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def solve_simple_math(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text)
    compact = compact.replace("＋", "+").replace("加", "+")
    compact = compact.replace("－", "-").replace("减", "-")
    compact = compact.replace("×", "*").replace("乘", "*")
    compact = compact.replace("÷", "/").replace("除以", "/").replace("除", "/")
    compact = compact.replace("等于", "=").replace("等", "=")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)([+\-*/])(-?\d+(?:\.\d+)?)(?:=?[?？]?)", compact)
    if not m:
        return None
    a = float(m.group(1))
    b = float(m.group(3))
    op = m.group(2)
    if op == "+":
        return f"{format_number(a)}+{format_number(b)}={format_number(a + b)}"
    if op == "-":
        return f"{format_number(a)}-{format_number(b)}={format_number(a - b)}"
    if op == "*":
        return f"{format_number(a)}×{format_number(b)}={format_number(a * b)}"
    if b == 0:
        return "除数不能是 0"
    return f"{format_number(a)}÷{format_number(b)}={format_number(a / b)}"


def tts_text(text: str) -> str:
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", text)
    text = text.replace("+", " 加 ").replace("=", " 等于 ")
    text = text.replace("-", " 减 ").replace("×", " 乘 ").replace("*", " 乘 ")
    text = text.replace("÷", " 除以 ")
    text = text.translate(PUNCT_TABLE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:260]


def tts_sample_rate() -> int:
    try:
        data = json.loads(Path(TTS_CONFIG).read_text(encoding="utf-8"))
        audio = data.get("audio", {})
        return int(audio.get("sample_rate") or data.get("sample_rate") or 22050)
    except Exception:
        return 22050


class AIAssistant:
    def __init__(self):
        print_audio_devices("ai_assistant")
        self.running = False
        self.device = self._find_mic()
        self._peak = 0.0
        self._noise_peak = 0.0
        self._dynamic_trigger = TRIGGER_PEAK
        self._dynamic_silence = SILENCE_PEAK
        self._history: list[tuple[str, str]] = []

        self._llm = None
        self._llm_ready = False
        self._llm_lock = threading.Lock()

        self._asr_model = None
        self._sensevoice_model = None
        self._asr_backend = ASR_BACKEND
        self._asr_ready = False
        self._asr_lock = threading.Lock()
        self._sensevoice_lock = threading.Lock()

        self._sherpa_tts = None
        self._sherpa_tts_ready = False
        self._tts_lock = threading.Lock()

        self._turn = 0
        self._turn_lock = threading.Lock()
        self._active_tts_proc: subprocess.Popen | None = None
        self._active_tts_lock = threading.Lock()
        self._tts_queue: queue.Queue[tuple[int, str] | None] = queue.Queue()
        self._asr_queue: queue.Queue[tuple[int, bytes] | None] = queue.Queue(maxsize=3)
        self._tts_rate = tts_sample_rate()
        self._speaking = False
        self._voice_thread: threading.Thread | None = None
        self._manual_audio_lock = threading.Lock()
        self._manual_audio_frames: list[bytes] = []
        self._manual_audio_peak = 0.0
        self._record_turn = 0

        self.win = tk.Tk()
        self.win.title("AI对话助手")
        self.win.geometry("600x560")
        self.win.configure(bg="#202124")

        tk.Label(
            self.win,
            text="AI对话助手",
            font=("Microsoft YaHei", 14, "bold"),
            bg="#202124",
            fg="#7ee787",
        ).pack(pady=(12, 6))

        self.chat = tk.Text(
            self.win,
            font=("Microsoft YaHei", 11),
            bg="#2b2d31",
            fg="#f5f5f5",
            wrap=tk.WORD,
            height=15,
            relief=tk.FLAT,
        )
        self.chat.pack(pady=6, padx=16, fill=tk.BOTH, expand=True)

        row = tk.Frame(self.win, bg="#202124")
        row.pack(pady=8, padx=16, fill=tk.X)
        self.inp = tk.Entry(row, font=("Microsoft YaHei", 12), bg="#34373d", fg="#ffffff", insertbackground="#ffffff")
        self.inp.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, ipady=6)
        self.inp.bind("<Return>", lambda _e: self.send_text())
        tk.Button(
            row,
            text="发送",
            font=("Microsoft YaHei", 11),
            bg="#7ee787",
            fg="#111111",
            command=self.send_text,
            width=8,
        ).pack(side=tk.RIGHT, padx=(8, 0))

        bar_row = tk.Frame(self.win, bg="#202124")
        bar_row.pack(pady=6, padx=16, fill=tk.X)
        self.bar = ttk.Progressbar(bar_row, length=320, mode="determinate", maximum=100)
        self.bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.voice_btn = tk.Button(
            bar_row,
            text="开始听",
            font=("Microsoft YaHei", 11),
            command=self.toggle_voice,
            bg="#58a6ff",
            fg="#111111",
            width=10,
        )
        self.voice_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self.status = tk.Label(self.win, text="正在加载模型...", font=("Microsoft YaHei", 9), bg="#202124", fg="#a5a5a5")
        self.status.pack(pady=(2, 12))

        self.win.protocol("WM_DELETE_WINDOW", self.on_close)
        self._raise_output_volume()
        self._update_bar()
        threading.Thread(target=self._init_sherpa_tts, daemon=True).start()
        threading.Thread(target=self._init_asr, daemon=True).start()
        threading.Thread(target=self._init_second_pass_asr, daemon=True).start()
        if LLM_PRELOAD:
            threading.Thread(target=self._init_llm_delayed, daemon=True).start()
        else:
            self._set_status("就绪，可打字或点“开始听”说话", "#7ee787")
        threading.Thread(target=self._asr_worker, daemon=True).start()
        threading.Thread(target=self._tts_worker, daemon=True).start()

    def _find_mic(self) -> str:
        if VOICE_DEVICE:
            return VOICE_DEVICE
        return "dsnoop:CARD=XFMDPV0018,DEV=0"

    def _set_status(self, text: str, color: str = "#a5a5a5") -> None:
        self.win.after(0, lambda: self.status.config(text=text, fg=color))

    def _raise_output_volume(self) -> None:
        for control in ("PCM", "Master", "Speaker"):
            with suppress(Exception):
                subprocess.run(
                    ["amixer", "-c", "0", "sset", control, "100%", "unmute"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )

    def chat_insert(self, text: str) -> None:
        self.win.after(0, lambda: self._chat_insert_ui(text))

    def _chat_insert_ui(self, text: str) -> None:
        self.chat.insert(tk.END, text)
        self.chat.see(tk.END)

    def _init_asr(self) -> None:
        if ASR_BACKEND in ("paraformer", "paraformer_onnx", "auto"):
            try:
                from funasr_onnx import Paraformer
                self.chat_insert("系统: 正在加载 Paraformer 量化语音识别...\n")
                self._asr_model = Paraformer(PARAFORMER_ASR_DIR, device_id="-1", quantize=True, intra_op_num_threads=4)
                self._asr_backend = "paraformer"
                self._asr_ready = True
                self.chat_insert("系统: Paraformer 语音识别已就绪。\n")
                return
            except Exception as exc:
                self.chat_insert(f"系统: Paraformer 加载失败，改用其他后端: {exc}\n")
        if ASR_BACKEND in ("sherpa", "sherpa_onnx", "auto"):
            try:
                model = Path(SHERPA_ASR_DIR) / "model.int8.onnx"
                tokens = Path(SHERPA_ASR_DIR) / "tokens.txt"
                if not model.exists() or not tokens.exists():
                    raise FileNotFoundError(f"{SHERPA_ASR_DIR} 不完整")
                self.chat_insert("系统: 正在加载 sherpa 实时语音识别...\n")
                import sherpa_onnx

                self._asr_model = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
                    tokens=str(tokens),
                    model=str(model),
                    num_threads=4,
                    sample_rate=SAMPLE_RATE,
                    feature_dim=80,
                    enable_endpoint_detection=True,
                    rule1_min_trailing_silence=0.55,
                    rule2_min_trailing_silence=0.20,
                    rule3_min_utterance_length=5.0,
                    decoding_method="greedy_search",
                    provider="cpu",
                )
                self._asr_backend = "sherpa"
                self._asr_ready = True
                self.chat_insert("系统: sherpa 实时语音识别已就绪。\n")
                return
            except Exception as exc:
                self.chat_insert(f"系统: sherpa 语音识别加载失败，改用 SenseVoice: {exc}\n")

        if ASR_BACKEND in ("sensevoice", "funasr", "auto"):
            try:
                self.chat_insert("系统: 正在加载 SenseVoice 语音识别...\n")
                from funasr import AutoModel

                self._asr_model = AutoModel(
                    model=SENSEVOICE_MODEL,
                    trust_remote_code=True,
                    disable_update=True,
                )
                self._asr_backend = "sensevoice"
                self._asr_ready = True
                self.chat_insert("系统: SenseVoice 语音识别已就绪。\n")
                return
            except Exception as exc:
                self.chat_insert(f"系统: SenseVoice 加载失败，改用 whisper.cpp: {exc}\n")

        self._asr_backend = "whisper"
        self._asr_ready = Path(WHISPER_BIN).exists() and Path(WHISPER_MODEL).exists()
        if self._asr_ready:
            self.chat_insert("系统: whisper.cpp 语音识别已就绪。\n")
        else:
            self.chat_insert("系统: 没找到可用语音识别模型。\n")

    def _init_second_pass_asr(self) -> None:
        if not SECOND_PASS_ASR:
            return
        try:
            if not Path(SENSEVOICE_LOCAL).exists() and not str(SENSEVOICE_MODEL).startswith("/"):
                return
            self.chat_insert("系统: 正在加载二级精准识别...\n")
            from funasr import AutoModel

            self._sensevoice_model = AutoModel(
                model=SENSEVOICE_MODEL,
                trust_remote_code=True,
                disable_update=True,
            )
            self.chat_insert("系统: 二级精准识别已就绪。\n")
        except Exception as exc:
            self._sensevoice_model = None
            self.chat_insert(f"系统: 二级精准识别加载失败: {exc}\n")

    def _init_sherpa_tts(self) -> None:
        try:
            base = Path(SHERPA_TTS_DIR)
            model = base / "model.onnx"
            tokens = base / "tokens.txt"
            lexicon = base / "lexicon.txt"
            if not model.exists() or not tokens.exists() or not lexicon.exists():
                raise FileNotFoundError(f"{SHERPA_TTS_DIR} 不完整")
            import sherpa_onnx

            rule_fsts = ",".join(
                str(p) for p in [base / "phone.fst", base / "date.fst", base / "number.fst"] if p.exists()
            )
            cfg = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=str(model),
                        tokens=str(tokens),
                        lexicon=str(lexicon),
                        data_dir="",
                        length_scale=SHERPA_TTS_LENGTH_SCALE,
                    ),
                    num_threads=4,
                    provider="cpu",
                ),
                rule_fsts=rule_fsts,
                max_num_sentences=1,
            )
            self._sherpa_tts = sherpa_onnx.OfflineTts(cfg)
            self._sherpa_tts_ready = True
            self.chat_insert("系统: 本地中文语音包已就绪。\n")
        except Exception as exc:
            self._sherpa_tts = None
            self._sherpa_tts_ready = False
            self.chat_insert(f"系统: 本地中文语音包加载失败，保留 Edge/Piper 兜底: {exc}\n")

    def _init_llm(self) -> None:
        if self._llm_ready and self._llm is not None:
            return
        available = available_memory_mb()
        if available and available < LLM_MIN_AVAILABLE_MB:
            raise RuntimeError(f"可用内存不足，当前约 {available}MB，暂不加载大模型")
        self.chat_insert("系统: 正在加载本地大模型...\n")
        try:
            from llama_cpp import Llama

            self._llm = Llama(
                model_path=LLM_MODEL,
                n_ctx=1024,
                n_threads=max(6, min(8, os.cpu_count() or 6)),
                n_batch=128,
                verbose=False,
            )
            self._llm_ready = True
            self._set_status("就绪，可打字或点“开始听”说话", "#7ee787")
            self.chat_insert("系统: 大模型已就绪。\n")
        except Exception as exc:
            self._set_status("大模型加载失败", "#ff6b6b")
            self.chat_insert(f"系统: 大模型加载失败: {exc}\n")

    def _init_llm_delayed(self) -> None:
        deadline = time.time() + 12.0
        while not self._sherpa_tts_ready and time.time() < deadline:
            time.sleep(0.1)
        self._init_llm()

    def next_turn(self) -> int:
        with self._turn_lock:
            self._turn += 1
            return self._turn

    def current_turn(self) -> int:
        with self._turn_lock:
            return self._turn

    def is_stale(self, turn: int) -> bool:
        return turn != self.current_turn()

    def interrupt_current(self) -> int:
        turn = self.next_turn()
        self._clear_tts_queue()
        self._stop_tts()
        return turn

    def _clear_tts_queue(self) -> None:
        while True:
            try:
                self._tts_queue.get_nowait()
            except queue.Empty:
                return

    def _stop_tts(self) -> None:
        with self._active_tts_lock:
            proc = self._active_tts_proc
            self._active_tts_proc = None
        if proc and proc.poll() is None:
            timing_log("tts_stop active_proc=1")
            with suppress(Exception):
                proc.terminate()
            with suppress(Exception):
                proc.wait(timeout=0.4)
            if proc.poll() is None:
                with suppress(Exception):
                    proc.kill()
        subprocess.run(["pkill", "-f", r"aplay.*ai_(tts|piper)_"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._speaking = False

    def send_text(self) -> None:
        txt = self.inp.get().strip()
        if not txt:
            return
        self.inp.delete(0, tk.END)
        turn = self.interrupt_current()
        self.ask(txt, turn)

    def ask(self, text: str, turn: int | None = None) -> None:
        if turn is None:
            turn = self.interrupt_current()
        self.chat_insert(f"你: {text}\n")

        math_reply = solve_simple_math(text)
        if math_reply:
            self.chat_insert(f"AI: {math_reply}\n")
            self._queue_tts_latest(turn, math_reply)
            return

        if is_fast_greeting(text):
            reply = "小帅，我在。你直接说想问的事就行。"
            self.chat_insert(f"AI: {reply}\n")
            self._history.append(("user", text))
            self._history.append(("assistant", reply))
            self._history = self._history[-12:]
            self._queue_tts_latest(turn, reply)
            return

        if not self._llm_ready or self._llm is None:
            try:
                self._init_llm()
            except Exception as exc:
                msg = f"小帅，我现在先用轻量模式回答：我在。大模型暂时没加载，原因是{exc}。"
                self.chat_insert(f"AI: {msg}\n")
                self._queue_tts_latest(turn, msg)
                return
        threading.Thread(target=self._llm_reply, args=(turn, text), daemon=True).start()

    def _build_prompt(self, user_text: str) -> str:
        turns = self._history[-8:]
        parts = [f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>"]
        for role, content in turns:
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        parts.append(f"<|im_start|>user\n{user_text}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    def _llm_reply(self, turn: int, user_text: str) -> None:
        self._set_status("思考中...", "#ffcc66")
        try:
            prompt = self._build_prompt(user_text)
            reply = self._generate_llm_text(turn, prompt)
            if self.is_stale(turn):
                return
            reply = reply.strip() or "我刚才没组织好语言，你再说一遍。"
            reply = re.sub(r"<\|.*?\|>", "", reply).strip()
            self._history.append(("user", user_text))
            self._history.append(("assistant", reply))
            self._history = self._history[-12:]
            self.chat_insert(f"AI: {reply}\n")
            self._queue_tts_latest(turn, reply)
        except Exception as exc:
            if not self.is_stale(turn):
                self.chat_insert(f"错误: {exc}\n")
        finally:
            if not self.is_stale(turn):
                self._set_status("就绪", "#7ee787")

    def _generate_llm_text(self, turn: int, prompt: str) -> str:
        kwargs = dict(
            max_tokens=72,
            temperature=0.55,
            top_p=0.9,
            repeat_penalty=1.14,
            stop=["<|im_end|>", "<|im_start|>"],
        )
        with self._llm_lock:
            if self.is_stale(turn):
                return ""
            try:
                pieces: list[str] = []
                for chunk in self._llm(prompt, stream=True, **kwargs):
                    if self.is_stale(turn):
                        return ""
                    choices = chunk.get("choices") or []
                    if choices:
                        pieces.append(choices[0].get("text", ""))
                return "".join(pieces)
            except TypeError:
                if self.is_stale(turn):
                    return ""
                resp = self._llm(prompt, **kwargs)
                choices = resp.get("choices") or []
                return choices[0].get("text", "") if choices else ""

    def _tts_worker(self) -> None:
        while True:
            item = self._tts_queue.get()
            if item is None:
                return
            turn, text = item
            if not self.is_stale(turn):
                self._speak(turn, text)

    def _speak(self, turn: int, text: str) -> None:
        clean = tts_text(text)
        if not clean or self.is_stale(turn):
            return
        self._speaking = True
        self._set_status("说话中，可直接打断", "#58a6ff")
        try:
            wait_until = time.time() + SHERPA_TTS_WAIT_SEC
            while not self._sherpa_tts_ready and not self.is_stale(turn) and time.time() < wait_until:
                time.sleep(0.05)
            if self._speak_sherpa_tts(turn, clean):
                return
            if self.is_stale(turn):
                return
            if not self._sherpa_tts_ready:
                self._set_status("本地语音加载中...", "#ffcc66")
            else:
                timing_log(f"tts_skip turn={turn} text={clean!r}")
        finally:
            if not self.is_stale(turn):
                self._set_status("就绪", "#7ee787")
            self._speaking = False

    def _speak_sherpa_tts(self, turn: int, text: str) -> bool:
        if not self._sherpa_tts_ready or self._sherpa_tts is None or self.is_stale(turn):
            return False
        fd, wav_path = tempfile.mkstemp(prefix="ai_sherpa_tts_", suffix=".wav")
        os.close(fd)
        play_path = None
        try:
            import sherpa_onnx

            with self._tts_lock:
                if self.is_stale(turn):
                    return False
                t0 = time.time()
                audio = self._sherpa_tts.generate(text, sid=SHERPA_TTS_SID, speed=SHERPA_TTS_SPEED)
                gen_sec = time.time() - t0
            if self.is_stale(turn):
                return False
            audio_dur = len(audio.samples) / float(audio.sample_rate or 1)
            timing_log(f"tts_gen turn={turn} sec={gen_sec:.3f} audio_dur={audio_dur:.3f} chars={len(text)}")
            sherpa_onnx.write_wave(wav_path, audio.samples, audio.sample_rate)
            boost_wav_file(wav_path, TTS_OUTPUT_GAIN)
            play_path = normalize_playback_wav(wav_path, gain=1.0, target_rate=48000, target_channels=2)
            return self._run_playback(turn, play_path)
        except Exception as exc:
            timing_log(f"tts_error turn={turn} err={exc!r}")
            return False
        finally:
            with suppress(FileNotFoundError):
                os.remove(wav_path)
            if play_path and play_path != wav_path:
                with suppress(FileNotFoundError):
                    os.remove(play_path)

    def _run_playback(self, turn: int, wav_path: str, timeout: int = 45) -> bool:
        if self.is_stale(turn):
            timing_log(f"tts_play_skip_stale turn={turn}")
            return False
        proc = subprocess.Popen(["aplay", "-q", "-D", TTS_DEVICE, wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self._active_tts_lock:
            self._active_tts_proc = proc
        start = time.time()
        timing_log(f"tts_play_start turn={turn} path={Path(wav_path).name}")
        try:
            while proc.poll() is None:
                if self.is_stale(turn):
                    self._stop_tts()
                    timing_log(f"tts_play_stale turn={turn} sec={time.time() - start:.3f}")
                    return False
                if time.time() - start > timeout:
                    self._stop_tts()
                    timing_log(f"tts_play_timeout turn={turn} sec={time.time() - start:.3f}")
                    return False
                time.sleep(0.05)
            timing_log(f"tts_play_end turn={turn} sec={time.time() - start:.3f} rc={proc.returncode}")
            return proc.returncode == 0
        finally:
            with self._active_tts_lock:
                if self._active_tts_proc is proc:
                    self._active_tts_proc = None

    def _speak_edge_tts(self, turn: int, text: str) -> bool:
        fd, mp3_path = tempfile.mkstemp(prefix="ai_tts_", suffix=".mp3")
        os.close(fd)
        wav_path = mp3_path[:-4] + ".wav"
        try:
            cmd = [
                "python3", "-m", "edge_tts",
                "--voice", EDGE_TTS_VOICE,
                "--rate", "+0%",
                "--volume", "+0%",
                "--text", text,
                "--write-media", mp3_path,
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self._active_tts_lock:
                self._active_tts_proc = proc
            start = time.time()
            while proc.poll() is None:
                if self.is_stale(turn):
                    self._stop_tts()
                    return False
                if time.time() - start > 35:
                    self._stop_tts()
                    return False
                time.sleep(0.05)
            with self._active_tts_lock:
                if self._active_tts_proc is proc:
                    self._active_tts_proc = None
            if proc.returncode != 0 or not Path(mp3_path).exists() or Path(mp3_path).stat().st_size < 1024:
                return False
            if self.is_stale(turn):
                return False
            conv = subprocess.run(
                ["ffmpeg", "-y", "-i", mp3_path, "-af", "volume=1.15", "-ac", "1", "-ar", "44100", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            )
            if conv.returncode != 0 or not Path(wav_path).exists() or Path(wav_path).stat().st_size < 1024:
                return False
            play_path = normalize_playback_wav(wav_path, gain=1.0, target_rate=48000, target_channels=2)
            return self._run_playback(turn, play_path)
        except Exception:
            return False
        finally:
            with suppress(FileNotFoundError):
                os.remove(mp3_path)
            with suppress(FileNotFoundError):
                os.remove(wav_path)

    def _speak_piper(self, turn: int, text: str) -> bool:
        if not Path(TTS_MODEL).exists() or not Path(TTS_CONFIG).exists() or self.is_stale(turn):
            return False
        fd, wav_path = tempfile.mkstemp(prefix="ai_piper_", suffix=".wav")
        os.close(fd)
        try:
            proc = subprocess.Popen(
                [
                    "piper",
                    "-m", TTS_MODEL,
                    "-c", TTS_CONFIG,
                    "--output-raw",
                    "--length-scale", "1.12",
                    "--sentence-silence", "0.12",
                    "--volume", "0.90",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            with self._active_tts_lock:
                self._active_tts_proc = proc
            try:
                raw, _ = proc.communicate(input=(text.strip() + "\n").encode("utf-8"), timeout=25)
            except subprocess.TimeoutExpired:
                self._stop_tts()
                return False
            with self._active_tts_lock:
                if self._active_tts_proc is proc:
                    self._active_tts_proc = None
            if proc.returncode != 0 or not raw:
                return False
            write_wav(wav_path, raw, self._tts_rate)
            boost_wav_file(wav_path, 1.20)
            play_path = normalize_playback_wav(wav_path, gain=1.0, target_rate=48000, target_channels=2)
            return self._run_playback(turn, play_path)
        except Exception:
            return False
        finally:
            with suppress(FileNotFoundError):
                os.remove(wav_path)

    def toggle_voice(self) -> None:
        if self.running:
            self.running = False
            self.voice_btn.config(text="开始听", bg="#58a6ff")
            self._set_status("收音结束，准备识别...", "#ffcc66")
        else:
            turn = self.interrupt_current()
            with self._manual_audio_lock:
                self._manual_audio_frames = []
                self._manual_audio_peak = 0.0
                self._record_turn = turn
            self._peak = 0.0
            self.running = True
            self.voice_btn.config(text="停止听", bg="#ff6b6b")
            self._set_status("监听中，说完后请点“停止听”", "#58a6ff")
            self._voice_thread = threading.Thread(target=self._voice_loop, args=(turn,), daemon=True)
            self._voice_thread.start()

    def _auto_start_voice(self) -> None:
        if not self.running:
            self.toggle_voice()

    def _open_pcm(self):
        import alsaaudio

        return alsaaudio.PCM(
            alsaaudio.PCM_CAPTURE,
            alsaaudio.PCM_NORMAL,
            self.device,
            channels=1,
            rate=SAMPLE_RATE,
            format=alsaaudio.PCM_FORMAT_S16_LE,
            periodsize=FRAME_SIZE,
        )

    def _voice_loop(self, turn: int | None = None) -> None:
        if turn is None:
            turn = self.current_turn()
        try:
            inp = self._open_pcm()
        except Exception as exc:
            self.running = False
            self.win.after(0, lambda: self.voice_btn.config(text="开始听", bg="#58a6ff"))
            self.chat_insert(f"系统: 麦克风打开失败: {exc}\n")
            return

        start = time.time()
        max_samples = max(1, int(MANUAL_MAX_RECORD_SEC * SAMPLE_RATE))
        captured_samples = 0
        peak = 0.0
        try:
            while self.running and not self.is_stale(turn):
                try:
                    length, data = inp.read()
                except Exception:
                    time.sleep(0.04)
                    continue
                if length <= 0:
                    time.sleep(0.005)
                    continue

                raw = np.frombuffer(data, dtype=np.int16)
                if raw.size == 0:
                    continue
                boosted = np.clip(raw.astype(np.float32) * GAIN, -32768, 32767).astype(np.int16)
                frame_peak = float(np.max(np.abs(boosted))) / 32768.0
                peak = max(peak, frame_peak)
                self._peak = min(frame_peak * 100, 100)
                with self._manual_audio_lock:
                    self._manual_audio_frames.append(boosted.tobytes())
                    self._manual_audio_peak = max(self._manual_audio_peak, frame_peak)
                captured_samples += boosted.size
                if captured_samples >= max_samples:
                    self.running = False
                    self.win.after(0, lambda: self.voice_btn.config(text="开始听", bg="#58a6ff"))
                    self._set_status("收音已到最长时长，开始识别...", "#ffcc66")
                    break
        finally:
            with self._manual_audio_lock:
                audio = b"".join(self._manual_audio_frames)
                final_peak = max(peak, self._manual_audio_peak)
                if self._record_turn == turn:
                    self._manual_audio_frames = []
                    self._manual_audio_peak = 0.0
            self._peak = 0.0

        if self.is_stale(turn):
            return
        audio = self._prepare_manual_audio(audio)
        sec = audio_seconds(audio)
        if not self._is_valid_manual_audio(audio, final_peak):
            timing_log(f"manual_drop turn={turn} sec={sec:.3f} peak={final_peak:.3f}")
            self._set_status("没听清，请按开始听再说一遍", "#ffcc66")
            return
        timing_log(f"manual_record turn={turn} sec={sec:.3f} elapsed={time.time() - start:.3f} bytes={len(audio)} peak={final_peak:.3f}")
        self._set_status("识别中...", "#ffcc66")
        self._queue_asr(turn, audio)

    def _prepare_manual_audio(self, audio: bytes) -> bytes:
        if not audio:
            return b""
        samples = np.frombuffer(audio, dtype=np.int16)
        if samples.size == 0:
            return b""
        return trim_audio_edges(samples.astype(np.int16).tobytes(), sample_rate=SAMPLE_RATE, edge_trim_sec=MANUAL_EDGE_TRIM_SEC)

    def _is_valid_manual_audio(self, audio: bytes, peak: float) -> bool:
        duration = audio_seconds(audio)
        if duration < MIN_VALID_AUDIO_SEC:
            return False
        samples = np.frombuffer(audio, dtype=np.int16)
        if samples.size == 0:
            return False
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) / 32768.0
        if peak < MANUAL_MIN_PEAK and rms < MANUAL_MIN_RMS:
            return False
        return True

    def _calibrate_noise(self, inp) -> None:
        peaks: list[float] = []
        deadline = time.time() + max(0.1, NOISE_CALIBRATE_SEC)
        while self.running and time.time() < deadline:
            try:
                length, data = inp.read()
            except Exception:
                break
            if length <= 0:
                continue
            raw = np.frombuffer(data, dtype=np.int16)
            if raw.size == 0:
                continue
            boosted = np.clip(raw.astype(np.float32) * GAIN, -32768, 32767).astype(np.int16)
            peaks.append(float(np.max(np.abs(boosted))) / 32768.0)
        if not peaks:
            return
        arr = np.array(peaks, dtype=np.float32)
        p50 = float(np.percentile(arr, 50))
        p75 = float(np.percentile(arr, 75))
        noise = min(p75, max(p50 * 1.6, p50 + 0.006))
        self._noise_peak = noise
        self._dynamic_trigger = adaptive_threshold(
            noise, TRIGGER_PEAK, NOISE_TRIGGER_MULT, 0.009, MAX_DYNAMIC_TRIGGER
        )
        self._dynamic_silence = max(SILENCE_PEAK, min(MAX_DYNAMIC_SILENCE, self._dynamic_trigger * 0.70, noise * NOISE_SILENCE_MULT + 0.005))
        timing_log(f"noise p50={p50:.3f} p75={p75:.3f} baseline={noise:.3f} trigger={self._dynamic_trigger:.3f} silence={self._dynamic_silence:.3f}")

    def _is_valid_audio(self, audio: bytes, peak: float) -> bool:
        duration = audio_seconds(audio)
        if duration < MIN_VALID_AUDIO_SEC:
            return False
        if peak < self._dynamic_trigger + MIN_VALID_PEAK_MARGIN:
            return False
        samples = np.frombuffer(audio, dtype=np.int16)
        if samples.size == 0:
            return False
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) / 32768.0
        if rms < max(0.004, self._noise_peak * 0.65):
            return False
        return True

    def _queue_asr(self, turn: int, audio: bytes) -> None:
        while True:
            with suppress(queue.Empty):
                self._asr_queue.get_nowait()
                continue
            break
        self._asr_queue.put_nowait((turn, audio))

    def _queue_tts_latest(self, turn: int, text: str) -> None:
        while True:
            with suppress(queue.Empty):
                self._tts_queue.get_nowait()
                continue
            break
        self._tts_queue.put_nowait((turn, text))

    def _asr_worker(self) -> None:
        while True:
            item = self._asr_queue.get()
            if item is None:
                return
            turn, audio = item
            self._recognize_and_ask(turn, audio)

    def _record_utterance(self, inp) -> tuple[bytes, float]:
        pre_roll = deque(maxlen=20)
        frames: list[bytes] = []
        speaking = False
        peak = 0.0
        min_samples = max(1, int(MIN_RECORD_SEC * SAMPLE_RATE))
        max_samples = max(min_samples, int(MAX_RECORD_SEC * SAMPLE_RATE))
        post_silence_samples = max(1, int(POST_SILENCE_SEC * SAMPLE_RATE))
        fast_post_silence_samples = max(1, int(FAST_POST_SILENCE_SEC * SAMPLE_RATE))
        interrupt_samples = max(1, int(INTERRUPT_MIN_SEC * SAMPLE_RATE))
        captured_samples = 0
        silence_samples = 0

        while self.running:
            try:
                length, data = inp.read()
            except Exception:
                time.sleep(0.06)
                continue
            if length <= 0:
                time.sleep(0.005)
                continue

            raw = np.frombuffer(data, dtype=np.int16)
            if raw.size == 0:
                continue
            boosted = np.clip(raw.astype(np.float32) * GAIN, -32768, 32767).astype(np.int16)
            frame_peak = float(np.max(np.abs(boosted))) / 32768.0
            self._peak = frame_peak * 100
            pre_roll.append(boosted.tobytes())

            trigger_level = BARGE_IN_TRIGGER_PEAK if self._speaking else self._dynamic_trigger
            if frame_peak >= trigger_level:
                if not speaking:
                    speaking = True
                    frames.extend(pre_roll)
                    captured_samples += sum(len(frame) // 2 for frame in pre_roll)
                    pre_roll.clear()
                else:
                    frames.append(boosted.tobytes())
                    captured_samples += boosted.size
                silence_samples = 0
                peak = max(peak, frame_peak)
                if BARGE_IN_ENABLED and self._speaking and captured_samples >= interrupt_samples:
                    self._stop_tts()
            elif speaking:
                frames.append(boosted.tobytes())
                captured_samples += boosted.size
                if frame_peak < self._dynamic_silence:
                    silence_samples += boosted.size
                else:
                    silence_samples = 0
                fast_short_done = captured_samples >= min_samples and captured_samples <= int(0.9 * SAMPLE_RATE) and silence_samples >= fast_post_silence_samples
                normal_done = captured_samples >= min_samples and silence_samples >= post_silence_samples
                if fast_short_done or normal_done:
                    break

            if speaking and captured_samples >= max_samples:
                break

        return (b"".join(frames) if speaking else b""), peak

    def _recognize_and_ask(self, turn: int, audio: bytes) -> None:
        t0 = time.time()
        text = self._recognize(audio)
        timing_log(f"asr turn={turn} sec={time.time() - t0:.3f} text={text!r}")
        if self.is_stale(turn):
            return
        if text:
            self.win.after(0, lambda t=text: self._on_voice(turn, t))
        elif not self.is_stale(turn):
            self._set_status("没识别到内容，请再说一遍", "#ffcc66")

    def _recognize(self, audio: bytes) -> str:
        if not self._asr_ready:
            return ""
        primary = ""
        with self._asr_lock:
            if self._asr_backend == "paraformer" and self._asr_model is not None:
                samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
                result = self._asr_model(samples)
                if result:
                    pred = result[0].get("preds", "")
                    return (pred[0] if isinstance(pred, tuple) else pred or "").strip()
            elif self._asr_backend == "sherpa" and self._asr_model is not None:
                primary = self._recognize_sherpa(audio)
            elif self._asr_backend == "sensevoice" and self._asr_model is not None:
                primary = self._recognize_sensevoice(audio, self._asr_model)
            else:
                primary = self._recognize_whisper(audio)

        if is_fast_greeting(primary):
            return primary

        duration = audio_seconds(audio)
        should_review = (
            SECOND_PASS_ASR
            and self._sensevoice_model is not None
            and (not primary or is_incomplete_asr(primary))
        )
        if not should_review:
            return primary

        t0 = time.time()
        with self._sensevoice_lock:
            reviewed = self._recognize_sensevoice(audio, self._sensevoice_model)
        timing_log(f"second_pass sec={time.time() - t0:.3f} primary={primary!r} reviewed={reviewed!r}")
        return prefer_reviewed_asr(primary, reviewed, audio_sec=duration, review_min_sec=SECOND_PASS_MIN_SEC)

    def _recognize_sherpa(self, audio: bytes) -> str:
        try:
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            stream = self._asr_model.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples)
            stream.accept_waveform(SAMPLE_RATE, np.zeros(int(0.12 * SAMPLE_RATE), dtype=np.float32))
            stream.input_finished()
            while self._asr_model.is_ready(stream):
                self._asr_model.decode_stream(stream)
            result = self._asr_model.get_result_all(stream)
            return normalize_common_asr(clean_asr_text(result.text))
        except Exception as exc:
            self.chat_insert(f"系统: sherpa 识别失败: {exc}\n")
            return ""

    def _recognize_sensevoice(self, audio: bytes, model=None) -> str:
        fd, wav_path = tempfile.mkstemp(prefix="ai_voice_", suffix=".wav")
        os.close(fd)
        try:
            write_wav(wav_path, audio)
            active_model = model or self._asr_model
            if active_model is None:
                return ""
            res = active_model.generate(
                input=wav_path,
                cache={},
                language="zh",
                use_itn=True,
            )
            if not res:
                return ""
            text = str(res[0].get("text", ""))
            return normalize_common_asr(clean_asr_text(text.split(">")[-1]))
        except Exception as exc:
            self.chat_insert(f"系统: SenseVoice 识别失败: {exc}\n")
            return ""
        finally:
            with suppress(FileNotFoundError):
                os.remove(wav_path)

    def _recognize_whisper(self, audio: bytes) -> str:
        if not Path(WHISPER_BIN).exists() or not Path(WHISPER_MODEL).exists():
            return ""
        fd, wav_path = tempfile.mkstemp(prefix="ai_voice_", suffix=".wav")
        os.close(fd)
        try:
            write_wav(wav_path, audio)
            result = subprocess.run(
                [
                    WHISPER_BIN,
                    "-m", WHISPER_MODEL,
                    "-l", "zh",
                    "-f", wav_path,
                    "--no-timestamps",
                    "-np",
                    "--best-of", "1",
                    "--beam-size", "1",
                    "--no-fallback",
                    "-t", str(max(4, min(6, os.cpu_count() or 4))),
                    "--prompt", "简体中文日常对话，可能包含英文、数字、歌名和算式。",
                ],
                capture_output=True,
                text=True,
                timeout=40,
            )
            ignored = ("whisper_", "system_", "main:", "read_audio", "WARNING")
            for line in result.stdout.splitlines():
                text = clean_asr_text(line)
                if text and not text.startswith(ignored):
                    return normalize_common_asr(text)
        except Exception as exc:
            self.chat_insert(f"系统: whisper.cpp 识别失败: {exc}\n")
        finally:
            with suppress(FileNotFoundError):
                os.remove(wav_path)
        return ""

    def _on_voice(self, turn: int, text: str) -> None:
        self._set_status("识别到语音", "#7ee787")
        self.inp.delete(0, tk.END)
        self.inp.insert(0, text)
        if is_incomplete_asr(text):
            timing_log(f"asr_incomplete turn={turn} text={text!r}")
            self.chat_insert(f"系统: 只听到“{text}”，这句不完整，我先不回答。\n")
            self._set_status("没听完整，请再说一遍", "#ffcc66")
            return
        self.ask(text, turn)

    def _update_bar(self) -> None:
        self.bar["value"] = min(self._peak, 100)
        self.win.after(80, self._update_bar)

    def on_close(self) -> None:
        self.running = False
        self.interrupt_current()
        with suppress(queue.Full):
            self._asr_queue.put_nowait(None)
        self._tts_queue.put(None)
        with suppress(Exception):
            self._stop_tts()
        with suppress(Exception):
            self.win.destroy()
        os._exit(0)

    def run(self) -> None:
        self.win.mainloop()


if __name__ == "__main__":
    AIAssistant().run()
