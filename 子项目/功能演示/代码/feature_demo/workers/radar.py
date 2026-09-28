from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable

from ..radar.detection import BaselineComparator, ConfirmationState, DetectionRegion
from ..radar.device import A1M8Device
from ..radar.protocol import ScanPoint


class RadarWorker:
    def __init__(
        self,
        *,
        event_sink: Callable[[dict], None],
        device_factory: Callable[[], object | None] | None = None,
        region: DetectionRegion | None = None,
        baseline_frames: int = 12,
        readiness_frames: int = 5,
        minimum_frame_points: int = 1,
        confirmation_frames: int = 3,
        change_distance_mm: float = 80,
        change_ratio: float = 0.35,
        sample_period_s: float = 0.1,
    ) -> None:
        self._event_sink = event_sink
        self._device_factory = device_factory or A1M8Device
        self._region = region or DetectionRegion(225, 315, 300, 2000)
        self._baseline_frames = max(1, int(baseline_frames))
        self._readiness_frames = max(1, int(readiness_frames))
        self._minimum_frame_points = max(1, int(minimum_frame_points))
        self._confirmation_frames = max(1, int(confirmation_frames))
        self._sample_period_s = max(0.0, float(sample_period_s))
        self._change_distance_mm = float(change_distance_mm)
        self._change_ratio = float(change_ratio)
        self._comparator = BaselineComparator(
            self._region,
            change_distance_mm=self._change_distance_mm,
            change_ratio=self._change_ratio,
        )
        self._confirmation = ConfirmationState(required_frames=self._confirmation_frames)
        self._frames: deque[tuple[ScanPoint, ...]] = deque(
            maxlen=max(self._baseline_frames, self._readiness_frames)
        )
        self._frames_condition = threading.Condition()
        self._valid_rotations = 0
        self._stop_event = threading.Event()
        self._detect_event = threading.Event()
        self._reader: threading.Thread | None = None
        self._device = None
        self._connected = False
        self._last_event: dict = {}
        self._last_result = "无物块"
        self._last_scan_emit_time = 0.0
        self._rate_sample_time = time.monotonic()
        self._rate_sample = {
            "bytes_received": 0,
            "valid_points": 0,
            "complete_rotations": 0,
        }

    @property
    def last_event(self) -> dict:
        return dict(self._last_event)

    @property
    def reader_alive(self) -> bool:
        return bool(self._reader and self._reader.is_alive())

    def _reset_baseline_state(self) -> None:
        self._comparator = BaselineComparator(
            self._region,
            change_distance_mm=self._change_distance_mm,
            change_ratio=self._change_ratio,
        )
        self._confirmation = ConfirmationState(required_frames=self._confirmation_frames)
        self._last_result = "无物块"

    def start(self) -> None:
        if self.reader_alive:
            return
        self._stop_event.clear()
        self._detect_event.clear()
        self._reset_baseline_state()
        with self._frames_condition:
            self._frames.clear()
            self._valid_rotations = 0
        self._last_scan_emit_time = 0.0
        self._rate_sample_time = time.monotonic()
        self._rate_sample = {
            "bytes_received": 0,
            "valid_points": 0,
            "complete_rotations": 0,
        }
        self._device = self._device_factory()
        if self._device is None:
            self._emit({"type": "ready", "connected": False, "message": "雷达未连接"})
            return
        try:
            self._connected = bool(self._device.open())
        except Exception as exc:
            self._connected = False
            self._emit({"type": "ready", "connected": False, "message": f"雷达不可读: {exc}"})
            return
        if not self._connected:
            self._emit({"type": "ready", "connected": False, "message": "雷达未连接或无法读取"})
            return
        self._reader = threading.Thread(target=self._read_loop, name="feature-demo-radar-reader")
        self._reader.start()
        self._emit({"type": "ready", "connected": True, "port": getattr(self._device, "port", None), "message": "雷达已连接"})

    def _read_loop(self) -> None:
        try:
            for frame in self._device.iter_scans(self._stop_event):
                if self._stop_event.is_set():
                    return
                frame = tuple(frame)
                if len(frame) < self._minimum_frame_points:
                    continue
                with self._frames_condition:
                    self._frames.append(frame)
                    self._valid_rotations += 1
                    valid_rotations = self._valid_rotations
                    self._frames_condition.notify_all()
                now = time.monotonic()
                data_ready = valid_rotations >= self._readiness_frames
                should_emit = (
                    self._last_scan_emit_time == 0.0
                    or now - self._last_scan_emit_time >= self._sample_period_s
                    or valid_rotations == self._readiness_frames
                )
                if should_emit:
                    self._emit_scan(
                        frame,
                        now=now,
                        valid_rotations=valid_rotations,
                        data_ready=data_ready,
                    )
                    self._last_scan_emit_time = now
                if self._detect_event.is_set() and self._comparator.ready:
                    result = self._comparator.compare(frame)
                    changed = False
                    if result.data_valid:
                        changed = self._confirmation.update(result.has_change)
                        if changed:
                            self._last_result = (
                                "有物块" if self._confirmation.stable_value else "无物块"
                            )
                    if should_emit or changed or not result.data_valid:
                        self._emit(
                            {
                                "type": "detection",
                                "radar_data_valid": result.data_valid,
                                "result": self._last_result if result.data_valid else None,
                                "change_ratio": round(result.change_ratio, 4),
                                "threshold": self._comparator.change_ratio_threshold,
                                "confirmation": self._confirmation.progress,
                                "confirmation_required": self._confirmation.required_frames,
                            }
                        )
        except Exception as exc:
            if not self._stop_event.is_set():
                self._connected = False
                with self._frames_condition:
                    self._frames_condition.notify_all()
                self._emit(
                    {
                        "type": "error",
                        "connected": False,
                        "message": f"雷达读取失败: {exc}",
                    }
                )

    def _emit_scan(
        self,
        frame: Iterable[ScanPoint],
        *,
        now: float,
        valid_rotations: int,
        data_ready: bool,
    ) -> None:
        points = tuple(
            point for point in frame
            if 0 <= point.angle_deg < 360 and point.distance_mm > 0
        )
        diagnostics = self._scan_diagnostics(now)
        # Keep websocket updates small enough for the embedded browser.
        if len(points) > 720:
            stride = max(1, len(points) // 720)
            points = points[::stride][:720]
        self._emit(
            {
                "type": "scan",
                "radar_data_valid": bool(points),
                "data_ready": data_ready,
                "valid_rotations": valid_rotations,
                "required_rotations": self._readiness_frames,
                **diagnostics,
                "points": [
                    {
                        "angle_deg": round(point.angle_deg, 2),
                        "distance_mm": round(point.distance_mm, 1),
                        "quality": point.quality,
                    }
                    for point in points
                ],
            }
        )

    def _scan_diagnostics(self, now: float) -> dict:
        diagnostics = dict(getattr(self._device, "diagnostics", {}) or {})
        elapsed = max(now - self._rate_sample_time, 1e-9)

        def rate(name: str) -> float:
            current = int(diagnostics.get(name, 0) or 0)
            previous = int(self._rate_sample.get(name, 0) or 0)
            return max(0.0, (current - previous) / elapsed)

        result = {
            "bytes_per_second": round(rate("bytes_received"), 1),
            "points_per_second": round(rate("valid_points"), 1),
            "rotations_per_second": round(rate("complete_rotations"), 2),
            "last_rotation_points": int(diagnostics.get("last_frame_size", 0) or 0),
            "last_rotation_age_ms": round(
                max(0.0, (now - float(diagnostics.get("last_frame_timestamp", 0.0) or 0.0)) * 1000),
                1,
            ),
        }
        self._rate_sample_time = now
        for name in self._rate_sample:
            self._rate_sample[name] = int(diagnostics.get(name, 0) or 0)
        return result

    def command(self, name: str, payload: dict) -> dict:
        if name == "build_baseline":
            if not self._connected:
                return {"ok": False, "error": "disconnected", "message": "雷达未连接"}
            deadline = time.monotonic() + max(2.0, self._baseline_frames * 0.5)
            with self._frames_condition:
                if self._valid_rotations < self._readiness_frames:
                    return {
                        "ok": False,
                        "error": "not_ready",
                        "valid_rotations": self._valid_rotations,
                        "required_rotations": self._readiness_frames,
                        "message": "有效扫描旋转数不足",
                    }
                while len(self._frames) < self._baseline_frames:
                    if self._stop_event.is_set() or not self._connected:
                        return {
                            "ok": False,
                            "error": "disconnected",
                            "message": "雷达未连接",
                        }
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return {
                            "ok": False,
                            "error": "timeout",
                            "message": "基准采样超时，请检查雷达数据",
                        }
                    self._frames_condition.wait(timeout=remaining)
                frames = list(self._frames)[-self._baseline_frames :]
            try:
                self._comparator.build_baseline(frames)
            except ValueError:
                return {
                    "ok": False,
                    "error": "region_empty",
                    "message": "检测区域内没有有效雷达数据",
                }
            self._confirmation = ConfirmationState(required_frames=self._confirmation_frames)
            self._last_result = "无物块"
            result = {"ok": True, "baseline_ready": True, "frames": len(frames), "message": "基准已建立"}
            self._emit({"type": "baseline", **result})
            return result
        if name == "start_detection":
            if not self._connected:
                return {"ok": False, "message": "雷达未连接"}
            if not self._comparator.ready:
                return {"ok": False, "message": "请先建立基准"}
            self._detect_event.set()
            result = {"ok": True, "detecting": True, "result": self._last_result, "message": "检测中"}
            self._emit({"type": "detection_started", **result})
            return result
        if name == "stop_detection":
            self._detect_event.clear()
            result = {"ok": True, "detecting": False, "message": "检测已停止"}
            self._emit({"type": "detection_stopped", **result})
            return result
        raise ValueError(f"不支持的雷达命令: {name}")

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        self._detect_event.clear()
        with self._frames_condition:
            self._frames_condition.notify_all()
        if self._reader is not None:
            self._reader.join(timeout=timeout)
            if self._reader.is_alive():
                raise TimeoutError("雷达读取线程未在限定时间内停止")
        if self._device is not None:
            self._device.close()
        self._reader = None
        self._connected = False
        self._emit({"type": "stopped", "message": "雷达检测已停止"})

    def _emit(self, event: dict) -> None:
        self._last_event = dict(event)
        self._event_sink(dict(event))
