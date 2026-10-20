"""Local lifecycle regressions; audio devices and models are external doubles."""
import threading

import pytest

from feature_demo.workers.voice import VoiceWorker
from feature_demo.workers.assistant import AssistantWorker


class PCM:
    def __init__(self):
        self.closed = threading.Event()

    def read(self):
        self.closed.wait(2)
        return 0, b""

    def close(self):
        self.closed.set()


class Engine:
    def __init__(self):
        self.loaded = False
        self.commands = {}

    def load(self):
        self.loaded = True
        return True

    def set_commands(self, commands):
        self.commands = commands

    def stop(self):
        self.running = False


@pytest.mark.parametrize("module", ["nursery_rhyme", "voice_robot_arm", "ai_assistant"])
def test_repeated_listening_keeps_model_but_reopens_microphone(module):
    engines, microphones = [], []

    def make_engine():
        engine = Engine()
        engines.append(engine)
        return engine

    def make_pcm():
        pcm = PCM()
        microphones.append(pcm)
        return pcm

    worker = VoiceWorker(module, event_sink=lambda _: None,
                         engine_factory=make_engine, pcm_factory=make_pcm)
    try:
        worker.start_listening()
        worker.stop_listening()
        worker.start_listening()
        assert len(engines) == 1
        assert len(microphones) == 2
        assert microphones[0].closed.is_set()
        assert not microphones[1].closed.is_set()
        assert engines[0].use_command_grammar is (module == "voice_robot_arm")
        assert bool(engines[0].commands) is (module == "voice_robot_arm")
    finally:
        worker.stop()


def test_capture_failure_releases_microphone_and_allows_retry():
    events = []
    failed = threading.Event()
    allow_failure = threading.Event()
    microphones = []

    class FailingPCM(PCM):
        def read(self):
            allow_failure.wait(2)
            raise RuntimeError("capture failed")

        def close(self):
            super().close()
            failed.set()

    def make_pcm():
        pcm = FailingPCM() if not microphones else PCM()
        microphones.append(pcm)
        return pcm

    worker = VoiceWorker("ai_assistant", event_sink=events.append,
                         engine_factory=Engine, pcm_factory=make_pcm)
    try:
        worker.start()
        thread = worker._thread
        allow_failure.set()
        thread.join(1)
        assert failed.is_set()
        assert not worker._listening.is_set()
        assert worker.start_listening()["listening"]
        assert len(microphones) == 2
        assert [event["message"] for event in events if event["type"] == "error"] == ["capture failed"]
    finally:
        worker.stop()


def test_restart_waits_for_cancelled_calibration_before_reusing_engine():
    entered, release = threading.Event(), threading.Event()

    class CalibratingEngine(Engine):
        def _calibrate_noise(self, _pcm):
            entered.set()
            release.wait(2)

    worker = VoiceWorker("ai_assistant", event_sink=lambda _: None,
                         engine_factory=CalibratingEngine, pcm_factory=PCM)
    results = []
    starter = threading.Thread(target=lambda: results.append(worker.start_listening()))
    starter.start()
    assert entered.wait(1)
    worker.stop_listening()
    try:
        with pytest.raises(RuntimeError, match="启动"):
            worker.start_listening()
    finally:
        release.set()
        starter.join(1)
        worker.stop()
    assert results == [{"ok": True, "listening": False}]


@pytest.mark.parametrize("stop_count", [1, 2])
def test_restart_rejected_until_all_engine_stops_finish(stop_count):
    entered = [threading.Event() for _ in range(stop_count)]
    releases = [threading.Event() for _ in range(stop_count)]
    stop_lock = threading.Lock()
    stop_calls = []

    class SlowStopEngine(Engine):
        def stop(self):
            with stop_lock:
                index = len(stop_calls)
                stop_calls.append(index)
            if index < stop_count:
                entered[index].set()
                releases[index].wait(2)
            super().stop()

    worker = VoiceWorker("ai_assistant", event_sink=lambda _: None,
                         engine_factory=SlowStopEngine, pcm_factory=PCM)
    worker.start()
    listener = worker._thread
    stoppers = []
    try:
        for index in range(stop_count):
            stopper = threading.Thread(target=worker.stop_listening)
            stoppers.append(stopper)
            stopper.start()
            assert entered[index].wait(1)
        listener.join(1)
        assert not listener.is_alive()
        # Dead listener is insufficient: native engine cleanup still owns it.
        with pytest.raises(RuntimeError, match="停止"):
            worker.start_listening()
        if stop_count == 2:
            releases[0].set()
            stoppers[0].join(1)
            assert not stoppers[0].is_alive()
            with pytest.raises(RuntimeError, match="停止"):
                worker.start_listening()
    finally:
        for release in releases:
            release.set()
        for stopper in stoppers:
            stopper.join(1)
        worker.stop_listening()
    try:
        assert worker.start_listening()["listening"]
    finally:
        worker.stop()


def test_interrupt_stays_responsive_during_model_loading():
    entered, release, interrupted = threading.Event(), threading.Event(), threading.Event()
    result = {}

    def factory():
        entered.set()
        release.wait(2)
        return lambda *_args, **_kwargs: iter([])

    worker = AssistantWorker(event_sink=lambda _: None, llm_factory=factory)
    ask = threading.Thread(target=lambda: result.update(worker.ask("问题")))
    ask.start()
    assert entered.wait(1)
    interrupt = threading.Thread(target=lambda: (worker.interrupt(), interrupted.set()))
    interrupt.start()
    try:
        assert interrupted.wait(0.1)
    finally:
        release.set()
        ask.join(1)
        interrupt.join(1)
        worker.stop()
    assert result == {"ok": True, "interrupted": True}


def test_new_turn_waits_for_old_model_stream_to_leave_context():
    entered, release, second_entered = threading.Event(), threading.Event(), threading.Event()
    calls = []
    results = []

    class Model:
        def __call__(self, prompt, **_kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                entered.set()
                release.wait(2)
            else:
                second_entered.set()
            yield {"choices": [{"text": "回答"}]}

    worker = AssistantWorker(event_sink=lambda _: None, llm_factory=Model)
    worker._queue_tts_latest = lambda *_: None
    first = threading.Thread(target=lambda: results.append(worker.ask("旧问题")))
    second = threading.Thread(target=lambda: results.append(worker.ask("新问题")))
    first.start()
    assert entered.wait(1)
    second.start()
    try:
        assert not second_entered.wait(0.1)
    finally:
        release.set()
        first.join(1)
        second.join(1)
        worker.stop()
    assert len(calls) == 2
    assert {"ok": True, "interrupted": True} in results
    assert any(result.get("text") == "回答" for result in results)
