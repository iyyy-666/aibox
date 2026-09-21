from __future__ import annotations

import base64
import threading
from typing import Callable, Protocol


class Camera(Protocol):
    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, object]: ...

    def release(self) -> None: ...


class VisionAdapter(Protocol):
    def process(self, frame: object) -> tuple[object, dict]: ...

    def close(self) -> None: ...


class DirectionalGimbal(Protocol):
    def step(self, direction: str, amount: int) -> dict: ...

    def close(self) -> None: ...


class VisionWorker:
    def __init__(
        self,
        *,
        adapter: VisionAdapter,
        camera_factory: Callable[[], Camera],
        encode_frame: Callable[[object], bytes],
        event_sink: Callable[[dict], None],
        gimbal: DirectionalGimbal | None = None,
        pause_tracking: Callable[[], None] | None = None,
    ) -> None:
        self._adapter = adapter
        self._camera_factory = camera_factory
        self._encode_frame = encode_frame
        self._event_sink = event_sink
        self._gimbal = gimbal
        self._pause_tracking = pause_tracking
        self._camera: Camera | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_event: dict = {}
        self._guard = threading.RLock()

    @property
    def last_event(self) -> dict:
        with self._guard:
            return dict(self._last_event)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        camera = self._camera_factory()
        if not camera.isOpened():
            camera.release()
            raise RuntimeError("无法打开摄像头 /dev/video41。")
        self._camera = camera
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="feature-demo-vision",
            daemon=False,
        )
        self._thread.start()
        self._emit({"type": "ready", "message": "视觉功能已准备就绪。"})

    def _run(self) -> None:
        while not self._stop_event.is_set():
            camera = self._camera
            if camera is None:
                return
            ok, frame = camera.read()
            if not ok:
                self._emit({"type": "status", "message": "正在等待摄像头画面…"})
                self._stop_event.wait(0.05)
                continue
            try:
                annotated, result = self._adapter.process(frame)
                encoded = base64.b64encode(self._encode_frame(annotated)).decode("ascii")
                self._emit(
                    {
                        "type": "frame",
                        "frame_jpeg_base64": encoded,
                        **result,
                    }
                )
            except Exception as exc:
                self._emit({"type": "error", "message": str(exc)})
                self._stop_event.wait(0.05)

    def command(self, name: str, payload: dict) -> dict:
        if name.startswith("gimbal_"):
            if self._gimbal is None:
                raise RuntimeError("云台服务未配置。")
            if self._pause_tracking is not None:
                self._pause_tracking()
            return self._gimbal.step(name.removeprefix("gimbal_"), payload.get("amount", 30))
        command = getattr(self._adapter, "command", None)
        if not callable(command):
            raise ValueError(f"不支持的视觉命令：{name}")
        return command(name, payload)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                raise TimeoutError("视觉处理线程未在限时内停止。")
        self._thread = None
        if self._camera is not None:
            self._camera.release()
            self._camera = None
        self._adapter.close()
        if self._gimbal is not None:
            self._gimbal.close()
        self._emit({"type": "stopped", "message": "视觉功能已停止。"})

    def _emit(self, event: dict) -> None:
        with self._guard:
            self._last_event = dict(event)
        self._event_sink(event)
