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

from vision_targeting import draw_target_roi, target_roi

CAMERA_DEVICE = os.getenv("SHAPE_CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("SHAPE_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("SHAPE_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("SHAPE_CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("SHAPE_DISPLAY_INTERVAL_MS", "80"))
CAPTURE_INTERVAL_SEC = float(os.getenv("SHAPE_CAPTURE_INTERVAL_SEC", "0.025"))
DETECT_INTERVAL_SEC = float(os.getenv("SHAPE_DETECT_INTERVAL_SEC", "0.16"))
MIN_AREA = int(os.getenv("SHAPE_MIN_AREA", "2200"))
MAX_RESULTS = int(os.getenv("SHAPE_MAX_RESULTS", "3"))
STABLE_HITS = int(os.getenv("SHAPE_STABLE_HITS", "3"))
SNAPSHOT_DIR = Path(os.getenv("SHAPE_SNAPSHOT_DIR", "/root/robot_arm/assets/shape_snapshots"))

T_TITLE = "\u5f62\u72b6\u8bc6\u522b"
T_OPENING = "\u6b63\u5728\u6253\u5f00\u6444\u50cf\u5934..."
T_WAIT = "\u7b49\u5f85\u753b\u9762"
T_RESULT = "\u8bc6\u522b\u7ed3\u679c"
T_SAVE = "\u4fdd\u5b58\u5f53\u524d\u753b\u9762"
T_EXIT = "\u9000\u51fa"
T_WAIT_DETECT = "\u7b49\u5f85\u8bc6\u522b"
T_NO_SHAPE = "\u672a\u68c0\u6d4b\u5230\u660e\u663e\u5f62\u72b6"
T_SAVED = "\u5df2\u4fdd\u5b58"
T_NO_SAVE = "\u8fd8\u6ca1\u6709\u53ef\u4fdd\u5b58\u7684\u753b\u9762"
T_CAMERA_FAIL = "\u6444\u50cf\u5934\u6253\u5f00\u5931\u8d25"
T_READ_FAIL = "\u8bfb\u53d6\u753b\u9762\u5931\u8d25\uff0c\u6b63\u5728\u91cd\u8bd5..."
T_OPENED = "\u5df2\u6253\u5f00"
T_NORMAL_VIEW = "\u6b63\u5e38\u753b\u9762"
T_NAME = "\u5f62\u72b6"
T_CENTER = "\u4f4d\u7f6e"
T_CONF = "\u7f6e\u4fe1\u5ea6"
T_AREA = "\u9762\u79ef"

SHAPE_TRIANGLE = "\u4e09\u89d2\u5f62"
SHAPE_SQUARE = "\u6b63\u65b9\u5f62"
SHAPE_RECTANGLE = "\u957f\u65b9\u5f62"
SHAPE_CIRCLE = "\u5706\u5f62"
SHAPE_ELLIPSE = "\u692d\u5706\u5f62"
SHAPE_PENTAGON = "\u4e94\u8fb9\u5f62"
SHAPE_HEXAGON = "\u516d\u8fb9\u5f62"
SHAPE_STAR = "\u661f\u5f62"
SHAPE_POLYGON = "\u591a\u8fb9\u5f62"

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
        mid = frame.shape[1] // 2
        return frame[:, :mid].copy()

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
        dark = cv2.inRange(gray, 0, 185)
        saturated = cv2.inRange(hsv, np.array((0, 38, 35), dtype=np.uint8), np.array((180, 255, 245), dtype=np.uint8))
        mask = cv2.bitwise_or(dark, saturated)

        # Remove the outside border of the phone/paper ROI, otherwise it becomes a false rectangle.
        border = max(6, min(roi.shape[:2]) // 35)
        mask[:border, :] = 0
        mask[-border:, :] = 0
        mask[:, :border] = 0
        mask[:, -border:] = 0

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi_h, roi_w = roi.shape[:2]
        full_h, full_w = image.shape[:2]
        detections: list[ShapeDetection] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < max(MIN_AREA, roi_w * roi_h * 0.012) or area > roi_w * roi_h * 0.58:
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            if bw < 38 or bh < 38:
                continue
            if bw > roi_w * 0.92 or bh > roi_h * 0.92:
                continue
            peri = cv2.arcLength(contour, True)
            if peri <= 0:
                continue
            approx = cv2.approxPolyDP(contour, 0.030 * peri, True)
            vertices = len(approx)
            circularity = 4.0 * np.pi * area / max(peri * peri, 1.0)
            extent = area / max(float(bw * bh), 1.0)
            aspect = bw / max(float(bh), 1.0)
            solidity = self._solidity(contour, area)
            name, conf = self._classify_shape(vertices, circularity, aspect, extent, solidity)
            if conf < 0.66:
                continue

            contour_full = contour + np.array([[[x0, y0]]], dtype=contour.dtype)
            bx1, by1, bx2, by2 = x0 + x, y0 + y, x0 + x + bw, y0 + y + bh
            cx, cy = bx1 + bw // 2, by1 + bh // 2
            sig = f"{name}:{round(cx / max(1, full_w) * 8)}:{round(cy / max(1, full_h) * 6)}:{round(max(bw, bh) / max(1, full_w) * 10)}"
            detections.append(ShapeDetection(name, (bx1, by1, bx2, by2), (cx, cy), area, conf, vertices, contour_full, sig))
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
        roi = target_roi(image, margin_x=0.16, margin_y=0.12)
        return (roi.x1, roi.y1, roi.x2, roi.y2)

    def _stabilize(self, raw: list[ShapeDetection]) -> list[ShapeDetection]:
        current = {d.signature for d in raw if d.signature}
        next_counts: dict[str, int] = {}
        for sig in current:
            next_counts[sig] = min(STABLE_HITS + 1, self._stable_signatures.get(sig, 0) + 1)
        self._stable_signatures = next_counts
        stable = [d for d in raw if self._stable_signatures.get(d.signature, 0) >= STABLE_HITS]
        return stable

    def _solidity(self, contour: np.ndarray, area: float) -> float:
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        if hull_area <= 0:
            return 0.0
        return float(area / hull_area)

    def _classify_shape(self, vertices: int, circularity: float, aspect: float, extent: float, solidity: float) -> tuple[str, float]:
        if vertices == 3:
            return SHAPE_TRIANGLE, 0.90
        if vertices == 4:
            if 0.86 <= aspect <= 1.16:
                return SHAPE_SQUARE, 0.88
            return SHAPE_RECTANGLE, 0.86
        if vertices == 5:
            return SHAPE_PENTAGON, 0.80
        if vertices == 6:
            return SHAPE_HEXAGON, 0.80
        if solidity < 0.78 and vertices >= 8:
            return SHAPE_STAR, 0.76
        if circularity >= 0.74:
            if 0.82 <= aspect <= 1.22:
                return SHAPE_CIRCLE, min(0.95, 0.70 + circularity * 0.25)
            return SHAPE_ELLIPSE, 0.82
        if vertices >= 7:
            return SHAPE_POLYGON, 0.65
        return SHAPE_POLYGON, 0.45

    def _annotate(self, image: np.ndarray, detections: list[ShapeDetection]) -> np.ndarray:
        out = image.copy()
        draw_target_roi(out, margin_x=0.16, margin_y=0.12)
        for idx, det in enumerate(detections):
            color = COLORS[idx % len(COLORS)]
            x1, y1, x2, y2 = det.box
            cv2.drawContours(out, [det.contour], -1, color, 3)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            label = f"shape {idx + 1} {det.confidence:.2f}"
            size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.68, 2)
            tw, th = size
            y0 = max(0, y1 - th - 16)
            cv2.rectangle(out, (x1, y0), (x1 + tw + 18, y0 + th + 14), color, -1)
            cv2.putText(out, label, (x1 + 9, y0 + th + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (8, 18, 12), 2, cv2.LINE_AA)
        cv2.putText(out, f"FPS {self.fps:.1f}", (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (100, 255, 180), 2, cv2.LINE_AA)
        return out

    def _set_results(self, detections: list[ShapeDetection]) -> None:
        if detections:
            lines = []
            for idx, d in enumerate(detections, 1):
                lines.append(f"{idx}. {T_NAME}: {d.name}\n   {T_CENTER}: ({d.center[0]}, {d.center[1]})\n   {T_CONF}: {d.confidence:.2f}\n   {T_AREA}: {int(d.area)}")
            text = "\n\n".join(lines)
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
