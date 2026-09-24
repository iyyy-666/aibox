from __future__ import annotations

import json
import os
import time

import serial


PORT = os.getenv("SORTING_GIMBAL_PORT", "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00")
STATE_FILE = os.getenv("AIBOX_GIMBAL_POSITION_STATE", "/tmp/aibox_gimbal_position.json")
TARGET_YAW = int(os.getenv("SORTING_GIMBAL_YAW", "1170"))
TARGET_PITCH = int(os.getenv("SORTING_GIMBAL_PITCH", "1110"))
STEP_PWM = int(os.getenv("SORTING_GIMBAL_STEP_PWM", "20"))
MOVE_TIME_MS = int(os.getenv("SORTING_GIMBAL_MOVE_TIME_MS", "350"))


class SortingGimbal:
    def __init__(self) -> None:
        self.yaw, self.pitch = self._load_position()

    def _load_position(self) -> tuple[int, int]:
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            return int(data.get("yaw", 1500)), int(data.get("pitch", 1500))
        except (OSError, ValueError, TypeError):
            return 1500, 1500

    def _save_position(self) -> None:
        try:
            tmp = f"{STATE_FILE}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"yaw": self.yaw, "pitch": self.pitch}, fh)
            os.replace(tmp, STATE_FILE)
        except OSError:
            pass

    @staticmethod
    def _frame(servo_id: int, pulse: int) -> bytes:
        return f"#{servo_id:03d}P{pulse:04d}T{MOVE_TIME_MS:04d}!\r\n".encode("ascii")

    def _send(self, ser: serial.Serial, servo_id: int, pulse: int) -> None:
        ser.reset_input_buffer()
        ser.write(self._frame(servo_id, pulse))
        ser.flush()
        expected = f"ACK id={servo_id} pulse={pulse}"
        deadline = time.monotonic() + 0.6
        received = b""
        while time.monotonic() < deadline:
            chunk = ser.read(128)
            if chunk:
                received += chunk
                if expected.encode("ascii") in received:
                    return
            else:
                time.sleep(0.01)
        raise TimeoutError(f"云台未确认 ID={servo_id} PWM={pulse}")

    def move_to_target(self, progress=None) -> tuple[bool, str]:
        try:
            with serial.Serial(PORT, 115200, timeout=0.05) as ser:
                for name, servo_id, current, target in (
                    ("水平", 1, self.yaw, TARGET_YAW),
                    ("俯仰", 2, self.pitch, TARGET_PITCH),
                ):
                    while current != target:
                        delta = max(-STEP_PWM, min(STEP_PWM, target - current))
                        current += delta
                        self._send(ser, servo_id, current)
                        if servo_id == 1:
                            self.yaw = current
                        else:
                            self.pitch = current
                        self._save_position()
                        if progress:
                            progress(f"云台归位：{name} {current}/{target}")
            return True, f"水平{self.yaw}，俯仰{self.pitch}"
        except Exception as exc:
            return False, str(exc)
