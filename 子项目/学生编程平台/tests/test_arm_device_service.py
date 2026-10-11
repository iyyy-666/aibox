from __future__ import annotations

from aibox_device.arm_service import ArmController


class FakeSerial:
    def __init__(self, calls):
        self.calls = calls
        self.connected = False

    def connect(self):
        self.calls.append("connect")
        self.connected = True
        return True

    def disconnect(self):
        self.calls.append("disconnect")
        self.connected = False


class FakeRobot:
    def __init__(self, serial, calls):
        self.calls = calls

    def execute_pose(self, name):
        self.calls.append(("pose", name))
        return True

    def move_servo_step(self, servo_id, delta, time_ms):
        self.calls.append(("joint_step", servo_id, delta, time_ms))
        return True

    def set_servo(self, servo_id, pwm, time_ms):
        self.calls.append(("servo", servo_id, pwm, time_ms))
        return True

    def stop(self):
        self.calls.append("stop")
        return True


def controller(calls):
    return ArmController(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: FakeRobot(serial, calls),
    )


def test_controller_is_lazy_and_releases_serial_after_command():
    calls = []
    device = controller(calls)
    assert calls == []

    result = device.execute("pose", {"name": "直立"})

    assert result["ok"] is True
    assert calls == ["connect", ("pose", "直立"), "disconnect"]


def test_controller_rejects_unsafe_absolute_pwm_before_connecting():
    calls = []
    device = controller(calls)

    result = device.execute("servo", {"servo_id": 0, "pwm": 799})

    assert result["ok"] is False
    assert result["code"] == "SAFETY_LIMIT"
    assert calls == []
