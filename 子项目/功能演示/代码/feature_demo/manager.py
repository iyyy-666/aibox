from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .models import PREEMPTIVE_COMMANDS, ModuleDefinition, ModuleState
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
        self._fd: int | None = None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            self._fd = None


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
        self._command_guard = threading.Lock()
        self._active_module: str | None = None
        self._state = ModuleState.IDLE
        self._worker: ManagedWorker | None = None
        self._last_error = ""

    @property
    def active_module(self) -> str | None:
        with self._guard:
            self._reconcile_worker_exit_locked()
            return self._active_module

    def start_module(self, module_id: str) -> LifecycleResult:
        module = get_module(module_id)
        with self._guard:
            self._reconcile_worker_exit_locked()
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
        if name in PREEMPTIVE_COMMANDS:
            return self._dispatch_command(module_id, name, payload or {})
        with self._command_guard:
            return self._dispatch_command(module_id, name, payload or {})

    def _dispatch_command(self, module_id: str, name: str, payload: dict) -> dict:
        with self._guard:
            self._reconcile_worker_exit_locked()
            if self._active_module != module_id or self._worker is None:
                raise ModuleConflictError("该功能当前未运行。")
            worker = self._worker
        return worker.command(name, payload)

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
            self._reconcile_worker_exit_locked()
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

    def _reconcile_worker_exit_locked(self) -> None:
        if (
            self._state != ModuleState.RUNNING
            or self._active_module is None
            or self._worker is None
        ):
            return
        details = self._worker.snapshot()
        if details.get("alive", True):
            return
        module = get_module(self._active_module)
        worker = self._worker
        self._last_error = str(
            details.get("message") or "功能进程意外退出，正在核验设备资源。"
        )
        try:
            worker.stop(self._stop_timeout)
        except Exception as exc:
            self._last_error = f"{self._last_error} 清理失败：{exc}"
        report = self._verifier.verify(module, worker.pids)
        if not report.ok:
            self._state = ModuleState.CLEANUP_FAILED
            return
        self._active_module = None
        self._worker = None
        self._state = ModuleState.FAILED
        self._process_lock.release()

    def shutdown(self) -> LifecycleResult:
        active = self.active_module
        if active is None:
            self._process_lock.release()
            return LifecycleResult(None, ModuleState.IDLE, "功能演示已停止。")
        return self.stop_module(active)
