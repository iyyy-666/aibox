from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class StereoMatch:
    matched: bool
    score: float = 0.0
    right_box: Box | None = None


@dataclass(frozen=True)
class Roi:
    x1: int
    y1: int
    x2: int
    y2: int

    def contains_center(self, box: tuple[int, int, int, int]) -> bool:
        x1, y1, x2, y2 = normalize_box(box)
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        return self.x1 <= cx <= self.x2 and self.y1 <= cy <= self.y2


def normalize_box(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    if x2 < x1 or y2 < y1:
        return x1, y1, x1 + max(0, x2), y1 + max(0, y2)
    return x1, y1, x2, y2


def split_stereo(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return equal-sized left and right eyes from a side-by-side BGR frame."""
    if frame.ndim != 3 or frame.shape[1] < 2:
        raise ValueError("expected a side-by-side stereo frame")
    eye_width = frame.shape[1] // 2
    return frame[:, :eye_width].copy(), frame[:, eye_width : eye_width * 2].copy()


def match_stereo_candidate(
    left_box: Box,
    right_boxes: list[Box],
    image_shape: tuple[int, ...],
) -> StereoMatch:
    """Select the geometrically most plausible right-eye match for a left box."""
    height, width = image_shape[:2]
    lx, ly, lw, lh = left_box
    left_area = max(1, lw * lh)
    left_center_y = ly + lh / 2.0
    best = StereoMatch(False)

    for right_box in right_boxes:
        rx, ry, rw, rh = right_box
        right_area = max(1, rw * rh)
        vertical_delta = abs((ry + rh / 2.0) - left_center_y) / max(1.0, height)
        area_ratio = right_area / left_area
        disparity = abs((lx + lw / 2.0) - (rx + rw / 2.0)) / max(1.0, width)
        if vertical_delta > 0.13 or not 0.45 <= area_ratio <= 2.2 or disparity > 0.45:
            continue
        score = max(0.0, 1.0 - (vertical_delta / 0.13 + abs(1.0 - area_ratio) + disparity) / 3.0)
        if not best.matched or score > best.score:
            best = StereoMatch(True, score, right_box)
    return best


def _box_iou(first: Box, second: Box) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


class BoxTracker:
    def __init__(self, iou_threshold: float = 0.3, hold_misses: int = 3) -> None:
        self.iou_threshold = iou_threshold
        self.hold_misses = hold_misses
        self.box: Box | None = None
        self.misses = 0

    def update(self, box: Box | None) -> bool:
        if box is not None and (self.box is None or _box_iou(self.box, box) >= self.iou_threshold):
            self.box = box
            self.misses = 0
            return True
        if self.box is None:
            return False
        self.misses += 1
        if self.misses > self.hold_misses:
            self.box = None
            return False
        return box is None


class TemporalGestureVote:
    def __init__(self, confirm_hits: int = 4, hold_misses: int = 3) -> None:
        self.confirm_hits = confirm_hits
        self.hold_misses = hold_misses
        self._candidate: str | None = None
        self._hits = 0
        self._misses = 0
        self.confirmed: str | None = None

    def update(self, label: str | None, *, eligible: bool) -> str | None:
        if eligible and label is not None:
            self._misses = 0
            if label == self._candidate:
                self._hits += 1
            else:
                self._candidate = label
                self._hits = 1
            if self._hits >= self.confirm_hits:
                self.confirmed = label
            return self.confirmed

        self._candidate = None
        self._hits = 0
        if self.confirmed is None:
            return None
        self._misses += 1
        if self._misses > self.hold_misses:
            self.confirmed = None
        return self.confirmed


def target_roi(image: np.ndarray, *, margin_x: float = 0.13, margin_y: float = 0.10) -> Roi:
    h, w = image.shape[:2]
    mx = int(w * margin_x)
    my = int(h * margin_y)
    return Roi(mx, my, max(mx + 1, w - mx), max(my + 1, h - my))


def box_is_target(
    image: np.ndarray,
    box: tuple[int, int, int, int],
    *,
    min_area: float,
    max_area_ratio: float = 0.55,
    min_side: int = 32,
    min_aspect: float = 0.18,
    max_aspect: float = 5.8,
    roi_margin_x: float = 0.13,
    roi_margin_y: float = 0.10,
) -> bool:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = normalize_box(box)
    bw = max(0, x2 - x1)
    bh = max(0, y2 - y1)
    area = bw * bh
    if bw < min_side or bh < min_side:
        return False
    if area < min_area or area > w * h * max_area_ratio:
        return False
    aspect = bw / max(float(bh), 1.0)
    if aspect < min_aspect or aspect > max_aspect:
        return False
    return target_roi(image, margin_x=roi_margin_x, margin_y=roi_margin_y).contains_center((x1, y1, x2, y2))


def stable_filter(
    previous: dict[str, int],
    detections,
    *,
    label_fn,
    box_fn,
    image_shape: tuple[int, ...],
    stable_hits: int = 2,
) -> tuple[list, dict[str, int]]:
    h, w = image_shape[:2]
    current: dict[str, int] = {}
    signatures: list[tuple[object, str]] = []
    for det in detections:
        x1, y1, x2, y2 = normalize_box(box_fn(det))
        cx = round(((x1 + x2) / 2.0) / max(1, w) * 8)
        cy = round(((y1 + y2) / 2.0) / max(1, h) * 6)
        size = round(max(x2 - x1, y2 - y1) / max(1, w) * 10)
        sig = f"{label_fn(det)}:{cx}:{cy}:{size}"
        current[sig] = min(stable_hits + 1, previous.get(sig, 0) + 1)
        signatures.append((det, sig))
    stable = [det for det, sig in signatures if current.get(sig, 0) >= stable_hits]
    return stable, current


def draw_target_roi(image: np.ndarray, *, margin_x: float = 0.13, margin_y: float = 0.10) -> None:
    roi = target_roi(image, margin_x=margin_x, margin_y=margin_y)
    cv2.rectangle(image, (roi.x1, roi.y1), (roi.x2, roi.y2), (92, 104, 116), 1)
