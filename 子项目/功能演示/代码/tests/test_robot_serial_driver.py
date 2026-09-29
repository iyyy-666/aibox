import importlib.util
import sys
import types
from pathlib import Path


SERIAL_DRIVER_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "RK3588_语音识别_机械臂"
    / "latest_from_3588"
    / "extracted"
    / "root"
    / "robot_arm"
    / "serial_driver.py"
)


def test_default_audit_log_is_isolated_by_user_id(monkeypatch):
    serial_module = types.ModuleType("serial")
    serial_module.Serial = object
    config_module = types.ModuleType("config")
    config_module.SERIAL_PORT = "/dev/esp32_arm"
    config_module.SERIAL_BAUD = 115200
    monkeypatch.setitem(sys.modules, "serial", serial_module)
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.delenv("AIBOX_ROBOT_SERIAL_AUDIT", raising=False)

    spec = importlib.util.spec_from_file_location(
        "tested_serial_driver", SERIAL_DRIVER_SOURCE
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.os, "getuid", lambda: 1000, raising=False)

    driver = module.SerialDriver()

    assert driver._audit_path == Path("/tmp/aibox_robot_serial_audit_1000.jsonl")
