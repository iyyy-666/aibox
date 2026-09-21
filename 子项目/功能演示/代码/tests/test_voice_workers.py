from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from feature_demo.adapters.audio import deployment_environment
from feature_demo.adapters.robot import RobotAdapter
from feature_demo.workers import runtime
from feature_demo.workers.assistant import AssistantWorker, assistant_system_prompt
from feature_demo.workers.voice import VoiceWorker


class FakePCM:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.closed = False
        self.release = threading.Event()

    def read(self):
        self.release.wait(timeout=1)
        return 0, b""

    def close(self) -> None:
        self.closed = True
        self.calls.append("pcm_close")
        self.release.set()


class BlockedPCM(FakePCM):
    def close(self) -> None:
        self.closed = True
        self.calls.append("pcm_close")


class FakeEngine:
    def __init__(self) -> None:
        self.loaded = False
        self.commands = {}

    def set_commands(self, commands) -> None:
        self.commands = dict(commands)

    def load(self) -> bool:
        self.loaded = True
        return True

    def recognize_pair(self, audio: bytes) -> tuple[str, str]:
        return "原始结果", "规范结果"

    def stop(self) -> None:
        return None


class FakePlayback:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.stopped = 0

    def play(self, path: str, **_kwargs) -> None:
        self.paths.append(path)

    def stop(self) -> None:
        self.stopped += 1


class FakeProcess:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.calls.append("terminate")
        self.returncode = 0

    def wait(self, timeout=None):
        self.calls.append("wait")
        return self.returncode

    def kill(self) -> None:
        self.calls.append("kill")
        self.returncode = -9


class FakeSerial:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.connected = False

    def connect(self):
        self.connected = True
        self.calls.append("connect")
        return True

    def disconnect(self):
        self.calls.append("disconnect")
        self.connected = False


class FakeRobot:
    def __init__(self, serial, calls: list[str]) -> None:
        self.calls = calls

    def execute_pose(self, name):
        self.calls.append(("pose", name))
        return True

    def execute_sequence(self, name):
        self.calls.append(("sequence", name))
        return True

    def all_center(self):
        self.calls.append("center")
        return True

    def stop(self):
        self.calls.append("stop_motion")
        return True

    def gripper_open(self):
        self.calls.append("open")
        return True

    def gripper_close(self):
        self.calls.append("close")
        return True


def test_voice_worker_closes_pcm_before_stopped_event() -> None:
    calls: list[str] = []
    pcm = FakePCM(calls)
    events: list[dict] = []
    worker = VoiceWorker(
        "voice_input_test",
        event_sink=lambda event: events.append(event),
        engine_factory=FakeEngine,
        pcm_factory=lambda: pcm,
    )

    worker.start()
    worker.stop()

    assert pcm.closed is True
    assert events[-1]["type"] == "stopped"
    assert calls.index("pcm_close") < len(calls)


def test_voice_worker_emits_ready_as_its_final_startup_signal() -> None:
    events: list[dict] = []
    worker = VoiceWorker(
        "voice_input_test",
        event_sink=events.append,
        engine_factory=FakeEngine,
        pcm_factory=lambda: FakePCM([]),
    )

    worker.start()

    assert events[-1]["type"] == "ready"
    worker.stop()


def test_blocked_voice_listener_prevents_premature_stopped_or_robot_disconnect() -> None:
    calls: list[str] = []
    pcm = BlockedPCM(calls)
    adapter = RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: FakeRobot(serial, calls),
    )
    events: list[dict] = []
    worker = VoiceWorker(
        "voice_robot_arm",
        event_sink=events.append,
        engine_factory=FakeEngine,
        pcm_factory=lambda: pcm,
        robot_adapter=adapter,
        join_timeout=0.05,
    )
    worker.start()

    with pytest.raises(TimeoutError):
        worker.stop()

    assert worker._thread is not None and worker._thread.is_alive()
    assert "disconnect" not in calls
    assert all(event["type"] != "stopped" for event in events)
    pcm.release.set()
    worker._thread.join(timeout=1.0)
    worker.stop()


def test_audio_player_only_terminates_its_tracked_process() -> None:
    calls: list[str] = []
    from feature_demo.adapters.audio import PlaybackController

    player = PlaybackController(popen_factory=lambda *_args, **_kwargs: FakeProcess(calls))
    player.play("/tmp/song.wav")
    player.stop()

    assert calls == ["terminate", "wait"]


def test_voice_configuration_uses_chinese() -> None:
    environment = deployment_environment()

    assert environment["VOICE_LANGUAGE"] == "zh"


def test_assistant_system_prompt_is_chinese() -> None:
    assert "中文" in assistant_system_prompt()


def test_runtime_dispatches_all_voice_modules_lazily() -> None:
    for module_id, expected_type in {
        "voice_input_test": VoiceWorker,
        "nursery_rhyme": VoiceWorker,
        "voice_robot_arm": VoiceWorker,
        "ai_assistant": AssistantWorker,
    }.items():
        worker = runtime.create_worker(module_id, event_sink=lambda _event: None)
        assert isinstance(worker, expected_type)


def test_voice_robot_arm_stops_microphone_before_robot_shutdown() -> None:
    calls: list[str] = []
    pcm = FakePCM(calls)
    adapter = RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: FakeRobot(serial, calls),
    )
    worker = VoiceWorker(
        "voice_robot_arm",
        event_sink=lambda _event: None,
        engine_factory=FakeEngine,
        pcm_factory=lambda: pcm,
        robot_adapter=adapter,
    )

    worker.start()
    worker.stop()

    assert calls.index("pcm_close") < calls.index("stop_motion") < calls.index("disconnect")


