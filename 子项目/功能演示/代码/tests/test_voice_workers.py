from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import pytest
import feature_demo.workers.voice as voice_workers

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
        self.read_started = threading.Event()

    def read(self):
        self.read_started.set()
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
        "ai_assistant",
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
        "ai_assistant",
        event_sink=events.append,
        engine_factory=FakeEngine,
        pcm_factory=lambda: FakePCM([]),
    )

    worker.start()

    assert events[-1]["type"] == "ready"
    worker.stop()


def test_voice_calibrates_before_listener_reads_pcm() -> None:
    calls: list[str] = []

    class CalibratingEngine(FakeEngine):
        running = False

        def _calibrate_noise(self, _pcm) -> None:
            assert self.running is True
            calls.append("calibrate")

        def _record_utterance(self, _pcm):
            calls.append("record")
            return b""

    worker = VoiceWorker(
        "ai_assistant",
        event_sink=lambda _event: None,
        engine_factory=CalibratingEngine,
        pcm_factory=lambda: FakePCM([]),
    )

    worker.start()
    deadline = time.monotonic() + 1.0
    while "record" not in calls and time.monotonic() < deadline:
        time.sleep(0.005)
    worker.stop()

    assert calls.index("calibrate") < calls.index("record")


def test_voice_restart_calibration_failure_rolls_back_resources() -> None:
    pcms = [FakePCM([]), FakePCM([]), FakePCM([])]

    class FailingCalibrationEngine(FakeEngine):
        def _calibrate_noise(self, _pcm):
            raise RuntimeError("calibration failed")

    engines = [FakeEngine(), FailingCalibrationEngine(), FakeEngine()]
    worker = VoiceWorker(
        "ai_assistant",
        event_sink=lambda _event: None,
        engine_factory=lambda: engines.pop(0),
        pcm_factory=lambda: pcms.pop(0),
    )
    first_pcm = pcms[0]
    worker.start()
    worker.stop_listening()
    failed_pcm = pcms[0]

    with pytest.raises(RuntimeError, match="calibration failed"):
        worker.start_listening()

    assert failed_pcm.closed is True
    assert worker._listening.is_set() is False
    assert worker._thread is None
    assert worker.start_listening() == {"ok": True, "listening": True}
    worker.stop()
    assert first_pcm.closed is True


def test_stop_during_voice_calibration_wins_without_ready_event() -> None:
    calibration_started = threading.Event()
    release_calibration = threading.Event()
    events = []

    class BlockingCalibrationEngine(FakeEngine):
        def _calibrate_noise(self, _pcm):
            calibration_started.set()
            release_calibration.wait(timeout=1.0)

    worker = VoiceWorker(
        "ai_assistant",
        event_sink=events.append,
        engine_factory=BlockingCalibrationEngine,
        pcm_factory=lambda: FakePCM([]),
    )
    result = {}
    starter = threading.Thread(target=lambda: result.update(worker.start_listening()))
    starter.start()
    assert calibration_started.wait(timeout=1.0)

    assert worker.stop_listening() == {"ok": True, "listening": False}
    release_calibration.set()
    starter.join(timeout=1.0)

    assert starter.is_alive() is False
    assert result == {"ok": True, "listening": False}
    assert worker._thread is None
    assert [event["type"] for event in events] == ["calibrating"]


@pytest.mark.parametrize("text", ["", "   ", "。", "，！", "... "])
def test_voice_ignores_punctuation_only_transcripts(text) -> None:
    calls: list[str] = []
    events: list[dict] = []
    adapter = RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: FakeRobot(serial, calls),
    )
    worker = VoiceWorker(
        "voice_robot_arm",
        event_sink=events.append,
        engine_factory=FakeEngine,
        pcm_factory=lambda: FakePCM(calls),
        robot_adapter=adapter,
        command_matcher=lambda _text, _commands: "抓取",
    )

    worker._handle_text(text, text)

    assert events == []
    assert calls == []


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
    assert pcm.read_started.wait(timeout=1.0)

    with pytest.raises(TimeoutError, match="语音监听停止超时"):
        worker.stop()

    assert worker._thread is not None and worker._thread.is_alive()
    assert "disconnect" not in calls
    assert all(event["type"] != "stopped" for event in events)
    with pytest.raises(RuntimeError, match="上一监听线程"):
        worker.start_listening()
    pcm.release.set()
    worker._thread.join(timeout=1.0)


