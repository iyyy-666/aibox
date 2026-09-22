from __future__ import annotations

from pathlib import Path
import sys
import threading


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import robot as robot_module
from robot import RobotArm


class RecordingSerial:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def send_command(self, command: str) -> bool:
        self.commands.append(command)
        return True


def test_stop_during_set_all_servos_prevents_motion_writes_after_emergency_stop(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    between_servo_writes = threading.Event()
    continue_action = threading.Event()

    def pause_after_first_write(_seconds: float) -> None:
        if not between_servo_writes.is_set():
            between_servo_writes.set()
            continue_action.wait(timeout=2)

    monkeypatch.setattr(robot_module.time, "sleep", pause_after_first_write)
    result: list[bool] = []
    action = threading.Thread(
        target=lambda: result.append(
            arm.set_all_servos([1100, 1200, 1300, 1400, 1500, 1600], 500)
        )
    )
    action.start()
    assert between_servo_writes.wait(timeout=1)

    assert arm.stop() is True
    continue_action.set()
    action.join(timeout=1)

    assert not action.is_alive()
    assert result == [False]
    emergency_index = serial.commands.index("$DST!")
    assert serial.commands[:emergency_index] == ["#000P1100T0500!"]
    assert serial.commands[emergency_index + 1 :] == []
