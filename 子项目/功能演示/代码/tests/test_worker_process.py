from __future__ import annotations

import sys
import time

import pytest

from feature_demo.worker import WorkerProcess


def test_worker_start_waits_for_ready_event():
    script = (
        "import sys,time;"
        "time.sleep(0.12);"
        "print('{\"type\":\"ready\"}',flush=True);"
        "sys.stdin.readline()"
    )
    worker = WorkerProcess([sys.executable, "-u", "-c", script], start_timeout=1.0)

    started_at = time.monotonic()
    worker.start()
    elapsed = time.monotonic() - started_at

    assert elapsed >= 0.1
    assert worker.snapshot()["type"] == "ready"
    worker.stop(1.0)


def test_worker_start_surfaces_error_event():
    script = "print('{\"type\":\"error\",\"message\":\"camera missing\"}',flush=True)"
    worker = WorkerProcess([sys.executable, "-u", "-c", script], start_timeout=1.0)

    with pytest.raises(RuntimeError, match="camera missing"):
        worker.start()
