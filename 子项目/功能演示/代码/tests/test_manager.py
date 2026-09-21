from __future__ import annotations

import pytest

from feature_demo.manager import ModuleConflictError, ModuleManager
from feature_demo.models import ModuleState
from feature_demo.resources import ReleaseReport
from tests.fakes.fake_worker import FakeWorker


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
