from __future__ import annotations

import sys
import time

import pytest

import feature_demo.worker as worker_module
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


def test_worker_snapshot_retains_correlatable_events_without_frame_bytes():
    script = (
        "import json,sys,time;"
        "print('{\"type\":\"ready\"}',flush=True);"
        "print(json.dumps({'type':'sorting_result','ok':True,'side':'left'}),flush=True);"
        "print(json.dumps({'type':'frame','frame_jpeg_base64':'large-bytes',"
        "'result':[{'label':'red'}]}),flush=True);"
        "time.sleep(0.5)"
    )
    worker = WorkerProcess([sys.executable, "-u", "-c", script], start_timeout=1.0)
    worker.start()
    deadline = time.monotonic() + 0.5
    snapshot = worker.snapshot()
    while snapshot.get("event_sequence", 0) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
        snapshot = worker.snapshot()

    assert snapshot["event_sequence"] == 3
    assert snapshot["recent_events"][-2]["type"] == "sorting_result"
    assert snapshot["recent_events"][-1]["result"] == [{"label": "red"}]
    assert "frame_jpeg_base64" not in snapshot["recent_events"][-1]
    worker.stop(0.1)


def test_worker_snapshot_keeps_latest_frame_when_status_changes():
    script = (
        "import json,sys,time;"
        "print('{\"type\":\"ready\"}',flush=True);"
        "print(json.dumps({'type':'frame','frame_sequence':7,"
        "'frame_jpeg_base64':'amBlZw=='}),flush=True);"
        "print(json.dumps({'type':'camera_reconnecting','message':'retry'}),flush=True);"
        "time.sleep(0.5)"
    )
    worker = WorkerProcess([sys.executable, "-u", "-c", script], start_timeout=1.0)
    worker.start()
    deadline = time.monotonic() + 0.5
    snapshot = worker.snapshot()
    while snapshot.get("event_sequence", 0) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
        snapshot = worker.snapshot()

    assert snapshot["type"] == "camera_reconnecting"
    assert snapshot["frame_sequence"] == 7
    assert snapshot["frame_jpeg_base64"] == "amBlZw=="
    worker.stop(0.1)


def test_worker_stop_cleans_process_group_after_leader_exits(monkeypatch):
    worker = WorkerProcess([sys.executable, "-c", "pass"])

    class ExitedLeader:
        pid = 41001

        def poll(self):
            return 0

    worker._process = ExitedLeader()
    worker._process_group_id = 41001
    terminated = []
    monkeypatch.setattr(
        worker,
        "_process_group_members",
        lambda: () if terminated else (41002,),
    )
    monkeypatch.setattr(
        worker,
        "_terminate_process_group",
        lambda: terminated.append(worker._process_group_id),
    )

    assert worker.pids == (41002,)
    worker.stop(0.1)

    assert terminated == [41001]
    assert worker.pids == ()


def test_worker_stop_retains_process_group_when_enumeration_fails_after_leader_exit(
    monkeypatch,
):
    worker = WorkerProcess([sys.executable, "-c", "pass"])

    class ExitedLeader:
        pid = 42001

        def poll(self):
            return 0

    worker._process = ExitedLeader()
    worker._process_group_id = 42001
    kill_calls = []
    monkeypatch.setattr(worker_module.os, "name", "posix")
    monkeypatch.setattr(
        worker_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("ps")),
    )
    monkeypatch.setattr(
        worker_module.os,
        "killpg",
        lambda pgid, sig: kill_calls.append((pgid, sig)),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="进程组"):
        worker.stop(0.1)

    assert kill_calls == [
        (42001, worker_module.signal.SIGTERM),
        (42001, getattr(worker_module.signal, "SIGKILL", 9)),
    ]
    assert worker._process_group_id == 42001
    assert worker._process is not None
    assert worker.pids is None
