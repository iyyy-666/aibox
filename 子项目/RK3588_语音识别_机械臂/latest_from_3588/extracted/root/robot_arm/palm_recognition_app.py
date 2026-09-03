#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
import tkinter as tk

import cv2
import numpy as np

from vision_targeting import box_is_target, draw_target_roi, stable_filter, target_roi


CAMERA_DEVICE = os.getenv("PALM_CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("PALM_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("PALM_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("PALM_CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("PALM_DISPLAY_INTERVAL_MS", "90"))
CAPTURE_INTERVAL_SEC = float(os.getenv("PALM_CAPTURE_INTERVAL_SEC", "0.03"))
DETECT_INTERVAL_SEC = float(os.getenv("PALM_DETECT_INTERVAL_SEC", "0.12"))
MIN_AREA = int(os.getenv("PALM_MIN_AREA", "2600"))
MAX_AREA_RATIO = float(os.getenv("PALM_MAX_AREA_RATIO", "0.58"))
STABLE_HITS = int(os.getenv("PALM_STABLE_HITS", "1"))
SNAPSHOT_DIR = Path(os.getenv("PALM_SNAPSHOT_DIR", "/root/robot_arm/assets/palm_snapshots"))
YOLO_MODEL_PATH = Path(os.getenv("PALM_YOLO_MODEL", "/root/robot_arm/models/hand/hand_yolov8n.pt"))
YOLO_CONF = float(os.getenv("PALM_YOLO_CONF", "0.25"))
YOLO_IMG_SIZE = int(os.getenv("PALM_YOLO_IMG_SIZE", "416"))
YOLO_EVERY_N = int(os.getenv("PALM_YOLO_EVERY_N", "1"))

T_TITLE = "\u624b\u638c\u8bc6\u522b\uff08\u53cc\u76ee\uff09"
T_OPENING = "\u6b63\u5728\u6253\u5f00\u53cc\u76ee\u6444\u50cf\u5934..."
T_RESULT = "\u8bc6\u522b\u7ed3\u679c"
T_WAIT = "\u7b49\u5f85\u624b\u638c\u8fdb\u5165\u753b\u9762"
T_NO_HAND = "\u672a\u68c0\u6d4b\u5230\u624b\u638c"
T_SAVE = "\u4fdd\u5b58\u5f53\u524d\u753b\u9762"
T_EXIT = "\u9000\u51fa"
T_CAMERA_FAIL = "\u6444\u50cf\u5934\u6253\u5f00\u5931\u8d25"
T_READ_FAIL = "\u8bfb\u53d6\u753b\u9762\u5931\u8d25\uff0c\u6b63\u5728\u91cd\u8bd5..."
T_OPENED = "\u5df2\u6253\u5f00"
T_NORMAL_VIEW = "\u53cc\u76ee\u6b63\u5e38\u753b\u9762"
T_SAVED = "\u5df2\u4fdd\u5b58"
T_NO_SAVE = "\u8fd8\u6ca1\u6709\u53ef\u4fdd\u5b58\u7684\u753b\u9762"


@dataclass
class HandDetection:
    gesture: str
    box: tuple[int, int, int, int]
    confidence: float
    center: tuple[int, int]
    area: float
    fingers: int
    source: str = "OpenCV"


class PalmRecognitionApp:
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
        self.detect_lock = threading.Lock()
        self.detections: list[HandDetection] = []
        self._stable_signatures: dict[str, int] = {}
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=18, detectShadows=False)
        self._bg_frames = 0
        self.photo: tk.PhotoImage | None = None
        self.last_view: np.ndarray | None = None
        self.fps = 0.0
        self.det_fps = 0.0
        self.last_frame_time = 0.0
        self.hand_model = None
        self.hand_model_name = "OpenCV fallback"
        self._detect_count = 0
        self._last_yolo_detections: list[HandDetection] = []

        self._build_ui()
        self._load_yolo_model()
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

        side = tk.Frame(body, bg="#181d22", width=280)
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        side.pack_propagate(False)
        tk.Label(side, text=T_RESULT, bg="#181d22", fg="#f1f5f9", font=("Microsoft YaHei", 13, "bold")).pack(anchor="w", padx=16, pady=(16, 10))
        self.result_box = tk.Text(side, height=18, bg="#0f1317", fg="#e8eef5", insertbackground="#e8eef5", relief=tk.FLAT, font=("Microsoft YaHei", 11), wrap=tk.WORD)
        self.result_box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        self.result_box.insert("1.0", T_WAIT)
        self.result_box.configure(state=tk.DISABLED)
        ttk.Button(side, text="\u91cd\u65b0\u6821\u51c6\u80cc\u666f", command=self.reset_background).pack(fill=tk.X, padx=16, pady=(4, 8))
        ttk.Button(side, text=T_SAVE, command=self.save_snapshot).pack(fill=tk.X, padx=16, pady=(4, 8))
        ttk.Button(side, text=T_EXIT, command=self.close).pack(fill=tk.X, padx=16, pady=(0, 14))
        tk.Label(side, textvariable=self.summary_text, bg="#181d22", fg="#9fb0c2", justify=tk.LEFT, font=("Consolas", 10)).pack(anchor="w", padx=16, pady=(0, 16))

    def reset_background(self) -> None:
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=18, detectShadows=False)
        self._bg_frames = 0
        self._stable_signatures.clear()
        self.detections = []
        self._set_status("\u80cc\u666f\u5df2\u91cd\u65b0\u6821\u51c6\uff0c\u8bf7\u628a\u624b\u653e\u5230\u4e2d\u95f4\u6846\u5185")

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
        mid = frame.shape[1] // 2
        return frame[:, :mid].copy()

    def _load_yolo_model(self) -> None:
        if not YOLO_MODEL_PATH.exists():
            self.hand_model_name = f"OpenCV fallback, no model: {YOLO_MODEL_PATH}"
            return
        try:
            from ultralytics import YOLO

            self.hand_model = YOLO(str(YOLO_MODEL_PATH))
            self.hand_model_name = YOLO_MODEL_PATH.name
            self._set_status(f"{T_OPENED} hand model: {YOLO_MODEL_PATH.name}")
        except Exception as exc:
            self.hand_model = None
            self.hand_model_name = f"OpenCV fallback, YOLO load failed: {exc}"

    def _detect_loop(self) -> None:
        while self.running:
            with self.frame_lock:
                frame = None if self.frame is None else self.frame.copy()
            if frame is not None:
                normal = self._normal_frame(frame)
                t0 = time.time()
                detections = self._detect_hands(normal)
                detections, self._stable_signatures = stable_filter(
                    self._stable_signatures,
                    detections,
                    label_fn=lambda d: "hand",
                    box_fn=lambda d: (d.box[0], d.box[1], d.box[0] + d.box[2], d.box[1] + d.box[3]),
                    image_shape=normal.shape,
                    stable_hits=STABLE_HITS,
                )
                dt = time.time() - t0
                if dt > 0:
                    inst = 1.0 / dt
                    self.det_fps = self.det_fps * 0.80 + inst * 0.20 if self.det_fps else inst
                with self.detect_lock:
                    self.detections = detections
            time.sleep(DETECT_INTERVAL_SEC)

    def _skin_mask(self, image: np.ndarray) -> np.ndarray:
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        ycrcb = cv2.cvtColor(blurred, cv2.COLOR_BGR2YCrCb)
        hsv_mask = cv2.inRange(hsv, np.array((0, 12, 28), dtype=np.uint8), np.array((35, 235, 255), dtype=np.uint8))
        hsv_mask2 = cv2.inRange(hsv, np.array((160, 12, 28), dtype=np.uint8), np.array((180, 235, 255), dtype=np.uint8))
        y_mask = cv2.inRange(ycrcb, np.array((0, 122, 65), dtype=np.uint8), np.array((255, 190, 150), dtype=np.uint8))
        mask = cv2.bitwise_or(cv2.bitwise_or(hsv_mask, hsv_mask2), y_mask)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.dilate(mask, kernel, iterations=1)
        return mask

    def _foreground_mask(self, image: np.ndarray) -> np.ndarray:
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        rate = 0.04 if self._bg_frames < 18 else 0.004
        fg = self._bg_subtractor.apply(blurred, learningRate=rate)
        self._bg_frames += 1
        _, fg = cv2.threshold(fg, 180, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel, iterations=1)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel, iterations=2)
        fg = cv2.dilate(fg, kernel, iterations=1)
        roi = target_roi(image, margin_x=0.14, margin_y=0.10)
        limited = np.zeros_like(fg)
        limited[roi.y1:roi.y2, roi.x1:roi.x2] = fg[roi.y1:roi.y2, roi.x1:roi.x2]
        return limited

    def _detect_hands(self, image: np.ndarray) -> list[HandDetection]:
        self._detect_count += 1
        yolo_detections = self._detect_yolo_hands(image)
        if yolo_detections:
            self._last_yolo_detections = yolo_detections
            return yolo_detections
        if self._last_yolo_detections and self._detect_count % max(1, YOLO_EVERY_N) != 0:
            return self._last_yolo_detections

        skin = self._skin_mask(image)
        foreground = self._foreground_mask(image)
        fg_skin = cv2.bitwise_and(skin, foreground)
        mask = fg_skin if int(cv2.countNonZero(fg_skin)) > MIN_AREA else skin
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[HandDetection] = []
        h, w = image.shape[:2]
        max_area = float(w * h) * MAX_AREA_RATIO
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < max(MIN_AREA, w * h * 0.006) or area > max_area:
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            if bw < 36 or bh < 36:
                continue
            if not box_is_target(image, (x, y, x + bw, y + bh), min_area=max(MIN_AREA, image.shape[0] * image.shape[1] * 0.006), max_area_ratio=MAX_AREA_RATIO, min_side=36, min_aspect=0.28, max_aspect=3.2, roi_margin_x=0.14, roi_margin_y=0.10):
                continue
            extent = area / max(float(bw * bh), 1.0)
            if extent < 0.14:
                continue
            hull_points = cv2.convexHull(contour)
            hull_area = float(cv2.contourArea(hull_points))
            if hull_area <= 0:
                continue
            solidity = area / hull_area
            fingers = self._count_fingers(contour, (x, y, bw, bh))
            gesture, confidence = self._classify_gesture(fingers, solidity, bw, bh, area)
            detections.append(HandDetection(gesture, (x, y, bw, bh), confidence, (x + bw // 2, y + bh // 2), area, fingers, "OpenCV skin"))
        if not detections:
            detections = self._detect_foreground_hand(image)
        detections.sort(key=lambda d: (d.confidence, d.area), reverse=True)
        return detections[:1]

    def _detect_yolo_hands(self, image: np.ndarray) -> list[HandDetection]:
        if self.hand_model is None:
            return []
        if self._detect_count % max(1, YOLO_EVERY_N) != 0:
            return self._last_yolo_detections
        try:
            results = self.hand_model.predict(image, imgsz=YOLO_IMG_SIZE, conf=YOLO_CONF, verbose=False, device="cpu")
        except Exception as exc:
            self.hand_model_name = f"OpenCV fallback, YOLO predict failed: {exc}"
            return []
        if not results:
            return []
        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return []

        detections: list[HandDetection] = []
        h, w = image.shape[:2]
        for item in boxes:
            xyxy = item.xyxy[0].detach().cpu().numpy()
            conf = float(item.conf[0].detach().cpu().item()) if item.conf is not None else 0.0
            x1, y1, x2, y2 = [int(round(v)) for v in xyxy[:4]]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            bw, bh = x2 - x1, y2 - y1
            if bw <= 0 or bh <= 0:
                continue
            if not box_is_target(
                image,
                (x1, y1, x2, y2),
                min_area=max(MIN_AREA, h * w * 0.006),
                max_area_ratio=MAX_AREA_RATIO,
                min_side=34,
                min_aspect=0.25,
                max_aspect=3.6,
                roi_margin_x=0.10,
                roi_margin_y=0.08,
            ):
                continue
            rx, ry, rw, rh, contour = self._refine_hand_box(image, (x1, y1, bw, bh))
            fingers = 0
            solidity = 0.76
            area = float(rw * rh)
            if contour is not None:
                hull_points = cv2.convexHull(contour)
                contour_area = float(cv2.contourArea(contour))
                hull_area = float(cv2.contourArea(hull_points))
                solidity = contour_area / hull_area if hull_area > 0 else solidity
                fingers = self._count_fingers(contour, (rx, ry, rw, rh))
                area = contour_area if contour_area > 0 else area
            gesture, g_conf = self._classify_gesture(fingers, solidity, rw, rh, area)
            confidence = max(conf, min(0.98, conf * 0.72 + g_conf * 0.28))
            detections.append(HandDetection(gesture, (rx, ry, rw, rh), confidence, (rx + rw // 2, ry + rh // 2), area, fingers, "YOLO+ROI"))
        detections.sort(key=lambda d: (d.confidence, d.area), reverse=True)
        return detections[:1]

    def _refine_hand_box(self, image: np.ndarray, box: tuple[int, int, int, int]) -> tuple[int, int, int, int, np.ndarray | None]:
        x, y, w, h = box
        pad = int(max(w, h) * 0.12)
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(image.shape[1], x + w + pad)
        y2 = min(image.shape[0], y + h + pad)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return x, y, w, h, None
        mask = self._skin_mask(crop)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return x, y, w, h, None
        contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(contour) < max(350.0, w * h * 0.08):
            return x, y, w, h, None
        contour_full = contour + np.array([[[x1, y1]]], dtype=contour.dtype)
        rx, ry, rw, rh = cv2.boundingRect(contour_full)
        if rw < 24 or rh < 24:
            return x, y, w, h, contour_full
        return rx, ry, rw, rh, contour_full

    def _detect_foreground_hand(self, image: np.ndarray) -> list[HandDetection]:
        roi = target_roi(image, margin_x=0.18, margin_y=0.13)
        crop = image[roi.y1:roi.y2, roi.x1:roi.x2]
        if crop.size == 0:
            return []
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 35, 105)
        saturated = cv2.inRange(hsv, np.array((0, 20, 25), dtype=np.uint8), np.array((180, 230, 255), dtype=np.uint8))
        bright_or_dark = cv2.inRange(gray, 25, 238)
        mask = cv2.bitwise_or(edges, cv2.bitwise_and(saturated, bright_or_dark))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.dilate(mask, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        items: list[HandDetection] = []
        full_area = image.shape[0] * image.shape[1]
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < max(MIN_AREA, full_area * 0.010):
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            x += roi.x1
            y += roi.y1
            if not box_is_target(image, (x, y, x + bw, y + bh), min_area=max(MIN_AREA, full_area * 0.010), max_area_ratio=0.50, min_side=46, min_aspect=0.35, max_aspect=2.8, roi_margin_x=0.18, roi_margin_y=0.13):
                continue
            contour_full = contour + np.array([[[roi.x1, roi.y1]]], dtype=contour.dtype)
            hull_points = cv2.convexHull(contour_full)
            hull_area = float(cv2.contourArea(hull_points))
            solidity = area / hull_area if hull_area > 0 else 0.0
            fingers = self._count_fingers(contour_full, (x, y, bw, bh))
            gesture, confidence = self._classify_gesture(fingers, solidity, bw, bh, area)
            items.append(HandDetection(gesture, (x, y, bw, bh), max(0.52, confidence - 0.10), (x + bw // 2, y + bh // 2), area, fingers, "OpenCV foreground"))
        items.sort(key=lambda d: (d.confidence, d.area), reverse=True)
        return items[:1]

    def _count_fingers(self, contour: np.ndarray, box: tuple[int, int, int, int]) -> int:
        x, y, w, h = box
        hull_indices = cv2.convexHull(contour, returnPoints=False)
        if hull_indices is None or len(hull_indices) < 4:
            return 0
        defects = cv2.convexityDefects(contour, hull_indices)
        if defects is None:
            return 0
        min_depth = max(10.0, min(w, h) * 0.075)
        candidates: list[tuple[int, int]] = []
        for i in range(defects.shape[0]):
            s, e, f, depth = defects[i, 0]
            start = contour[s][0]
            end = contour[e][0]
            far = contour[f][0]
            a = np.linalg.norm(end - start)
            b = np.linalg.norm(far - start)
            c = np.linalg.norm(end - far)
            if b <= 1 or c <= 1:
                continue
            angle = math.degrees(math.acos(max(-1.0, min(1.0, (b * b + c * c - a * a) / (2 * b * c)))))
            if angle < 88 and depth / 256.0 > min_depth and far[1] > y + h * 0.28:
                candidates.append((int(start[0]), int(start[1])))
                candidates.append((int(end[0]), int(end[1])))
        if not candidates:
            return 0
        unique: list[tuple[int, int]] = []
        for pt in candidates:
            if pt[1] > y + h * 0.82:
                continue
            if all(abs(pt[0] - old[0]) > max(14, w * 0.07) for old in unique):
                unique.append(pt)
        return min(5, len(unique))

    def _classify_gesture(self, fingers: int, solidity: float, w: int, h: int, area: float) -> tuple[str, float]:
        aspect = w / max(float(h), 1.0)
        if fingers >= 4 or (fingers >= 3 and solidity < 0.78):
            return "\u5e03", min(0.95, 0.62 + fingers * 0.07)
        if fingers in (2, 3):
            return "\u526a\u5200", 0.78 if aspect < 1.55 else 0.68
        if solidity > 0.72 or fingers <= 1:
            return "\u77f3\u5934", 0.76 if area > MIN_AREA * 1.5 else 0.62
        return "\u624b\u638c", 0.55

    def _annotate(self, image: np.ndarray, detections: list[HandDetection]) -> np.ndarray:
        out = image.copy()
        draw_target_roi(out)
        for det in detections:
            x, y, w, h = det.box
            color = (80, 220, 245) if det.gesture == "\u5e03" else (245, 185, 75) if det.gesture == "\u526a\u5200" else (110, 210, 120)
            cv2.rectangle(out, (x, y), (x + w, y + h), color, 3)
            label = {"\u77f3\u5934": "Rock", "\u526a\u5200": "Scissors", "\u5e03": "Paper"}.get(det.gesture, "Hand")
            text = f"{label} {det.confidence:.2f}"
            text_size, _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.68, 2)
            tw, th = text_size
            y0 = max(0, y - th - 16)
            cv2.rectangle(out, (x, y0), (x + tw + 18, y0 + th + 14), color, -1)
            cv2.putText(out, text, (x + 9, y0 + th + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (20, 24, 28), 2, cv2.LINE_AA)
        cv2.putText(out, f"FPS {self.fps:.1f}", (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (100, 255, 180), 2, cv2.LINE_AA)
        return out

    def _set_results(self, detections: list[HandDetection]) -> None:
        if detections:
            lines = []
            for idx, det in enumerate(detections, 1):
                lines.append(
                    f"{idx}. 手势：{det.gesture}\n"
                    f"   位置：({det.center[0]}, {det.center[1]})\n"
                    f"   置信度：{det.confidence:.2f}\n"
                    f"   手指估计：{det.fingers}\n"
                    f"   来源：{det.source}"
                )
            text = "\n\n".join(lines)
        else:
            text = T_NO_HAND
        self.result_box.configure(state=tk.NORMAL)
        self.result_box.delete("1.0", tk.END)
        self.result_box.insert("1.0", text)
        self.result_box.configure(state=tk.DISABLED)
        self.summary_text.set(
            f"device: {CAMERA_DEVICE}\n"
            f"input: {CAMERA_WIDTH}x{CAMERA_HEIGHT}\n"
            f"view: stereo normal\n"
            f"model: {self.hand_model_name}\n"
            f"fps: {self.fps:.1f}\n"
            f"detect: {self.det_fps:.1f}/s"
        )

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()
        with self.detect_lock:
            detections = list(self.detections)

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        if frame is None:
            self.canvas.create_text(cw // 2, ch // 2, fill="#dfe7f2", font=("Microsoft YaHei", 16), text=T_OPENING)
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
        path = SNAPSHOT_DIR / time.strftime("palm_%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(str(path), self.last_view, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        self._set_status(f"{T_SAVED}: {path}")

    def close(self) -> None:
        self.running = False
        if self.cap is not None:
            self.cap.release()
        self.root.after(80, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    PalmRecognitionApp().run()
