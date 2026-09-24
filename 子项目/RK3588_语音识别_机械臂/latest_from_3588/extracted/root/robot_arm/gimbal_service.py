from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

import serial


DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00"


class GimbalService:
    def __init__(
        self,
        *,
        state_path: Path | str = "/tmp/aibox_gimbal_position.json",
        serial_factory: Callable[..., serial.Serial] = serial.Serial,
        initial_yaw: int = 1500,
        initial_pitch: int = 1500,
        port: str = DEFAULT_PORT,
    ) -> None:
        self.state_path = Path(state_path)
        self.serial_factory = serial_factory
        self.port = port
        self.yaw, self.pitch = self._load(initial_yaw, initial_pitch)

    @property
    def position(self) -> tuple[int, int]:
        return self.yaw, self.pitch

    def _load(self, yaw: int, pitch: int) -> tuple[int, int]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return int(data["yaw"]), int(data["pitch"])
        except (OSError, ValueError, KeyError, TypeError):
            return yaw, pitch

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"yaw": self.yaw, "pitch": self.pitch}), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def move(self, axis: str, direction: int, *, step_pwm: int = 40, time_ms: int = 350) -> tuple[bool, str]:
        if axis not in ("yaw", "pitch") or direction not in (-1, 1):
            return False, "invalid gimbal direction"
        current = self.yaw if axis == "yaw" else self.pitch
        target = max(500, min(2500, current + direction * max(1, min(500, int(step_pwm)))))
        servo_id = 1 if axis == "yaw" else 2
        try:
            ser = self.serial_factory(self.port, 115200, timeout=0.05)
            try:
                command = f"#{servo_id:03d}P{target:04d}T{max(1, int(time_ms)):04d}!\r\n".encode("ascii")
                ser.reset_input_buffer()
                ser.write(command)
                ser.flush()
                expected = f"ACK id={servo_id} pulse={target}".encode("ascii")
                deadline = time.monotonic() + 0.6
                response = b""
                while time.monotonic() < deadline:
                    response += ser.read(128)
                    if expected in response:
                        if axis == "yaw":
                            self.yaw = target
                        else:
                            self.pitch = target
                        self._save()
                        return True, f"{axis}={target}"
                    time.sleep(0.01)
                return False, "gimbal ACK timeout"
            finally:
                ser.close()
        except Exception as exc:
            return False, str(exc)
