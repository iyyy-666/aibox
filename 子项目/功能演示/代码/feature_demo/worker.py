from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Mapping, Sequence


class WorkerProcess:
    def __init__(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._command = tuple(command)
        self._environment = dict(environment or {})
        self._log_path = log_path
        self._process: subprocess.Popen[str] | None = None
        self._log_handle = None
        self._last_event: dict = {}
        self._reader: threading.Thread | None = None

    @property
    def pids(self) -> tuple[int, ...]:
        process = self._process
        if process is None or process.poll() is not None:
            return ()
        return (process.pid,)

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        env = os.environ.copy()
        env.update(self._environment)
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
        self._reader = threading.Thread(target=self._read_events, daemon=True)
        self._reader.start()

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
                self._last_event = event

    def command(self, name: str, payload: dict) -> dict:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("功能进程未运行")
        process.stdin.write(
            json.dumps({"command": name, "payload": payload}, ensure_ascii=False)
            + "\n"
        )
        process.stdin.flush()
        return {"ok": True, "command": name}

    def snapshot(self) -> dict:
        process = self._process
        return {
            **self._last_event,
            "pid": process.pid if process is not None else None,
            "alive": bool(process is not None and process.poll() is None),
        }

    def stop(self, timeout: float) -> None:
        process = self._process
        if process is None:
            self._close_log()
            return
        if process.poll() is None:
            try:
                self.command("stop", {})
                process.wait(timeout=timeout)
            except (RuntimeError, BrokenPipeError, subprocess.TimeoutExpired):
                self._terminate_group(process)
        if self._reader is not None:
            self._reader.join(timeout=1.0)
        self._process = None
        self._close_log()

    @staticmethod
    def _terminate_group(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _close_log(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
