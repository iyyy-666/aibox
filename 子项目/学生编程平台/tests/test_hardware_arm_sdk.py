from __future__ import annotations

import aibox
from aibox import Arm, SafetyError, simulation_events


def test_arm_pose_routes_to_device_service_in_hardware_mode(monkeypatch):
    calls = []
    monkeypatch.setenv("AIBOX_DEVICE_MODE", "hardware")
    monkeypatch.setattr(
        aibox,
        "_device_request",
        lambda command, payload: calls.append((command, payload)) or {"ok": True},
    )
    simulation_events.clear()

    Arm().pose("直立")

    assert calls == [("pose", {"name": "直立"})]
    assert simulation_events[-1]["hardware"] is True


def test_arm_adjust_uses_relative_hardware_command(monkeypatch):
    calls = []
    monkeypatch.setenv("AIBOX_DEVICE_MODE", "hardware")
    monkeypatch.setattr(
        aibox,
        "_device_request",
        lambda command, payload: calls.append((command, payload)) or {"ok": True},
    )

    Arm().adjust(2, -30)

    assert calls == [("joint_step", {"servo_id": 1, "delta": -30, "time_ms": 200})]


def test_hardware_servo_keeps_student_pwm_safety_boundary(monkeypatch):
    monkeypatch.setenv("AIBOX_DEVICE_MODE", "hardware")
    monkeypatch.setattr(aibox, "_device_request", lambda *_args: {"ok": True})

    for pwm in (799, 2201):
        try:
            Arm().servo(1, pwm)
        except SafetyError:
            pass
        else:
            raise AssertionError(f"unsafe PWM accepted: {pwm}")
