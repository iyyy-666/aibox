#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


DEVICE = "/dev/esp32_arm"
UPRIGHT_PWMS = (1432, 1500, 1500, 1500, 1500, 1241)
PWM_MIN = 800
PWM_MAX = 2200
STATE_FILE = Path("/root/robot_arm/last_servo_pwms.json")
MARKER_FILE = Path("/var/lib/aibox-arm/prepower-state.json")


def build_group_command(pwms: list[int] | tuple[int, ...], time_ms: int) -> str:
    if len(pwms) != 6:
        raise ValueError("必须提供 6 路舵机 PWM")
    if not 100 <= int(time_ms) <= 5000:
        raise ValueError("动作时间必须在 100 至 5000 毫秒之间")
    values = [int(value) for value in pwms]
    if any(value < PWM_MIN or value > PWM_MAX for value in values):
        raise ValueError(f"PWM 必须在 {PWM_MIN} 至 {PWM_MAX} 之间")
    body = "".join(
        f"#{servo_id:03d}P{pwm:04d}T{int(time_ms):04d}!"
        for servo_id, pwm in enumerate(values)
    )
    return f"{{G0000{body}}}\r\n"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def preload(device: str, *, wait_seconds: float = 20.0) -> None:
    import serial

    deadline = time.monotonic() + max(0.0, wait_seconds)
    while not Path(device).exists():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"机械臂控制串口不存在：{device}")
        time.sleep(0.25)

    connection = serial.Serial(
        port=None,
        baudrate=115200,
        timeout=0.2,
        write_timeout=1.0,
        dsrdtr=False,
        rtscts=False,
        exclusive=True,
    )
    connection.dtr = False
    connection.rts = False
    connection.port = device
    try:
        connection.open()
        connection.reset_input_buffer()
        connection.reset_output_buffer()
        command = build_group_command(UPRIGHT_PWMS, 1500)
        connection.write(command.encode("ascii"))
        connection.flush()
        time.sleep(0.2)
    finally:
        connection.close()

    now = time.time()
    _atomic_json(STATE_FILE, {"pwms": list(UPRIGHT_PWMS), "updated_at": now})
    _atomic_json(
        MARKER_FILE,
        {
            "status": "upright_preloaded",
            "device": device,
            "pwms": list(UPRIGHT_PWMS),
            "time_ms": 1500,
            "updated_at": now,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="机械臂舵机上电前预置直立姿态")
    parser.add_argument("--device", default=DEVICE)
    parser.add_argument("--wait-seconds", type=float, default=20.0)
    arguments = parser.parse_args()
    preload(arguments.device, wait_seconds=arguments.wait_seconds)
    print("机械臂直立 PWM 已预装载，串口已释放。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
