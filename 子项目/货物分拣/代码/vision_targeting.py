from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


def split_stereo(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split a side-by-side stereo frame into equal left and right views."""
    if frame.ndim != 3 or frame.shape[1] < 2:
        raise ValueError("expected a side-by-side stereo frame")
    width = frame.shape[1] // 2
    return frame[:, :width].copy(), frame[:, width:width * 2].copy()


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
