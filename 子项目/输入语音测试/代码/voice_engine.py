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
from speech_context import HOTWORDS, correct_text, match_command, normalize_text as _normalize_text

WHISPER_BIN = os.getenv("WHISPER_BIN", "/tmp/whisper.cpp/build/bin/whisper-cli")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "/tmp/whisper.cpp/models/ggml-base.bin")
VOICE_BACKEND = os.getenv("VOICE_BACKEND", "auto").strip().lower()
PARAFORMER_MODEL_DIR = os.getenv("PARAFORMER_MODEL_DIR", "/root/sherpa_models/paraformer-large-int8")
SHERPA_ASR_DIR = os.getenv(
    "SHERPA_ASR_DIR",
    "/root/sherpa_models/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01",
)
VOSK_MODEL_DIR = os.getenv("VOSK_MODEL_DIR", "/root/robot_arm/voice/vosk-model-cn-0.22")
SENSEVOICE_MODEL = os.getenv(
    "SENSEVOICE_MODEL",
    "/home/ztl/.cache/modelscope/models/iic--SenseVoiceSmall/snapshots/master",
)
SENSEVOICE_FALLBACK = os.getenv("VOICE_SENSEVOICE_FALLBACK", "1").strip().lower() in {"1", "true", "yes", "on"}
VOICE_INPUT_DEVICE = voice_input_device()
AUDIO_OUTPUT_DEVICE = audio_output_device()
VOICE_DEVICE = VOICE_INPUT_DEVICE
SAMPLE_RATE = int(os.getenv("VOICE_SAMPLE_RATE", "16000"))
FRAME_SIZE = int(os.getenv("VOICE_FRAME_SIZE", "160"))
GAIN = float(os.getenv("VOICE_GAIN", "3.0"))
TRIGGER_PEAK = float(os.getenv("VOICE_TRIGGER_PEAK", "0.038"))
SILENCE_PEAK = float(os.getenv("VOICE_SILENCE_PEAK", "0.022"))
MIN_RECORD_SEC = float(os.getenv("VOICE_MIN_RECORD_SEC", "0.46"))
MAX_RECORD_SEC = float(os.getenv("VOICE_MAX_RECORD_SEC", "3.20"))
POST_SILENCE_SEC = float(os.getenv("VOICE_POST_SILENCE_SEC", "0.58"))
FAST_POST_SILENCE_SEC = float(os.getenv("VOICE_FAST_POST_SILENCE_SEC", "0.38"))
SHORT_UTTERANCE_SEC = float(os.getenv("VOICE_SHORT_UTTERANCE_SEC", "0.92"))
COOLDOWN_SEC = float(os.getenv("VOICE_COOLDOWN_SEC", "0.05"))
PRE_ROLL_FRAMES = int(os.getenv("VOICE_PRE_ROLL_FRAMES", "35"))
SHERPA_FINAL_PAD_SEC = float(os.getenv("VOICE_SHERPA_FINAL_PAD_SEC", "0.28"))
SHERPA_FALLBACK = os.getenv("VOICE_SHERPA_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
TIMING_LOG = os.getenv("VOICE_TIMING_LOG", "/tmp/robot_voice_timing.log")
DEBUG_WAV_DIR = Path(os.getenv("VOICE_DEBUG_WAV_DIR", "/tmp/voice_debug"))
NOISE_CALIBRATE_SEC = float(os.getenv("VOICE_NOISE_CALIBRATE_SEC", "0.35"))
NOISE_TRIGGER_MULT = float(os.getenv("VOICE_NOISE_TRIGGER_MULT", "1.25"))
NOISE_SILENCE_MULT = float(os.getenv("VOICE_NOISE_SILENCE_MULT", "1.05"))
MIN_TRIGGER_MARGIN = float(os.getenv("VOICE_MIN_TRIGGER_MARGIN", "0.009"))
MAX_DYNAMIC_TRIGGER = float(os.getenv("VOICE_MAX_DYNAMIC_TRIGGER", "0.22"))
MAX_DYNAMIC_SILENCE = float(os.getenv("VOICE_MAX_DYNAMIC_SILENCE", "0.14"))
EDGE_TRIM_SEC = float(os.getenv("VOICE_EDGE_TRIM_SEC", "0.18"))

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

_ROBOT_EXTRA_ALIASES = {
    "直立": (
        "立起来", "站起来", "竖起来", "竖直起来", "直起来", "直立起来",
        "机械臂直立", "机械臂站起来", "机械臂竖起来", "手臂直立", "手臂站起来",
        "之力起来", "实力起来", "只立起来", "治理起来", "纸立", "支棱起来",
        "站起", "站直", "竖直一点", "立正一点", "直立一点", "直力起来",
        "支力起来", "治立起来", "纸里起来", "机械臂立起来",
    ),
    "放平": (
        "放平一点", "放下来", "放低一点", "往下放", "向下放", "平下来",
        "机械臂放平", "手臂放平", "机械臂放下来", "手臂放下来", "躺下来",
        "放瓶", "放评", "访平", "方评", "防评", "防屏", "放品",
        "放平一下", "放低下来", "往前放", "向前放", "平放一下", "趴下来",
        "平躺", "放倒一点", "房平", "方屏", "放凭", "防凭",
    ),
    "抓取": (
        "抓一下", "抓一个", "抓物块", "抓住物块", "抓起物块", "抓这个",
        "夹一下", "夹一个", "夹物块", "夹住物块", "夹起物块", "拿一下",
        "拿住", "拿起来", "爪举", "抓举", "抓去", "夹去", "夹举", "早取",
        "抓取一下", "抓紧物块", "夹取物块", "拿起物块", "拿这个", "取一下",
        "抓住这个", "夹住这个", "加取", "家取", "爪取一下", "找取一下",
    ),
    "搬运": (
        "搬运一下", "搬一下", "搬一搬", "帮我搬运", "开始搬运", "执行搬运",
        "搬运物块", "搬一下物块", "搬这个物块", "把物块搬走", "把物块搬过去",
        "移动物块", "移动一下物块", "转移物块", "转运物块", "运送物块",
        "搬云一下", "搬晕一下", "搬用一下", "搬孕一下", "半运一下", "班运一下",
        "帮运一下", "般运一下", "办运一下", "板运一下", "搬过来", "搬过去",
        "机器臂搬运", "机械手搬运", "机械臂帮运", "机械臂班运",
        "帮我搬一下", "帮我搬一搬", "搬运一下物块", "搬运这个", "搬运这块",
        "把它搬走", "把它搬过去", "把这个搬走", "把这个搬过去", "帮我转移",
        "开始转移", "执行转移", "搬一", "搬运一", "搬运一块", "班用一下",
        "半用一下", "帮用一下", "搬嗯一下", "机器搬运", "机器臂班运",
    ),
    "停止": (
        "停一下", "先停", "暂停一下", "不要动", "别动了", "停止动作",
        "停止运行", "停住", "停下来", "停一停", "先别动",
        "停住别动", "马上停", "立即停", "别运行", "先暂停", "停掉",
    ),
    "张开": (
        "张开一点", "打开一点", "打开夹爪", "张开夹爪", "松开夹爪",
        "松爪", "开爪子", "打开爪子", "夹爪松开", "爪子张开",
        "张卡", "张凯", "章凯", "展开夹爪", "展开爪子",
        "张开一下", "打开一下", "松一点", "松开一点", "张爪", "打开爪",
        "开一下夹爪", "张凯一下", "章开一下", "展开一下",
    ),
    "闭合": (
        "闭合一点", "合起来", "合上一点", "关闭夹爪", "夹爪闭合",
        "夹爪合上", "夹爪夹紧", "爪子合上", "爪子夹紧", "夹紧一点",
        "闭盒", "闭和", "并合", "闭夹", "合夹",
        "闭合一下", "合上夹爪", "合一下", "夹一下", "夹住一点", "关上夹爪",
        "关闭爪子", "合住", "闭上一点", "并拢",
    ),
    "复位": (
        "回到原点", "回原位", "回到原位", "恢复原位", "恢复一下",
        "回中间", "回正一下", "复原一下", "重新复位", "重置一下",
        "归位一下", "归中一下", "付位一下", "腹位一下",
        "回初始", "回到初始", "恢复初始", "回默认", "回到默认", "回正位",
    ),
}

_VOSK_EXTRA_ALIASES = {
    "直立": ("立起来", "站起来", "竖起来", "直起来", "机械臂直立", "实力起来", "站直", "直立一点", "机械臂立起来"),
    "放平": ("放下来", "往下放", "机械臂放平", "放瓶", "方评", "防评", "放平一下", "放低下来", "平放一下"),
    "抓取": ("抓一下", "抓物块", "夹一下", "夹物块", "抓举", "夹举", "抓取一下", "抓紧物块", "夹取物块"),
    "搬运": ("搬运一下", "搬一下", "搬物块", "搬运物块", "班运一下", "帮运一下", "转运物块", "帮我搬一下", "把它搬走", "开始转移", "执行转移", "搬运一块", "班用一下"),
    "停止": ("停一下", "先停", "别动了", "停下来", "停止动作", "马上停", "立即停", "停掉"),
    "张开": ("打开夹爪", "松开夹爪", "张开一点", "张卡", "章凯", "张开一下", "打开一下", "松一点"),
    "闭合": ("合起来", "夹紧一点", "关闭夹爪", "闭盒", "闭和", "闭合一下", "合上夹爪", "夹一下"),
    "复位": ("回原位", "回到原位", "恢复原位", "重置一下", "归位一下", "回初始", "恢复初始", "回默认"),
}

for _command, _aliases in _ROBOT_EXTRA_ALIASES.items():
    COMMAND_ALIASES[_command] = tuple(dict.fromkeys(COMMAND_ALIASES.get(_command, ()) + _aliases))
for _command, _aliases in _VOSK_EXTRA_ALIASES.items():
    VOSK_GRAMMAR_ALIASES[_command] = tuple(dict.fromkeys(VOSK_GRAMMAR_ALIASES.get(_command, ()) + _aliases))


def timing_log(message: str) -> None:
    try:
        with open(TIMING_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.time():.3f} {message}\n")
    except Exception:
        pass


def adaptive_threshold(noise: float, base: float, multiplier: float, margin: float, maximum: float) -> float:
    """Set a trigger above the measured noise floor without unbounded growth."""
    return max(base, min(maximum, noise * multiplier + margin))


def put_latest(command_queue: queue.Queue, item) -> None:
    """Replace queued work so only the newest command remains pending."""
    while True:
        try:
            command_queue.get_nowait()
        except queue.Empty:
            break
    command_queue.put_nowait(item)


def trim_audio_edges(audio: bytes, *, sample_rate: int = SAMPLE_RATE, edge_trim_sec: float = EDGE_TRIM_SEC) -> bytes:
    if not audio:
        return b""
    samples = np.frombuffer(audio, dtype=np.int16)
    if samples.size == 0:
        return b""
    trim = max(0, int(edge_trim_sec * sample_rate))
    if trim == 0:
        return audio
    abs_samples = np.abs(samples.astype(np.int32))
    threshold = max(180, int(min(1800, np.percentile(abs_samples, 90) * 0.12)))
    active = np.flatnonzero(abs_samples > threshold)
    if not active.size:
        return audio
    start = max(0, int(active[0]) - trim)
    end = min(samples.size, int(active[-1]) + trim)
    if end <= start:
        return audio
    return samples[start:end].astype(np.int16).tobytes()


def is_probably_truncated_asr(text: str) -> bool:
    compact = re.sub(r"[\s,。！？!?；;：:]+", "", text or "")
    if not compact:
        return True
    if len(compact) <= 1:
        return True
    if compact in {"我", "你", "他", "她", "它", "嗯", "啊", "哦", "是", "有", "了", "的"}:
        return True
    return False


def is_probably_incomplete_command_asr(text: str, commands: tuple[str, ...]) -> bool:
    compact = _normalize_text(text)
    if len(compact) < 2:
        return False

    aliases = []
    for command in commands:
        aliases.extend(HOTWORDS.get("robot", {}).get(command, ()))
        aliases.append(command)
    normalized_aliases = {_normalize_text(alias) for alias in aliases}
    normalized_aliases.discard("")
    if compact in normalized_aliases:
        return False
    return any(alias.startswith(compact) for alias in normalized_aliases)


def is_command_candidate(text: str, commands: tuple[str, ...]) -> bool:
    if not text or not commands:
        return False
    normalized = _normalize_text(text)
    allowed = set()
    for command in commands:
        allowed.add(_normalize_text(command))
        allowed.update(_normalize_text(alias) for alias in HOTWORDS.get("robot", {}).get(command, ()))
        allowed.update(_normalize_text(alias) for alias in COMMAND_ALIASES.get(command, ()))
    return normalized in {item for item in allowed if item}


def normalize_backend_name(value: str) -> str:
    value = (value or "").strip().lower().replace("-", "_")
    return "paraformer" if value in {"paraformer", "paraformer_onnx", "paraformer_int8"} else value


def prefer_reviewed_asr(
    primary: str,
    reviewed: str,
    *,
    audio_sec: float = 0.0,
    review_min_sec: float = 0.55,
    command_matched: bool | None = None,
) -> str:
    primary = (primary or "").strip()
    reviewed = (reviewed or "").strip()
    if not reviewed:
        return primary
    if not primary:
        return reviewed
    if reviewed == primary:
        return primary
    if is_probably_truncated_asr(primary):
        return reviewed
    if command_matched is False:
        return reviewed
    if audio_sec >= review_min_sec:
        return reviewed
    return primary


def should_review_asr(primary: str, *, audio_sec: float = 0.0, command_matched: bool | None = None) -> bool:
    """Keep the slow SenseVoice pass for uncertain results only."""
    del audio_sec
    return (
        not primary.strip()
        or is_probably_truncated_asr(primary)
        or command_matched is False
    )

class VoiceEngine:
    def __init__(self):
        print_audio_devices("voice")
        self.running = False
        self._thread = None
        self._loaded = False
        self._busy = False
        self._backend = normalize_backend_name(VOICE_BACKEND)
        self._sherpa_model = None
        self._paraformer_model = None
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
        self._noise_floor = 0.0
        self._dynamic_trigger = TRIGGER_PEAK
        self._dynamic_silence = SILENCE_PEAK
        self._pending_callback = None
        self._pending_callback_lock = threading.Lock()
        self._pending_watcher = None

    def load(self, device=None):
        if device:
            self._device = device
        elif VOICE_DEVICE:
            self._device = VOICE_DEVICE
        else:
            self._device = self._find_mic()

        self._backend = self._pick_backend()
        if self._backend == "paraformer":
            if not self._load_paraformer_model():
                return False
        elif self._backend == "sherpa":
            if not self._load_sherpa_model():
                self._backend = "vosk" if self._find_vosk_model() else "whisper"
            elif SENSEVOICE_FALLBACK:
                self._load_sensevoice_model()

        if self._backend == "vosk":
            if not self._load_vosk_model():
                self._backend = "whisper"
            elif SENSEVOICE_FALLBACK:
                self._load_sensevoice_model()
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
        if normalize_backend_name(VOICE_BACKEND) == "paraformer":
            return "paraformer"
        if VOICE_BACKEND in {"vosk", "auto"} and self._find_vosk_model():
            return "vosk"
        if VOICE_BACKEND in {"sherpa", "sherpa_onnx", "auto"} and self._find_sherpa_model():
            return "sherpa"
        return "whisper"

    def _find_paraformer_model(self) -> str | None:
        model_dir = Path(PARAFORMER_MODEL_DIR)
        if (model_dir / "tokens.json").exists() and (model_dir / "model_quant.onnx").exists():
            return str(model_dir)
        return None

    def _load_paraformer_model(self) -> bool:
        model_dir = self._find_paraformer_model()
        if not model_dir:
            self.last_error = f"paraformer model not found: {PARAFORMER_MODEL_DIR}"
            print(f"[语音] {self.last_error}")
            return False
        try:
            from funasr_onnx import Paraformer
            self._paraformer_model = Paraformer(
                model_dir,
                device_id="-1",
                quantize=True,
                intra_op_num_threads=max(1, int(os.getenv("VOICE_MODEL_THREADS", "4"))),
            )
            print(f"[语音] paraformer模型就绪 ({model_dir})")
            return True
        except Exception as exc:
            self.last_error = f"paraformer load failed: {exc}"
            print(f"[语音] {self.last_error}")
            return False

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
                rule1_min_trailing_silence=0.45,
                rule2_min_trailing_silence=0.15,
                rule3_min_utterance_length=4.0,
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
        with self._pending_callback_lock:
            self._pending_callback = None

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

        self._calibrate_noise(inp)
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
                    self._calibrate_noise(inp)
                    busy_seen = False
                    consecutive_misses = 0

                t_record = time.time()
                audio, peak = self._record_utterance(inp)
                record_sec = time.time() - t_record
                self.last_peak = peak
                if not audio or peak < self._dynamic_trigger:
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
                    self.last_raw_text = raw_text
                    self.last_normalized_text = normalized_text
                    self.last_audio_sec = len(audio) / 2 / SAMPLE_RATE
                    self.last_asr_sec = asr_sec
                    self.last_debug_wav = debug_wav
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
                        self._calibrate_noise(inp)
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
        fast_post_silence_samples = max(1, int(FAST_POST_SILENCE_SEC * SAMPLE_RATE))
        short_utterance_samples = max(1, int(SHORT_UTTERANCE_SEC * SAMPLE_RATE))
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

            trigger_peak = self._dynamic_trigger
            silence_peak = self._dynamic_silence

            if frame_peak >= trigger_peak:
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
                if frame_peak < silence_peak:
                    silence_frames += 1
                    silence_samples += boosted.size
                else:
                    silence_frames = 0
                    silence_samples = 0
                fast_done = (
                    captured_samples >= min_samples
                    and captured_samples <= short_utterance_samples
                    and silence_samples >= fast_post_silence_samples
                )
                normal_done = captured_samples >= min_samples and silence_samples >= post_silence_samples
                if fast_done or normal_done:
                    break

            if speaking and captured_samples >= max_samples:
                break
            if not speaking and time.monotonic() - started_at > 0.35:
                pre_roll.clear()

        return (b"".join(frames) if speaking else b""), peak

    def _calibrate_noise(self, inp) -> None:
        self._drain_pcm(inp, 20)
        peaks: list[float] = []
        deadline = time.monotonic() + max(0.05, NOISE_CALIBRATE_SEC)
        while self.running and time.monotonic() < deadline:
            try:
                length, data = inp.read()
            except Exception:
                break
            if length <= 0 or not data:
                continue
            raw = np.frombuffer(data, dtype=np.int16)
            if raw.size == 0:
                continue
            boosted = np.clip(raw.astype(np.float32) * GAIN, -32768, 32767)
            peaks.append(float(np.max(np.abs(boosted))) / 32768.0)
        if not peaks:
            self._noise_floor = 0.0
            self._dynamic_trigger = TRIGGER_PEAK
            self._dynamic_silence = SILENCE_PEAK
            return
        arr = np.array(peaks, dtype=np.float32)
        p50 = float(np.percentile(arr, 50))
        p75 = float(np.percentile(arr, 75))
        p90 = float(np.percentile(arr, 90))
        # Ignore short bumps during calibration; otherwise one accidental sound can make
        # the trigger too high and clip the first/last Chinese character.
        baseline = min(p75, max(p50 * 1.6, p50 + 0.006))
        self._noise_floor = baseline
        self._dynamic_trigger = adaptive_threshold(
            baseline, TRIGGER_PEAK, NOISE_TRIGGER_MULT, MIN_TRIGGER_MARGIN, MAX_DYNAMIC_TRIGGER
        )
        self._dynamic_silence = min(
            MAX_DYNAMIC_SILENCE,
            max(SILENCE_PEAK, min(self._dynamic_trigger * 0.70, baseline * NOISE_SILENCE_MULT + 0.006)),
        )
        timing_log(
            f"noise_calibrate device={self._device} p50={p50:.3f} p75={p75:.3f} p90={p90:.3f} baseline={baseline:.3f} "
            f"trigger={self._dynamic_trigger:.3f} silence={self._dynamic_silence:.3f}"
        )

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
        reviewed = self._review_asr(audio, raw)
        if reviewed:
            raw = reviewed
        normalized = self._normalize_asr_text(raw)
        return raw, normalized

    def _recognize(self, audio: bytes) -> str:
        return self._recognize_pair(audio)[1]

    def _review_asr(self, audio: bytes, primary: str) -> str:
        if self._sensevoice_model is None:
            return primary
        audio_sec = len(audio) / 2 / SAMPLE_RATE if audio else 0.0
        command_matched = None
        if self.commands:
            commands = tuple(self.commands.keys())
            command_matched = bool(match_command(primary, commands))
            if command_matched and is_probably_incomplete_command_asr(primary, commands):
                command_matched = False
        if not should_review_asr(primary, audio_sec=audio_sec, command_matched=command_matched):
            return primary
        reviewed = self._recognize_sensevoice(audio)
        if not reviewed:
            return primary
        timing_log(f"sensevoice_review primary={primary!r} reviewed={reviewed!r}")
        return prefer_reviewed_asr(
            primary,
            reviewed,
            audio_sec=audio_sec,
            command_matched=command_matched,
        )

    def _recognize_raw(self, audio: bytes) -> str:
        if self._backend == "paraformer":
            return self._recognize_paraformer(audio)
        if self._backend == "sherpa":
            text = self._recognize_sherpa(audio)
            if text and match_command(text, tuple(self.commands.keys())):
                return text
            return text
        if self._backend == "vosk":
            text = self._recognize_vosk(audio)
            if text:
                if match_command(text, tuple(self.commands.keys())):
                    return text
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
            chunk = 8000
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

    def _recognize_paraformer(self, audio: bytes) -> str:
        if self._paraformer_model is None or not audio:
            return ""
        try:
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            result = self._paraformer_model(samples)
            if not result:
                return ""
            pred = result[0].get("preds", "")
            return (pred[0] if isinstance(pred, tuple) else pred or "").strip()
        except Exception as exc:
            self.last_error = str(exc)
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
        if matched and not is_command_candidate(text, tuple(self.commands.keys())):
            timing_log(f"reject_unregistered_command text={text!r} matched={matched!r}")
            return

        for kw, cb in self.commands.items():
            if kw == matched:
                self.last_command = kw
                self.last_error = ""
                print(f"[语音] 匹配:{kw}")
                put_latest(self.command_queue, kw)
                self._dispatch_callback(kw, cb)
                return

    def _dispatch_callback(self, command, callback) -> None:
        if not callable(callback):
            return
        with self._pending_callback_lock:
            self._pending_callback = (command, callback)
            if self._pending_watcher is None or not self._pending_watcher.is_alive():
                self._pending_watcher = threading.Thread(target=self._run_pending_callback, daemon=True)
                self._pending_watcher.start()

    def _run_pending_callback(self) -> None:
        while self.running:
            if self._robot_busy():
                time.sleep(0.05)
                continue
            with self._pending_callback_lock:
                pending = self._pending_callback
                self._pending_callback = None
            if pending is None:
                with self._pending_callback_lock:
                    if self._pending_callback is None:
                        self._pending_watcher = None
                        return
                continue
            self._invoke_callback(*pending)

    def _invoke_callback(self, command, callback) -> None:
        try:
            callback(command)
        except Exception as e:
            self.last_error = str(e)
            print(f"[语音] 回调:{e}")

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
            "noise_floor": self._noise_floor,
            "trigger_peak": self._dynamic_trigger,
            "silence_peak": self._dynamic_silence,
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
