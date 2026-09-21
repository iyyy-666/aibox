from __future__ import annotations

import time

from feature_demo.workers.vision import VisionWorker


class FakeCamera:
    def __init__(self, calls):
        self.calls = calls
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        time.sleep(0.005)
        return True, "frame"

    def release(self):
        self.released = True
        self.calls.append("camera.release")


class FakeVisionAdapter:
    def __init__(self, calls):
        self.calls = calls
        self.closed = False

    def process(self, frame):
        return frame, {"result": "已识别"}

    def close(self):
        self.closed = True
        self.calls.append("adapter.close")


class FakeGimbal:
    def __init__(self, calls):
        self.calls = calls
        self.closed = False

    def step(self, direction, amount):
        return {"ok": True, "direction": direction, "amount": amount}

    def close(self):
        self.closed = True
        self.calls.append("gimbal.close")


def test_vision_worker_opens_camera_only_when_started():
    created = []
    worker = VisionWorker(
        adapter=FakeVisionAdapter([]),
        camera_factory=lambda: created.append(FakeCamera([])) or created[-1],
        encode_frame=lambda frame: b"jpeg",
        event_sink=lambda event: None,
    )

    assert created == []
    worker.start()
    worker.stop()

    assert len(created) == 1


def test_vision_worker_releases_resources_before_reporting_stopped():
    calls = []
    events = []
    camera = FakeCamera(calls)
    adapter = FakeVisionAdapter(calls)
    gimbal = FakeGimbal(calls)
    worker = VisionWorker(
        adapter=adapter,
        camera_factory=lambda: camera,
        encode_frame=lambda frame: b"jpeg",
        event_sink=lambda event: events.append(event) or calls.append(event["type"]),
        gimbal=gimbal,
    )

    worker.start()
    worker.stop()

    assert camera.released
    assert adapter.closed
    assert gimbal.closed
    assert calls.index("camera.release") < calls.index("stopped")
    assert calls.index("gimbal.close") < calls.index("stopped")
    assert events[-1]["type"] == "stopped"


def test_manual_gimbal_step_pauses_tracking_first():
    calls = []
    worker = VisionWorker(
        adapter=FakeVisionAdapter(calls),
        camera_factory=lambda: FakeCamera(calls),
        encode_frame=lambda frame: b"jpeg",
        event_sink=lambda event: None,
        gimbal=FakeGimbal(calls),
        pause_tracking=lambda: calls.append("tracking.pause"),
    )
    worker.start()

    result = worker.command("gimbal_left", {"amount": 30})
    worker.stop()

    assert result["ok"] is True
    assert calls[0] == "tracking.pause"
