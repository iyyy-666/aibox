"""
Web服务 - 机械臂控制面板
启动: python3 server.py
访问: http://<IP>:8000
"""
import json
import os
import time
import threading
import audioop
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from config import WEB_HOST, WEB_PORT, PRESET_POSES, PWM_MIN, PWM_MAX
from serial_driver import SerialDriver
from robot import RobotArm
from voice_engine import VoiceEngine, idle_timeout_due
from audio_config import audio_output_device, voice_input_device

# ---- 全局实例 ----
ser = SerialDriver()
robot = RobotArm(ser)
voice = VoiceEngine()
VOICE_AUTO_UPRIGHT_SEC = float(os.getenv("VOICE_AUTO_UPRIGHT_SEC", "20"))
_voice_timeout_thread = None
_voice_timeout_started = False


def _voice_timeout_worker():
    idle_started = time.monotonic()
    while voice.running:
        time.sleep(0.5)
        if robot.is_moving:
            idle_started = time.monotonic()
            continue
        if voice.last_command_at and voice.last_command_at > time.time() - 1.0:
            idle_started = time.monotonic()
            continue
        idle_sec = time.monotonic() - idle_started
        already_upright = getattr(robot, "current_pose", "") == "直立"
        if not idle_timeout_due(idle_sec, moving=False, already_upright=already_upright, timeout=VOICE_AUTO_UPRIGHT_SEC):
            continue
        robot.execute_pose("直立")
        idle_started = time.monotonic()
        voice.last_command_at = time.time()


def _start_voice_timeout_worker():
    global _voice_timeout_thread, _voice_timeout_started
    if _voice_timeout_thread and _voice_timeout_thread.is_alive():
        return
    _voice_timeout_started = True
    _voice_timeout_thread = threading.Thread(target=_voice_timeout_worker, daemon=True)
    _voice_timeout_thread.start()

# ---- WebSocket 连接池 ----
ws_clients: list[WebSocket] = []

# ---- FastAPI ----
app = FastAPI(title="KM1 机械臂控制台", version="2.0")

# ---- 系统 API ----

@app.get("/api/status")
def get_status():
    return {
        "serial": ser.status(),
        "robot": robot.status(),
        "voice": voice.status(),
        "timestamp": time.time(),
    }


@app.get("/api/serial/connect")
def serial_connect():
    ok = ser.connect()
    upright = robot.execute_pose("直立") if ok else False
    broadcast_status()
    return {"success": ok, "port": ser.status()["port"], "upright": upright}


@app.get("/api/serial/disconnect")
def serial_disconnect():
    ser.disconnect()
    return {"success": True}


# ---- 机械臂 API ----

@app.post("/api/robot/servo/{servo_id}")
def set_servo(servo_id: int, pwm: int, time_ms: int = 500):
    ok = robot.set_servo(servo_id, pwm, time_ms)
    broadcast_status()
    return {"success": ok, "servo_id": servo_id, "pwm": pwm, "time_ms": time_ms}


@app.post("/api/robot/all")
def set_all_servos(pwms: list[int], time_ms: int = 1000):
    ok = robot.set_all_servos(pwms, time_ms)
    broadcast_status()
    return {"success": ok, "pwms": pwms, "time_ms": time_ms}


@app.post("/api/robot/group")
def set_all_group(pwms: list[int], time_ms: int = 1000):
    """使用群组指令发送"""
    ok = robot.set_all_servos_group(pwms, time_ms)
    broadcast_status()
    return {"success": ok, "pwms": pwms, "time_ms": time_ms}


@app.post("/api/robot/pose/{pose_name}")
def execute_pose(pose_name: str):
    ok = robot.execute_pose(pose_name)
    broadcast_status()
    return {"success": ok, "pose": pose_name}


@app.post("/api/robot/stop")
def stop():
    ok = robot.stop()
    broadcast_status()
    return {"success": ok}


@app.post("/api/robot/gripper/{action}")
def gripper(action: str):
    if action == "open":
        ok = robot.gripper_open()
    elif action == "close":
        ok = robot.gripper_close()
    elif action == "half":
        ok = robot.gripper_half()
    else:
        return {"success": False, "error": f"unknown action: {action}"}
    broadcast_status()
    return {"success": ok, "action": action}


