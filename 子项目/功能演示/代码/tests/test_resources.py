from __future__ import annotations

from pathlib import Path

import pytest

from feature_demo import devices, resources
from feature_demo.devices import resolve_camera_device
from feature_demo.registry import get_module
from feature_demo.resources import DEFAULT_DEVICE_PATHS, ResourceVerifier


STABLE_CAMERA_DEVICE = "/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0"


def test_default_device_paths_match_the_deployed_hardware_names():
    assert DEFAULT_DEVICE_PATHS == {
        "camera": (STABLE_CAMERA_DEVICE,),
        "microphone": ("/dev/snd/pcmC1D0c",),
        "speaker": ("/dev/snd/pcmC0D0p",),
        "robot": ("/dev/esp32_arm",),
        "gimbal": ("/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00",),
    }


def test_resource_verifier_uses_environment_camera_override(monkeypatch):
    checked = []
    monkeypatch.setenv("AIBOX_CAMERA_DEVICE", "/dev/custom-capture")
    monkeypatch.setattr(devices, "camera_supports_capture", lambda _path: True)
    verifier = ResourceVerifier(
        pid_exists=lambda _pid: False,
        device_in_use=lambda path: checked.append(path) or False,
    )

    report = verifier.verify(get_module("color_recognition"), ())

    assert report.ok
    assert checked[0] == "/dev/custom-capture"


def test_resource_verifier_prefers_stable_device_but_falls_back_to_present_legacy(
    monkeypatch,
):
    checked = []
    monkeypatch.delenv("AIBOX_CAMERA_DEVICE", raising=False)
    monkeypatch.setattr(
        resources.os.path,
        "exists",
        lambda path: path == "/dev/video41",
    )
    monkeypatch.setattr(devices, "camera_supports_capture", lambda _path: True)
    verifier = ResourceVerifier(
        pid_exists=lambda _pid: False,
        device_in_use=lambda path: checked.append(path) or False,
    )

    verifier.verify(get_module("color_recognition"), ())

    assert checked[0] == "/dev/video41"


def test_camera_override_accepts_capture_capable_video43():
    assert resolve_camera_device(
        environ={"AIBOX_CAMERA_DEVICE": "/dev/video43"},
        supports_capture=lambda _path: True,
    ) == "/dev/video43"


def test_camera_override_rejects_metadata_capability_at_any_number():
    selected = "/dev/video77"
    with pytest.raises(ValueError, match=selected):
        resolve_camera_device(
            environ={"AIBOX_CAMERA_DEVICE": selected},
            supports_capture=lambda _path: False,
        )


def test_camera_resolution_falls_back_from_metadata_stable_link_to_legacy_capture():
    assert resolve_camera_device(
        environ={},
        exists=lambda _path: True,
        supports_capture=lambda path: path == "/dev/video41",
    ) == "/dev/video41"


@pytest.mark.parametrize(
    ("udev_output", "v4l2_output", "expected"),
    [
        ("ID_V4L_CAPABILITIES=:capture:\n", "", True),
        ("ID_V4L_CAPABILITIES=:metadata:\n", "", False),
        ("", "Device Caps      : 0x1\n\tVideo Capture\n\tStreaming\n", True),
        (
            "",
            "Capabilities     : 0x1\n\tVideo Capture\nDevice Caps      : 0x2\n\tMetadata Capture\n",
            False,
        ),
    ],
)
def test_camera_capability_probe_uses_node_specific_udev_or_device_caps(
    udev_output, v4l2_output, expected
):
    def run(command, **_kwargs):
        output = udev_output if command[0] == "udevadm" else v4l2_output
        return type("Result", (), {"returncode": 0 if output else 1, "stdout": output})()

    assert devices.camera_supports_capture("/dev/video77", run=run) is expected


def test_palm_tracking_uses_the_same_gimbal_device_as_resource_verification():
    adapter_source = (Path(__file__).resolve().parents[1] / "feature_demo" / "adapters" / "vision.py").read_text(encoding="utf-8")

    assert "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00" in adapter_source


def test_resource_verifier_rejects_gimbal_aliasing_robot_device(tmp_path):
    robot = tmp_path / "robot"
    robot.write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="gimbal.*robot"):
        ResourceVerifier(
            device_paths={"robot": (str(robot),), "gimbal": (str(robot),)}
        )


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


@pytest.mark.parametrize(
    "failure",
    [FileNotFoundError("fuser"), resources.subprocess.TimeoutExpired("fuser", 2)],
)
def test_device_probe_failure_is_unknown_instead_of_free(monkeypatch, failure):
    monkeypatch.setattr(resources.os.path, "exists", lambda _path: True)

    def fail_probe(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(resources.subprocess, "run", fail_probe)

    assert resources._device_in_use("/dev/video41") is None


def test_resource_verifier_rejects_unverified_device_state():
    verifier = ResourceVerifier(
        pid_exists=lambda pid: False,
        device_in_use=lambda path: None,
        device_paths={"camera": ("/dev/video41",)},
    )

    report = verifier.verify(get_module("color_recognition"), ())

    assert report.ok is False
    assert report.busy_resources == ()
    assert report.unverified_resources == ("camera:/dev/video41",)
