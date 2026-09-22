from __future__ import annotations

import io
import threading

import pytest

from feature_demo import devices
from feature_demo.adapters.robot import RobotAdapter
from feature_demo.workers.robot import RobotWorker
from feature_demo.workers import runtime
from feature_demo.workers.runtime import create_vision_worker


class FakeCapture:
    def __init__(self):
        self.settings = []

    def set(self, key, value):
        self.settings.append((key, value))


class FakeCv2:
    CAP_V4L2 = 200
    CAP_PROP_FOURCC = 1
    CAP_PROP_FRAME_WIDTH = 2
    CAP_PROP_FRAME_HEIGHT = 3
    CAP_PROP_FPS = 4
    CAP_PROP_BUFFERSIZE = 5
    IMWRITE_JPEG_QUALITY = 6

    def __init__(self):
        self.created = []

    def VideoCapture(self, device, backend):
        capture = FakeCapture()
        self.created.append((device, backend, capture))
        return capture

    def VideoWriter_fourcc(self, *letters):
        return 77

    def imencode(self, extension, frame, options):
        return True, b"jpeg"


class FakeAdapter:
    def process(self, frame):
        return frame, {}

    def close(self):
        return None


def test_runtime_keeps_camera_lazy_and_uses_stable_capture_device(monkeypatch):
    monkeypatch.delenv("AIBOX_CAMERA_DEVICE", raising=False)
    monkeypatch.setattr(
        devices.os.path,
        "exists",
        lambda path: path
        in {
            "/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0",
            "/dev/video41",
        },
    )
    cv2 = FakeCv2()
    adapter_calls = []

    worker = create_vision_worker(
        "color_recognition",
        cv2_module=cv2,
        adapter_builder=lambda module_id: adapter_calls.append(module_id) or FakeAdapter(),
        event_sink=lambda event: None,
        gimbal=None,
    )

    assert cv2.created == []
    camera = worker._camera_factory()

    assert adapter_calls == ["color_recognition"]
    assert cv2.created[0][:2] == (
        "/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0",
        200,
    )
    assert camera.settings == [(1, 77), (2, 1280), (3, 480), (4, 30), (5, 1)]


def test_runtime_uses_environment_camera_override(monkeypatch):
    monkeypatch.setenv("AIBOX_CAMERA_DEVICE", "/dev/custom-capture")
    cv2 = FakeCv2()

    worker = create_vision_worker(
        "color_recognition",
        cv2_module=cv2,
        adapter_builder=lambda _module_id: FakeAdapter(),
        event_sink=lambda _event: None,
        gimbal=None,
    )
    worker._camera_factory()

    assert cv2.created[0][:2] == ("/dev/custom-capture", 200)


def test_camera_open_error_reports_selected_device(monkeypatch):
    selected = "/dev/custom-capture"
    monkeypatch.setenv("AIBOX_CAMERA_DEVICE", selected)
    cv2 = FakeCv2()
    worker = create_vision_worker(
        "color_recognition",
        cv2_module=cv2,
        adapter_builder=lambda _module_id: FakeAdapter(),
        event_sink=lambda _event: None,
        gimbal=None,
    )
    cv2.VideoCapture = lambda *_args: type(
        "ClosedCapture",
        (),
        {
            "set": lambda *_args: None,
            "isOpened": lambda _self: False,
            "release": lambda _self: None,
        },
    )()

    with pytest.raises(RuntimeError, match=selected):
        worker.start()


def test_worker_entry_emits_the_original_startup_failure(monkeypatch):
    events = []

    class FailingWorker:
        last_event = {}

        def start(self):
            raise RuntimeError("无法打开摄像头 /dev/video41。")

        def stop(self):
            self.last_event = {"type": "stopped"}
            runtime.emit_json({"type": "stopped", "message": "cleanup done"})

    monkeypatch.setattr(runtime, "create_worker", lambda *args, **kwargs: FailingWorker())
    monkeypatch.setattr(runtime, "emit_json", events.append)

    assert runtime.run_worker("color_recognition") == 1
    assert events[0] == {"type": "error", "message": "无法打开摄像头 /dev/video41。"}
    assert events[1]["type"] == "stopped"


def test_worker_entry_correlates_command_result_and_error(monkeypatch):
    events = []

    class CommandWorker:
        last_event = {"type": "ready"}

        def start(self):
            return None

        def command(self, name, payload):
            if name == "fail":
                raise RuntimeError("physical command failed")
            return {"ok": True, "name": name, "payload": payload}

        def stop(self):
            self.last_event = {"type": "stopped"}

    requests = (
        '{"request_id":"req-ok","command":"move","payload":{"amount":1}}\n'
        '{"request_id":"req-fail","command":"fail","payload":{}}\n'
    )
    monkeypatch.setattr(runtime, "create_worker", lambda *args, **kwargs: CommandWorker())
    monkeypatch.setattr(runtime, "emit_json", events.append)
    monkeypatch.setattr(runtime.sys, "stdin", io.StringIO(requests))

    assert runtime.run_worker("robot_button") == 0
    assert events[0]["request_id"] == "req-ok"
    assert events[0]["type"] == "command_result"
    assert events[1] == {
        "type": "error",
        "request_id": "req-fail",
        "message": "physical command failed",
    }