def test_audio_returned_after_stop_never_emits_speech() -> None:
    capture_started = threading.Event()
    release_capture = threading.Event()
    events: list[dict] = []

    class LateAudioEngine(FakeEngine):
        def _record_utterance(self, _pcm):
            capture_started.set()
            release_capture.wait(timeout=1.0)
            return b"late audio"

    worker = VoiceWorker(
        "ai_assistant",
        event_sink=events.append,
        engine_factory=LateAudioEngine,
        pcm_factory=lambda: BlockedPCM([]),
        join_timeout=0.05,
    )
    worker.start()
    assert capture_started.wait(timeout=1.0)

    with pytest.raises(TimeoutError, match="语音监听停止超时"):
        worker.stop_listening()
    release_capture.set()
    worker._thread.join(timeout=1.0)

    assert all(event["type"] != "speech" for event in events)
    worker.stop_listening()


def test_stop_between_final_check_and_text_acceptance_discards_audio() -> None:
    final_check_passed = threading.Event()
    release_final_check = threading.Event()
    events: list[dict] = []

    class ImmediateAudioEngine(FakeEngine):
        def _record_utterance(self, _pcm):
            return b"captured audio"

    class PausingWorker(VoiceWorker):
        def _accept_transcript(self, generation, engine, pcm, raw, normalized):
            final_check_passed.set()
            release_final_check.wait(timeout=1.0)
            return super()._accept_transcript(
                generation, engine, pcm, raw, normalized
            )

    worker = PausingWorker(
        "ai_assistant",
        event_sink=events.append,
        engine_factory=ImmediateAudioEngine,
        pcm_factory=lambda: FakePCM([]),
        join_timeout=0.5,
    )
    worker.start()
    assert final_check_passed.wait(timeout=1.0)
    stopped = {}
    stopper = threading.Thread(target=lambda: stopped.update(worker.stop_listening()))
    stopper.start()
    deadline = time.monotonic() + 1.0
    while worker._listening.is_set() and time.monotonic() < deadline:
        time.sleep(0.005)
    release_final_check.set()
    stopper.join(timeout=1.0)

    assert stopped == {"ok": True, "listening": False}
    assert all(event["type"] != "speech" for event in events)


@pytest.mark.parametrize(
    "module_id", ["nursery_rhyme", "ai_assistant"]
)
def test_non_robot_voice_workers_disable_command_grammar(module_id) -> None:
    engine = FakeEngine()
    engine.use_command_grammar = True
    worker = VoiceWorker(
        module_id,
        event_sink=lambda _event: None,
        engine_factory=lambda: engine,
        pcm_factory=lambda: FakePCM([]),
    )

    worker.start()

    assert engine.use_command_grammar is False
    assert engine.commands == {}
    worker.stop()
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
        "nursery_rhyme": VoiceWorker,
        "voice_robot_arm": VoiceWorker,
        "ai_assistant": AssistantWorker,
    }.items():
        worker = runtime.create_worker(module_id, event_sink=lambda _event: None)
        assert isinstance(worker, expected_type)


def test_voice_robot_arm_closes_microphone_then_preserves_upright_on_shutdown() -> None:
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
    upright_label = next(
        label
        for label, (command, payload) in voice_workers.ROBOT_COMMANDS.items()
        if command == "pose" and payload.get("name") == "直立"
    )
    worker._dispatch_robot(upright_label)
    worker._dispatch_robot(upright_label)
    worker.stop()

    assert "stop_motion" not in calls
    assert calls.count("connect") == 1
    assert calls.count("disconnect") == 1
    assert "pcm_close" in calls


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
    events: list[dict] = []
    pcm = FakePCM(calls)
    adapter = RobotAdapter(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: FakeRobot(serial, calls),
    )
    worker = VoiceWorker(
        "voice_robot_arm",
        event_sink=events.append,
        engine_factory=FakeEngine,
        pcm_factory=lambda: pcm,
        robot_adapter=adapter,
        command_matcher=lambda _text, _commands: "复位",
    )
    worker.start()
    worker._handle_text("回到中间", "回到中间")

    assert "center" in calls
    assert events[-1]["type"] == "robot_action"
    assert events[-1]["recognized"] == "复位"
    assert events[-1]["command"] == "center"
    assert events[-1]["ok"] is True
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

    assert result == {"ok": True, "interrupted": True}
    assert worker.last_event == {
        "type": "assistant_status",
        "status": "idle",
        "message": "回答已停止。",
    }


