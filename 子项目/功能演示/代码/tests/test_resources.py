from __future__ import annotations

from pathlib import Path

from feature_demo.registry import get_module
from feature_demo.resources import DEFAULT_DEVICE_PATHS, ResourceVerifier


def test_default_device_paths_match_the_deployed_hardware_names():
    assert DEFAULT_DEVICE_PATHS == {
        "camera": ("/dev/video41",),
        "microphone": ("/dev/snd/pcmC5D0c",),
        "speaker": ("/dev/snd/pcmC0D0p",),
        "robot": ("/dev/esp32_arm",),
        "gimbal": ("/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0",),
    }


def test_palm_tracking_uses_the_same_gimbal_device_as_resource_verification():
    adapter_source = (Path(__file__).resolve().parents[1] / "feature_demo" / "adapters" / "vision.py").read_text(encoding="utf-8")

    assert "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0" in adapter_source


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
