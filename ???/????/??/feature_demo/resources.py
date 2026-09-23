from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from .devices import STABLE_CAMERA_DEVICE, resolve_camera_device
from .models import ModuleDefinition


DEFAULT_DEVICE_PATHS: dict[str, tuple[str, ...]] = {
    "camera": (STABLE_CAMERA_DEVICE,),
    "microphone": ("/dev/snd/pcmC1D0c",),
    "speaker": ("/dev/snd/pcmC0D0p",),
    "robot": ("/dev/esp32_arm",),
    "gimbal": (
        "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00",
    ),
}


def ensure_distinct_actuator_devices(
    device_paths: Mapping[str, tuple[str, ...]],
) -> None:
    for robot_path in device_paths.get("robot", ()):
        for gimbal_path in device_paths.get("gimbal", ()):
            if os.path.realpath(robot_path) == os.path.realpath(gimbal_path):
                raise RuntimeError(
                    "gimbal and robot serial devices resolve to the same device"
                )


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    ok: bool
    busy_resources: tuple[str, ...] = ()
    unverified_resources: tuple[str, ...] = ()


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _device_in_use(path: str) -> bool | None:
    if not os.path.exists(path):
        return False
    try:
        result = subprocess.run(
            ["fuser", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


class ResourceVerifier:
    def __init__(
        self,
        *,
        pid_exists: Callable[[int], bool] = _pid_exists,
        device_in_use: Callable[[str], bool | None] = _device_in_use,
        device_paths: Mapping[str, tuple[str, ...]] | None = None,
        camera_device: str | None = None,
    ) -> None:
        self._pid_exists = pid_exists
        self._device_in_use = device_in_use
        if device_paths is None:
            self._device_paths = dict(DEFAULT_DEVICE_PATHS)
            self._device_paths["camera"] = (
                camera_device or resolve_camera_device(),
            )
        else:
            self._device_paths = dict(device_paths)
        ensure_distinct_actuator_devices(self._device_paths)

    def verify(
        self,
        module: ModuleDefinition,
        worker_pids: Iterable[int] | None,
    ) -> ReleaseReport:
        busy: list[str] = []
        unverified: list[str] = []
        if worker_pids is None:
            unverified.append("process-group")
        else:
            for pid in worker_pids:
                if self._pid_exists(pid):
                    busy.append(f"process:{pid}")
        for resource in module.resources:
            for path in self._device_paths.get(resource, ()):
                state = self._device_in_use(path)
                if state is True:
                    busy.append(f"{resource}:{path}")
                elif state is None:
                    unverified.append(f"{resource}:{path}")
        return ReleaseReport(
            ok=not busy and not unverified,
            busy_resources=tuple(busy),
            unverified_resources=tuple(unverified),
        )