def test_object_sorting_does_not_emit_component_ready_before_camera_failure(
    monkeypatch,
):
    events = []

    class RobotComponent:
        def __init__(self, _adapter, *, event_sink):
            self._event_sink = event_sink

        def start(self):
            self._event_sink({"type": "ready", "message": "robot ready"})

        def stop(self):
            return None

        def stop_motion(self):
            return None

        def disconnect(self):
            return None

        def command(self, _name, _payload):
            return {"ok": True}

    class FailingVisionComponent:
        def start(self):
            raise RuntimeError("camera unavailable")

        def stop(self):
            return None

    monkeypatch.setattr(runtime, "RobotWorker", RobotComponent)
    monkeypatch.setattr(
        runtime,
        "create_vision_worker",
        lambda *_args, **_kwargs: FailingVisionComponent(),
    )
    worker = runtime.create_worker(
        "object_sorting",
        event_sink=events.append,
        robot_adapter=object(),
        adapter_builder=lambda _module_id: object(),
    )

    try:
        worker.start()
    except RuntimeError as exc:
        assert str(exc) == "camera unavailable"
    else:
        raise AssertionError("camera startup failure must propagate")
    assert [event for event in events if event.get("type") == "ready"] == []


def test_object_sorting_emits_one_ready_after_both_components_start(monkeypatch):
    events = []
    starts = []

    class RobotComponent:
        def __init__(self, _adapter, *, event_sink):
            self._event_sink = event_sink

        def start(self):
            starts.append("robot")
            self._event_sink({"type": "ready", "message": "robot ready"})

        def stop(self):
            return None

        def stop_motion(self):
            return None

        def disconnect(self):
            return None

        def command(self, _name, _payload):
            return {"ok": True}

    class VisionComponent:
        def __init__(self, event_sink):
            self._event_sink = event_sink

        def start(self):
            starts.append("vision")
            self._event_sink({"type": "ready", "message": "vision ready"})

        def stop(self):
            return None

    monkeypatch.setattr(runtime, "RobotWorker", RobotComponent)
    monkeypatch.setattr(
        runtime,
        "create_vision_worker",
        lambda *_args, **kwargs: VisionComponent(kwargs["event_sink"]),
    )
    worker = runtime.create_worker(
        "object_sorting",
        event_sink=events.append,
        robot_adapter=object(),
        adapter_builder=lambda _module_id: object(),
    )

    worker.start()

    assert starts == ["robot", "vision"]
    assert [event["message"] for event in events if event.get("type") == "ready"] == [
        "物体分拣已准备就绪。"
    ]


def test_worker_runtime_processes_control_while_ordinary_command_is_blocked(
    monkeypatch,
):
    events = []
    ordinary_started = threading.Event()
    release_ordinary = threading.Event()
    control_seen = threading.Event()

    class BlockingCommandWorker:
        last_event = {"type": "ready"}

        def start(self):
            return None

        def command(self, name, payload):
            if name == "sequence":
                ordinary_started.set()
                release_ordinary.wait(timeout=2)
            if name == "stop_motion":
                control_seen.set()
                release_ordinary.set()
            return {"ok": True, "name": name, "payload": payload}

        def stop(self):
            release_ordinary.set()
            self.last_event = {"type": "stopped"}

    requests = (
        '{"request_id":"ordinary","command":"sequence","payload":{}}\n'
        '{"request_id":"control","command":"stop_motion","payload":{}}\n'
    )
    monkeypatch.setattr(
        runtime, "create_worker", lambda *_args, **_kwargs: BlockingCommandWorker()
    )
    monkeypatch.setattr(runtime, "emit_json", events.append)
    monkeypatch.setattr(runtime.sys, "stdin", io.StringIO(requests))
    run = threading.Thread(target=lambda: runtime.run_worker("robot_button"))
    run.start()
    assert ordinary_started.wait(timeout=1)

    try:
        assert control_seen.wait(timeout=0.2)
    finally:
        release_ordinary.set()
        run.join(timeout=1)
    assert {event.get("request_id") for event in events} >= {
        "ordinary",
        "control",
    }


def test_runtime_stop_motion_preempts_real_robot_adapter_sequence(monkeypatch):
    events = []
    sequence_started = threading.Event()
    stop_called = threading.Event()
    release_sequence = threading.Event()

    class Serial:
        connected = False

        def connect(self):
            self.connected = True
            return True

        def disconnect(self):
            self.connected = False

    class Robot:
        def __init__(self, _serial):
            pass

        def execute_sequence(self, _name):
            sequence_started.set()
            release_sequence.wait(timeout=2)
            return not stop_called.is_set()

        def stop(self):
            stop_called.set()
            release_sequence.set()
            return True

    worker = RobotWorker(
        RobotAdapter(serial_factory=Serial, robot_factory=Robot),
        event_sink=lambda event: None,
    )
    requests = (
        '{"request_id":"sequence","command":"sequence","payload":{"name":"move"}}\n'
        '{"request_id":"stop","command":"stop_motion","payload":{}}\n'
    )
    monkeypatch.setattr(runtime, "create_worker", lambda *_args, **_kwargs: worker)
    monkeypatch.setattr(runtime, "emit_json", events.append)
    monkeypatch.setattr(runtime.sys, "stdin", io.StringIO(requests))

    run = threading.Thread(target=lambda: runtime.run_worker("robot_button"))
    run.start()
    try:
        assert sequence_started.wait(timeout=1)
        assert stop_called.wait(timeout=0.2)
    finally:
        release_sequence.set()
        run.join(timeout=1)

    assert not run.is_alive()
    results = {event.get("request_id"): event for event in events}
    assert results["stop"]["type"] == "command_result"
    assert results["stop"]["ok"] is True
    assert results["sequence"]["ok"] is False
