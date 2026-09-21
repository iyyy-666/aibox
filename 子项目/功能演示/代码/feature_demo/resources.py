from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from .models import ModuleDefinition


DEFAULT_DEVICE_PATHS: dict[str, tuple[str, ...]] = {
    "camera": ("/dev/video41",),
    "microphone": ("/dev/snd/pcmC5D0c",),
    "speaker": ("/dev/snd/pcmC0D0p",),
    "robot": ("/dev/esp32_arm",),
    "gimbal": (
        "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00",
    ),
}


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    ok: bool
    busy_resources: tuple[str, ...] = ()


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _device_in_use(path: str) -> bool:
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
        return False
    return result.returncode == 0


class ResourceVerifier:
    def __init__(
        self,
        *,
        pid_exists: Callable[[int], bool] = _pid_exists,
        device_in_use: Callable[[str], bool] = _device_in_use,
        device_paths: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._pid_exists = pid_exists
        self._device_in_use = device_in_use
        self._device_paths = dict(device_paths or DEFAULT_DEVICE_PATHS)

    def verify(
        self,
        module: ModuleDefinition,
        worker_pids: Iterable[int],
    ) -> ReleaseReport:
        busy: list[str] = []
        for pid in worker_pids:
            if self._pid_exists(pid):
                busy.append(f"process:{pid}")
        for resource in module.resources:
            for path in self._device_paths.get(resource, ()):
                if self._device_in_use(path):
                    busy.append(f"{resource}:{path}")
        return ReleaseReport(ok=not busy, busy_resources=tuple(busy))