def test_two_tigers_song_id_is_trimmed_and_normalized_before_playback(tmp_path: Path) -> None:
    source = tmp_path / "liangzhilaohu_vocal.mp3"
    source.write_bytes(b"source")
    output = tmp_path / "two_tigers.wav"
    commands: list[list[str]] = []
    playback = FakePlayback()

    def runner(command, **_kwargs):
        commands.append(command)
        output.write_bytes(b"wav")
        return type("Completed", (), {"returncode": 0})()

    worker = VoiceWorker(
        "nursery_rhyme",
        event_sink=lambda _event: None,
        engine_factory=FakeEngine,
        pcm_factory=lambda: FakePCM([]),
        playback=playback,
        asset_dir=tmp_path,
        song_preparer=lambda spec, source_path: worker.prepare_song(spec, source_path, output_path=output, runner=runner),
    )

    result = worker.command("play", {"song_id": "two_tigers"})

    assert result["ok"] is True
    assert playback.paths == [str(output)]
    assert "-t" in commands[0]
    assert commands[0][commands[0].index("-t") + 1] == "16.1"
    assert commands[0][commands[0].index("-ar") + 1] == "48000"
    assert commands[0][commands[0].index("-ac") + 1] == "2"


def test_nursery_play_event_and_result_include_legacy_english_lyrics(tmp_path: Path) -> None:
    source = tmp_path / "xiaoxingxing_vocal.mp3"
    source.write_bytes(b"source")
    events: list[dict] = []
    worker = VoiceWorker(
        "nursery_rhyme",
        event_sink=events.append,
        engine_factory=FakeEngine,
        pcm_factory=lambda: FakePCM([]),
        playback=FakePlayback(),
        asset_dir=tmp_path,
        song_preparer=lambda _spec, source_path: str(source_path),
    )

    result = worker.play_song("twinkle")

    expected = [
        "Twinkle, twinkle, little star",
        "How I wonder what you are",
        "Up above the world so high",
        "Like a diamond in the sky",
        "Twinkle, twinkle, little star",
        "How I wonder what you are",
    ]
    assert result["lyrics"] == expected
    assert events[-1]["lyrics"] == expected


def test_voice_robot_arm_uses_legacy_command_match_and_all_center() -> None:
    calls: list[str] = []
    pcm = FakePCM(calls)
    adapter = RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: FakeRobot(serial, calls),
    )
    worker = VoiceWorker(
        "voice_robot_arm",
        event_sink=lambda _event: None,
        engine_factory=FakeEngine,
        pcm_factory=lambda: pcm,
        robot_adapter=adapter,
        command_matcher=lambda _text, _commands: "复位",
    )
    worker.start()
    worker._handle_text("回到中间", "回到中间")

    assert "center" in calls
    worker.stop()


def test_assistant_discards_stale_reply_and_never_queues_it() -> None:
    holder = {}

    class InterruptingModel:
        def __call__(self, *_args, **_kwargs):
            yield {"choices": [{"text": "第一段"}]}
            holder["worker"].interrupt()
            yield {"choices": [{"text": "第二段"}]}

    worker = AssistantWorker(event_sink=lambda _event: None, llm_factory=InterruptingModel)
    holder["worker"] = worker

    result = worker.ask("请介绍人工智能")

    assert result == {"ok": False, "interrupted": True}
    assert worker.last_event == {}


def test_assistant_lazily_synthesizes_latest_reply_for_tracked_playback(tmp_path: Path) -> None:
    generated = threading.Event()
    playback = FakePlayback()
    wav = tmp_path / "assistant.wav"
    wav.write_bytes(b"wav")

    class ReplyModel:
        def __call__(self, *_args, **_kwargs):
            yield {"choices": [{"text": "这是中文回答。"}]}

    def synthesize(text: str) -> str:
        assert text == "这是中文回答。"
        generated.set()
        return str(wav)

    worker = AssistantWorker(
        event_sink=lambda _event: None,
        llm_factory=ReplyModel,
        tts_factory=synthesize,
        playback=playback,
    )

    assert worker.ask("请用中文回答")["ok"] is True
    assert generated.wait(timeout=1.0)
    assert playback.paths == [str(wav)]
    worker.stop()


def test_assistant_stop_invalidates_blocked_tts_before_playback(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    playback = FakePlayback()
    wav = tmp_path / "late.wav"
    wav.write_bytes(b"wav")

    class ReplyModel:
        def __call__(self, *_args, **_kwargs):
            yield {"choices": [{"text": "延迟回答"}]}

    def synthesize(_text: str) -> str:
        started.set()
        assert release.wait(timeout=1.0)
        return str(wav)

    worker = AssistantWorker(
        event_sink=lambda _event: None,
        llm_factory=ReplyModel,
        tts_factory=synthesize,
        playback=playback,
        tts_join_timeout=0.05,
    )
    worker.ask("测试关闭")
    assert started.wait(timeout=1.0)

    with pytest.raises(TimeoutError):
        worker.stop()

    assert worker._tts_thread is not None and worker._tts_thread.is_alive()
    assert playback.paths == []
    assert worker.last_event["type"] != "stopped"
    release.set()
    worker._tts_thread.join(timeout=1.0)
    worker.stop()
    assert playback.paths == []
    assert not wav.exists()
