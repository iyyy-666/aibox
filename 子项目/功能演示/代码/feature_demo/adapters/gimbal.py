from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Protocol


class UnsupportedCommand(ValueError):
    pass


class GimbalServiceProtocol(Protocol):
    @property
    def position(self) -> tuple[int, int]: ...

    def move(
        self,
        axis: str,
        direction: int,
        *,
        step_pwm: int,
        time_ms: int,
    ) -> tuple[bool, str]: ...


DIRECTION_MAP = {
    "up": ("pitch", -1),
    "down": ("pitch", 1),
    "left": ("yaw", -1),
    "right": ("yaw", 1),
}

PITCH_MIN = 500
PITCH_MAX = 2500


def _load_existing_service() -> GimbalServiceProtocol:
    legacy_root = Path(os.getenv("AIBOX_LEGACY_ROOT", "/root/robot_arm"))
    if str(legacy_root) not in sys.path:
        sys.path.insert(0, str(legacy_root))
    from gimbal_service import GimbalService

    state_path = os.getenv(
        "AIBOX_GIMBAL_POSITION_STATE", "/tmp/aibox_gimbal_position.json"
    )
    return GimbalService(state_path=state_path)


class GimbalAdapter:
    def __init__(self, *, service: GimbalServiceProtocol | None = None) -> None:
        self._service = service

    def step(self, direction: str, amount: int) -> dict:
        try:
            axis, sign = DIRECTION_MAP[direction]
        except KeyError as exc:
            raise UnsupportedCommand(f"不支持的云台方向：{direction}") from exc
        step_pwm = max(1, min(500, int(amount)))
        if self._service is None:
            self._service = _load_existing_service()
        if axis == "pitch":
            pitch = int(self._service.position[1])
            if sign < 0 and pitch <= PITCH_MIN:
                return {
                    "ok": False,
                    "direction": direction,
                    "amount": step_pwm,
                    "message": "云台已到上限。",
                }
            if sign > 0 and pitch >= PITCH_MAX:
                return {
                    "ok": False,
                    "direction": direction,
                    "amount": step_pwm,
                    "message": "云台已到下限。",
                }
        ok, detail = self._service.move(
            axis,
            sign,
            step_pwm=step_pwm,
            time_ms=350,
        )
        return {
            "ok": ok,
            "direction": direction,
            "amount": step_pwm,
            "message": "云台已步进。" if ok else f"云台通信失败：{detail}",
        }

    def move_to(self, yaw: int, pitch: int) -> dict:
        targets = (int(yaw), int(pitch))
        if any(target < 500 or target > 2500 for target in targets):
            return {"ok": False, "message": "云台目标位置超出安全范围。"}
        if self._service is None:
            self._service = _load_existing_service()
        for index, (axis, target) in enumerate(zip(("yaw", "pitch"), targets)):
            while True:
                current = int(self._service.position[index])
                if current == target:
                    break
                direction = 1 if target > current else -1
                step_pwm = min(150, abs(target - current))
                ok, detail = self._service.move(
                    axis,
                    direction,
                    step_pwm=step_pwm,
                    time_ms=650,
                )
                if not ok:
                    return {"ok": False, "message": f"云台通信失败：{detail}"}
                if int(self._service.position[index]) == current:
                    return {"ok": False, "message": "云台位置未更新。"}
        return {
            "ok": True,
            "yaw": targets[0],
            "pitch": targets[1],
            "message": "云台已到达物体分拣位置。",
        }

    def close(self) -> None:
        if self._service is None:
            return
        close = getattr(self._service, "close", None)
        if callable(close):
            close()
        self._service = None
