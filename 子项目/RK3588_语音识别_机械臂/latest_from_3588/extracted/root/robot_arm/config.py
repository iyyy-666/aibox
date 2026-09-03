"""
机械臂配置 - KM1 6轴机械臂 + ESP32
"""
import json
from pathlib import Path

# ---- 串口 ----
SERIAL_PORT = "/dev/esp32_arm"
SERIAL_BAUD = 115200
SERIAL_TIMEOUT = 0.1

# ---- 机械臂 ----
NUM_SERVOS = 6
SERVO_NAMES = ["底座", "肩部", "肘部1", "肘部2", "腕部", "夹爪"]

# PWM范围：500~2500，对应舵机角度0°~270°
# 扩大安全范围：±700PWM ≈ ±95°
PWM_MIN = 800
PWM_MAX = 2200
PWM_CENTER = 1500
SAFE_RANGE = 700

# ---- 预设姿势 ----
PRESET_POSES = {
    "直立": {
        "pwms": [1500, 1500, 1500, 1500, 1500, -1],
        "time": 1500,
        "description": "竖直待命，夹爪保持原样"
    },
    "放平": {
        "pwms": [1500, 870, 1500, 1500, 1500, -1],
        "time": 2000,
        "description": "肩前倾85°，臂身笔直"
    },
    "抓取位": {
        "pwms": [1500, 850, 1500, 1500, 1500, 2200],
        "time": 2000,
        "description": "下弯+夹爪闭合"
    },
}

# ---- 动作序列（多步骤）----
ACTION_SEQUENCES = {
    "抓取": [
        {"pwms": [1402, 1500, 1500, 1500, 1500, 1171], "time": 1000, "desc": "1/4 底座微转，夹爪半开"},
        {"sleep": 1.5, "desc": "等1完成"},
        {"pwms": [1402, 1360, 1997, 1003, 1500, 1171], "time": 2500, "desc": "2/4 A形拱桥下折"},
        {"sleep": 2.5, "desc": "等2完成"},
        {"pwms": [1402, 1360, 1997, 1003, 1500, 1437], "time": 2000, "desc": "3/4 夹爪半闭合"},
        {"sleep": 2.2, "desc": "等3完成"},
        {"pwms": [1402, 1360, 1787, 1003, 1500, 1437], "time": 1500, "desc": "4/4 上台"},
    ],
    "搬运": [
        {"pwms": [1402, 1500, 1500, 1500, 1500, 1171], "time": 1000, "desc": "1/6 底座微转，夹爪半开"},
        {"sleep": 1.5, "desc": "等1"},
        {"pwms": [1402, 1360, 1997, 1003, 1500, 1171], "time": 2500, "desc": "2/6 A形拱桥下折"},
        {"sleep": 2.5, "desc": "等2"},
        {"pwms": [1402, 1360, 1997, 1003, 1500, 1437], "time": 2000, "desc": "3/6 夹爪半闭合"},
        {"sleep": 2.2, "desc": "等3"},
        {"pwms": [1402, 1360, 1787, 1003, 1500, 1437], "time": 1500, "desc": "4/6 上台"},
        {"sleep": 2.0, "desc": "等4"},
        {"pwms": [933, 1269, 1787, 800, 1500, 1437], "time": 2000, "desc": "5/6 转移物块"},
        {"sleep": 2.2, "desc": "等5"},
        {"pwms": [933, 1269, 1787, 800, 1500, 1241], "time": 1000, "desc": "6/6 释放物块"},
    ],
}

# ---- 自定义姿势文件 ----
# Keep the legacy transfer command as a compatibility alias, while exposing
# explicit right and left transfer actions for sorting.
_right_transfer = ACTION_SEQUENCES["\u642c\u8fd0"]
ACTION_SEQUENCES["\u8f6c\u79fb"] = _right_transfer
ACTION_SEQUENCES["\u53f3\u8f6c\u79fb"] = _right_transfer
ACTION_SEQUENCES["\u5de6\u8f6c\u79fb"] = [
    {"pwms": [1402, 1500, 1500, 1500, 1500, 1171], "time": 1000, "desc": "1/6 base pre-position"},
    {"sleep": 1.5, "desc": "wait"},
    {"pwms": [1402, 1360, 1997, 1003, 1500, 1171], "time": 2500, "desc": "2/6 lower"},
    {"sleep": 2.5, "desc": "wait"},
    {"pwms": [1402, 1360, 1997, 1003, 1500, 1437], "time": 2000, "desc": "3/6 grip"},
    {"sleep": 2.2, "desc": "wait"},
    {"pwms": [1402, 1360, 1787, 1003, 1500, 1437], "time": 1500, "desc": "4/6 lift"},
    {"sleep": 2.0, "desc": "wait"},
    {"pwms": [1871, 1269, 1787, 800, 1500, 1437], "time": 2000, "desc": "5/6 move left"},
    {"sleep": 2.2, "desc": "wait"},
    {"pwms": [1871, 1269, 1787, 800, 1500, 1241], "time": 1000, "desc": "6/6 release"},
]

SORTING_READY_PWMS = [1402, 1360, 1787, 1003, 1500, 800]
SORTING_GRIP_CLOSED = 1437
SORTING_GRIP_RELEASE = 1241
SORTING_RIGHT_BASE = 933
SORTING_LEFT_BASE = 1871

POSES_FILE = Path(__file__).parent / "poses.json"

def load_custom_poses():
    if POSES_FILE.exists():
        try:
            return json.loads(POSES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_custom_pose(name, pwms, time_ms=1500, description=""):
    poses = load_custom_poses()
    poses[name] = {
        "pwms": pwms,
        "time": time_ms,
        "description": description or f"自定义姿势: {name}"
    }
    POSES_FILE.write_text(json.dumps(poses, ensure_ascii=False, indent=2), encoding="utf-8")
    PRESET_POSES[name] = poses[name]

for name, data in load_custom_poses().items():
    if name not in PRESET_POSES:
        PRESET_POSES[name] = data

# ---- Web 服务 ----
WEB_HOST = "0.0.0.0"
WEB_PORT = 8000

# ---- 语音识别（后续扩展）----
VOICE_COMMANDS = {
    "直立": "直立",
    "放平": "放平",
    "抓取": "抓取位",
    "张开": "张开",
    "闭合": "闭合",
}
