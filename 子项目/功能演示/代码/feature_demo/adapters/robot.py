from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Callable


def _legacy_factories():
    legacy_root = Path(os.getenv("AIBOX_LEGACY_ROOT", "/root/robot_arm"))
    if str(legacy_root) not in sys.path:
        sys.path.insert(0, str(legacy_root))
    from robot import RobotArm
    from serial_driver import SerialDriver

    return SerialDriver, RobotArm


class RobotAdapter:
    def __init__(
        self,
        *,
        serial_factory: Callable[[], object] | None = None,
        robot_factory: Callable[[object], object] | None = None,
    ) -> None:
        self._serial_factory = serial_factory
        self._robot_factory = robot_factory
        self._serial = None
        self._robot = None
        self._lock = threading.RLock()
        self._stop_lock = threading.RLock()
        self._transfer_finished = threading.Condition(self._lock)
        self._active_transfers = 0
        self._holding_upright = False
        self._stop_generation = 0
        self._closed = False

    @property
    def connected(self) -> bool:
        return bool(self._serial is not None and getattr(self._serial, "connected", False))

    @property
    def holding_upright(self) -> bool:
        with self._stop_lock:
            return self._holding_upright

    @property
    def motion_generation(self) -> int:
        with self._lock:
            if self._robot is None:
                raise RuntimeError("机械臂当前未连接。")
            current_generation = getattr(self._robot, "_current_motion_generation", None)
            if not callable(current_generation):
                raise RuntimeError("机械臂驱动不支持安全运动代次。")
            return int(current_generation())

    def connect(self) -> None:
        self._acquire_lifecycle_locks()
        try:
            if self._closed:
                raise RuntimeError("机械臂功能已经停止。")
            self._connect_locked()
        finally:
            self._stop_lock.release()
            self._lock.release()

    def _acquire_lifecycle_locks(self) -> None:
        # Never wait for an active action while holding the preemptive stop lock.
        while True:
            self._lock.acquire()
            if self._stop_lock.acquire(blocking=False):
                return
            self._lock.release()
            with self._stop_lock:
                pass

    def _connect_locked(self) -> None:
        if self.connected:
            return
        if self._serial_factory is None or self._robot_factory is None:
            serial_class, robot_class = _legacy_factories()
            self._serial_factory = serial_class
            self._robot_factory = robot_class
        serial = self._serial_factory()
        if not serial.connect():
            raise RuntimeError("无法连接机械臂串口 /dev/esp32_arm。")
        self._serial = serial
        self._robot = self._robot_factory(serial)

    def command(self, name: str, payload: dict) -> dict:
        if name == "stop_motion":
            ok = self._stop_motion_now()
            return {
                "ok": bool(ok),
                "command": name,
                "result": "停止",
                "message": "机械臂命令已执行。" if ok else "机械臂未能执行该命令。",
            }
        self._acquire_lifecycle_locks()
        try:
            if self._closed:
                raise RuntimeError("机械臂功能已经停止。")
            if (
                name == "pose"
                and str(payload.get("name", "")) == "直立"
                and self._holding_upright
            ):
                result = {
                    "ok": True,
                    "command": name,
                    "result": "直立",
                    "message": "机械臂已保持直立。",
                }
                self._stop_lock.release()
                self._lock.release()
                return result
            self._holding_upright = False
            stop_generation = self._stop_generation
            self._connect_locked()
            robot = self._robot
        except Exception:
            self._stop_lock.release()
            self._lock.release()
            raise
        self._stop_lock.release()
        try:
            if self._robot is None:
                raise RuntimeError("机械臂当前未连接。")
            if name == "sorting_transfer":
                return self._sorting_transfer_locked(payload, robot)
            if name == "pose":
                label = str(payload.get("name", ""))
                if not label:
                    raise ValueError("请选择机械臂姿态。")
                ok = robot.execute_pose(label)
            elif name == "sequence":
                label = str(payload.get("name", ""))
                if not label:
                    raise ValueError("请选择机械臂动作组。")
                generation = payload.get("_motion_generation")
                if generation is None:
                    ok = robot.execute_sequence(label)
                else:
                    ok = robot.execute_sequence(
                        label,
                        _motion_generation=int(generation),
                    )
            elif name == "joint_step":
                servo_id = int(payload.get("servo_id", -1))
                delta = max(-500, min(500, int(payload.get("delta", 0))))
                if servo_id not in range(6) or delta == 0:
                    raise ValueError("关节和步进量参数无效。")
                ok = robot.move_servo_step(servo_id, delta, int(payload.get("time_ms", 200)))
                label = f"关节 {servo_id}"
            elif name == "gripper":
                action = str(payload.get("action", ""))
                method = getattr(robot, f"gripper_{action}", None)
                if action not in {"open", "close", "half"} or not callable(method):
                    raise ValueError("夹爪命令必须是 open、close 或 half。")
                ok = method()
                label = action
            elif name == "center":
                ok = robot.all_center()
                label = "center"
            elif name == "sorting_ready":
                ok = robot.prepare_sorting_pose()
                label = "分拣准备"
            else:
                raise ValueError(f"不支持的机械臂命令：{name}")
            result = {
                "ok": bool(ok),
                "command": name,
                "result": label,
                "message": "机械臂命令已执行。" if ok else "机械臂未能执行该命令。",
            }
        finally:
            self._lock.release()
        if ok and name == "pose" and label == "直立":
            with self._stop_lock:
                with self._lock:
                    self._holding_upright = (
                        not self._closed
                        and self._stop_generation == stop_generation
                        and self._robot is robot
                    )
                    if self._holding_upright:
                        self._disconnect_locked()
        return result

    def _sorting_transfer_locked(self, payload: dict, robot: object) -> dict:
        side = str(payload.get("side", ""))
        if side not in {"left", "right"}:
            raise ValueError("分拣方向必须是 left 或 right。")
        ok = robot.execute_sort_transfer(side)
        return {
            "ok": bool(ok),
            "command": "sorting_transfer",
            "result": side,
            "message": "机械臂命令已执行。" if ok else "机械臂未能执行该命令。",
        }

    def stop_motion(self) -> None:
        if not self._stop_motion_now():
            raise RuntimeError("机械臂急停命令执行失败。")

    def _stop_motion_now(self) -> bool:
        # The legacy robot stop flag must be set while a synchronous sequence is
        # still running. Its SerialDriver serializes the emergency serial write.
        with self._stop_lock:
            reconnect_for_stop = self._robot is None and self._holding_upright
            if reconnect_for_stop:
                with self._lock:
                    self._connect_locked()
            self._stop_generation += 1
            robot = self._robot
            ok = True if robot is None else bool(robot.stop())
            if ok:
                self._holding_upright = False
            if reconnect_for_stop and self._closed:
                with self._lock:
                    self._disconnect_locked()
            return ok

    def stop_motion_for_shutdown(self) -> None:
        with self._stop_lock:
            if self._holding_upright:
                return
            self._stop_generation += 1
            robot = self._robot
            if robot is not None and not robot.stop():
                raise RuntimeError("机械臂急停命令执行失败。")

    def shutdown(self) -> None:
        with self._stop_lock:
            self._closed = True
            try:
                if not self._holding_upright:
                    self._stop_generation += 1
                    robot = self._robot
                    if robot is not None and not robot.stop():
                        raise RuntimeError("机械臂急停命令执行失败。")
            finally:
                with self._lock:
                    self._disconnect_locked()

    def disconnect(self) -> None:
        self._acquire_lifecycle_locks()
        try:
            self._disconnect_locked()
        finally:
            self._stop_lock.release()
            self._lock.release()

    def _disconnect_locked(self) -> None:
        if self._serial is not None:
            self._serial.disconnect()
        self._robot = None
        self._serial = None
