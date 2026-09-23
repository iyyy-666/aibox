from __future__ import annotations

import sys
import types

import pytest

from feature_demo.adapters.gimbal import GimbalAdapter, UnsupportedCommand


class FakeGimbalService:
    def __init__(self):
        self.moves = []
        self.closed = False

    def move(self, axis, direction, *, step_pwm, time_ms):
        self.moves.append((axis, direction, step_pwm, time_ms))
        return True, f"{axis} moved"

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("up", ("pitch", -1, 30, 350)),
        ("down", ("pitch", 1, 30, 350)),
        ("left", ("yaw", -1, 30, 350)),
        ("right", ("yaw", 1, 30, 350)),
    ],
)
def test_gimbal_accepts_only_directional_steps(direction, expected):
    service = FakeGimbalService()
    gimbal = GimbalAdapter(service=service)

    result = gimbal.step(direction, 30)

    assert result["ok"] is True
    assert service.moves == [expected]


def test_gimbal_rejects_center():
    gimbal = GimbalAdapter(service=FakeGimbalService())

    with pytest.raises(UnsupportedCommand):
        gimbal.step("center", 30)


def test_gimbal_clamps_step_to_existing_safe_range():
    service = FakeGimbalService()
    gimbal = GimbalAdapter(service=service)

    gimbal.step("left", 900)

    assert service.moves == [("yaw", -1, 500, 350)]


def test_gimbal_close_releases_service():
    service = FakeGimbalService()
    gimbal = GimbalAdapter(service=service)

    gimbal.close()

    assert service.closed is True


def test_default_gimbal_service_shares_configured_position_state(monkeypatch):
    created = []

    class RecordingGimbalService(FakeGimbalService):
        def __init__(self, *, state_path):
            super().__init__()
            created.append(state_path)

    monkeypatch.setenv(
        "AIBOX_GIMBAL_POSITION_STATE", "/tmp/aibox_gimbal_position_1000.json"
    )
    monkeypatch.setitem(
        sys.modules,
        "gimbal_service",
        types.SimpleNamespace(GimbalService=RecordingGimbalService),
    )

    GimbalAdapter().step("left", 30)

    assert created == ["/tmp/aibox_gimbal_position_1000.json"]