@app.post("/api/robot/gripper_adjust")
def gripper_step(delta: int, time_ms: int = 180):
    ok = robot.gripper_step(delta, time_ms)
    broadcast_status()
    return {"success": ok, "delta": delta, "time_ms": time_ms}


@app.post("/api/robot/joint/{servo_id}/stop")
def joint_stop(servo_id: int):
    ok = robot.stop_rotate(servo_id)
    return {"success": ok}


@app.post("/api/robot/joint/{servo_id}/{direction}")
def joint_rotate(servo_id: int, direction: str, delta: int = 60, time_ms: int = 180):
    """关节微调: servo_id 0-5, direction=plus/minus，每次只调整一次PWM。"""
    if servo_id < 0 or servo_id > 5:
        return {"success": False, "error": "invalid servo_id 0-5"}
    delta = max(1, min(200, abs(int(delta))))
    if direction == "plus":
        ok = robot.move_servo_step(servo_id, delta, time_ms)
    elif direction == "minus":
        ok = robot.move_servo_step(servo_id, -delta, time_ms)
    else:
        return {"success": False, "error": "use plus or minus"}
    broadcast_status()
    return {
        "success": ok,
        "servo_id": servo_id,
        "direction": direction,
        "delta": delta,
        "time_ms": time_ms,
        "pwm": robot.status().get("servo_pwms", [None] * 6)[servo_id],
    }


@app.post("/api/robot/all_center")
def all_center():
    ok = robot.all_center()
    broadcast_status()
    return {"success": ok}


@app.post("/api/robot/sequence/{seq_name}")
def execute_sequence(seq_name: str):
    ok = robot.execute_sequence(seq_name)
    broadcast_status()
    return {"success": ok, "sequence": seq_name}



# ---- 校准 API ----

@app.post("/api/robot/sorting/ready")
def sorting_ready():
    ok = robot.prepare_sorting_pose()
    broadcast_status()
    return {"success": ok, "pose": "分拣待命"}


@app.post("/api/robot/sorting/{side}")
def sorting_transfer(side: str):
    if side not in {"left", "right"}:
        return {"success": False, "error": "side must be left or right"}
    ok = robot.execute_sort_transfer(side)
    broadcast_status()
    return {"success": ok, "side": side}


@app.get("/api/robot/sorting/stages")
def sorting_stages():
    return {"success": True, "stages": robot.get_sorting_stages()}


@app.post("/api/robot/sorting/stage/{side}/{stage}")
def save_sorting_stage(side: str, stage: int, time_ms: int = 1500):
    result = robot.save_sorting_stage(side, stage, time_ms)
    broadcast_status()
    return result


@app.get("/api/calibrate/poses")
def get_poses():
    return robot.get_pose_list()


@app.post("/api/calibrate/save")
def save_pose(data: dict):
    name = data.get("name", "").strip()
    pwms = data.get("pwms", [])
    time_ms = data.get("time", 1500)
    if not name or len(pwms) != 6:
        return {"success": False, "error": "名称或PWM值无效"}
    ok = robot.save_pose(name, pwms, time_ms)
    return {"success": ok, "name": name}


