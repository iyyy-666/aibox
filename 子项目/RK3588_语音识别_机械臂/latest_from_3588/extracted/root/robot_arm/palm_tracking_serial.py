from __future__ import annotations

import json
import os
import time
from typing import Callable

import serial


POSITION_STATE = os.getenv("AIBOX_GIMBAL_POSITION_STATE", "/tmp/aibox_gimbal_position.json")


class SerialGimbalClient:
    def __init__(
        self,
        *,
        port: str,
        baud: int,
        yaw_id: int,
        pitch_id: int,
        pwm_min: int,
        pwm_max: int,
        initial_pwm: int = 1500,
        serial_factory: Callable[..., serial.Serial] = serial.Serial,
    ) -> None:
        self.port = port
        self.baud = baud
        self.yaw_id = yaw_id
        self.pitch_id = pitch_id
        self.pwm_min = pwm_min
        self.pwm_max = pwm_max
        self.yaw_pwm = initial_pwm
        self.pitch_pwm = initial_pwm
        self.last_error = ""
        self._serial_factory = serial_factory
        self._serial: serial.Serial | None = None

    def connect(self) -> tuple[bool, str]:
        if self._serial is not None and self._serial.is_open:
            return True, self.port
        try:
            self._serial = self._serial_factory(self.port, self.baud, timeout=0.05)
            return True, self.port
        except Exception as exc:
            self._serial = None
            self.last_error = str(exc)
            return False, self.last_error

    def disconnect(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def move(self, yaw_delta_pwm: int, pitch_delta_pwm: int, time_ms: int = 100) -> tuple[bool, str]:
        targets: list[tuple[int, int]] = []
        if yaw_delta_pwm:
            targets.append((self.yaw_id, self._clamp(self.yaw_pwm + yaw_delta_pwm)))
        if pitch_delta_pwm:
            targets.append((self.pitch_id, self._clamp(self.pitch_pwm + pitch_delta_pwm)))
        if not targets:
            return True, "no movement requested"

        ok, detail = self.connect()
        if not ok:
            return False, detail
        try:
            assert self._serial is not None
            for servo_id, pulse in targets:
                self._serial.write(self._frame(servo_id, pulse, time_ms))
                self._serial.flush()
                if not self._await_ack(servo_id, pulse):
                    raise TimeoutError(f"missing or mismatched gimbal ACK for id={servo_id}")
        except Exception as exc:
            self.last_error = str(exc)
            self.disconnect()
            return False, self.last_error

        for servo_id, pulse in targets:
            if servo_id == self.yaw_id:
                self.yaw_pwm = pulse
            else:
                self.pitch_pwm = pulse
        self._save_position()
        self.last_error = ""
        return True, self.port

    def _save_position(self) -> None:
        try:
            tmp = f"{POSITION_STATE}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"yaw": self.yaw_pwm, "pitch": self.pitch_pwm}, fh)
            os.replace(tmp, POSITION_STATE)
        except OSError:
            pass

    def _await_ack(self, servo_id: int, pulse: int) -> bool:
        assert self._serial is not None
        expected = f"ACK id={servo_id} pulse={pulse}"
        received = ""
        deadline = time.monotonic() + 0.45
        while time.monotonic() < deadline:
            chunk = self._serial.read(128)
            if not chunk:
                time.sleep(0.01)
                continue
            received += chunk.decode("ascii", errors="ignore")
            if expected in received:
                return True
        return False

    def _clamp(self, pulse: int) -> int:
        return max(self.pwm_min, min(self.pwm_max, int(pulse)))

    @staticmethod
    def _frame(servo_id: int, pulse: int, time_ms: int) -> bytes:
        return f"#{servo_id:03d}P{pulse:04d}T{max(1, int(time_ms)):04d}!\r\n".encode("ascii")
