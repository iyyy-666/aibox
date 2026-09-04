from __future__ import annotations

from dataclasses import dataclass


Box = tuple[int, int, int, int]


def _center(box: Box) -> tuple[float, float]:
    x, y, width, height = box
    return x + width / 2.0, y + height / 2.0


def _iou(first: Box, second: Box) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


@dataclass(frozen=True)
class TrackingConfig:
    deadband_ratio: float = 0.07
    smoothing_alpha: float = 0.35
    control_interval_sec: float = 0.10
    lost_timeout_sec: float = 0.50
    max_degrees_per_second: float = 20.0
    pwm_per_degree: float = 11.11
    min_step_pwm: int = 4
    max_step_pwm: int = 22
    pwm_min: int = 500
    pwm_max: int = 2500
    yaw_sign: int = 1
    pitch_sign: int = 1


@dataclass(frozen=True)
class TrackingDecision:
    yaw_delta_pwm: int = 0
    pitch_delta_pwm: int = 0
    state: str = "idle"
    offset_x: float = 0.0
    offset_y: float = 0.0


class PalmTargetLock:
    def __init__(self, iou_threshold: float = 0.15) -> None:
        self.iou_threshold = iou_threshold
        self.box: Box | None = None

    def arm(self, boxes: list[Box], image_size: tuple[int, int]) -> Box | None:
        if not boxes:
            self.box = None
            return None
        image_width, image_height = image_size
        target_x, target_y = image_width / 2.0, image_height / 2.0
        self.box = min(boxes, key=lambda box: (_center(box)[0] - target_x) ** 2 + (_center(box)[1] - target_y) ** 2)
        return self.box

    def update(self, boxes: list[Box]) -> Box | None:
        if self.box is None:
            return None
        matched = [box for box in boxes if _iou(self.box, box) >= self.iou_threshold]
        if not matched:
            return None
        self.box = max(matched, key=lambda box: _iou(self.box or box, box))
        return self.box

    def clear(self) -> None:
        self.box = None


class PalmTrackingController:
    def __init__(self, config: TrackingConfig | None = None) -> None:
        self.config = config or TrackingConfig()
        self.active = False
        self._last_seen_at: float | None = None
        self._last_command_at: float | None = None
        self._smooth_x = 0.0
        self._smooth_y = 0.0
        self.yaw_sign = self.config.yaw_sign
        self.pitch_sign = self.config.pitch_sign
        self._feedback_x: tuple[float, int] | None = None
        self._feedback_y: tuple[float, int] | None = None

    def start(self, box: Box, now: float) -> None:
        self.active = True
        self._last_seen_at = now
        self._last_command_at = now
        self._smooth_x = 0.0
        self._smooth_y = 0.0
        self._feedback_x = None
        self._feedback_y = None

    def stop(self) -> None:
        self.active = False
        self._last_seen_at = None
        self._last_command_at = None
        self._smooth_x = 0.0
        self._smooth_y = 0.0

    def update(self, box: Box | None, image_size: tuple[int, int], now: float) -> TrackingDecision:
        if not self.active:
            return TrackingDecision()
        if box is None:
            if self._last_seen_at is not None and now - self._last_seen_at >= self.config.lost_timeout_sec:
                return TrackingDecision(state="lost")
            return TrackingDecision(state="waiting")

        self._last_seen_at = now
        width, height = image_size
        center_x, center_y = _center(box)
        offset_x = (center_x - width / 2.0) / max(1.0, width / 2.0)
        offset_y = (center_y - height / 2.0) / max(1.0, height / 2.0)
        alpha = min(1.0, max(0.0, self.config.smoothing_alpha))
        self._smooth_x = alpha * offset_x + (1.0 - alpha) * self._smooth_x
        self._smooth_y = alpha * offset_y + (1.0 - alpha) * self._smooth_y

        last_command_at = self._last_command_at if self._last_command_at is not None else now
        elapsed = max(0.0, now - last_command_at)
        if elapsed < self.config.control_interval_sec:
            return TrackingDecision(state="waiting", offset_x=self._smooth_x, offset_y=self._smooth_y)

        yaw = self._axis_delta(self._smooth_x, elapsed, self.yaw_sign)
        pitch = self._axis_delta(self._smooth_y, elapsed, self.pitch_sign)
        self._last_command_at = now
        if yaw == 0 and pitch == 0:
            return TrackingDecision(state="centered", offset_x=self._smooth_x, offset_y=self._smooth_y)
        if yaw:
            self._feedback_x = (self._smooth_x, yaw)
        if pitch:
            self._feedback_y = (self._smooth_y, pitch)
        return TrackingDecision(yaw, pitch, "tracking", self._smooth_x, self._smooth_y)

    def observe_feedback(self, *, offset_x: float, offset_y: float) -> tuple[bool, bool]:
        yaw_reversed = self._feedback_x is not None and abs(offset_x) > abs(self._feedback_x[0]) + 0.04
        pitch_reversed = self._feedback_y is not None and abs(offset_y) > abs(self._feedback_y[0]) + 0.04
        if yaw_reversed:
            self.yaw_sign *= -1
        if pitch_reversed:
            self.pitch_sign *= -1
        self._feedback_x = None
        self._feedback_y = None
        return yaw_reversed, pitch_reversed

    def _axis_delta(self, offset: float, elapsed: float, sign: int) -> int:
        if abs(offset) <= self.config.deadband_ratio:
            return 0
        proportional = round(abs(offset) * self.config.max_step_pwm)
        step = max(self.config.min_step_pwm, proportional)
        permitted = int(self.config.max_degrees_per_second * self.config.pwm_per_degree * elapsed)
        limit = min(self.config.max_step_pwm, max(0, permitted))
        step = min(step, limit)
        if step == 0:
            return 0
        return step * (1 if offset > 0 else -1) * (1 if sign >= 0 else -1)
