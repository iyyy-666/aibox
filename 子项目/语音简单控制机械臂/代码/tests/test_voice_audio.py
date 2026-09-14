import threading
import time
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from voice_engine import VoiceEngine, clamp_level, dbfs_percent, trigger_confirmed


def test_clamp_level_prevents_display_overflow() -> None:
    assert clamp_level(-0.2) == 0.0
    assert clamp_level(0.45) == 0.45
    assert clamp_level(2.0) == 1.0


def test_dbfs_percent_stays_in_display_range() -> None:
    assert dbfs_percent(0.0) == 0
    assert dbfs_percent(1.0) == 100
    assert 0 < dbfs_percent(0.1) < 100


def test_trigger_requires_consecutive_frames() -> None:
    assert not trigger_confirmed(0, True, required_frames=3)
    assert not trigger_confirmed(1, True, required_frames=3)
    assert trigger_confirmed(2, True, required_frames=3)
    assert not trigger_confirmed(2, False, required_frames=3)


def test_concurrent_load_requests_initialize_model_once() -> None:
    engine = VoiceEngine()
    model_load_started = threading.Event()
    release_model_load = threading.Event()
    load_count = 0
    count_lock = threading.Lock()

    engine._pick_backend = lambda: "sensevoice"

    def load_model() -> bool:
        nonlocal load_count
        with count_lock:
            load_count += 1
        model_load_started.set()
        assert release_model_load.wait(timeout=2)
        return True

    engine._load_sensevoice_model = load_model

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(engine.load)
        assert model_load_started.wait(timeout=1)
        second = pool.submit(engine.load)
        time.sleep(0.05)
        concurrent_load_count = load_count
        release_model_load.set()

        assert first.result(timeout=1)
        assert second.result(timeout=1)

    assert concurrent_load_count == 1
    assert load_count == 1
    assert engine.status()["loaded"] is True


def test_busy_robot_accepts_only_emergency_stop() -> None:
    engine = VoiceEngine()
    invoked = []
    engine.set_commands({
        "停止": lambda command: invoked.append(command),
        "张开": lambda command: invoked.append(command),
    })

    engine._match("open", stop_only=True)
    engine._match("stop", stop_only=True)

    assert invoked == ["停止"]
