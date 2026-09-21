from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

from .api import create_app
from .manager import ManagedWorker, ModuleManager
from .models import ModuleDefinition
from .resources import ResourceVerifier
from .worker import WorkerProcess


def default_lock_path() -> Path:
    if os.name == "posix":
        return Path(f"/run/user/{os.getuid()}/aibox-feature-demo.lock")
    return Path(tempfile.gettempdir()) / "aibox-feature-demo.lock"


def _default_worker_factory(module: ModuleDefinition) -> ManagedWorker:
    return WorkerProcess(
        [sys.executable, "-m", "feature_demo.workers", module.worker],
        environment={"PYTHONUNBUFFERED": "1"},
    )


def build_application(
    *,
    worker_factory: Callable[[ModuleDefinition], ManagedWorker] | None = None,
    verifier: ResourceVerifier | None = None,
    lock_path: Path | None = None,
):
    manager = ModuleManager(
        worker_factory=worker_factory or _default_worker_factory,
        verifier=verifier or ResourceVerifier(),
        lock_path=lock_path or default_lock_path(),
    )
    return create_app(manager), manager


app, manager = build_application()