@app.get("/api/calibrate/delete/{pose_name}")
def delete_pose(pose_name: str):
    if pose_name in PRESET_POSES:
        del PRESET_POSES[pose_name]
        from config import save_custom_pose
        # 从文件也删除
        import config
        poses = config.load_custom_poses()
        if pose_name in poses:
            del poses[pose_name]
            config.POSES_FILE.write_text(
                json.dumps(poses, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"success": True}
    return {"success": False, "error": "姿势不存在"}


# ---- 语音 API ----

@app.get("/api/voice/start")
def voice_start():
    """启动语音监听"""
    voice._robot = robot  # 运动时屏蔽识别
    voice.set_commands({
        "直立": lambda _: robot.execute_pose("直立"),
        "放平": lambda _: robot.execute_pose("放平"),
        "抓取": lambda _: robot.execute_sequence("抓取"),
        "搬运": lambda _: robot.execute_sequence("搬运"),
        "张开": lambda _: robot.gripper_open(),
        "闭合": lambda _: robot.gripper_close(),
    })
    voice.commands.update({
        "\u53f3\u8f6c\u79fb": lambda _: robot.execute_sequence("\u53f3\u8f6c\u79fb"),
        "\u5de6\u8f6c\u79fb": lambda _: robot.execute_sequence("\u5de6\u8f6c\u79fb"),
    })
    voice.set_commands(voice.commands)
    if not voice.status().get("loaded"):
        if not voice.load():
            return {"success": False, "error": "voice model not loaded"}
    ok = voice.start()
    if ok:
        _start_voice_timeout_worker()
    return {"success": ok, "running": voice.status()["running"], "device": voice.status()["device"]}


@app.get("/api/voice/stop")
def voice_stop():
    voice.stop()
    return {"success": True, "running": voice.status()["running"]}



@app.get("/api/voice/level")
def voice_level():
    """Read a tiny slice from M260C for UI level display only."""
    try:
        import alsaaudio
        import numpy as np
        device = voice_input_device()
        pcm = alsaaudio.PCM(
            alsaaudio.PCM_CAPTURE,
            alsaaudio.PCM_NORMAL,
            device,
            channels=1,
            rate=16000,
            format=alsaaudio.PCM_FORMAT_S16_LE,
            periodsize=320,
        )
        chunks = []
        for _ in range(5):
            length, data = pcm.read()
            if length > 0 and data:
                chunks.append(data)
        raw = b"".join(chunks)
        if not raw:
            return {"success": False, "peak": 0.0, "rms": 0.0, "error": "no audio"}
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        raw_peak = float(np.max(np.abs(samples)) / 32768.0) if samples.size else 0.0
        raw_rms = float(np.sqrt(np.mean(samples * samples)) / 32768.0) if samples.size else 0.0
        gain = float(os.getenv("VOICE_LEVEL_GAIN", "3.0"))
        boosted = np.clip(samples * gain, -32768.0, 32767.0)
        peak = float(np.max(np.abs(boosted)) / 32768.0) if boosted.size else 0.0
        rms = float(np.sqrt(np.mean(boosted * boosted)) / 32768.0) if boosted.size else 0.0
        return {
            "success": True,
            "peak": peak,
            "rms": rms,
            "raw_peak": raw_peak,
            "raw_rms": raw_rms,
            "gain": gain,
            "device": device,
            "output_device": audio_output_device(),
        }
    except Exception as exc:
        return {"success": False, "peak": 0.0, "rms": 0.0, "error": str(exc)}

@app.get("/api/voice/poll")
def voice_poll():
    cmd = voice.get_command(timeout=0)
    return {"command": cmd}


# ---- WebSocket ----

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
            elif data == "status":
                await websocket.send_text(json.dumps(robot.status()))
    except WebSocketDisconnect:
        ws_clients.remove(websocket)


def broadcast_status():
    """向所有WebSocket客户端推送状态"""
    status = json.dumps(robot.status())
    for ws in ws_clients[:]:
        try:
            import asyncio
            asyncio.create_task(ws.send_text(status))
        except Exception:
            if ws in ws_clients:
                ws_clients.remove(ws)


# ---- 前端页面 ----

FRONTEND_DIR = Path(__file__).parent / "frontend"


def _read_page(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index():
    return _read_page("button.html")


@app.get("/button", response_class=HTMLResponse)
def button_page():
    return _read_page("button.html")


@app.get("/voice", response_class=HTMLResponse)
def voice_page():
    return _read_page("voice.html")


@app.get("/calibrate", response_class=HTMLResponse)
def calibrate_page():
    return (FRONTEND_DIR / "calibrate.html").read_text(encoding="utf-8")


# ---- 启动 ----

def start():
    print("=" * 50)
    print("KM1 机械臂控制台 v2.0")
    print("=" * 50)

    # 连接串口后自动恢复直立，避免断电重启后停在搬运/分拣末姿态。
    if ser.connect():
        time.sleep(0.3)
        upright = robot.execute_pose("直立")
        print(f"[机械臂] 上电直立: {'成功' if upright else '失败'}")

    # 启动Web服务
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, log_level="warning", access_log=False)


if __name__ == "__main__":
    start()

