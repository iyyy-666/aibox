from __future__ import annotations

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


def test_runtime_keeps_camera_lazy_and_uses_existing_capture_settings():
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
    assert cv2.created[0][:2] == ("/dev/video41", 200)
    assert camera.settings == [(1, 77), (2, 1280), (3, 480), (4, 30), (5, 1)]


def test_worker_entry_emits_the_original_startup_failure(monkeypatch):
    events = []

    class FailingWorker:
        last_event = {}

        def start(self):
            raise RuntimeError("无法打开摄像头 /dev/video41。")

        def stop(self):
            self.last_event = {"type": "stopped"}

    monkeypatch.setattr(runtime, "create_worker", lambda *args, **kwargs: FailingWorker())
    monkeypatch.setattr(runtime, "emit_json", events.append)

    assert runtime.run_worker("color_recognition") == 1
    assert events == [{"type": "error", "message": "无法打开摄像头 /dev/video41。"}]
