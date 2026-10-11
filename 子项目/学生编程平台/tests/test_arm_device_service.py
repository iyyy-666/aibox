from __future__ import annotations

import threading

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

    def send_command(self, command):
        self.calls.append(("write", command))
        return True


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


def test_repeated_upright_pose_keeps_position_without_resending_pwm():
    calls = []
    device = controller(calls)

    first = device.execute("pose", {"name": "直立"})
    second = device.execute("pose", {"name": "直立"})

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["held"] is True
    assert calls == ["connect", ("pose", "直立"), "disconnect"]


def test_arm_joint_motion_invalidates_the_held_upright_pose():
    calls = []
    device = controller(calls)

    assert device.execute("pose", {"name": "直立"})["ok"] is True
    assert device.execute("joint_step", {"servo_id": 1, "delta": 20})["ok"] is True
    assert device.execute("pose", {"name": "直立"})["ok"] is True

    assert calls.count(("pose", "直立")) == 2


def test_gripper_motion_preserves_the_held_upright_pose():
    calls = []
    device = controller(calls)

    assert device.execute("pose", {"name": "直立"})["ok"] is True
    assert device.execute("servo", {"servo_id": 5, "pwm": 1200})["ok"] is True
    repeated = device.execute("pose", {"name": "直立"})

    assert repeated["ok"] is True
    assert repeated["held"] is True
    assert calls.count(("pose", "直立")) == 1


def test_stop_invalidates_the_held_upright_pose():
    calls = []
    device = controller(calls)

    assert device.execute("pose", {"name": "直立"})["ok"] is True
    assert device.execute("pose", {"name": "直立"})["ok"] is True
    assert device.execute("stop", {})["ok"] is True
    assert device.execute("pose", {"name": "直立"})["ok"] is True

    assert calls.count(("pose", "直立")) == 2


def test_stop_during_pose_does_not_restore_stale_held_state():
    calls = []
    pose_started = threading.Event()
    finish_pose = threading.Event()

    class BlockingRobot(FakeRobot):
        def execute_pose(self, name):
            self.calls.append(("pose", name))
            if self.calls.count(("pose", name)) == 1:
                pose_started.set()
                assert finish_pose.wait(timeout=2)
            return True

    device = ArmController(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: BlockingRobot(serial, calls),
    )
    pose_thread = threading.Thread(target=device.execute, args=("pose", {"name": "直立"}))
    pose_thread.start()
    assert pose_started.wait(timeout=2)

    assert device.execute("stop", {})["ok"] is True
    finish_pose.set()
    pose_thread.join(timeout=2)
    assert not pose_thread.is_alive()
    assert device.execute("pose", {"name": "直立"})["ok"] is True

    assert calls.count(("pose", "直立")) == 2


def test_failed_pose_clears_previous_held_pose():
    calls = []

    class FailingPoseRobot(FakeRobot):
        def execute_pose(self, name):
            self.calls.append(("pose", name))
            return name == "直立"

    device = ArmController(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: FailingPoseRobot(serial, calls),
    )

    assert device.execute("pose", {"name": "直立"})["ok"] is True
    assert device.execute("pose", {"name": "放平"})["ok"] is False
    assert device.execute("pose", {"name": "直立"})["ok"] is True

    assert calls.count(("pose", "直立")) == 2


def test_stop_before_robot_registration_cancels_motion_write():
    calls = []
    robot_factory_started = threading.Event()
    finish_robot_factory = threading.Event()

    class WritingRobot(FakeRobot):
        def __init__(self, serial, calls):
            self.serial = serial
            self.calls = calls

        def execute_pose(self, name):
            return self.serial.send_command("#000P1500T1000!")

    def robot_factory(serial):
        robot_factory_started.set()
        assert finish_robot_factory.wait(timeout=2)
        return WritingRobot(serial, calls)

    device = ArmController(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=robot_factory,
    )
    pose_thread = threading.Thread(target=device.execute, args=("pose", {"name": "直立"}))
    pose_thread.start()
    assert robot_factory_started.wait(timeout=2)

    assert device.execute("stop", {})["ok"] is True
    finish_robot_factory.set()
    pose_thread.join(timeout=2)

    assert not pose_thread.is_alive()
    assert ("write", "#000P1500T1000!") not in calls


def test_stop_between_motion_writes_blocks_later_pwm():
    calls = []
    first_write_done = threading.Event()
    continue_motion = threading.Event()

    class MultiWriteRobot(FakeRobot):
        def __init__(self, serial, calls):
            self.serial = serial
            self.calls = calls

        def execute_pose(self, name):
            assert self.serial.send_command("#000P1500T1000!") is True
            first_write_done.set()
            assert continue_motion.wait(timeout=2)
            return self.serial.send_command("#001P1500T1000!")

        def stop(self):
            return self.serial.send_command("$DST!")

    device = ArmController(
        serial_factory=lambda: FakeSerial(calls),
        robot_factory=lambda serial: MultiWriteRobot(serial, calls),
    )
    pose_thread = threading.Thread(target=device.execute, args=("pose", {"name": "直立"}))
    pose_thread.start()
    assert first_write_done.wait(timeout=2)

    assert device.execute("stop", {})["ok"] is True
    continue_motion.set()
    pose_thread.join(timeout=2)

    assert not pose_thread.is_alive()
    assert ("write", "$DST!") in calls
    assert ("write", "#001P1500T1000!") not in calls
