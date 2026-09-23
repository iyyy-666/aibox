from __future__ import annotations

import base64
import threading
from typing import Callable, Protocol

from ..devices import STABLE_CAMERA_DEVICE


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
        manual_gimbal_step: Callable[[Callable[[], dict]], dict] | None = None,
        camera_device: str = STABLE_CAMERA_DEVICE,
        read_failure_limit: int = 3,
        reconnect_delays: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0),
    ) -> None:
        self._adapter = adapter
        self._camera_factory = camera_factory
        self._encode_frame = encode_frame
        self._event_sink = event_sink
        self._gimbal = gimbal
        self._pause_tracking = pause_tracking
        self._manual_gimbal_step = manual_gimbal_step
        self._camera_device = camera_device
        self._read_failure_limit = max(1, read_failure_limit)
        self._reconnect_delays = reconnect_delays or (0.1,)
        self._camera: Camera | None = None
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._processing_thread: threading.Thread | None = None
        self._frame_ready = threading.Condition()
        self._frame_sequence = 0
        self._latest_frame: object | None = None
        self._last_event: dict = {}
        self._guard = threading.RLock()

    @property
    def last_event(self) -> dict:
        with self._guard:
            return dict(self._last_event)

    def start(self) -> None:
        if self._capture_thread is not None and self._capture_thread.is_alive():
            return
        camera = self._camera_factory()
        if not camera.isOpened():
            camera.release()
            raise RuntimeError(f"无法打开摄像头 {self._camera_device}。")
        self._camera = camera
        self._stop_event.clear()
        with self._frame_ready:
            self._frame_sequence = 0
            self._latest_frame = None
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="feature-demo-vision-capture",
            daemon=False,
        )
        self._processing_thread = threading.Thread(
            target=self._processing_loop,
            name="feature-demo-vision-processing",
            daemon=False,
        )
        self._capture_thread.start()
        self._processing_thread.start()
        self._emit({"type": "ready", "message": "视觉功能已准备就绪。"})

    def _capture_loop(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            camera = self._camera
            if camera is None:
                return
            ok, frame = camera.read()
            if ok:
                failures = 0
                with self._frame_ready:
                    self._frame_sequence += 1
                    self._latest_frame = frame
                    self._frame_ready.notify()
                continue
            failures += 1
            if failures < self._read_failure_limit:
                self._stop_event.wait(0.05)
                continue
            failures = 0
            if not self._reconnect_camera():
                return

    def _reconnect_camera(self) -> bool:
        camera = self._camera
        self._camera = None
        if camera is not None:
            camera.release()
        self._emit(
            {
                "type": "camera_reconnecting",
                "message": "摄像头连接中断，正在重新连接。",
            }
        )
        attempt = 0
        while not self._stop_event.is_set():
            delay = self._reconnect_delays[min(attempt, len(self._reconnect_delays) - 1)]
            if self._stop_event.wait(delay):
                return False
            replacement = None
            try:
                replacement = self._camera_factory()
                if replacement.isOpened() and not self._stop_event.is_set():
                    self._camera = replacement
                    self._emit(
                        {
                            "type": "camera_recovered",
                            "message": "摄像头已重新连接。",
                        }
                    )
                    return True
            except Exception:
                pass
            if replacement is not None:
                replacement.release()
            attempt += 1
        return False

    def _processing_loop(self) -> None:
        processed_sequence = 0
        while not self._stop_event.is_set():
            with self._frame_ready:
                self._frame_ready.wait_for(
                    lambda: self._stop_event.is_set()
                    or self._frame_sequence > processed_sequence
                )
                if self._stop_event.is_set():
                    return
                processed_sequence = self._frame_sequence
                frame = self._latest_frame
            try:
                annotated, result = self._adapter.process(frame)
                encoded = base64.b64encode(self._encode_frame(annotated)).decode("ascii")
                self._emit(
                    {
                        "type": "frame",
                        "frame_sequence": processed_sequence,
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
            step = lambda: self._gimbal.step(
                name.removeprefix("gimbal_"), payload.get("amount", 30)
            )
            if self._manual_gimbal_step is not None:
                return self._manual_gimbal_step(step)
            if self._pause_tracking is not None:
                self._pause_tracking()
            return step()
        command = getattr(self._adapter, "command", None)
        if not callable(command):
            raise ValueError(f"不支持的视觉命令：{name}")
        return command(name, payload)

    def stop(self) -> None:
        self._stop_event.set()
        with self._frame_ready:
            self._frame_ready.notify_all()
        for thread in (self._capture_thread, self._processing_thread):
            if thread is not None:
                thread.join(timeout=3.0)
                if thread.is_alive():
                    raise TimeoutError("视觉处理线程未在限时内停止。")
        self._capture_thread = None
        self._processing_thread = None
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
