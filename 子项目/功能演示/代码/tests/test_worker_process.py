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


def test_worker_start_preserves_error_when_stopped_event_follows_immediately():
    script = (
        "print('{\"type\":\"error\",\"message\":\"camera missing\"}',flush=True);"
        "print('{\"type\":\"stopped\",\"message\":\"cleanup done\"}',flush=True);"
        "import time;time.sleep(0.2)"
    )
    worker = WorkerProcess([sys.executable, "-u", "-c", script], start_timeout=1.0)

    with pytest.raises(RuntimeError, match="camera missing"):
        worker.start()


def test_worker_command_waits_for_correlated_result():
    script = (
        "import json,sys;"
        "print('{\"type\":\"ready\"}',flush=True);"
        "request=json.loads(sys.stdin.readline());"
        "print(json.dumps({'type':'command_result','request_id':'unrelated',"
        "'ok':True,'effect':'wrong'}),flush=True);"
        "print(json.dumps({'type':'command_result','request_id':request['request_id'],"
        "'ok':True,'effect':'moved'}),flush=True);"
        "sys.stdin.readline()"
    )
    worker = WorkerProcess(
        [sys.executable, "-u", "-c", script],
        start_timeout=1.0,
        command_timeout=1.0,
    )
    worker.start()

    assert worker.command("gimbal_left", {"amount": 1}) == {
        "ok": True,
        "effect": "moved",
    }
    worker.stop(1.0)


def test_worker_command_rejects_correlated_failure_result():
    script = (
        "import json,sys;"
        "print('{\"type\":\"ready\"}',flush=True);"
        "request=json.loads(sys.stdin.readline());"
        "print(json.dumps({'type':'command_result','request_id':request['request_id'],"
        "'ok':False,'message':'gimbal nack'}),flush=True);"
        "sys.stdin.readline()"
    )
    worker = WorkerProcess(
        [sys.executable, "-u", "-c", script],
        start_timeout=1.0,
        command_timeout=1.0,
    )
    worker.start()

    with pytest.raises(RuntimeError, match="gimbal nack"):
        worker.command("gimbal_left", {"amount": 1})
    worker.stop(1.0)


def test_worker_command_rejects_correlated_error_event():
    script = (
        "import json,sys;"
        "print('{\"type\":\"ready\"}',flush=True);"
        "request=json.loads(sys.stdin.readline());"
        "print(json.dumps({'type':'error','request_id':request['request_id'],"
        "'message':'serial write failed'}),flush=True);"
        "sys.stdin.readline()"
    )
    worker = WorkerProcess(
        [sys.executable, "-u", "-c", script],
        start_timeout=1.0,
        command_timeout=1.0,
    )
    worker.start()

    with pytest.raises(RuntimeError, match="serial write failed"):
        worker.command("gimbal_left", {"amount": 1})
    worker.stop(1.0)


def test_worker_command_times_out_without_a_correlated_result():
    script = (
        "import sys,time;"
        "print('{\"type\":\"ready\"}',flush=True);"
        "sys.stdin.readline();"
        "time.sleep(1)"
    )
    worker = WorkerProcess(
        [sys.executable, "-u", "-c", script],
        start_timeout=1.0,
        command_timeout=0.05,
    )
    worker.start()

    with pytest.raises(TimeoutError, match="gimbal_left"):
        worker.command("gimbal_left", {"amount": 1})
    worker.stop(0.05)
