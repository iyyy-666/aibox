from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "部署" / "arm_prepower_upright.py"
SERVICE = ROOT / "部署" / "aibox-arm-prepower-upright.service"
UDEV_RULE = ROOT / "部署" / "99-aibox-arm-prepower.rules"


def load_module():
    spec = importlib.util.spec_from_file_location("arm_prepower_upright", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_prepower_command_sets_all_six_servos_to_calibrated_upright():
    module = load_module()

    command = module.build_group_command(module.UPRIGHT_PWMS, 1500)

    assert command == (
        "{G0000#000P1432T1500!#001P1500T1500!#002P1500T1500!"
        "#003P1500T1500!#004P1500T1500!#005P1241T1500!}\r\n"
    )


def test_prepower_rejects_unsafe_pwm_values():
    module = load_module()

    try:
        module.build_group_command([1432, 1500, 1500, 1500, 1500, 799], 1500)
    except ValueError as error:
        assert "800" in str(error)
    else:
        raise AssertionError("unsafe PWM was accepted")


def test_prepower_service_is_one_shot_and_does_not_restart():
    service = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert "RemainAfterExit=no" in service
    assert "Restart=" not in service
    assert "arm_prepower_upright.py" in service


def test_reconnect_rule_targets_only_the_calibrated_robot_usb_path():
    rule = UDEV_RULE.read_text(encoding="utf-8")

    assert 'ENV{ID_PATH}=="platform-xhci-hcd.3.auto-usb-0:1.3:1.0"' in rule
    assert 'ENV{SYSTEMD_WANTS}+="aibox-arm-prepower-upright.service"' in rule
    assert 'ATTRS{idVendor}=="1a86"' not in rule
