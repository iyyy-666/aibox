"""Headless Chinese AI assistant worker with turn-based interruption."""
from __future__ import annotations

import os
import queue
import threading
import tempfile
from pathlib import Path
from typing import Callable

from ..adapters.audio import PlaybackController, deployment_environment
from .voice import VoiceWorker


def assistant_system_prompt() -> str:
    return (
        "你是运行在 RK3588 人工智能实验箱上的中文 AI 助手。"
        "请使用清晰、自然、简洁的中文回答，先直接回答，再补充一到两点有用信息。"
        "语音识别结果可能有误，请结合上下文理解；不确定时提出简短的澄清问题。"
        "除非用户要求详细说明，否则控制在一到四句话。"
        "你可以解释人工智能、计算机视觉、语音识别、机器人和本实验箱。"
    )


class AssistantWorker:
    LLM_MODEL = "/root/llm_models/qwen2.5-3b-instruct-q4_k_m.gguf"
    LLM_SETTINGS = {
        "max_tokens": 72,
        "temperature": 0.55,
        "top_p": 0.9,
        "repeat_penalty": 1.14,
        "stop": ["<|im_end|>", "<|im_start|>"],
    }

    def __init__(
        self,
        *,
        event_sink: Callable[[dict], None],
        llm_factory: Callable[[], object] | None = None,
        voice_factory: Callable[[Callable[[str], None]], VoiceWorker] | None = None,
        playback: PlaybackController | None = None,
        tts_factory: Callable[[str], str] | None = None,
        tts_join_timeout: float = 1.0,
    ) -> None:
        self._event_sink = event_sink
        self._llm_factory = llm_factory or self._default_llm_factory
        self._voice_factory = voice_factory or self._default_voice_factory
        self._playback = playback or PlaybackController()
        self._tts_factory = tts_factory or self._default_tts_factory
        self._llm = None
        self._history: list[tuple[str, str]] = []
        self._turn = 0
        self._lock = threading.RLock()
        self._voice: VoiceWorker | None = None
        self._tts_queue: queue.Queue[tuple[int, str] | None] = queue.Queue()
        self._tts_thread: threading.Thread | None = None
        self._tts_engine = None
        self._tts_lock = threading.Lock()
        self._tts_join_timeout = tts_join_timeout
        self._last_event: dict = {}

    @property
    def last_event(self) -> dict:
        return dict(self._last_event)

    def start(self) -> None:
        self._emit({"type": "ready", "message": "中文 AI 助手已就绪。"})

    def ask(self, text: str) -> dict:
        question = text.strip()
        if not question:
            raise ValueError("请输入问题")
        turn = self.interrupt()
        reply = self._generate(turn, question)
        if turn != self._current_turn():
            return {"ok": False, "interrupted": True}
        with self._lock:
            self._history.extend((("user", question), ("assistant", reply)))
            self._history = self._history[-12:]
        result = {"ok": True, "turn": turn, "text": reply}
        self._emit({"type": "assistant_reply", **result})
        self._queue_tts_latest(turn, reply)
        return result

    def start_listening(self) -> dict:
        if self._voice is None:
            self._voice = self._voice_factory(self.ask)
        return self._voice.start_listening()

    def stop_listening(self) -> dict:
        return self._voice.stop_listening() if self._voice is not None else {"ok": True, "listening": False}

    def interrupt(self) -> int:
        with self._lock:
            self._turn += 1
            turn = self._turn
        self._clear_tts_queue()
        self._playback.stop()
        return turn

    def command(self, name: str, payload: dict) -> dict:
        if name == "ask":
            return self.ask(str(payload.get("text", "")))
        if name == "start_listening":
            return self.start_listening()
        if name == "stop_listening":
            return self.stop_listening()
        if name == "interrupt":
            return {"ok": True, "turn": self.interrupt()}
        raise ValueError(f"不支持的助手命令: {name}")

    def stop(self) -> None:
        self.interrupt()
        if self._voice is not None:
            self._voice.stop()
        self._playback.stop()
        self._clear_tts_queue()
        if self._tts_thread is not None:
            self._tts_queue.put(None)
            self._tts_thread.join(timeout=self._tts_join_timeout)
            if self._tts_thread.is_alive():
                raise TimeoutError("assistant speech shutdown timed out")
            self._tts_thread = None
        self._emit({"type": "stopped", "message": "中文 AI 助手已停止并释放资源。"})

    def _current_turn(self) -> int:
        with self._lock:
            return self._turn

    def _default_llm_factory(self):
        from llama_cpp import Llama

        model_path = os.getenv("LLM_MODEL", self.LLM_MODEL)
        return Llama(
            model_path=model_path,
            n_ctx=1024,
            n_threads=max(6, min(8, os.cpu_count() or 6)),
            n_batch=128,
            verbose=False,
        )

    def _default_voice_factory(self, on_text: Callable[[str], None]) -> VoiceWorker:
        return VoiceWorker("ai_assistant", event_sink=self._emit, on_text=on_text)

    def _default_tts_factory(self, text: str) -> str:
        """Load the legacy Sherpa VITS model only when a reply needs speech."""
        with self._tts_lock:
            if self._tts_engine is None:
                import sherpa_onnx

                base = Path(deployment_environment()["SHERPA_TTS_DIR"])
                model, tokens, lexicon = base / "model.onnx", base / "tokens.txt", base / "lexicon.txt"
                if not model.exists() or not tokens.exists() or not lexicon.exists():
                    raise FileNotFoundError(f"TTS 模型不完整: {base}")
                cfg = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(
                        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                            model=str(model), tokens=str(tokens), lexicon=str(lexicon), data_dir="", length_scale=1.05
                        ),
                        provider="cpu",
                        num_threads=4,
                    ),
                    max_num_sentences=1,
                )
                self._tts_engine = sherpa_onnx.OfflineTts(cfg)
            audio = self._tts_engine.generate(text, sid=0, speed=0.8)
        fd, path = tempfile.mkstemp(prefix="feature_demo_assistant_", suffix=".wav")
        os.close(fd)
        import sherpa_onnx

        sherpa_onnx.write_wave(path, audio.samples, audio.sample_rate)
        return path

    def _generate(self, turn: int, question: str) -> str:
        with self._lock:
            if self._llm is None:
                self._llm = self._llm_factory()
            history = self._history[-8:]
            llm = self._llm
        parts = [f"<|im_start|>system\n{assistant_system_prompt()}<|im_end|>"]
        parts.extend(f"<|im_start|>{role}\n{content}<|im_end|>" for role, content in history)
        parts.extend((f"<|im_start|>user\n{question}<|im_end|>", "<|im_start|>assistant\n"))
        response = llm("\n".join(parts), stream=True, **self.LLM_SETTINGS)
        pieces: list[str] = []
        for chunk in response:
            if turn != self._current_turn():
                return ""
            choices = chunk.get("choices") or []
            if choices:
                pieces.append(str(choices[0].get("text", "")))
        return "".join(pieces).strip() or "抱歉，我暂时无法生成回答。"

    def _queue_tts_latest(self, turn: int, text: str) -> None:
        self._clear_tts_queue()
        self._tts_queue.put((turn, text))
        if self._tts_thread is None or not self._tts_thread.is_alive():
            self._tts_thread = threading.Thread(target=self._tts_loop, daemon=True)
            self._tts_thread.start()

    def _clear_tts_queue(self) -> None:
        while True:
            try:
                self._tts_queue.get_nowait()
            except queue.Empty:
                return

    def _tts_loop(self) -> None:
        while True:
            item = self._tts_queue.get()
            if item is None:
                return
            turn, text = item
            if turn != self._current_turn():
                continue
            try:
                wav_path = self._tts_factory(text)
                if turn != self._current_turn():
                    Path(wav_path).unlink(missing_ok=True)
                    continue
                self._playback.play(wav_path, cleanup=True)
                self._emit({"type": "speaking", "turn": turn, "message": "正在播报回答。"})
            except Exception as exc:
                if turn == self._current_turn():
                    self._emit({"type": "error", "message": str(exc)})

    def _emit(self, event: dict) -> None:
        self._last_event = dict(event)
        self._event_sink(event)
