from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

from .protocol import ScanPoint


@dataclass(frozen=True, slots=True)
class DetectionRegion:
    min_angle_deg: float
    max_angle_deg: float
    min_distance_mm: float
    max_distance_mm: float

    def contains(self, point: ScanPoint) -> bool:
        angle = point.angle_deg % 360.0
        low = self.min_angle_deg % 360.0
        high = self.max_angle_deg % 360.0
        in_angle = low <= angle <= high if low <= high else angle >= low or angle <= high
        return in_angle and self.min_distance_mm <= point.distance_mm <= self.max_distance_mm

    def select(self, points: Iterable[ScanPoint]) -> tuple[ScanPoint, ...]:
        return tuple(point for point in points if self.contains(point))


@dataclass(frozen=True, slots=True)
class DetectionResult:
    data_valid: bool
    has_change: bool
    change_ratio: float
    changed_points: int
    compared_points: int


class BaselineComparator:
    def __init__(self, region: DetectionRegion, *, change_distance_mm: float, change_ratio: float) -> None:
        if change_distance_mm <= 0 or not 0 < change_ratio <= 1:
            raise ValueError("change thresholds must be positive")
        self.region = region
        self.change_distance_mm = float(change_distance_mm)
        self.change_ratio_threshold = float(change_ratio)
        self._baseline: dict[int, float] = {}

    @property
    def ready(self) -> bool:
        return bool(self._baseline)

    def build_baseline(self, frames: Iterable[Iterable[ScanPoint]]) -> None:
        values: dict[int, list[float]] = {}
        for frame in frames:
            for point in self.region.select(frame):
                values.setdefault(self._key(point.angle_deg), []).append(point.distance_mm)
        self._baseline = {key: median(distances) for key, distances in values.items() if distances}
        if not self._baseline:
            raise ValueError("no valid points were collected in the detection region")

    def compare(self, frame: Iterable[ScanPoint]) -> DetectionResult:
        if not self.ready:
            raise RuntimeError("radar baseline has not been established")
        current: dict[int, float] = {}
        for point in self.region.select(frame):
            current[self._key(point.angle_deg)] = point.distance_mm
        common_keys = self._baseline.keys() & current.keys()
        if not common_keys:
            return DetectionResult(False, False, 0.0, 0, 0)
        changed = 0
        for key in common_keys:
            baseline_distance = self._baseline[key]
            if abs(current[key] - baseline_distance) >= max(
                self.change_distance_mm,
                baseline_distance * self.change_ratio_threshold,
            ):
                changed += 1
        compared = len(common_keys)
        ratio = changed / compared
        return DetectionResult(True, ratio >= self.change_ratio_threshold, ratio, changed, compared)

    @staticmethod
    def _key(angle: float) -> int:
        return round((angle % 360.0) * 2)


class ConfirmationState:
    def __init__(self, *, required_frames: int) -> None:
        self.required_frames = max(1, int(required_frames))
        self.stable_value = False
        self._candidate = False
        self._count = 0

    @property
    def progress(self) -> int:
        return self._count

    def update(self, candidate: bool) -> bool:
        candidate = bool(candidate)
        if candidate != self._candidate:
            self._candidate = candidate
            self._count = 0
        self._count += 1
        if self._candidate != self.stable_value and self._count >= self.required_frames:
            self.stable_value = self._candidate
            self._count = 0
            return True
        return False
