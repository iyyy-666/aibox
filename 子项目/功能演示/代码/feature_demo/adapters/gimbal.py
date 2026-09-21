from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Protocol


class UnsupportedCommand(ValueError):
    pass


class GimbalServiceProtocol(Protocol):
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


def _load_existing_service() -> GimbalServiceProtocol:
    legacy_root = Path(os.getenv("AIBOX_LEGACY_ROOT", "/root/robot_arm"))
    if str(legacy_root) not in sys.path:
        sys.path.insert(0, str(legacy_root))
    from gimbal_service import GimbalService

    return GimbalService()


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

    def close(self) -> None:
        if self._service is None:
            return
        close = getattr(self._service, "close", None)
        if callable(close):
            close()
        self._service = None
