from __future__ import annotations

import multiprocessing
import threading
from pathlib import Path

import pytest

from feature_demo.manager import ModuleConflictError, ModuleManager, ProcessLock
from feature_demo.models import ModuleState
from feature_demo.resources import ReleaseReport
from tests.fakes.fake_worker import FakeWorker


def _attempt_process_lock(path, acquired, release):
    lock = ProcessLock(Path(path))
    held = lock.acquire()
    acquired.put(held)
    if held:
        release.wait(timeout=5)
        lock.release()


class FakeVerifier:
    def __init__(self):
        self.report = ReleaseReport(ok=True)
        self.calls = []

    def verify(self, module, worker_pids):
        self.calls.append((module.module_id, tuple(worker_pids)))
        return self.report


@pytest.fixture
def verifier():
    return FakeVerifier()


@pytest.fixture
def workers():
    return {}


@pytest.fixture
def manager(tmp_path, verifier, workers):
    def factory(module):
        worker = FakeWorker(module.module_id, pid=42000 + len(workers))
        workers[module.module_id] = worker
        return worker

    return ModuleManager(
        worker_factory=factory,
        verifier=verifier,
        lock_path=tmp_path / "feature-demo.lock",
    )


def test_manager_rejects_second_module_while_one_is_active(manager):
    manager.start_module("color_recognition")

    with pytest.raises(ModuleConflictError):
        manager.start_module("shape_recognition")


def test_process_lock_uses_os_ownership_and_keeps_lock_file(tmp_path):
    context = multiprocessing.get_context("spawn")
    lock_path = tmp_path / "process.lock"
    first_result = context.Queue()
    first_release = context.Event()
    first = context.Process(
        target=_attempt_process_lock,
        args=(str(lock_path), first_result, first_release),
    )
    first.start()
    assert first_result.get(timeout=5) is True

    second_result = context.Queue()
    second_release = context.Event()
    second_release.set()
    second = context.Process(
        target=_attempt_process_lock,
        args=(str(lock_path), second_result, second_release),
    )
    second.start()
    assert second_result.get(timeout=5) is False
    second.join(timeout=5)

    first_release.set()
    first.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert lock_path.is_file()
    later = ProcessLock(lock_path)
    assert later.acquire() is True
    later.release()
    assert lock_path.is_file()


def test_manager_keeps_active_module_when_release_verification_fails(
    manager, verifier
):
    manager.start_module("color_recognition")
    verifier.report = ReleaseReport(ok=False, busy_resources=("camera",))

    result = manager.stop_module("color_recognition")

    assert result.state == ModuleState.CLEANUP_FAILED
    assert result.busy_resources == ("camera",)
    assert manager.active_module == "color_recognition"


def test_repeated_stop_is_idempotent(manager):
    result = manager.stop_module("color_recognition")

    assert result.state == ModuleState.IDLE
    assert manager.active_module is None


def test_successful_stop_clears_active_module_after_verification(
    manager, verifier, workers
):
    manager.start_module("color_recognition")

    result = manager.stop_module("color_recognition")

    assert workers["color_recognition"].stopped
    assert verifier.calls == [("color_recognition", ())]
    assert result.state == ModuleState.IDLE
    assert manager.active_module is None


def test_manager_rejects_unregistered_command(manager):
    manager.start_module("color_recognition")

    with pytest.raises(ValueError, match="不支持的命令"):
        manager.command("color_recognition", "gimbal_center", {})


class BlockingWorker(FakeWorker):
    def __init__(self, module_id):
        super().__init__(module_id)
        self.command_started = threading.Event()
        self.release_command = threading.Event()
        self.control_seen = threading.Event()

    def command(self, name, payload):
        if name in {"sequence", "ask"}:
            self.command_started.set()
            self.release_command.wait(timeout=2)
        if name in {"stop_motion", "interrupt"}:
            self.control_seen.set()
            self.release_command.set()
        return super().command(name, payload)

    def stop(self, timeout):
        self.control_seen.set()
        self.release_command.set()
        super().stop(timeout)


def _blocking_manager(tmp_path, verifier, module_id):
    worker = BlockingWorker(module_id)
    instance = ModuleManager(
        worker_factory=lambda _module: worker,
        verifier=verifier,
        lock_path=tmp_path / f"{module_id}.lock",
    )
    instance.start_module(module_id)
    return instance, worker


def test_preemptive_command_bypasses_a_long_ordinary_command(tmp_path, verifier):
    manager, worker = _blocking_manager(tmp_path, verifier, "robot_button")
    ordinary = threading.Thread(
        target=lambda: manager.command("robot_button", "sequence", {"name": "搬运"})
    )
    ordinary.start()
    assert worker.command_started.wait(timeout=1)

    control = threading.Thread(
        target=lambda: manager.command("robot_button", "stop_motion", {})
    )
    control.start()

    try:
        assert worker.control_seen.wait(timeout=0.2)
    finally:
        worker.release_command.set()
        ordinary.join(timeout=1)
        control.join(timeout=1)


def test_stop_module_preempts_a_long_ordinary_command(tmp_path, verifier):
    manager, worker = _blocking_manager(tmp_path, verifier, "robot_button")
    ordinary = threading.Thread(
        target=lambda: manager.command("robot_button", "sequence", {"name": "搬运"})
    )
    ordinary.start()
    assert worker.command_started.wait(timeout=1)

    stopping = threading.Thread(target=lambda: manager.stop_module("robot_button"))
    stopping.start()

    try:
        assert worker.control_seen.wait(timeout=0.2)
    finally:
        worker.release_command.set()
        ordinary.join(timeout=1)
        stopping.join(timeout=1)


class ExitedWorker(FakeWorker):
    def __init__(self, module_id):
        super().__init__(module_id)
        self.alive = True

    def snapshot(self):
        return {"alive": self.alive, "type": "ready"}


def test_snapshot_reconciles_unexpected_worker_exit_before_next_start(
    tmp_path, verifier
):
    workers = []

    def factory(module):
        worker = ExitedWorker(module.module_id)
        workers.append(worker)
        return worker

    manager = ModuleManager(
        worker_factory=factory,
        verifier=verifier,
        lock_path=tmp_path / "exit.lock",
    )
    manager.start_module("color_recognition")
    workers[0].alive = False

    result = manager.snapshot()

    assert result.state == ModuleState.FAILED
    assert "意外退出" in result.message
    assert manager.active_module is None
    assert verifier.calls[-1][0] == "color_recognition"
    assert manager.start_module("shape_recognition").state == ModuleState.RUNNING


def test_unverified_cleanup_after_worker_exit_blocks_next_start(tmp_path, verifier):
    worker = ExitedWorker("color_recognition")
    manager = ModuleManager(
        worker_factory=lambda _module: worker,
        verifier=verifier,
        lock_path=tmp_path / "exit-busy.lock",
    )
    manager.start_module("color_recognition")
    worker.alive = False
    verifier.report = ReleaseReport(
        ok=False, busy_resources=("unverified:camera:/dev/video41",)
    )

    assert manager.snapshot().state == ModuleState.CLEANUP_FAILED
    with pytest.raises(ModuleConflictError):
        manager.start_module("shape_recognition")
