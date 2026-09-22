from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence


@dataclass
class _PendingCommand:
    event: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None


class WorkerProcess:
    def __init__(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        log_path: Path | None = None,
        start_timeout: float = 15.0,
        command_timeout: float = 15.0,
    ) -> None:
        self._command = tuple(command)
        self._environment = dict(environment or {})
        self._log_path = log_path
        self._start_timeout = start_timeout
        self._command_timeout = command_timeout
        self._process: subprocess.Popen[str] | None = None
        self._process_group_id: int | None = None
        self._log_handle = None
        self._last_event: dict = {}
        self._reader: threading.Thread | None = None
        self._startup_event = threading.Event()
        self._startup_result: dict | None = None
        self._state_lock = threading.Lock()
        self._stdin_lock = threading.Lock()
        self._pending_commands: dict[str, _PendingCommand] = {}
        self._event_sequence = 0
        self._recent_events: deque[dict] = deque(maxlen=32)

    @property
    def pids(self) -> tuple[int, ...] | None:
        if self._process_group_id is None:
            return ()
        return self._process_group_members()

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        env = os.environ.copy()
        env.update(self._environment)
        self._last_event = {}
        self._startup_result = None
        self._startup_event.clear()
        self._event_sequence = 0
        self._recent_events.clear()
        stderr = subprocess.DEVNULL
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = self._log_path.open("a", encoding="utf-8")
            stderr = self._log_handle
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
            env=env,
        )
        self._process_group_id = self._process.pid
        self._reader = threading.Thread(target=self._read_events, daemon=True)
        self._reader.start()
        deadline = time.monotonic() + self._start_timeout
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            if self._startup_event.wait(timeout=min(0.05, remaining)):
                with self._state_lock:
                    startup_result = dict(self._startup_result or {})
                event_type = startup_result.get("type")
                if event_type == "ready":
                    return
                message = startup_result.get("message", "功能进程启动失败。")
                self._finish_failed_start()
                raise RuntimeError(str(message))
            if self._process is None or self._process.poll() is not None:
                self._finish_failed_start()
                raise RuntimeError("功能进程在就绪前已退出。")
        self._finish_failed_start()
        raise TimeoutError("功能进程启动超时。")

    def _read_events(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                event_type = event.get("type")
                request_id = event.get("request_id")
                with self._state_lock:
                    self._last_event = event
                    self._event_sequence += 1
                    compact_event = {
                        key: value
                        for key, value in event.items()
                        if key != "frame_jpeg_base64"
                    }
                    compact_event["_sequence"] = self._event_sequence
                    self._recent_events.append(compact_event)
                    if (
                        self._startup_result is None
                        and event_type in {"ready", "error"}
                    ):
                        self._startup_result = dict(event)
                        self._startup_event.set()
                    pending = (
                        self._pending_commands.get(str(request_id))
                        if request_id is not None
                        and event_type in {"command_result", "error"}
                        else None
                    )
                    if pending is not None:
                        pending.result = dict(event)
                        pending.event.set()

    def _finish_failed_start(self) -> None:
        members = self._process_group_members()
        if members is None or members:
            self._terminate_process_group()
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=1.0)
        members = self._process_group_members()
        if members == ():
            self._process = None
            self._process_group_id = None
            self._reader = None
        self._close_log()

    def command(self, name: str, payload: dict) -> dict:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("功能进程未运行")
        request_id = uuid.uuid4().hex
        pending = _PendingCommand()
        with self._state_lock:
            self._pending_commands[request_id] = pending
        try:
            request = {
                "request_id": request_id,
                "command": name,
                "payload": payload,
            }
            with self._stdin_lock:
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
            deadline = time.monotonic() + self._command_timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"命令 {name} 等待执行结果超时。")
                if pending.event.wait(timeout=min(0.05, remaining)):
                    break
                if process.poll() is not None:
                    raise RuntimeError(f"命令 {name} 执行期间功能进程已退出。")
            with self._state_lock:
                event = dict(pending.result or {})
            result = {
                key: value
                for key, value in event.items()
                if key not in {"type", "request_id"}
            }
            if event.get("type") == "error" or result.get("ok") is False:
                raise RuntimeError(str(result.get("message", f"命令 {name} 执行失败。")))
            return result
        finally:
            with self._state_lock:
                self._pending_commands.pop(request_id, None)

    def snapshot(self) -> dict:
        process = self._process
        with self._state_lock:
            last_event = dict(self._last_event)
            recent_events = [dict(event) for event in self._recent_events]
            event_sequence = self._event_sequence
        return {
            **last_event,
            "pid": process.pid if process is not None else None,
            "alive": bool(process is not None and process.poll() is None),
            "event_sequence": event_sequence,
            "recent_events": recent_events,
        }

    def stop(self, timeout: float) -> None:
        process = self._process
        if process is None:
            self._close_log()
            return
        if process.poll() is None:
            try:
                if process.stdin is None:
                    raise RuntimeError("功能进程标准输入不可用。")
                with self._stdin_lock:
                    process.stdin.write(
                        json.dumps({"command": "stop", "payload": {}}) + "\n"
                    )
                    process.stdin.flush()
                process.wait(timeout=timeout)
            except (RuntimeError, BrokenPipeError, subprocess.TimeoutExpired):
                self._terminate_process_group()
        members = self._process_group_members()
        if members is None or members:
            self._terminate_process_group()
        members = self._process_group_members()
        if self._reader is not None:
            self._reader.join(timeout=1.0)
        if members is None:
            raise RuntimeError("无法核验工作进程组是否已释放。")
        if members:
            raise RuntimeError(f"工作进程组仍有存活进程：{members}")
        self._process = None
        self._process_group_id = None
        self._reader = None
        self._close_log()

    def _process_group_members(self) -> tuple[int, ...] | None:
        group_id = self._process_group_id
        process = self._process
        if group_id is None:
            return ()
        if os.name == "nt":
            if process is not None and process.poll() is None:
                return (process.pid,)
            return ()
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,pgid="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        members = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2:
                continue
            try:
                pid, pgid = (int(value) for value in fields)
            except ValueError:
                continue
            if pgid == group_id:
                members.append(pid)
        return tuple(sorted(members))

    def _terminate_process_group(self) -> None:
        process = self._process
        group_id = self._process_group_id
        if group_id is None:
            return
        try:
            if os.name == "nt":
                if process is not None and process.poll() is None:
                    process.terminate()
            else:
                os.killpg(group_id, signal.SIGTERM)
            if process is not None and process.poll() is None:
                process.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        members = self._process_group_members()
        if members is None or members:
            try:
                if os.name == "nt" and process is not None and process.poll() is None:
                    process.kill()
                elif os.name != "nt":
                    os.killpg(group_id, getattr(signal, "SIGKILL", 9))
                if process is not None and process.poll() is None:
                    process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _close_log(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