def test_assistant_interrupt_immediately_reports_stopped_while_model_is_blocked() -> None:
    model_started = threading.Event()
    release_model = threading.Event()
    events = []

    class BlockingModel:
        def __call__(self, *_args, **_kwargs):
            model_started.set()
            assert release_model.wait(timeout=2)
            yield {"choices": [{"text": "过期回答"}]}

    worker = AssistantWorker(event_sink=events.append, llm_factory=BlockingModel)
    result = {}
    ask_thread = threading.Thread(target=lambda: result.update(worker.ask("问题")))
    ask_thread.start()
    assert model_started.wait(timeout=1)

    assert worker.command("interrupt", {})["ok"] is True
    assert worker.last_event == {
        "type": "assistant_status",
        "status": "idle",
        "message": "回答已停止。",
    }

    release_model.set()
    ask_thread.join(timeout=1)
    assert result == {"ok": True, "interrupted": True}
    assert all(event["type"] != "assistant_reply" for event in events)


def test_interrupted_assistant_ignores_stale_model_error() -> None:
    model_started = threading.Event()
    release_model = threading.Event()
    events = []

    class FailingModel:
        def __call__(self, *_args, **_kwargs):
            model_started.set()
            assert release_model.wait(timeout=2)
            raise RuntimeError("stale failure")

    worker = AssistantWorker(event_sink=events.append, llm_factory=FailingModel)
    result = {}
    ask_thread = threading.Thread(target=lambda: result.update(worker.ask("问题")))
    ask_thread.start()
    assert model_started.wait(timeout=1)

    worker.command("interrupt", {})
    release_model.set()
    ask_thread.join(timeout=1)

    assert not ask_thread.is_alive()
    assert result == {"ok": True, "interrupted": True}
    assert worker.last_event["status"] == "idle"
    assert all(event.get("status") != "error" for event in events)


def test_assistant_does_not_commit_reply_after_newer_turn() -> None:
    events = []
    worker = AssistantWorker(event_sink=events.append)
    old_turn = worker.interrupt(emit_status=False)
    worker.interrupt()

    committed = worker._commit_reply(old_turn, "旧问题", "旧回答")

    assert committed is None
    assert worker.last_event["status"] == "idle"
    assert all(event["type"] != "assistant_reply" for event in events)


def test_assistant_turn_change_waits_for_previous_status_publication() -> None:
    idle_publication_started = threading.Event()
    release_idle_publication = threading.Event()
    newer_turn_finished = threading.Event()

    def sink(event):
        if event.get("status") == "idle" and not idle_publication_started.is_set():
            idle_publication_started.set()
            assert release_idle_publication.wait(timeout=2)

    worker = AssistantWorker(event_sink=sink)
    idle_thread = threading.Thread(target=worker.interrupt)
    idle_thread.start()
    assert idle_publication_started.wait(timeout=1)

    newer_thread = threading.Thread(
        target=lambda: (
            worker.interrupt(emit_status=False),
            newer_turn_finished.set(),
        )
    )
    newer_thread.start()
    assert not newer_turn_finished.wait(timeout=0.05)

    release_idle_publication.set()
    idle_thread.join(timeout=1)
    newer_thread.join(timeout=1)
    assert newer_turn_finished.is_set()


def test_stale_tts_cannot_replace_newer_turn_queue() -> None:
    class ExistingThread:
        @staticmethod
        def is_alive():
            return True

    worker = AssistantWorker(event_sink=lambda _event: None)
    worker._tts_thread = ExistingThread()
    old_turn = worker.interrupt(emit_status=False)
    new_turn = worker.interrupt(emit_status=False)

    worker._queue_tts_latest(new_turn, "新回答")
    worker._queue_tts_latest(old_turn, "旧回答")

    assert worker._tts_queue.get_nowait() == (new_turn, "新回答")
    with pytest.raises(queue.Empty):
        worker._tts_queue.get_nowait()


def test_assistant_emits_generating_status_before_reply() -> None:
    events = []

    class ReplyModel:
        def __call__(self, *_args, **_kwargs):
            yield {"choices": [{"text": "回答"}]}

    worker = AssistantWorker(event_sink=events.append, llm_factory=ReplyModel)

    result = worker.ask("问题")

    assert result["ok"] is True
    assert events[-2] == {
        "type": "assistant_status",
        "status": "generating",
        "message": "模型正在生成…",
    }
    assert events[-1]["type"] == "assistant_reply"


def test_assistant_reports_voice_input_status_after_listener_starts() -> None:
    events = []

    class Voice:
        def start_listening(self):
            return {"ok": True, "listening": True}

        def stop_listening(self):
            return {"ok": True, "listening": False}

    worker = AssistantWorker(
        event_sink=events.append,
        voice_factory=lambda _on_text: Voice(),
    )

    assert worker.start_listening() == {"ok": True, "listening": True}
    assert events[-1] == {
        "type": "assistant_status",
        "status": "listening",
        "message": "正在语音输入…",
    }
    assert worker.stop_listening() == {"ok": True, "listening": False}
    assert events[-1]["status"] == "idle"


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


