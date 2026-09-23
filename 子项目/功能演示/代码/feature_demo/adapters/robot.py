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
        self._stop_lock = threading.Lock()
        self._transfer_finished = threading.Condition(self._lock)
        self._active_transfers = 0

    @property
    def connected(self) -> bool:
        return bool(self._serial is not None and getattr(self._serial, "connected", False))

    def connect(self) -> None:
        with self._lock:
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
        if name != "stop_motion" and not self.connected:
            self.connect()
        if name == "sorting_transfer":
            return self._sorting_transfer(payload)
        if name == "stop_motion":
            ok = self._stop_motion_now()
            return {
                "ok": bool(ok),
                "command": name,
                "result": "停止",
                "message": "机械臂命令已执行。" if ok else "机械臂未能执行该命令。",
            }
        with self._lock:
            if self._robot is None:
                raise RuntimeError("机械臂当前未连接。")
            robot = self._robot
            if name == "pose":
                label = str(payload.get("name", ""))
                if not label:
                    raise ValueError("请选择机械臂姿态。")
                ok = robot.execute_pose(label)
            elif name == "sequence":
                label = str(payload.get("name", ""))
                if not label:
                    raise ValueError("请选择机械臂动作组。")
                ok = robot.execute_sequence(label)
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
            return {
                "ok": bool(ok),
                "command": name,
                "result": label,
                "message": "机械臂命令已执行。" if ok else "机械臂未能执行该命令。",
            }

    def _sorting_transfer(self, payload: dict) -> dict:
        side = str(payload.get("side", ""))
        if side not in {"left", "right"}:
            raise ValueError("分拣方向必须是 left 或 right。")
        with self._transfer_finished:
            if self._robot is None:
                raise RuntimeError("机械臂当前未连接。")
            robot = self._robot
            self._active_transfers += 1
        try:
            ok = robot.execute_sort_transfer(side)
        finally:
            with self._transfer_finished:
                self._active_transfers -= 1
                self._transfer_finished.notify_all()
        return {
            "ok": bool(ok),
            "command": "sorting_transfer",
            "result": side,
            "message": "机械臂命令已执行。" if ok else "机械臂未能执行该命令。",
        }

    def stop_motion(self) -> None:
        self._stop_motion_now()

    def _stop_motion_now(self) -> bool:
        # The legacy robot stop flag must be set while a synchronous sequence is
        # still running. Its SerialDriver serializes the emergency serial write.
        with self._stop_lock:
            robot = self._robot
            return True if robot is None else bool(robot.stop())

    def disconnect(self) -> None:
        with self._transfer_finished:
            while self._active_transfers:
                self._transfer_finished.wait()
            if self._serial is not None:
                self._serial.disconnect()
            self._robot = None
            self._serial = None
