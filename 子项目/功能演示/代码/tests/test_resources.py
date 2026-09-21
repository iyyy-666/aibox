from __future__ import annotations

from feature_demo.registry import get_module
from feature_demo.resources import ResourceVerifier


def test_resource_verifier_reports_live_worker_pid():
    verifier = ResourceVerifier(
        pid_exists=lambda pid: pid == 101,
        device_in_use=lambda path: False,
    )

    report = verifier.verify(get_module("color_recognition"), (101, 102))

    assert not report.ok
    assert report.busy_resources == ("process:101",)


def test_resource_verifier_checks_only_declared_devices():
    checked = []

    def device_in_use(path):
        checked.append(path)
        return path == "/dev/video41"

    verifier = ResourceVerifier(
        pid_exists=lambda pid: False,
        device_in_use=device_in_use,
        device_paths={
            "camera": ("/dev/video41",),
            "robot": ("/dev/esp32_arm",),
            "gimbal": ("/dev/ttyACM1",),
        },
    )

    report = verifier.verify(get_module("color_recognition"), ())

    assert not report.ok
    assert report.busy_resources == ("camera:/dev/video41",)
    assert checked == ["/dev/video41", "/dev/ttyACM1"]


def test_resource_verifier_returns_clean_report():
    verifier = ResourceVerifier(
        pid_exists=lambda pid: False,
        device_in_use=lambda path: False,
    )

    report = verifier.verify(get_module("voice_input_test"), ())

    assert report.ok
    assert report.busy_resources == ()
