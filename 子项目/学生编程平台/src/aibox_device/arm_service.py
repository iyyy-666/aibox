from __future__ import annotations

import json
import os
import socket
import socketserver
import struct
import sys
import threading
from pathlib import Path
from typing import Callable


SOCKET_PATH = Path("/run/aibox-device/arm.sock")
PWM_MIN = 800
PWM_MAX = 2200


def _legacy_factories():
    legacy_root = Path(os.getenv("AIBOX_LEGACY_ROOT", "/root/robot_arm"))
    if str(legacy_root) not in sys.path:
        sys.path.insert(0, str(legacy_root))
    from robot import RobotArm
    from serial_driver import SerialDriver

    return SerialDriver, RobotArm


class ArmController:
    def __init__(
        self,
        *,
        serial_factory: Callable[[], object] | None = None,
        robot_factory: Callable[[object], object] | None = None,
    ) -> None:
        self._serial_factory = serial_factory
        self._robot_factory = robot_factory
        self._operation_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_robot = None

    def execute(self, command: str, payload: dict) -> dict:
        error = self._validate(command, payload)
        if error:
            return {"ok": False, "code": "SAFETY_LIMIT", "message": error}
        if command == "stop":
            return self._stop()

        with self._operation_lock:
            serial = None
            try:
                serial_class, robot_class = self._factories()
                serial = serial_class()
                if not serial.connect():
                    return {"ok": False, "code": "DEVICE_UNAVAILABLE", "message": "无法连接机械臂控制器。"}
                robot = robot_class(serial)
                with self._state_lock:
                    self._active_robot = robot
                ok = self._dispatch(robot, command, payload)
                return {
                    "ok": bool(ok),
                    "command": command,
                    "message": "机械臂指令已执行。" if ok else "机械臂拒绝或未完成该指令。",
                }
            except Exception as error:
                return {"ok": False, "code": "DEVICE_ERROR", "message": f"机械臂执行失败：{error}"}
            finally:
                with self._state_lock:
                    self._active_robot = None
                if serial is not None:
                    serial.disconnect()

    def _factories(self):
        if self._serial_factory is None or self._robot_factory is None:
            self._serial_factory, self._robot_factory = _legacy_factories()
        return self._serial_factory, self._robot_factory

    @staticmethod
    def _validate(command: str, payload: dict) -> str:
        if command == "pose" and payload.get("name") not in {"直立", "放平"}:
            return "机械臂姿态只支持直立或放平。"
        if command == "sequence" and payload.get("name") not in {"抓取", "搬运", "左转移", "右转移"}:
            return "机械臂动作不在安全白名单中。"
        if command == "gripper" and payload.get("action") not in {"open", "half", "close"}:
            return "夹爪动作不在安全白名单中。"
        if command in {"servo", "joint_step"}:
            servo_id = int(payload.get("servo_id", -1))
            if servo_id not in range(6):
                return "舵机编号必须在 1 至 6 之间。"
        if command == "servo" and not PWM_MIN <= int(payload.get("pwm", 0)) <= PWM_MAX:
            return f"PWM 必须在 {PWM_MIN} 至 {PWM_MAX} 之间。"
        if command == "joint_step":
            delta = int(payload.get("delta", 0))
            if delta == 0 or not -100 <= delta <= 100:
                return "单次微调必须在 -100 至 100 之间且不能为 0。"
        if command not in {"pose", "sequence", "gripper", "center", "servo", "joint_step", "stop"}:
            return "不支持的机械臂指令。"
        return ""

    @staticmethod
    def _dispatch(robot, command: str, payload: dict) -> bool:
        if command == "pose":
            return bool(robot.execute_pose(str(payload["name"])))
        if command == "sequence":
            return bool(robot.execute_sequence(str(payload["name"])))
        if command == "gripper":
            return bool(getattr(robot, f"gripper_{payload['action']}")())
        if command == "center":
            return bool(robot.all_center())
        if command == "servo":
            return bool(robot.set_servo(int(payload["servo_id"]), int(payload["pwm"]), int(payload.get("time_ms", 500))))
        if command == "joint_step":
            return bool(robot.move_servo_step(int(payload["servo_id"]), int(payload["delta"]), int(payload.get("time_ms", 200))))
        raise ValueError(f"unsupported command: {command}")

    def _stop(self) -> dict:
        with self._state_lock:
            robot = self._active_robot
        ok = True if robot is None else bool(robot.stop())
        return {"ok": ok, "command": "stop", "message": "机械臂已停止。"}


class ArmRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        credentials = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", credentials)
        if uid not in self.server.allowed_uids:
            self._write({"ok": False, "code": "UNAUTHORIZED", "message": "未授权的设备请求。"})
            return
        try:
            request = json.loads(self.rfile.readline(65537).decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            response = self.server.controller.execute(
                str(request.get("command", "")),
                request.get("payload", {}) if isinstance(request.get("payload", {}), dict) else {},
            )
        except Exception as error:
            response = {"ok": False, "code": "BAD_REQUEST", "message": f"设备请求格式错误：{error}"}
        self._write(response)

    def _write(self, response: dict) -> None:
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


_UnixServerBase = getattr(socketserver, "ThreadingUnixStreamServer", socketserver.ThreadingTCPServer)


class ArmSocketServer(_UnixServerBase):
    daemon_threads = True

    def __init__(self, path: str, controller: ArmController, allowed_uids: set[int]):
        self.controller = controller
        self.allowed_uids = allowed_uids
        super().__init__(path, ArmRequestHandler)


def main() -> int:
    import grp

    socket_path = Path(os.getenv("AIBOX_ARM_SOCKET", SOCKET_PATH))
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    ztl_uid = int(os.getenv("AIBOX_STUDENT_UID", "1000"))
    server = ArmSocketServer(str(socket_path), ArmController(), {0, ztl_uid})
    try:
        group_id = grp.getgrnam(os.getenv("AIBOX_DEVICE_GROUP", "ztl")).gr_gid
        os.chown(socket_path, 0, group_id)
        os.chmod(socket_path, 0o660)
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        socket_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
