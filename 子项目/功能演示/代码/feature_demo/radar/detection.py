from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
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


@dataclass(slots=True)
class _FlowEdge:
    target: int
    reverse: int
    capacity: int
    cost: float


class BaselineComparator:
    def __init__(
        self,
        region: DetectionRegion,
        *,
        change_distance_mm: float,
        change_ratio: float,
        angle_match_tolerance_deg: float = 2.0,
    ) -> None:
        if change_distance_mm <= 0 or not 0 < change_ratio <= 1:
            raise ValueError("change thresholds must be positive")
        angle_match_tolerance_deg = float(angle_match_tolerance_deg)
        if not isfinite(angle_match_tolerance_deg) or not (
            0 <= angle_match_tolerance_deg <= 180
        ):
            raise ValueError("angle match tolerance must be between 0 and 180 degrees")
        self.region = region
        self.change_distance_mm = float(change_distance_mm)
        self.change_ratio_threshold = float(change_ratio)
        self.angle_match_tolerance_deg = angle_match_tolerance_deg
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
        matches = self._minimum_cost_maximum_matching(current)
        if not matches:
            return DetectionResult(False, False, 0.0, 0, 0)
        changed = 0
        for baseline_key, current_key in matches:
            baseline_distance = self._baseline[baseline_key]
            if abs(current[current_key] - baseline_distance) >= max(
                self.change_distance_mm,
                baseline_distance * self.change_ratio_threshold,
            ):
                changed += 1
        compared = len(matches)
        ratio = changed / compared
        return DetectionResult(True, ratio >= self.change_ratio_threshold, ratio, changed, compared)

    @staticmethod
    def _key(angle: float) -> int:
        return round((angle % 360.0) * 2)

    @staticmethod
    def _key_distance(first: int, second: int) -> float:
        difference = abs(first - second) / 2.0
        return min(difference, 360.0 - difference)

    def _minimum_cost_maximum_matching(
        self,
        current: dict[int, float],
    ) -> list[tuple[int, int]]:
        baseline_keys = sorted(self._baseline)
        current_keys = sorted(current)
        baseline_start = 1
        current_start = baseline_start + len(baseline_keys)
        sink = current_start + len(current_keys)
        graph: list[list[_FlowEdge]] = [[] for _ in range(sink + 1)]

        def add_edge(source: int, target: int, capacity: int, cost: float) -> None:
            forward = _FlowEdge(target, len(graph[target]), capacity, cost)
            reverse = _FlowEdge(source, len(graph[source]), 0, -cost)
            graph[source].append(forward)
            graph[target].append(reverse)

        for baseline_index, baseline_key in enumerate(baseline_keys):
            baseline_node = baseline_start + baseline_index
            add_edge(0, baseline_node, 1, 0.0)
            neighbors = []
            for current_index, current_key in enumerate(current_keys):
                distance = self._key_distance(baseline_key, current_key)
                if distance <= self.angle_match_tolerance_deg:
                    neighbors.append((distance, current_index))
            neighbors.sort(
                key=lambda neighbor: (neighbor[0], current_keys[neighbor[1]]),
            )
            for distance, current_index in neighbors:
                add_edge(baseline_node, current_start + current_index, 1, distance)
        for current_index in range(len(current_keys)):
            add_edge(current_start + current_index, sink, 1, 0.0)

        while True:
            distances = [float("inf")] * len(graph)
            previous: list[tuple[int, int] | None] = [None] * len(graph)
            distances[0] = 0.0
            for _ in range(len(graph) - 1):
                updated = False
                for node, edges in enumerate(graph):
                    if not isfinite(distances[node]):
                        continue
                    for edge_index, edge in enumerate(edges):
                        candidate = distances[node] + edge.cost
                        if edge.capacity and candidate < distances[edge.target]:
                            distances[edge.target] = candidate
                            previous[edge.target] = (node, edge_index)
                            updated = True
                if not updated:
                    break
            if previous[sink] is None:
                break
            node = sink
            while node != 0:
                source, edge_index = previous[node]
                edge = graph[source][edge_index]
                edge.capacity -= 1
                graph[node][edge.reverse].capacity += 1
                node = source

        matches: list[tuple[int, int]] = []
        for baseline_index, baseline_key in enumerate(baseline_keys):
            baseline_node = baseline_start + baseline_index
            for edge in graph[baseline_node]:
                if current_start <= edge.target < sink and edge.capacity == 0:
                    matches.append((baseline_key, current_keys[edge.target - current_start]))
        return matches


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
