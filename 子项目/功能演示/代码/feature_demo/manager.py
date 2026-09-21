from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .models import ModuleDefinition, ModuleState
from .registry import get_module
from .resources import ReleaseReport, ResourceVerifier


class ModuleConflictError(RuntimeError):
    pass


class ManagedWorker(Protocol):
    @property
    def pids(self) -> tuple[int, ...]: ...

    def start(self) -> None: ...

    def command(self, name: str, payload: dict) -> dict: ...

    def stop(self, timeout: float) -> None: ...

    def snapshot(self) -> dict: ...


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    module_id: str | None
    state: ModuleState
    message: str
    busy_resources: tuple[str, ...] = ()
    details: dict | None = None


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False

    def acquire(self) -> bool:
        if self._held:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if not self._remove_stale_lock():
                    return False
                continue
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(str(os.getpid()))
            self._held = True
            return True
        return False

    def _remove_stale_lock(self) -> bool:
        try:
            pid = int(self.path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            pid = -1
        if pid > 0:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                pass
            else:
                return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return True

    def release(self) -> None:
        if not self._held:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._held = False


class ModuleManager:
    def __init__(
        self,
        *,
        worker_factory: Callable[[ModuleDefinition], ManagedWorker],
        verifier: ResourceVerifier,
        lock_path: Path,
        stop_timeout: float = 5.0,
    ) -> None:
        self._worker_factory = worker_factory
        self._verifier = verifier
        self._process_lock = ProcessLock(lock_path)
        self._stop_timeout = stop_timeout
        self._guard = threading.RLock()
        self._active_module: str | None = None
        self._state = ModuleState.IDLE
        self._worker: ManagedWorker | None = None
        self._last_error = ""

    @property
    def active_module(self) -> str | None:
        with self._guard:
            return self._active_module

    def start_module(self, module_id: str) -> LifecycleResult:
        module = get_module(module_id)
        with self._guard:
            if self._active_module == module_id and self._state == ModuleState.RUNNING:
                return self.snapshot()
            if self._active_module is not None:
                raise ModuleConflictError("已有功能正在运行，请先退出当前功能。")
            if not self._process_lock.acquire():
                raise ModuleConflictError("另一个功能演示进程正在运行。")
            self._active_module = module_id
            self._state = ModuleState.STARTING
            self._last_error = ""
            worker = self._worker_factory(module)
            self._worker = worker
            try:
                worker.start()
            except Exception as exc:
                self._last_error = str(exc)
                self._state = ModuleState.FAILED
                self._cleanup_failed_start(module, worker)
                return self.snapshot()
            self._state = ModuleState.RUNNING
            return self.snapshot()

    def _cleanup_failed_start(
        self, module: ModuleDefinition, worker: ManagedWorker
    ) -> None:
        try:
            worker.stop(self._stop_timeout)
        except Exception:
            pass
        report = self._verifier.verify(module, worker.pids)
        if report.ok:
            self._active_module = None
            self._worker = None
            self._process_lock.release()
        else:
            self._state = ModuleState.CLEANUP_FAILED

    def command(self, module_id: str, name: str, payload: dict | None = None) -> dict:
        module = get_module(module_id)
        if name not in module.commands:
            raise ValueError(f"不支持的命令：{name}")
        with self._guard:
            if self._active_module != module_id or self._worker is None:
                raise ModuleConflictError("该功能当前未运行。")
            return self._worker.command(name, payload or {})

    def stop_module(self, module_id: str) -> LifecycleResult:
        with self._guard:
            if self._active_module is None:
                return LifecycleResult(None, ModuleState.IDLE, "当前没有运行中的功能。")
            if self._active_module != module_id:
                raise ModuleConflictError("请求停止的功能不是当前活动功能。")
            module = get_module(module_id)
            worker = self._worker
            self._state = ModuleState.STOPPING
            if worker is not None:
                try:
                    worker.stop(self._stop_timeout)
                except Exception as exc:
                    self._last_error = str(exc)
            worker_pids = worker.pids if worker is not None else ()
            report = self._verifier.verify(module, worker_pids)
            if not report.ok:
                self._state = ModuleState.CLEANUP_FAILED
                return LifecycleResult(
                    module_id,
                    self._state,
                    "资源未能完全释放。",
                    busy_resources=report.busy_resources,
                    details=worker.snapshot() if worker is not None else {},
                )
            self._active_module = None
            self._worker = None
            self._state = ModuleState.IDLE
            self._process_lock.release()
            return LifecycleResult(module_id, ModuleState.IDLE, "功能已停止。")

    def snapshot(self) -> LifecycleResult:
        with self._guard:
            details = self._worker.snapshot() if self._worker is not None else {}
            message = {
                ModuleState.IDLE: "当前没有运行中的功能。",
                ModuleState.STARTING: "正在启动功能…",
                ModuleState.RUNNING: "功能已准备就绪。",
                ModuleState.STOPPING: "正在停止功能并释放资源…",
                ModuleState.FAILED: f"功能启动失败：{self._last_error}",
                ModuleState.CLEANUP_FAILED: "资源未能完全释放。",
            }[self._state]
            return LifecycleResult(
                self._active_module,
                self._state,
                message,
                details=details,
            )

    def shutdown(self) -> LifecycleResult:
        active = self.active_module
        if active is None:
            self._process_lock.release()
            return LifecycleResult(None, ModuleState.IDLE, "功能演示已停止。")
        return self.stop_module(active)
