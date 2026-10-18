from __future__ import annotations

import json
import os
import socket
from pathlib import Path


class AIBoxError(RuntimeError):
    pass


class SafetyError(AIBoxError):
    pass


simulation_events: list[dict] = []


def _hardware_enabled() -> bool:
    return os.getenv("AIBOX_DEVICE_MODE", "simulation").lower() == "hardware"


def _device_request(command: str, payload: dict) -> dict:
    socket_path = os.getenv("AIBOX_ARM_SOCKET", "/run/aibox-device/arm.sock")
    request = json.dumps({"command": command, "payload": payload}, ensure_ascii=False) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(35.0)
            client.connect(socket_path)
            client.sendall(request.encode("utf-8"))
            response = b""
            while not response.endswith(b"\n") and len(response) <= 65536:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
    except OSError as error:
        raise AIBoxError(f"机械臂设备服务未连接：{error}") from error
    try:
        result = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AIBoxError("机械臂设备服务返回了无效数据。") from error
    if not result.get("ok"):
        error_type = SafetyError if result.get("code") == "SAFETY_LIMIT" else AIBoxError
        raise error_type(str(result.get("message", "机械臂指令执行失败。")))
    return result


def _emit(event: dict) -> None:
    simulation_events.append(event)
    event_file = os.getenv("AIBOX_EVENT_FILE")
    if event_file:
        with Path(event_file).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


class Arm:
    def __init__(self) -> None:
        self._pwms = [1500] * 6

    def pose(self, name: str) -> None:
        if name not in {"直立", "放平"}:
            raise SafetyError("机械臂姿态只支持：直立、放平。")
        self._run("pose", {"name": name}, name)

    def open(self) -> None:
        self._run("gripper", {"action": "open"}, "张开")

    def half_open(self) -> None:
        self._run("gripper", {"action": "half"}, "半开")

    def close(self) -> None:
        self._run("gripper", {"action": "close"}, "闭合")

    def reset(self) -> None:
        self._pwms = [1500] * 6
        self._run("center", {}, "复位")

    def action(self, name: str) -> None:
        if name not in {"抓取", "搬运", "左转移", "右转移"}:
            raise SafetyError("不支持的机械臂动作。")
        self._run("sequence", {"name": name}, name)

    def command(self, name: str) -> None:
        commands = {
            "直立": lambda: self.pose("直立"),
            "放平": lambda: self.pose("放平"),
            "抓取": lambda: self.action("抓取"),
            "搬运": lambda: self.action("搬运"),
            "复位": self.reset,
            "停止": self.stop,
            "张开": self.open,
            "闭合": self.close,
            "右转移": lambda: self.action("右转移"),
            "左转移": lambda: self.action("左转移"),
        }
        command = commands.get(name)
        if command is None:
            raise SafetyError(f"不支持的机械臂命令：{name}")
        command()

    def stop(self) -> None:
        self._run("stop", {}, "停止")

    def servo(self, joint: int, pwm: int) -> None:
        index = self._joint_index(joint)
        pwm = int(pwm)
        if not 800 <= pwm <= 2200:
            raise SafetyError("PWM必须在 800 至 2200 之间。")
        self._pwms[index] = pwm
        self._run("servo", {"servo_id": index, "pwm": pwm, "time_ms": 500}, f"关节{joint}调整到{pwm}")

    def adjust(self, joint: int, delta: int = 30) -> None:
        index = self._joint_index(joint)
        delta = int(delta)
        if not -100 <= delta <= 100 or delta == 0:
            raise SafetyError("单次微调必须在 -100 至 100 之间且不能为0。")
        if _hardware_enabled():
            self._run(
                "joint_step",
                {"servo_id": index, "delta": delta, "time_ms": 200},
                f"关节{joint}微调{delta}",
            )
        else:
            self.servo(joint, self._pwms[index] + delta)

    @staticmethod
    def _joint_index(joint: int) -> int:
        joint = int(joint)
        if not 1 <= joint <= 6:
            raise SafetyError("舵机编号必须在 1 至 6 之间。")
        return joint - 1

    @staticmethod
    def _run(command: str, payload: dict, action: str) -> None:
        hardware = _hardware_enabled()
        if hardware:
            _device_request(command, payload)
        event = {
            "type": "robot.state",
            "action": action,
            "message": f"机械臂执行：{action}",
        }
        if hardware:
            event["hardware"] = True
        _emit(event)


class Camera:
    def show(self) -> None:
        _emit(
            {
                "type": "frame.updated",
                "mode": "live",
                "message": "模拟摄像头画面已打开",
            }
        )

    def close(self) -> None:
        _emit({"type": "frame.updated", "mode": "closed", "message": "摄像头已关闭"})


class Voice:
    def listen(self, timeout: int = 8) -> str:
        text = os.getenv("AIBOX_SIM_VOICE_TEXT", "张开")
        _emit({"type": "audio.state", "state": "heard", "text": text, "message": f"识别到：{text}"})
        return text

    def speak(self, text: str) -> None:
        text = str(text).strip()
        if not 1 <= len(text) <= 200:
            raise SafetyError("朗读文字长度必须为 1 至 200 个字符。")
        _emit(
            {
                "type": "audio.state",
                "state": "played",
                "text": text,
                "message": f"声卡播放：{text}",
            }
        )

    def stop(self) -> None:
        _emit({"type": "audio.state", "state": "stopped", "message": "语音功能已停止"})


class Vision:
    def _result(self, method: str, value: str) -> str:
        _emit({"type": "result.updated", "method": method, "value": value, "message": f"识别结果：{value}"})
        return value

    def color(self) -> str:
        return self._result("color", "红色")

    def fruit(self) -> str:
        return self._result("fruit", "苹果")

    def classify(self) -> str:
        return self._result("classify", "积木")

    def shape(self) -> str:
        return self._result("shape", "圆形")


class Face:
    def detect(self) -> int:
        _emit({"type": "result.updated", "method": "face", "value": 1, "message": "检测到 1 张人脸"})
        return 1


class Hand:
    def detect(self) -> bool:
        _emit({"type": "result.updated", "method": "hand", "value": True, "message": "检测到手掌"})
        return True

    def gesture(self) -> str:
        _emit({"type": "result.updated", "method": "gesture", "value": "剪刀", "message": "识别手势：剪刀"})
        return "剪刀"

    def track(self) -> None:
        _emit({"type": "frame.updated", "mode": "hand-track", "message": "手掌跟踪已启动"})

    def stop(self) -> None:
        _emit({"type": "frame.updated", "mode": "closed", "message": "手掌跟踪已停止"})


class Lidar:
    def show(self) -> None:
        _emit({"type": "radar.scan", "distance": 860.0, "message": "模拟雷达扫描中"})

    def get_distance(self) -> float:
        return 860.0

    def detect(self) -> bool:
        _emit({"type": "radar.scan", "distance": 860.0, "changed": True, "message": "检测区域发生变化"})
        return True

    def stop(self) -> None:
        _emit({"type": "radar.scan", "state": "stopped", "message": "雷达已停止"})


class AI:
    def chat(self, text: str) -> str:
        answer = f"人工智能可以帮助机器理解信息并完成任务。你问的是：{text}"
        _emit({"type": "assistant.token", "text": answer, "message": answer})
        return answer

    def stop(self) -> None:
        _emit({"type": "assistant.token", "state": "stopped", "message": "回答已停止"})
