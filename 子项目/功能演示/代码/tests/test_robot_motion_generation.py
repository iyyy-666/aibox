import importlib.util
import sys
import types
from pathlib import Path


ROBOT_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "RK3588_语音识别_机械臂"
    / "latest_from_3588"
    / "extracted"
    / "root"
    / "robot_arm"
    / "robot.py"
)


def load_robot_arm(monkeypatch):
    serial_driver = types.ModuleType("serial_driver")
    serial_driver.SerialDriver = object
    config = types.ModuleType("config")
    config.PRESET_POSES = {}
    config.ACTION_SEQUENCES = {
        "搬运": [
            {"pwms": [1500] * 6, "time": 1, "desc": "test motion"},
        ]
    }
    config.NUM_SERVOS = 6
    config.SERVO_NAMES = [str(index) for index in range(6)]
    config.PWM_MIN = 500
    config.PWM_MAX = 2500
    config.PWM_CENTER = 1500
    config.SORTING_READY_PWMS = [1500] * 6
    config.SORTING_GRIP_CLOSED = 2200
    config.SORTING_GRIP_RELEASE = 800
    config.SORTING_RIGHT_BASE = 1800
    config.SORTING_LEFT_BASE = 1200
    config.save_custom_pose = lambda *_args: None
    monkeypatch.setitem(sys.modules, "serial_driver", serial_driver)
    monkeypatch.setitem(sys.modules, "config", config)
    spec = importlib.util.spec_from_file_location("tested_robot_driver", ROBOT_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RobotArm


def test_sequence_with_pre_stop_generation_never_sends_motion(monkeypatch, tmp_path):
    commands = []

    class Serial:
        def send_command(self, command):
            commands.append(command)
            return True

    robot_class = load_robot_arm(monkeypatch)
    robot = robot_class(Serial())
    robot._last_pwms_file = tmp_path / "last_servo_pwms.json"
    admitted_generation = robot._current_motion_generation()
    assert robot.stop() is True
    commands.clear()

    result = robot.execute_sequence(
        "搬运",
        _motion_generation=admitted_generation,
    )

    assert result is False
    assert commands == []
