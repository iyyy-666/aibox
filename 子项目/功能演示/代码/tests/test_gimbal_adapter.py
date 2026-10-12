from __future__ import annotations

import sys
import types

import pytest

from feature_demo.adapters.gimbal import GimbalAdapter, UnsupportedCommand


class FakeGimbalService:
    def __init__(self):
        self.moves = []
        self.closed = False
        self.yaw = 1500
        self.pitch = 1500

    @property
    def position(self):
        return self.yaw, self.pitch

    def move(self, axis, direction, *, step_pwm, time_ms):
        self.moves.append((axis, direction, step_pwm, time_ms))
        if axis == "yaw":
            self.yaw += direction * step_pwm
        else:
            self.pitch += direction * step_pwm
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


@pytest.mark.parametrize(
    ("direction", "pitch", "message"),
    [
        ("up", 500, "云台已到上限。"),
        ("down", 2500, "云台已到下限。"),
    ],
)
def test_gimbal_reports_pitch_limit_without_repeating_serial_command(
    direction, pitch, message
):
    service = FakeGimbalService()
    service.pitch = pitch
    gimbal = GimbalAdapter(service=service)

    result = gimbal.step(direction, 30)

    assert result == {
        "ok": False,
        "direction": direction,
        "amount": 30,
        "message": message,
    }
    assert service.moves == []


def test_gimbal_moves_to_an_absolute_saved_demo_position():
    service = FakeGimbalService()
    gimbal = GimbalAdapter(service=service)

    result = gimbal.move_to(1200, 1110)

    assert result["ok"] is True
    assert service.position == (1200, 1110)
    assert service.moves == [
        ("yaw", -1, 150, 650),
        ("yaw", -1, 150, 650),
        ("pitch", -1, 150, 650),
        ("pitch", -1, 150, 650),
        ("pitch", -1, 90, 650),
    ]


def test_gimbal_keeps_still_when_already_at_demo_position():
    service = FakeGimbalService()
    service.yaw, service.pitch = 1200, 1110
    gimbal = GimbalAdapter(service=service)

    result = gimbal.move_to(1200, 1110)

    assert result["ok"] is True
    assert service.moves == []


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
