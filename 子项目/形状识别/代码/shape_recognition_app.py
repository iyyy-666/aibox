#!/usr/bin/env python3
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
import tkinter as tk

import cv2
import numpy as np

from vision_targeting import draw_target_roi, split_stereo, target_roi
from gimbal_controls import GimbalControls

CAMERA_DEVICE = os.getenv("SHAPE_CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("SHAPE_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("SHAPE_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("SHAPE_CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("SHAPE_DISPLAY_INTERVAL_MS", "80"))
CAPTURE_INTERVAL_SEC = float(os.getenv("SHAPE_CAPTURE_INTERVAL_SEC", "0.025"))
DETECT_INTERVAL_SEC = float(os.getenv("SHAPE_DETECT_INTERVAL_SEC", "0.16"))
MIN_AREA = int(os.getenv("SHAPE_MIN_AREA", "700"))
MAX_RESULTS = int(os.getenv("SHAPE_MAX_RESULTS", "3"))
STABLE_HITS = int(os.getenv("SHAPE_STABLE_HITS", "2"))
STABLE_HOLD_MISSES = int(os.getenv("SHAPE_STABLE_HOLD_MISSES", "2"))
SNAPSHOT_DIR = Path(os.getenv("SHAPE_SNAPSHOT_DIR", "/root/robot_arm/assets/shape_snapshots"))

T_TITLE = "Shape Recognition"
T_OPENING = "Opening camera..."
T_WAIT = "Waiting for video"
T_RESULT = "Detection Results"
T_SAVE = "Save Snapshot"
T_EXIT = "Exit"
T_WAIT_DETECT = "Waiting for detection"
T_NO_SHAPE = "暂未识别到形状"
T_SAVED = "Saved"
T_NO_SAVE = "No frame available to save"
T_CAMERA_FAIL = "Failed to open camera"
T_READ_FAIL = "Camera read failed; retrying..."
T_OPENED = "Opened"
T_NORMAL_VIEW = "Standard View"
T_NAME = "Shape"
T_CENTER = "Position"
T_CONF = "Confidence"
T_AREA = "Area"

SHAPE_TRIANGLE = "Triangle"
SHAPE_SQUARE = "Square"
SHAPE_RECTANGLE = "Rectangle"
SHAPE_PARALLELOGRAM = "Parallelogram"
SHAPE_CIRCLE = "Circle"
SHAPE_ELLIPSE = "Ellipse"
SHAPE_PENTAGON = "Pentagon"
SHAPE_HEXAGON = "Hexagon"
SHAPE_STAR = "Star"
SHAPE_POLYGON = "Polygon"

SHAPE_NAMES_CN = {
    SHAPE_SQUARE: "正方形",
    SHAPE_PARALLELOGRAM: "斜平行四边形",
    SHAPE_CIRCLE: "圆形",
    SHAPE_STAR: "星形",
    SHAPE_RECTANGLE: "长方形",
    SHAPE_PENTAGON: "正五边形",
    SHAPE_TRIANGLE: "三角形",
}
DETECTABLE_SHAPES = frozenset(SHAPE_NAMES_CN)

COLORS = [
    (80, 220, 245),
    (75, 210, 120),
    (245, 170, 70),
    (170, 120, 245),
    (245, 120, 140),
    (120, 210, 255),
]

@dataclass
class ShapeDetection:
    name: str
    name_cn: str
    box: tuple[int, int, int, int]
    center: tuple[int, int]
    area: float
    confidence: float
    vertices: int
    contour: np.ndarray
    signature: str = ""

class ShapeRecognitionApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(T_TITLE)
        self.root.geometry("1180x720")
        self.root.minsize(960, 560)
        self.root.configure(bg="#111417")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status_text = tk.StringVar(value=T_OPENING)
        self.summary_text = tk.StringVar(value=T_WAIT)
        self.running = True
        self.cap: cv2.VideoCapture | None = None
        self.frame: np.ndarray | None = None
        self.frame_lock = threading.Lock()
        self.detections: list[ShapeDetection] = []
        self.detect_lock = threading.Lock()
        self.photo: tk.PhotoImage | None = None
        self.last_view: np.ndarray | None = None
        self.fps = 0.0
        self.det_fps = 0.0
        self.last_frame_time = 0.0
        self._stable_signatures: dict[str, int] = {}
        self._shape_tracks: dict[str, dict[str, object]] = {}
        self._last_raw_count = 0

        self._build_ui()
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._detect_loop, daemon=True).start()
        self._update_view()

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#1c2228", height=54)
        top.pack(side=tk.TOP, fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text=T_TITLE, bg="#1c2228", fg="#f5f7fa", font=("Microsoft YaHei", 16, "bold")).pack(side=tk.LEFT, padx=(16, 18))
        tk.Label(top, textvariable=self.status_text, bg="#1c2228", fg="#aeb8c5", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)

        body = tk.Frame(self.root, bg="#111417")
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, bg="#080a0d", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 8), pady=12)

        side = tk.Frame(body, bg="#181d22", width=300)
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        side.pack_propagate(False)
        tk.Label(side, text=T_RESULT, bg="#181d22", fg="#f1f5f9", font=("Microsoft YaHei", 13, "bold")).pack(anchor="w", padx=16, pady=(16, 10))
        self.result_box = tk.Text(side, height=18, bg="#0f1317", fg="#e8eef5", insertbackground="#e8eef5", relief=tk.FLAT, font=("Microsoft YaHei", 11), wrap=tk.WORD)
        self.result_box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        self.result_box.insert("1.0", T_WAIT_DETECT)
        self.result_box.configure(state=tk.DISABLED)
        self.gimbal_controls = GimbalControls(side, self.root, self._set_status)
        ttk.Button(side, text=T_SAVE, command=self.save_snapshot).pack(fill=tk.X, padx=16, pady=(4, 8))
        ttk.Button(side, text=T_EXIT, command=self.close).pack(fill=tk.X, padx=16, pady=(0, 14))
        tk.Label(side, textvariable=self.summary_text, bg="#181d22", fg="#9fb0c2", justify=tk.LEFT, font=("Consolas", 10)).pack(anchor="w", padx=16, pady=(0, 16))

    def _open_camera(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _capture_loop(self) -> None:
        retry_at = 0.0
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                if time.time() < retry_at:
                    time.sleep(0.2)
                    continue
                self.cap = self._open_camera()
                if not self.cap.isOpened():
                    self._set_status(f"{T_CAMERA_FAIL}: {CAMERA_DEVICE}")
                    retry_at = time.time() + 2.0
                    continue
                self._set_status(f"{T_OPENED} {CAMERA_DEVICE}  {CAMERA_WIDTH}x{CAMERA_HEIGHT}@{CAMERA_FPS}")
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self._set_status(T_READ_FAIL)
                self.cap.release()
                self.cap = None
                time.sleep(0.4)
                continue
            now = time.time()
            if self.last_frame_time:
                inst = 1.0 / max(0.001, now - self.last_frame_time)
                self.fps = self.fps * 0.85 + inst * 0.15 if self.fps else inst
            self.last_frame_time = now
            with self.frame_lock:
                self.frame = frame
            time.sleep(CAPTURE_INTERVAL_SEC)

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_text.set(text))

    def _normal_frame(self, frame: np.ndarray) -> np.ndarray:
        return split_stereo(frame)[0]

    def _detect_loop(self) -> None:
        while self.running:
            with self.frame_lock:
                frame = None if self.frame is None else self.frame.copy()
            if frame is not None:
                normal = self._normal_frame(frame)
                t0 = time.time()
                raw_detections = self._detect_shapes(normal)
                self._last_raw_count = len(raw_detections)
                detections = self._stabilize(raw_detections)
                dt = time.time() - t0
                if dt > 0:
                    inst = 1.0 / dt
                    self.det_fps = self.det_fps * 0.80 + inst * 0.20 if self.det_fps else inst
                with self.detect_lock:
                    self.detections = detections
            time.sleep(DETECT_INTERVAL_SEC)

    def _detect_shapes(self, image: np.ndarray) -> list[ShapeDetection]:
        roi_box = self._find_display_roi(image)
        x0, y0, x1, y1 = roi_box
        roi = image[y0:y1, x0:x1]
        if roi.size == 0:
            return []

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # Phone/paper screens usually have a bright background with dark or saturated shapes.
        dark = cv2.inRange(gray, 0, 178)
        saturated = cv2.inRange(hsv, np.array((0, 48, 38), dtype=np.uint8), np.array((180, 255, 255), dtype=np.uint8))
        mask = cv2.bitwise_or(dark, saturated)

        # Remove the outside border of the phone/paper ROI, otherwise it becomes a false rectangle.
        border = max(6, min(roi.shape[:2]) // 35)
        mask[:border, :] = 0
        mask[-border:, :] = 0
        mask[:, :border] = 0
        mask[:, -border:] = 0

        open_kernel = np.ones((3, 3), np.uint8)
        close_kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi_h, roi_w = roi.shape[:2]
        full_h, full_w = image.shape[:2]
        detections: list[ShapeDetection] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < max(MIN_AREA, roi_w * roi_h * 0.004) or area > roi_w * roi_h * 0.58:
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            if bw < 24 or bh < 24:
                continue
            if bw > roi_w * 0.92 or bh > roi_h * 0.92:
                continue
            edge_margin = max(2, min(roi_w, roi_h) // 100)
            if x <= edge_margin or y <= edge_margin or x + bw >= roi_w - edge_margin or y + bh >= roi_h - edge_margin:
                continue
            peri = cv2.arcLength(contour, True)
            if peri <= 0:
                continue
            approx = cv2.approxPolyDP(contour, 0.018 * peri, True)
            vertices = len(approx)
            circularity = 4.0 * np.pi * area / max(peri * peri, 1.0)
            extent = area / max(float(bw * bh), 1.0)
            aspect = bw / max(float(bh), 1.0)
            rotated_width, rotated_height = cv2.minAreaRect(contour)[1]
            rotated_aspect = max(rotated_width, rotated_height) / max(1.0, min(rotated_width, rotated_height))
            solidity = self._solidity(contour, area)
            if solidity < 0.32 or extent < 0.20:
                continue
            if vertices == 4 and area > roi_w * roi_h * 0.25 and solidity >= 0.94 and extent >= 0.82:
                contour_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
                cv2.drawContours(contour_mask, [contour], -1, 255, -1)
                mean_saturation = cv2.mean(hsv[:, :, 1], mask=contour_mask)[0]
                if mean_saturation < 22.0:
                    continue
            quad = self._quadrilateral_features(approx)
            side_ratio = quad.get("side_ratio")
            max_angle_cosine = quad.get("max_angle_cosine")
            enclosing_fill = self._enclosing_circle_fill(contour, area)
            ellipse_ratio = self._ellipse_ratio(contour)
            radial_variation = self._radial_variation(contour)
            side_cv, angle_mean, angle_std = self._polygon_regularity(approx)
            name, conf = self._classify_shape(
                vertices,
                circularity,
                aspect,
                extent,
                solidity,
                rotated_aspect,
                side_ratio,
                max_angle_cosine,
                opposite_parallel_error=quad.get("opposite_parallel_error"),
                opposite_side_ratio=quad.get("opposite_side_ratio"),
                enclosing_fill=enclosing_fill,
                ellipse_ratio=ellipse_ratio,
                radial_variation=radial_variation,
                side_cv=side_cv,
                angle_mean=angle_mean,
                angle_std=angle_std,
                is_convex=bool(cv2.isContourConvex(approx)),
            )
            if name not in DETECTABLE_SHAPES or conf < 0.66:
                continue

            contour_full = contour + np.array([[[x0, y0]]], dtype=contour.dtype)
            bx1, by1, bx2, by2 = x0 + x, y0 + y, x0 + x + bw, y0 + y + bh
            cx, cy = bx1 + bw // 2, by1 + bh // 2
            sig = f"{name}:{round(cx / max(1, full_w) * 8)}:{round(cy / max(1, full_h) * 6)}:{round(max(bw, bh) / max(1, full_w) * 10)}"
            detections.append(
                ShapeDetection(
                    name=name,
                    name_cn=SHAPE_NAMES_CN[name],
                    box=(bx1, by1, bx2, by2),
                    center=(cx, cy),
                    area=area,
                    confidence=conf,
                    vertices=vertices,
                    contour=contour_full,
                    signature=sig,
                )
            )
        detections.sort(key=lambda d: d.area, reverse=True)
        return detections[:MAX_RESULTS]

    def _find_display_roi(self, image: np.ndarray) -> tuple[int, int, int, int]:
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        bright = cv2.inRange(gray, 145, 255)
        kernel = np.ones((13, 13), np.uint8)
        bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_area = 0.0
        for c in contours:
            area = cv2.contourArea(c)
            if area < w * h * 0.10 or area > w * h * 0.92:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            if bw < w * 0.25 or bh < h * 0.25:
                continue
            ratio = bw / max(1.0, float(bh))
            if ratio < 0.45 or ratio > 3.2:
                continue
            if area > best_area:
                best_area = area
                best = (x, y, x + bw, y + bh)
        if best is not None:
            pad = 8
            return (max(0, best[0] + pad), max(0, best[1] + pad), min(w, best[2] - pad), min(h, best[3] - pad))
        margin = max(4, min(h, w) // 80)
        return (margin, margin, w - margin, h - margin)

    def _stabilize(self, raw: list[ShapeDetection]) -> list[ShapeDetection]:
        tracks = getattr(self, "_shape_tracks", {})
        next_tracks: dict[str, dict[str, object]] = {}
        used_tracks: set[str] = set()

        for detection in raw:
            track_key = detection.signature
            if track_key not in tracks:
                track_key = self._matching_track(detection, tracks, used_tracks) or detection.signature
            previous = tracks.get(track_key, {})
            hits = min(STABLE_HITS + 1, int(previous.get("hits", 0)) + 1)
            next_tracks[detection.signature] = {
                "hits": hits,
                "misses": 0,
                "detection": detection,
            }
            used_tracks.add(track_key)

        for track_key, track in tracks.items():
            if track_key in used_tracks:
                continue
            hits = int(track.get("hits", 0))
            misses = int(track.get("misses", 0)) + 1
            if hits >= STABLE_HITS and misses <= STABLE_HOLD_MISSES:
                next_tracks[track_key] = {**track, "misses": misses}

        self._shape_tracks = next_tracks
        self._stable_signatures = {
            key: int(track["hits"]) for key, track in next_tracks.items()
        }
        stable = [
            track["detection"]
            for track in next_tracks.values()
            if int(track["hits"]) >= STABLE_HITS
        ]
        stable.sort(key=lambda item: item.area, reverse=True)
        return stable[:MAX_RESULTS]

    def _matching_track(
        self,
        detection: ShapeDetection,
        tracks: dict[str, dict[str, object]],
        used_tracks: set[str],
    ) -> str | None:
        best_key = None
        best_distance = float("inf")
        for key, track in tracks.items():
            if key in used_tracks:
                continue
            previous = track.get("detection")
            if not isinstance(previous, ShapeDetection) or previous.name != detection.name:
                continue
            size = max(
                detection.box[2] - detection.box[0],
                detection.box[3] - detection.box[1],
                previous.box[2] - previous.box[0],
                previous.box[3] - previous.box[1],
            )
            distance = float(np.linalg.norm(np.subtract(detection.center, previous.center)))
            if distance <= max(24.0, size * 0.35) and distance < best_distance:
                best_key, best_distance = key, distance
        return best_key

    def _solidity(self, contour: np.ndarray, area: float) -> float:
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        if hull_area <= 0:
            return 0.0
        return float(area / hull_area)

    def _quadrilateral_quality(self, approx: np.ndarray) -> tuple[float | None, float | None]:
        features = self._quadrilateral_features(approx)
        return features.get("side_ratio"), features.get("max_angle_cosine")

    def _quadrilateral_features(self, approx: np.ndarray) -> dict[str, float | None]:
        if len(approx) != 4:
            return {}
        points = approx.reshape(4, 2).astype(np.float32)
        vectors = [points[(index + 1) % 4] - points[index] for index in range(4)]
        sides = [float(np.linalg.norm(vector)) for vector in vectors]
        if max(sides) <= 0:
            return {}
        corner_cosines = []
        for index in range(4):
            before = points[(index - 1) % 4] - points[index]
            after = points[(index + 1) % 4] - points[index]
            denominator = float(np.linalg.norm(before) * np.linalg.norm(after))
            if denominator <= 0:
                return {}
            corner_cosines.append(abs(float(np.dot(before, after)) / denominator))

        parallel_errors = []
        for first, second in ((0, 2), (1, 3)):
            denominator = sides[first] * sides[second]
            cross = float(
                vectors[first][0] * vectors[second][1]
                - vectors[first][1] * vectors[second][0]
            )
            parallel_errors.append(abs(cross) / max(denominator, 1.0))
        opposite_ratios = [
            min(sides[first], sides[second]) / max(sides[first], sides[second])
            for first, second in ((0, 2), (1, 3))
        ]
        return {
            "side_ratio": min(sides) / max(sides),
            "max_angle_cosine": max(corner_cosines),
            "opposite_parallel_error": max(parallel_errors),
            "opposite_side_ratio": min(opposite_ratios),
        }

    def _enclosing_circle_fill(self, contour: np.ndarray, area: float) -> float:
        _center, radius = cv2.minEnclosingCircle(contour)
        return float(area / max(np.pi * radius * radius, 1.0))

    def _ellipse_ratio(self, contour: np.ndarray) -> float | None:
        if len(contour) < 5:
            return None
        _center, axes, _angle = cv2.fitEllipse(contour)
        return min(axes) / max(max(axes), 1.0)

    def _radial_variation(self, contour: np.ndarray) -> float:
        moments = cv2.moments(contour)
        if abs(moments["m00"]) < 1e-6:
            return 0.0
        center = np.array(
            [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]],
            dtype=np.float32,
        )
        distances = np.linalg.norm(contour.reshape(-1, 2).astype(np.float32) - center, axis=1)
        return float(np.std(distances) / max(float(np.mean(distances)), 1.0))

    def _polygon_regularity(
        self, approx: np.ndarray
    ) -> tuple[float | None, float | None, float | None]:
        if len(approx) < 3:
            return None, None, None
        points = approx.reshape(-1, 2).astype(np.float32)
        sides = np.array(
            [np.linalg.norm(points[(index + 1) % len(points)] - points[index]) for index in range(len(points))]
        )
        if float(np.mean(sides)) <= 0:
            return None, None, None
        angles = []
        for index in range(len(points)):
            before = points[(index - 1) % len(points)] - points[index]
            after = points[(index + 1) % len(points)] - points[index]
            denominator = float(np.linalg.norm(before) * np.linalg.norm(after))
            if denominator <= 0:
                return None, None, None
            cosine = float(np.clip(np.dot(before, after) / denominator, -1.0, 1.0))
            angles.append(float(np.degrees(np.arccos(cosine))))
        return (
            float(np.std(sides) / np.mean(sides)),
            float(np.mean(angles)),
            float(np.std(angles)),
        )

    def _classify_shape(
        self,
        vertices: int,
        circularity: float,
        aspect: float,
        extent: float,
        solidity: float,
        rotated_aspect: float | None = None,
        side_ratio: float | None = None,
        max_angle_cosine: float | None = None,
        *,
        opposite_parallel_error: float | None = None,
        opposite_side_ratio: float | None = None,
        enclosing_fill: float | None = None,
        ellipse_ratio: float | None = None,
        radial_variation: float | None = None,
        side_cv: float | None = None,
        angle_mean: float | None = None,
        angle_std: float | None = None,
        is_convex: bool | None = None,
    ) -> tuple[str, float]:
        if vertices == 3:
            return SHAPE_TRIANGLE, 0.90
        if vertices == 4:
            square_aspect = rotated_aspect if rotated_aspect is not None else max(aspect, 1.0 / max(aspect, 0.001))
            angles_are_rectangular = max_angle_cosine is None or max_angle_cosine <= 0.07
            sides_are_balanced = side_ratio is None or side_ratio >= 0.78
            opposite_sides_match = opposite_side_ratio is None or opposite_side_ratio >= 0.78
            both_pairs_parallel = opposite_parallel_error is None or opposite_parallel_error <= 0.14
            if square_aspect <= 1.16 and angles_are_rectangular and sides_are_balanced and opposite_sides_match:
                return SHAPE_SQUARE, max(0.82, 0.94 - abs(1.0 - square_aspect) * 0.5)
            if angles_are_rectangular and opposite_sides_match and both_pairs_parallel:
                ratio_score = min(1.0, max(0.0, (square_aspect - 1.12) / 0.8))
                return SHAPE_RECTANGLE, 0.82 + 0.10 * ratio_score
            if both_pairs_parallel and opposite_sides_match and max_angle_cosine is not None and max_angle_cosine >= 0.18:
                return SHAPE_PARALLELOGRAM, min(0.94, 0.76 + max_angle_cosine * 0.45)
            return SHAPE_POLYGON, 0.68
        if vertices == 5:
            regular = (
                (is_convex is None or is_convex)
                and (side_cv is None or side_cv <= 0.18)
                and (angle_mean is None or 96.0 <= angle_mean <= 120.0)
                and (angle_std is None or angle_std <= 13.0)
            )
            return (SHAPE_PENTAGON, 0.88) if regular else (SHAPE_POLYGON, 0.52)
        if vertices == 6:
            return SHAPE_HEXAGON, 0.80
        star_like = (
            8 <= vertices <= 14
            and solidity <= 0.78
            and (is_convex is None or not is_convex)
            and (radial_variation is None or radial_variation >= 0.20)
        )
        if star_like:
            completeness = min(1.0, max(0.0, (vertices - 7) / 3.0))
            return SHAPE_STAR, 0.72 + completeness * 0.16
        circle_like = (
            circularity >= 0.76
            and solidity >= 0.94
            and extent <= 0.86
            and (enclosing_fill is None or enclosing_fill >= 0.76)
            and (ellipse_ratio is None or ellipse_ratio >= 0.80)
            and (radial_variation is None or radial_variation <= 0.14)
        )
        if circle_like:
            if 0.76 <= aspect <= 1.32:
                return SHAPE_CIRCLE, min(0.95, 0.72 + circularity * 0.24)
            return SHAPE_ELLIPSE, 0.82
        if vertices >= 7:
            return SHAPE_POLYGON, 0.68
        return SHAPE_POLYGON, 0.45

    def _annotate(self, image: np.ndarray, detections: list[ShapeDetection]) -> np.ndarray:
        out = image.copy()
        draw_target_roi(out, margin_x=0.16, margin_y=0.12)
        for idx, det in enumerate(detections):
            color = COLORS[idx % len(COLORS)]
            x1, y1, x2, y2 = det.box
            cv2.drawContours(out, [det.contour], -1, color, 3)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            label = f"{det.name} {det.confidence:.2f}"
            size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.68, 2)
            tw, th = size
            y0 = max(0, y1 - th - 16)
            cv2.rectangle(out, (x1, y0), (x1 + tw + 18, y0 + th + 14), color, -1)
            cv2.putText(out, label, (x1 + 9, y0 + th + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (8, 18, 12), 2, cv2.LINE_AA)
        cv2.putText(out, f"FPS {self.fps:.1f}", (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (100, 255, 180), 2, cv2.LINE_AA)
        return out

    def _set_results(self, detections: list[ShapeDetection]) -> None:
        if detections:
            lines = [f"{d.name_cn}（置信度 {round(d.confidence * 100)}%）" for d in detections]
            text = "\n".join(lines)
        else:
            text = T_NO_SHAPE
        self.result_box.configure(state=tk.NORMAL)
        self.result_box.delete("1.0", tk.END)
        self.result_box.insert("1.0", text)
        self.result_box.configure(state=tk.DISABLED)
        self.summary_text.set(f"device: {CAMERA_DEVICE}\ninput: {CAMERA_WIDTH}x{CAMERA_HEIGHT}\nview: {T_NORMAL_VIEW}\nengine: screen ROI + stable contours\nraw: {self._last_raw_count}\nfps: {self.fps:.1f}\ndet: {self.det_fps:.1f}/s")

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()
        with self.detect_lock:
            detections = list(self.detections)
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        if frame is None:
            self.canvas.create_text(cw // 2, ch // 2, fill="#dfe7f2", font=("Microsoft YaHei", 16), text=T_WAIT)
        else:
            normal = self._normal_frame(frame)
            view = self._annotate(normal, detections)
            self.last_view = view.copy()
            rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            scale = min(cw / w, ch / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            header = f"P6 {nw} {nh} 255\n".encode("ascii")
            self.photo = tk.PhotoImage(data=header + rgb.tobytes(), format="PPM")
            self.canvas.create_image(cw // 2, ch // 2, image=self.photo, anchor=tk.CENTER)
            self._set_results(detections)
        if self.running:
            self.root.after(DISPLAY_INTERVAL_MS, self._update_view)

    def save_snapshot(self) -> None:
        if self.last_view is None:
            self._set_status(T_NO_SAVE)
            return
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOT_DIR / time.strftime("shape_%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(str(path), self.last_view, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        self._set_status(f"{T_SAVED}: {path}")

    def close(self) -> None:
        self.running = False
        if self.cap is not None:
            self.cap.release()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

if __name__ == "__main__":
    ShapeRecognitionApp().run()
