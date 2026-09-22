from __future__ import annotations

import json
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
    arm._servo_pwms = [1500] * 6
    arm._rot_offsets = [0] * 6
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


def test_stop_before_direct_set_servo_generation_capture_prevents_motion_write(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    arm._servo_pwms = [1500] * 6
    arm._rot_offsets = [0] * 6
    critical_check_ready = threading.Event()
    continue_action = threading.Event()
    critical_action = arm._critical_action

    def delayed_critical_check(_arm: RobotArm) -> bool:
        critical_check_ready.set()
        continue_action.wait(timeout=2)
        return critical_action

    monkeypatch.setattr(
        RobotArm, "_critical_action", property(delayed_critical_check), raising=False
    )
    result: list[bool] = []
    action = threading.Thread(target=lambda: result.append(arm.set_servo(0, 1100)))
    action.start()
    assert critical_check_ready.wait(timeout=1)

    assert arm.stop() is True
    continue_action.set()
    action.join(timeout=1)

    assert not action.is_alive()
    assert result == [False]
    assert serial.commands == ["$DST!"]
    assert arm._servo_pwms == [1500] * 6
    assert arm._rot_offsets == [0] * 6
    assert not arm._last_pwms_file.exists()


def test_stop_before_direct_servo_batch_generation_capture_prevents_motion_write(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    arm._servo_pwms = [1500] * 6
    arm._rot_offsets = [0] * 6
    critical_check_ready = threading.Event()
    continue_action = threading.Event()
    critical_action = arm._critical_action

    def delayed_critical_check(_arm: RobotArm) -> bool:
        critical_check_ready.set()
        continue_action.wait(timeout=2)
        return critical_action

    monkeypatch.setattr(
        RobotArm, "_critical_action", property(delayed_critical_check), raising=False
    )
    result: list[bool] = []
    action = threading.Thread(
        target=lambda: result.append(arm.set_all_servos([1100] * 6))
    )
    action.start()
    assert critical_check_ready.wait(timeout=1)

    assert arm.stop() is True
    continue_action.set()
    action.join(timeout=1)

    assert not action.is_alive()
    assert result == [False]
    assert serial.commands == ["$DST!"]
    assert arm._servo_pwms == [1500] * 6
    assert arm._rot_offsets == [0] * 6
    assert not arm._last_pwms_file.exists()


def test_new_direct_action_after_stop_uses_current_generation(tmp_path) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"

    assert arm.stop() is True
    assert arm.set_servo(0, 1100) is True

    assert serial.commands == ["$DST!", "#000P1100T0500!"]


def test_old_action_cannot_overwrite_new_action_state_after_stop(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    arm._servo_pwms = [1500] * 6
    arm._rot_offsets = [0] * 6
    old_send_done = threading.Event()
    continue_old_action = threading.Event()
    original_send = arm._send_motion_command

    def delayed_old_send(command: str, generation: int, *args, **kwargs):
        sent = original_send(command, generation, *args, **kwargs)
        if "P1100" in command:
            old_send_done.set()
            continue_old_action.wait(timeout=2)
        return sent

    monkeypatch.setattr(arm, "_send_motion_command", delayed_old_send)
    old_result: list[bool] = []
    old_action = threading.Thread(
        target=lambda: old_result.append(arm.set_servo(0, 1100))
    )
    old_action.start()
    assert old_send_done.wait(timeout=1)

    assert arm.stop() is True
    assert arm.set_servo(0, 1300) is True
    continue_old_action.set()
    old_action.join(timeout=1)

    assert not old_action.is_alive()
    assert old_result == [True]
    assert serial.commands == [
        "#000P1100T0500!",
        "$DST!",
        "#000P1300T0500!",
    ]
    assert arm._servo_pwms == [1300, 1500, 1500, 1500, 1500, 1500]
    assert arm._rot_offsets == [-200, 0, 0, 0, 0, 0]
    assert json.loads(arm._last_pwms_file.read_text(encoding="utf-8"))["pwms"] == [
        1300,
        1500,
        1500,
        1500,
        1500,
        1500,
    ]


def test_stop_does_not_wait_for_motion_state_persistence(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    persistence_started = threading.Event()
    continue_persistence = threading.Event()

    def delayed_remember() -> None:
        persistence_started.set()
        continue_persistence.wait(timeout=2)

    monkeypatch.setattr(arm, "_remember_pwms", delayed_remember)
    motion_result: list[bool] = []
    motion = threading.Thread(
        target=lambda: motion_result.append(arm.set_servo(0, 1100))
    )
    motion.start()
    assert persistence_started.wait(timeout=1)

    stop_result: list[bool] = []
    stop_finished = threading.Event()

    def stop_robot() -> None:
        stop_result.append(arm.stop())
        stop_finished.set()

    emergency_stop = threading.Thread(target=stop_robot)
    emergency_stop.start()
    stop_returned_without_disk = stop_finished.wait(timeout=0.2)
    continue_persistence.set()
    motion.join(timeout=1)
    emergency_stop.join(timeout=1)

    assert stop_returned_without_disk
    assert not motion.is_alive()
    assert not emergency_stop.is_alive()
    assert motion_result == [True]
    assert stop_result == [True]
    assert serial.commands == ["#000P1100T0500!", "$DST!"]


def test_sequence_stop_before_nested_servo_batch_uses_action_generation(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    nested_call_ready = threading.Event()
    continue_nested_call = threading.Event()
    original_set_all = arm.set_all_servos

    def delayed_set_all(*args, **kwargs):
        nested_call_ready.set()
        continue_nested_call.wait(timeout=2)
        return original_set_all(*args, **kwargs)

    monkeypatch.setattr(arm, "set_all_servos", delayed_set_all)
    monkeypatch.setitem(
        robot_module.ACTION_SEQUENCES,
        "test-sequence",
        [{"desc": "test step", "pwms": [1100] * 6, "time": 500}],
    )
    result: list[bool] = []
    action = threading.Thread(
        target=lambda: result.append(arm.execute_sequence("test-sequence"))
    )
    action.start()
    assert nested_call_ready.wait(timeout=1)

    assert arm.stop() is True
    continue_nested_call.set()
    action.join(timeout=1)

    assert not action.is_alive()
    assert result == [False]
    assert serial.commands == ["$DST!"]


def test_all_center_stop_before_nested_batch_preserves_previous_state(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    arm._servo_pwms = [1600] * 6
    arm._rot_offsets = [100] * 6
    nested_call_ready = threading.Event()
    continue_nested_call = threading.Event()
    original_set_all = arm.set_all_servos

    def delayed_set_all(*args, **kwargs):
        nested_call_ready.set()
        continue_nested_call.wait(timeout=2)
        return original_set_all(*args, **kwargs)

    monkeypatch.setattr(arm, "set_all_servos", delayed_set_all)
    result: list[bool] = []
    action = threading.Thread(target=lambda: result.append(arm.all_center()))
    action.start()
    assert nested_call_ready.wait(timeout=1)

    assert arm.stop() is True
    continue_nested_call.set()
    action.join(timeout=1)

    assert not action.is_alive()
    assert result == [False]
    assert serial.commands == ["$DST!"]
    assert arm._servo_pwms == [1600] * 6
    assert arm._rot_offsets == [100] * 6
    assert not arm._last_pwms_file.exists()


def test_joint_rotation_stop_before_write_preserves_previous_state(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    arm._servo_pwms = [1500] * 6
    arm._rot_offsets = [0] * 6
    arm._rotating[0] = True
    write_ready = threading.Event()
    continue_write = threading.Event()
    original_send = arm._send_motion_command

    def delayed_send(command: str, generation: int, *args, **kwargs):
        write_ready.set()
        continue_write.wait(timeout=2)
        return original_send(command, generation, *args, **kwargs)

    monkeypatch.setattr(arm, "_send_motion_command", delayed_send)
    action = threading.Thread(target=lambda: arm._joint_rotate_loop(0, 10))
    action.start()
    assert write_ready.wait(timeout=1)

    assert arm.stop() is True
    continue_write.set()
    action.join(timeout=1)

    assert not action.is_alive()
    assert serial.commands == ["$DST!"]
    assert arm._servo_pwms == [1500] * 6
    assert arm._rot_offsets == [0] * 6
    assert not arm.is_rotating


def test_sorting_stop_before_nested_group_write_uses_action_generation(
    monkeypatch, tmp_path
) -> None:
    serial = RecordingSerial()
    arm = RobotArm(serial)
    arm._last_pwms_file = tmp_path / "last_servo_pwms.json"
    arm._servo_pwms = [1500] * 6
    arm._rot_offsets = [0] * 6
    nested_call_ready = threading.Event()
    continue_nested_call = threading.Event()
    original_set_group = arm.set_all_servos_group

    def delayed_set_group(*args, **kwargs):
        nested_call_ready.set()
        continue_nested_call.wait(timeout=2)
        return original_set_group(*args, **kwargs)

    stages = [
        {"pwms": [1100 + index] * 6, "time": 500}
        for index in range(6)
    ]
    monkeypatch.setattr(arm, "set_all_servos_group", delayed_set_group)
    monkeypatch.setattr(arm, "get_sorting_stages", lambda _side: stages)
    result: list[bool] = []
    action = threading.Thread(
        target=lambda: result.append(arm.execute_sort_transfer("left"))
    )
    action.start()
    assert nested_call_ready.wait(timeout=1)

    assert arm.stop() is True
    continue_nested_call.set()
    action.join(timeout=1)

    assert not action.is_alive()
    assert result == [False]
    assert serial.commands == ["$DST!"]
    assert arm._servo_pwms == [1500] * 6
    assert arm._rot_offsets == [0] * 6
    assert not arm._last_pwms_file.exists()
