from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping


CAMERA_DEVICE_ENV = "AIBOX_CAMERA_DEVICE"
STABLE_CAMERA_DEVICE = (
    "/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0"
)
LEGACY_CAMERA_DEVICE = "/dev/video41"


def _udev_capture_capability(output: str) -> bool | None:
    for line in output.splitlines():
        if line.startswith("ID_V4L_CAPABILITIES="):
            capabilities = line.partition("=")[2].strip(":").split(":")
            return "capture" in capabilities
    return None


def _v4l2_capture_capability(output: str) -> bool:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("Device Caps"):
            continue
        device_caps: list[str] = []
        for capability in lines[index + 1 :]:
            if capability and not capability[0].isspace():
                break
            device_caps.append(capability.strip())
        return any(
            capability in {"Video Capture", "Video Capture Multiplanar"}
            for capability in device_caps
        )
    return False


def camera_supports_capture(
    device: str,
    *,
    run: Callable[..., object] = subprocess.run,
) -> bool:
    try:
        result = run(
            ["udevadm", "info", "--query=property", "--name", device],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and getattr(result, "returncode", 1) == 0:
        capability = _udev_capture_capability(str(getattr(result, "stdout", "")))
        if capability is not None:
            return capability
    try:
        result = run(
            ["v4l2-ctl", "--all", "--device", device],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if getattr(result, "returncode", 1) != 0:
        return False
    return _v4l2_capture_capability(str(getattr(result, "stdout", "")))


def resolve_camera_device(
    *,
    environ: Mapping[str, str] | None = None,
    exists: Callable[[str], bool] | None = None,
    supports_capture: Callable[[str], bool] | None = None,
) -> str:
    environment = os.environ if environ is None else environ
    path_exists = os.path.exists if exists is None else exists
    capture_capable = (
        camera_supports_capture if supports_capture is None else supports_capture
    )
    override = environment.get(CAMERA_DEVICE_ENV)
    if override:
        if capture_capable(override):
            return override
        raise ValueError(
            f"Camera device does not provide Video Capture capability: {override}"
        )
    rejected: list[str] = []
    for candidate in (STABLE_CAMERA_DEVICE, LEGACY_CAMERA_DEVICE):
        if not path_exists(candidate):
            continue
        if capture_capable(candidate):
            return candidate
        rejected.append(candidate)
    if rejected:
        raise ValueError(
            "Camera devices do not provide Video Capture capability: "
            + ", ".join(rejected)
        )
    return STABLE_CAMERA_DEVICE
