from __future__ import annotations

import os
import sys
import tempfile
from functools import partial
from pathlib import Path
from typing import Callable

from .api import create_app
from .devices import CAMERA_DEVICE_ENV, resolve_camera_device
from .manager import ManagedWorker, ModuleManager
from .models import ModuleDefinition
from .resources import ResourceVerifier
from .worker import WorkerProcess


def default_lock_path() -> Path:
    if os.name == "posix":
        return Path(f"/run/user/{os.getuid()}/aibox-feature-demo.lock")
    return Path(tempfile.gettempdir()) / "aibox-feature-demo.lock"


def _default_worker_factory(
    module: ModuleDefinition,
    *,
    camera_device: str | None = None,
) -> ManagedWorker:
    selected_camera = camera_device or resolve_camera_device()
    return WorkerProcess(
        [sys.executable, "-m", "feature_demo.workers", module.worker],
        environment={
            "PYTHONUNBUFFERED": "1",
            CAMERA_DEVICE_ENV: selected_camera,
        },
    )


def build_application(
    *,
    worker_factory: Callable[[ModuleDefinition], ManagedWorker] | None = None,
    verifier: ResourceVerifier | None = None,
    lock_path: Path | None = None,
):
    camera_device = resolve_camera_device()
    manager = ModuleManager(
        worker_factory=worker_factory
        or partial(_default_worker_factory, camera_device=camera_device),
        verifier=verifier or ResourceVerifier(camera_device=camera_device),
        lock_path=lock_path or default_lock_path(),
    )
    return create_app(manager), manager


app, manager = build_application()
