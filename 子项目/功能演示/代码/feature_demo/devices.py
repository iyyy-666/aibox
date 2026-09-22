from __future__ import annotations

import os
from collections.abc import Callable, Mapping


CAMERA_DEVICE_ENV = "AIBOX_CAMERA_DEVICE"
STABLE_CAMERA_DEVICE = (
    "/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0"
)
LEGACY_CAMERA_DEVICE = "/dev/video41"
METADATA_CAMERA_DEVICE = "/dev/video43"


def _validate_camera_device(device: str) -> str:
    if device == METADATA_CAMERA_DEVICE or os.path.realpath(device) == METADATA_CAMERA_DEVICE:
        raise ValueError(f"Camera device is metadata-only and cannot capture: {device}")
    return device


def resolve_camera_device(
    *,
    environ: Mapping[str, str] | None = None,
    exists: Callable[[str], bool] | None = None,
) -> str:
    environment = os.environ if environ is None else environ
    path_exists = os.path.exists if exists is None else exists
    override = environment.get(CAMERA_DEVICE_ENV)
    if override:
        return _validate_camera_device(override)
    if path_exists(STABLE_CAMERA_DEVICE):
        return _validate_camera_device(STABLE_CAMERA_DEVICE)
    if path_exists(LEGACY_CAMERA_DEVICE):
        return _validate_camera_device(LEGACY_CAMERA_DEVICE)
    return _validate_camera_device(STABLE_CAMERA_DEVICE)