def test_assistant_stop_does_not_fail_while_daemon_tts_finishes(tmp_path: Path) -> None:
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
    tts_thread = worker._tts_thread
    assert tts_thread is not None

    worker.stop()

    assert tts_thread.is_alive()
    assert playback.paths == []
    assert worker.last_event["type"] == "stopped"
    release.set()
    tts_thread.join(timeout=1.0)
    assert playback.paths == []
    assert not wav.exists()


def test_assistant_interrupt_serializes_with_playback_start(tmp_path: Path) -> None:
    play_entered = threading.Event()
    release_play = threading.Event()
    interrupt_finished = threading.Event()
    wav = tmp_path / "race.wav"
    wav.write_bytes(b"wav")

    class GatedPlayback(FakePlayback):
        def __init__(self) -> None:
            super().__init__()
            self.active = False

        def play(self, path: str, **_kwargs) -> None:
            play_entered.set()
            assert release_play.wait(timeout=1.0)
            self.paths.append(path)
            self.active = True

        def stop(self) -> None:
            super().stop()
            self.active = False

    class ReplyModel:
        def __call__(self, *_args, **_kwargs):
            yield {"choices": [{"text": "旧回答"}]}

    playback = GatedPlayback()
    worker = AssistantWorker(
        event_sink=lambda _event: None,
        llm_factory=ReplyModel,
        tts_factory=lambda _text: str(wav),
        playback=playback,
    )

    worker.ask("测试中断竞态")
    assert play_entered.wait(timeout=1.0)
    interrupt_thread = threading.Thread(
        target=lambda: (worker.interrupt(), interrupt_finished.set()),
    )
    interrupt_thread.start()

    assert not interrupt_finished.wait(timeout=0.05)
    release_play.set()
    interrupt_thread.join(timeout=1.0)
    assert interrupt_finished.is_set()
    assert playback.active is False
    assert worker.last_event["status"] == "idle"
    worker.stop()


def test_assistant_interrupt_serializes_with_tts_error_publication() -> None:
    error_entered = threading.Event()
    release_error = threading.Event()
    interrupt_finished = threading.Event()

    def emit(event: dict) -> None:
        if event.get("type") == "error":
            error_entered.set()
            assert release_error.wait(timeout=1.0)

    class ReplyModel:
        def __call__(self, *_args, **_kwargs):
            yield {"choices": [{"text": "回答"}]}

    worker = AssistantWorker(
        event_sink=emit,
        llm_factory=ReplyModel,
        tts_factory=lambda _text: (_ for _ in ()).throw(RuntimeError("tts failed")),
        playback=FakePlayback(),
    )
    worker.ask("测试语音错误")
    assert error_entered.wait(timeout=1.0)
    interrupt_thread = threading.Thread(
        target=lambda: (worker.interrupt(), interrupt_finished.set()),
    )
    interrupt_thread.start()

    assert not interrupt_finished.wait(timeout=0.05)
    release_error.set()
    interrupt_thread.join(timeout=1.0)
    assert interrupt_finished.is_set()
    assert worker.last_event["status"] == "idle"
    worker.stop()


@pytest.mark.parametrize("operation", ["start", "stop"])
def test_assistant_listening_result_does_not_overwrite_newer_turn(operation: str) -> None:
    operation_entered = threading.Event()
    release_operation = threading.Event()

    class Voice:
        def start_listening(self):
            operation_entered.set()
            assert release_operation.wait(timeout=1.0)
            return {"ok": True, "listening": True}

        def stop_listening(self):
            operation_entered.set()
            assert release_operation.wait(timeout=1.0)
            return {"ok": True, "listening": False}

        def stop(self):
            return None

    voice = Voice()
    worker = AssistantWorker(
        event_sink=lambda _event: None,
        voice_factory=lambda _on_text: voice,
        playback=FakePlayback(),
    )
    if operation == "stop":
        worker._voice = voice
    listening_thread = threading.Thread(
        target=worker.start_listening if operation == "start" else worker.stop_listening,
    )
    listening_thread.start()
    assert operation_entered.wait(timeout=1.0)

    newer_turn = worker.interrupt(status="generating")
    release_operation.set()
    listening_thread.join(timeout=1.0)
    assert not listening_thread.is_alive()
    assert worker.last_event == {
        "type": "assistant_status",
        "status": "generating",
        "message": "模型正在生成…",
    }
    assert worker._current_turn() == newer_turn
    worker.stop()
