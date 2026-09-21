from __future__ import annotations

import threading
from typing import Callable

from ..adapters.robot import RobotAdapter


class RobotWorker:
    def __init__(self, adapter: RobotAdapter, *, event_sink: Callable[[dict], None]) -> None:
        self._adapter = adapter
        self._event_sink = event_sink
        self._started = False
        self._last_event: dict = {}

    @property
    def last_event(self) -> dict:
        return dict(self._last_event)

    def start(self) -> None:
        if self._started:
            return
        self._adapter.connect()
        self._started = True
        self._emit({"type": "ready", "message": "机械臂已连接，等待操作。"})

    def command(self, name: str, payload: dict) -> dict:
        if not self._started:
            raise RuntimeError("机械臂功能尚未启动。")
        result = self._adapter.command(name, payload)
        self._emit({"type": "result", **result})
        return result

    def stop(self) -> None:
        try:
            self.stop_motion()
        finally:
            self.disconnect()

    def stop_motion(self) -> None:
        if self._started:
            self._adapter.stop_motion()

    def disconnect(self) -> None:
        if not self._started:
            return
        self._adapter.disconnect()
        self._started = False
        self._emit({"type": "stopped", "message": "机械臂已停止并断开连接。"})

    def _emit(self, event: dict) -> None:
        self._last_event = dict(event)
        self._event_sink(event)


class SortingController:
    """Coordinates the existing sorting poses with stable color detections."""

    DESTINATIONS = {"red": "left", "blue": "right"}

    def __init__(
        self,
        robot_worker: RobotWorker,
        *,
        stable_hits: int = 2,
        event_sink: Callable[[dict], None],
    ) -> None:
        self._robot_worker = robot_worker
        self._stable_hits = stable_hits
        self._event_sink = event_sink
        self._prepared = False
        self._sorting = False
        self._paused = False
        self._busy = False
        self._candidate_color = ""
        self._candidate_count = 0
        self._lock = threading.RLock()

    @property
    def stable_hits(self) -> int:
        return self._stable_hits

    def prepare(self) -> dict:
        result = self._robot_worker.command("sorting_ready", {})
        with self._lock:
            self._prepared = bool(result["ok"])
            self._sorting = False
            self._paused = False
            self._reset_candidate()
        return result

    def start(self) -> dict:
        with self._lock:
            if not self._prepared:
                return {"ok": False, "message": "请先让机械臂进入分拣准备姿态。"}
            if self._busy:
                return {"ok": False, "message": "机械臂正在执行分拣动作。"}
            self._sorting = True
            self._paused = False
            self._reset_candidate()
        return {"ok": True, "message": "已开始等待红色或蓝色物块。"}

    def pause(self) -> dict:
        with self._lock:
            if not self._sorting:
                return {"ok": False, "message": "分拣尚未开始。"}
            self._paused = not self._paused
            self._reset_candidate()
            paused = self._paused
        return {"ok": True, "paused": paused, "message": "分拣已暂停。" if paused else "分拣已继续。"}

    def stop(self) -> dict:
        try:
            result = self._robot_worker.command("stop_motion", {})
        finally:
            with self._lock:
                self._prepared = False
                self._sorting = False
                self._paused = False
                self._busy = False
                self._reset_candidate()
        return result

    def observe_color(self, color: str | None) -> dict | None:
        normalized_color = color.lower() if isinstance(color, str) else ""
        side = self.DESTINATIONS.get(normalized_color)
        with self._lock:
            if side is None:
                self._reset_candidate()
                return None
            if not self._sorting or self._paused or self._busy:
                return None
            if normalized_color == self._candidate_color:
                self._candidate_count += 1
            else:
                self._candidate_color = normalized_color
                self._candidate_count = 1
            if self._candidate_count < self._stable_hits:
                return None
            self._busy = True
            self._sorting = False
        try:
            result = self._robot_worker.command("sorting_transfer", {"side": side})
            self._event_sink(
                {
                    "type": "sorting_result",
                    "color": normalized_color,
                    "side": side,
                    **result,
                }
            )
            return result
        finally:
            with self._lock:
                self._busy = False
                self._prepared = True
                self._paused = False
                self._reset_candidate()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "prepared": self._prepared,
                "sorting": self._sorting,
                "paused": self._paused,
                "candidate_color": self._candidate_color,
                "candidate_count": self._candidate_count,
            }

    def _reset_candidate(self) -> None:
        self._candidate_color = ""
        self._candidate_count = 0


class ObjectSortingWorker:
    """Runs the camera pipeline and robot sorting controls in one worker process."""

    def __init__(
        self,
        vision_worker: object,
        robot_worker: RobotWorker,
        controller: SortingController,
        *,
        event_sink: Callable[[dict], None],
    ) -> None:
        self._vision_worker = vision_worker
        self._robot_worker = robot_worker
        self._controller = controller
        self._event_sink = event_sink
        self._last_event: dict = {}

    @property
    def last_event(self) -> dict:
        return dict(self._last_event)

    def start(self) -> None:
        self._robot_worker.start()
        try:
            self._vision_worker.start()
        except Exception:
            self._robot_worker.stop()
            raise
        self._emit({"type": "ready", "message": "物体分拣已准备就绪。"})

    def command(self, name: str, payload: dict) -> dict:
        if name == "prepare":
            return self._controller.prepare()
        if name == "start_sorting":
            return self._controller.start()
        if name == "pause_sorting":
            return self._controller.pause()
        if name == "stop_sorting":
            return self._controller.stop()
        return self._vision_worker.command(name, payload)

    def stop(self) -> None:
        try:
            self._robot_worker.stop_motion()
        finally:
            try:
                self._vision_worker.stop()
            finally:
                try:
                    self._robot_worker.disconnect()
                finally:
                    self._emit({"type": "stopped", "message": "物体分拣已停止。"})

    def _emit(self, event: dict) -> None:
        self._last_event = dict(event)
        self._event_sink(event)
