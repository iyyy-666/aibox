from __future__ import annotations

import time
import threading

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


def test_capture_keeps_only_latest_frame_for_slow_processing():
    processed = []
    first_processing = threading.Event()
    release_processing = threading.Event()

    class CountingCamera(FakeCamera):
        def __init__(self):
            super().__init__([])
            self.sequence = 0

        def read(self):
            time.sleep(0.001)
            self.sequence += 1
            return True, self.sequence

    class SlowAdapter(FakeVisionAdapter):
        def process(self, frame):
            processed.append(frame)
            if len(processed) == 1:
                first_processing.set()
                release_processing.wait(timeout=1.0)
            return frame, {}

    camera = CountingCamera()
    worker = VisionWorker(
        adapter=SlowAdapter([]),
        camera_factory=lambda: camera,
        encode_frame=lambda frame: str(frame).encode(),
        event_sink=lambda event: None,
    )

    worker.start()
    assert first_processing.wait(timeout=1.0)
    deadline = time.monotonic() + 1.0
    while camera.sequence < 10 and time.monotonic() < deadline:
        time.sleep(0.005)
    release_processing.set()
    deadline = time.monotonic() + 1.0
    while len(processed) < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    worker.stop()

    assert camera.sequence >= 10
    assert processed[1] >= 10


def test_camera_reopens_after_consecutive_read_failures():
    events = []

    class FailingCamera(FakeCamera):
        def read(self):
            return False, None

    recovered_frame = threading.Event()

    class RecoveredCamera(FakeCamera):
        def read(self):
            time.sleep(0.005)
            recovered_frame.set()
            return True, "recovered"

    cameras = [FailingCamera([]), RecoveredCamera([])]
    created = []

    def camera_factory():
        camera = cameras[len(created)]
        created.append(camera)
        return camera

    worker = VisionWorker(
        adapter=FakeVisionAdapter([]),
        camera_factory=camera_factory,
        encode_frame=lambda frame: b"jpeg",
        event_sink=events.append,
        read_failure_limit=3,
        reconnect_delays=(0.01,),
    )

    worker.start()
    assert recovered_frame.wait(timeout=1.0)
    worker.stop()

    assert cameras[0].released
    assert len(created) == 2
    assert "camera_reconnecting" in [event["type"] for event in events]
    assert "camera_recovered" in [event["type"] for event in events]


def test_stop_during_reconnect_never_opens_another_camera():
    reconnecting = threading.Event()

    class FailingCamera(FakeCamera):
        def read(self):
            return False, None

    created = []
    worker = VisionWorker(
        adapter=FakeVisionAdapter([]),
        camera_factory=lambda: created.append(FailingCamera([])) or created[-1],
        encode_frame=lambda frame: b"jpeg",
        event_sink=lambda event: reconnecting.set()
        if event["type"] == "camera_reconnecting"
        else None,
        read_failure_limit=1,
        reconnect_delays=(1.0,),
    )

    worker.start()
    assert reconnecting.wait(timeout=1.0)
    started = time.monotonic()
    worker.stop()

    assert time.monotonic() - started < 0.5
    assert len(created) == 1
