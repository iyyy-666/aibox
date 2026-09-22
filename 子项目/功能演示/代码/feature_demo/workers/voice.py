"""Headless voice workers for transcription, nursery songs, and robot control."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import wave
from contextlib import suppress
from pathlib import Path
from typing import Callable

from ..adapters.audio import PlaybackController, deployment_environment
from ..adapters.robot import RobotAdapter


NURSERY_ASSET_DIR = Path("/root/robot_arm/assets/nursery")
NURSERY_SONGS = {
    "小星星": {
        "song_id": "twinkle",
        "source_file": "xiaoxingxing_vocal.mp3",
        "lyrics": [
            "Twinkle, twinkle, little star",
            "How I wonder what you are",
            "Up above the world so high",
            "Like a diamond in the sky",
            "Twinkle, twinkle, little star",
            "How I wonder what you are",
        ],
    },
    "两只老虎": {
        "song_id": "two_tigers",
        "source_file": "liangzhilaohu_vocal.mp3",
        "trim_start": 0.0,
        "trim_duration": 16.1,
        "lyrics": [
            "Two tigers, two tigers",
            "Running fast, running fast",
            "One has no eyes",
            "One has no tail",
            "How strange, how strange",
        ],
    },
}
ROBOT_COMMANDS = {
    "直立": ("pose", {"name": "直立"}),
    "放平": ("pose", {"name": "放平"}),
    "抓取": ("sequence", {"name": "抓取"}),
    "搬运": ("sequence", {"name": "搬运"}),
    "复位": ("center", {}),
    "停止": ("stop_motion", {}),
    "张开": ("gripper", {"action": "open"}),
    "闭合": ("gripper", {"action": "close"}),
    "右转移": ("sequence", {"name": "右转移"}),
    "左转移": ("sequence", {"name": "左转移"}),
}


def _legacy_engine_factory():
    root = Path(os.getenv("AIBOX_LEGACY_ROOT", "/root/robot_arm"))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from voice_engine import VoiceEngine

    return VoiceEngine()


def _alsa_pcm_factory():
    import alsaaudio

    return alsaaudio.PCM(
        alsaaudio.PCM_CAPTURE,
        alsaaudio.PCM_NORMAL,
        deployment_environment()["VOICE_INPUT_DEVICE"],
        channels=1,
        rate=16000,
        format=alsaaudio.PCM_FORMAT_S16_LE,
        periodsize=160,
    )


def _legacy_speech_context():
    root = Path(os.getenv("AIBOX_LEGACY_ROOT", "/root/robot_arm"))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from speech_context import correct_text, match_command, match_song

    return correct_text, match_command, match_song


class VoiceWorker:
    def __init__(
        self,
        module_id: str,
        *,
        event_sink: Callable[[dict], None],
        engine_factory: Callable[[], object] | None = None,
        pcm_factory: Callable[[], object] | None = None,
        playback: PlaybackController | None = None,
        robot_adapter: RobotAdapter | None = None,
        on_text: Callable[[str], None] | None = None,
        asset_dir: Path | None = None,
        song_preparer: Callable[[dict, Path], str] | None = None,
        command_matcher: Callable[[str, tuple[str, ...]], str | None] | None = None,
        song_matcher: Callable[[str], str | None] | None = None,
        join_timeout: float = 1.0,
    ) -> None:
        if module_id not in {"voice_input_test", "nursery_rhyme", "voice_robot_arm", "ai_assistant"}:
            raise ValueError(f"未知语音模块: {module_id}")
        self.module_id = module_id
        self._event_sink = event_sink
        self._engine_factory = engine_factory or _legacy_engine_factory
        self._pcm_factory = pcm_factory or _alsa_pcm_factory
        self._playback = playback or PlaybackController()
        self._robot = robot_adapter
        self._on_text = on_text
        self._asset_dir = asset_dir or NURSERY_ASSET_DIR
        self._song_preparer = song_preparer
        self._command_matcher = command_matcher
        self._song_matcher = song_matcher
        self._engine = None
        self._pcm = None
        self._thread: threading.Thread | None = None
        self._listener_started = threading.Event()
        self._join_timeout = join_timeout
        self._listening = threading.Event()
        self._started = False
        self._play_token = 0
        self._play_file: str | None = None
        self._last_event: dict = {}

    @property
    def last_event(self) -> dict:
        return dict(self._last_event)

    def start(self) -> None:
        self.start_listening()

    def start_listening(self) -> dict:
        if self._listening.is_set():
            return {"ok": True, "listening": True}
        if self.module_id == "voice_robot_arm" and self._robot is not None:
            self._robot.connect()
        self._engine = self._engine_factory()
        set_commands = getattr(self._engine, "set_commands", None)
        if self.module_id == "voice_robot_arm":
            commands = {name: None for name in ROBOT_COMMANDS}
            self._engine.use_command_grammar = True
            if callable(set_commands):
                set_commands(commands)
        else:
            self._engine.use_command_grammar = False
            if callable(set_commands):
                set_commands({})
        load = getattr(self._engine, "load", None)
        if callable(load) and not load():
            raise RuntimeError(getattr(self._engine, "last_error", "语音模型加载失败"))
        self._pcm = self._pcm_factory()
        self._started = True
        self._listening.set()
        self._listener_started.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        self._emit({"type": "listening", "module": self.module_id, "message": "正在监听中文语音。"})
        if not self._listener_started.wait(timeout=self._join_timeout):
            self.stop_listening()
            raise TimeoutError("语音监听启动超时。")
        self._emit({"type": "ready", "module": self.module_id, "message": "语音功能已就绪。"})
        return {"ok": True, "listening": True}

    def stop_listening(self) -> dict:
        self._listening.clear()
        if self._engine is not None:
            with suppress(Exception):
                self._engine.running = False
        # Close first: ALSA read may be blocked and must release before stopped.
        pcm = self._pcm
        self._pcm = None
        close = getattr(pcm, "close", None)
        if callable(close):
            with suppress(Exception):
                close()
        stop = getattr(self._engine, "stop", None)
        if callable(stop):
            with suppress(Exception):
                stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._join_timeout)
        if thread is not None and thread.is_alive():
            raise TimeoutError("语音监听停止超时。")
        self._thread = None
        return {"ok": True, "listening": False}

    def stop(self) -> None:
        self.stop_listening()
        self.stop_playback()
        if self.module_id == "voice_robot_arm" and self._robot is not None:
            try:
                self._robot.stop_motion()
            finally:
                self._robot.disconnect()
        self._started = False
        self._emit({"type": "stopped", "module": self.module_id, "message": "语音功能已停止并释放资源。"})

    def command(self, name: str, payload: dict) -> dict:
        if name == "start_listening":
            return self.start_listening()
        if name == "stop_listening":
            return self.stop_listening()
        if name == "play" and self.module_id == "nursery_rhyme":
            return self.play_song(str(payload.get("song_id") or payload.get("song", "")))
        if name == "stop_playback" and self.module_id == "nursery_rhyme":
            self.stop_playback()
            return {"ok": True}
        if name == "stop_motion" and self.module_id == "voice_robot_arm":
            self._stop_robot_now()
            return {"ok": True}
        raise ValueError(f"不支持的语音命令: {name}")

    def play_song(self, song: str) -> dict:
        song = self._resolve_song(song)
        if song not in NURSERY_SONGS:
            raise ValueError("仅支持小星星或两只老虎")
        self._play_token += 1
        token = self._play_token
        source = self._asset_dir / NURSERY_SONGS[song]["source_file"]
        if not source.exists():
            return {"ok": False, "message": f"儿歌资源不存在: {source}"}
        self._remove_play_file()
        play_file = self._song_preparer(NURSERY_SONGS[song], source) if self._song_preparer else self.prepare_song(NURSERY_SONGS[song], source)
        self._play_file = str(play_file)
        self._playback.play(self._play_file, cleanup=True)
        lyrics = list(NURSERY_SONGS[song]["lyrics"])
        result = {"ok": True, "song": song, "lyrics": lyrics, "token": token}
        self._emit({"type": "playing", "message": f"正在播放{song}。", **result})
        return result

    def stop_playback(self) -> None:
        self._play_token += 1
        self._playback.stop()
        self._remove_play_file()

    def prepare_song(
        self,
        spec: dict,
        source: Path,
        *,
        output_path: Path | None = None,
        runner: Callable[..., object] = subprocess.run,
    ) -> str:
        if output_path is None:
            fd, path = tempfile.mkstemp(prefix="feature_demo_nursery_", suffix=".wav")
            os.close(fd)
            output_path = Path(path)
        command = ["ffmpeg", "-y"]
        if "trim_start" in spec:
            command.extend(("-ss", str(spec["trim_start"])))
        command.extend(("-i", str(source)))
        if "trim_duration" in spec:
            command.extend(("-t", str(spec["trim_duration"])))
        command.extend(("-ar", "48000", "-ac", "2", "-acodec", "pcm_s16le", str(output_path)))
        completed = runner(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        if getattr(completed, "returncode", 1) != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            with suppress(FileNotFoundError):
                output_path.unlink()
            raise RuntimeError("儿歌音频转换失败")
        return str(output_path)

    def _listen_loop(self) -> None:
        self._listener_started.set()
        engine = self._engine
        while self._listening.is_set():
            pcm = self._pcm
            if pcm is None:
                return
            try:
                record = getattr(engine, "_record_utterance", None)
                if callable(record):
                    engine.running = self._listening.is_set()
                    captured = record(pcm)
                    audio = captured[0] if isinstance(captured, tuple) else captured
                else:
                    length, audio = pcm.read()
                    if not length:
                        continue
                if not audio:
                    continue
                recognize = getattr(engine, "_recognize_pair", None) or getattr(engine, "recognize_pair", None)
                if not callable(recognize):
                    continue
                raw, normalized = recognize(audio)
                if normalized:
                    self._handle_text(str(raw), str(normalized))
            except Exception as exc:
                if self._listening.is_set():
                    self._emit({"type": "error", "message": str(exc)})
                return

    def _handle_text(self, raw: str, normalized: str) -> None:
        self._emit({"type": "speech", "raw": raw, "normalized": normalized})
        if self._on_text is not None:
            self._on_text(normalized)
        if self.module_id == "nursery_rhyme":
            song = self._match_song(normalized)
            if song:
                self.play_song(song)
        if self.module_id == "voice_robot_arm":
            command = self._match_command(normalized)
            if command:
                self._dispatch_robot(command)

    def _dispatch_robot(self, text: str) -> None:
        if self._robot is None:
            return
        command, payload = ROBOT_COMMANDS[text]
        if command == "center":
            self._robot.command("center", {})
        elif command == "stop_motion":
            self._stop_robot_now()
        else:
            self._robot.command(command, payload)

    def _stop_robot_now(self) -> None:
        if self._robot is not None:
            self._robot.stop_motion()

    def _resolve_song(self, value: str) -> str:
        for label, spec in NURSERY_SONGS.items():
            if value in {label, spec["song_id"]}:
                return label
        return value

    def _match_song(self, text: str) -> str | None:
        if text in NURSERY_SONGS:
            return text
        if self._song_matcher is not None:
            return self._resolve_song(self._song_matcher(text) or "")
        try:
            correct_text, _match_command, match_song = _legacy_speech_context()
            return self._resolve_song(match_song(correct_text(text, "nursery", strict=True)) or "")
        except Exception:
            return None

    def _match_command(self, text: str) -> str | None:
        if text in ROBOT_COMMANDS:
            return text
        matcher = self._command_matcher
        if matcher is None:
            try:
                _correct_text, matcher, _match_song = _legacy_speech_context()
            except Exception:
                return None
        return matcher(text, tuple(ROBOT_COMMANDS))

    def _remove_play_file(self) -> None:
        if self._play_file:
            with suppress(FileNotFoundError):
                Path(self._play_file).unlink()
        self._play_file = None

    def _emit(self, event: dict) -> None:
        self._last_event = dict(event)
        self._event_sink(event)
