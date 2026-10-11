from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from .policy import CodePolicy, Diagnostic


@dataclass(frozen=True)
class RunRequest:
    code: str
    allowed_imports: tuple[str, ...]
    capabilities: tuple[str, ...]
    timeout_seconds: float
    output_limit_bytes: int


@dataclass(frozen=True)
class RunResult:
    status: str
    stdout: str = ""
    stderr: str = ""
    events: tuple[dict, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


class Runner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._cancel_requested = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def cancel(self) -> None:
        self._request_hardware_stop()
        with self._lock:
            self._cancel_requested = True
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    @staticmethod
    def _request_hardware_stop() -> None:
        if os.getenv("AIBOX_DEVICE_MODE", "simulation").lower() != "hardware":
            return
        import socket

        request = json.dumps({"command": "stop", "payload": {}}).encode("utf-8") + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.0)
                client.connect(os.getenv("AIBOX_ARM_SOCKET", "/run/aibox-device/arm.sock"))
                client.sendall(request)
                client.recv(4096)
        except OSError:
            pass

    def run(self, request: RunRequest) -> RunResult:
        validation = CodePolicy(
            allowed_imports=request.allowed_imports,
            capabilities=request.capabilities,
        ).validate(request.code)
        if not validation.allowed:
            return RunResult(status="rejected", diagnostics=validation.diagnostics)

        with tempfile.TemporaryDirectory(prefix="aibox-run-") as temporary:
            temporary_path = Path(temporary)
            code_path = temporary_path / "student_code.py"
            event_path = temporary_path / "events.jsonl"
            code_path.write_text(request.code, encoding="utf-8")
            source_root = Path(__file__).resolve().parents[1]
            bootstrap = (
                "import runpy,sys;"
                "sys.path.insert(0,sys.argv[1]);"
                "runpy.run_module('aibox_studio.runner_child',run_name='__main__')"
            )
            environment = os.environ.copy()
            environment["AIBOX_EVENT_FILE"] = str(event_path)
            environment["PYTHONIOENCODING"] = "utf-8"
            with self._lock:
                self._cancel_requested = False
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        bootstrap,
                        str(source_root),
                        str(code_path),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    cwd=temporary,
                )
                self._process = process
            try:
                stdout, stderr = process.communicate(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                status = "timeout"
            else:
                with self._lock:
                    cancelled = self._cancel_requested
                if cancelled:
                    status = "cancelled"
                else:
                    status = "completed" if process.returncode == 0 else "failed"
            finally:
                with self._lock:
                    self._process = None

            return RunResult(
                status=status,
                stdout=stdout[: request.output_limit_bytes],
                stderr=stderr[: request.output_limit_bytes],
                events=self._events(event_path),
            )

    @staticmethod
    def _events(path: Path) -> tuple[dict, ...]:
        if not path.exists():
            return ()
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return tuple(events)

