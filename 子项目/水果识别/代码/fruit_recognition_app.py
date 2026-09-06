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

from vision_targeting import box_is_target, draw_target_roi, split_stereo, stable_filter
from gimbal_controls import GimbalControls

CAMERA_DEVICE = os.getenv("FRUIT_CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("FRUIT_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("FRUIT_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("FRUIT_CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("FRUIT_DISPLAY_INTERVAL_MS", "70"))
CAPTURE_INTERVAL_SEC = float(os.getenv("FRUIT_CAPTURE_INTERVAL_SEC", "0.025"))
DETECT_INTERVAL_SEC = float(os.getenv("FRUIT_DETECT_INTERVAL_SEC", "0.18"))
YOLO_MODEL_PATH = os.getenv("FRUIT_YOLO_MODEL", "/root/robot_arm/models/fruit/yolov8n.pt")
YOLO_CLS_MODEL_PATH = os.getenv("FRUIT_YOLO_CLS_MODEL", "/root/robot_arm/models/fruit/yolov8n-cls.pt")
YOLO_IMG_SIZE = int(os.getenv("FRUIT_YOLO_IMG_SIZE", "512"))
CONF_THRESHOLD = float(os.getenv("FRUIT_CONF", "0.28"))
STABLE_HITS = int(os.getenv("FRUIT_STABLE_HITS", "2"))
SNAPSHOT_DIR = Path(os.getenv("FRUIT_SNAPSHOT_DIR", "/root/robot_arm/assets/fruit_snapshots"))

T_TITLE = "\u6c34\u679c\u8bc6\u522b"
T_OPENING = "\u6b63\u5728\u6253\u5f00\u6444\u50cf\u5934..."
T_WAIT = "\u7b49\u5f85\u753b\u9762"
T_RESULT = "\u8bc6\u522b\u7ed3\u679c"
T_SAVE = "\u4fdd\u5b58\u5f53\u524d\u753b\u9762"
T_EXIT = "\u9000\u51fa"
T_NO_MODEL = "\u6a21\u578b\u52a0\u8f7d\u5931\u8d25"
T_NO_FRUIT = "\u672a\u68c0\u6d4b\u5230\u6c34\u679c"
T_WAIT_DETECT = "\u7b49\u5f85\u8bc6\u522b"
T_SAVED = "\u5df2\u4fdd\u5b58"
T_NO_SAVE = "\u8fd8\u6ca1\u6709\u53ef\u4fdd\u5b58\u7684\u753b\u9762"
T_CAMERA_FAIL = "\u6444\u50cf\u5934\u6253\u5f00\u5931\u8d25"
T_READ_FAIL = "\u8bfb\u53d6\u753b\u9762\u5931\u8d25\uff0c\u6b63\u5728\u91cd\u8bd5..."
T_OPENED = "\u5df2\u6253\u5f00"
T_NORMAL_VIEW = "\u6b63\u5e38\u753b\u9762"
T_IMAGE_MODE = "\u56fe\u7247\u8bc6\u522b"

FRUIT_CN = {
    "apple": "\u82f9\u679c",
    "banana": "\u9999\u8549",
    "orange": "\u6a59\u5b50",
    "strawberry": "\u8349\u8393",
    "pineapple": "\u83e0\u841d",
    "grape": "\u8461\u8404",
    "watermelon": "\u897f\u74dc",
    "pear": "\u68a8",
    "peach": "\u6843\u5b50",
    "lemon": "\u67e0\u6aac",
    "mango": "\u8292\u679c",
    "kiwi": "\u7315\u7334\u6843",
}
FALLBACK_FRUIT_CLASS_IDS = {46, 47, 49}
FRUIT_CLS_KEYWORDS = {
    "apple": "\u82f9\u679c",
    "banana": "\u9999\u8549",
    "orange": "\u6a59\u5b50",
    "strawberry": "\u8349\u8393",
    "pineapple": "\u83e0\u841d",
    "granny_smith": "\u82f9\u679c",
    "lemon": "\u67e0\u6aac",
    "fig": "\u65e0\u82b1\u679c",
    "pomegranate": "\u77f3\u69b4",
    "jackfruit": "\u83e0\u841d\u871c",
    "custard_apple": "\u756a\u8354\u679d",
    "acorn_squash": "\u74dc\u679c",
    "cucumber": "\u9ec4\u74dc",
    "bell_pepper": "\u751c\u6912",
}
BOX_COLOR = (75, 210, 120)
FALLBACK_BOX_COLOR = (80, 170, 255)
COLOR_BOX_COLOR = (80, 220, 245)

@dataclass
class FruitDetection:
    name_en: str
    name_cn: str
    box: tuple[int, int, int, int]
    confidence: float
    center: tuple[int, int]
    source: str = "detect"

class FruitRecognitionApp:
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
        self.detections: list[FruitDetection] = []
        self.detect_lock = threading.Lock()
        self.photo: tk.PhotoImage | None = None
        self.last_view: np.ndarray | None = None
        self.fps = 0.0
        self.det_fps = 0.0
        self.last_frame_time = 0.0
        self._stable_signatures: dict[str, int] = {}
        self.model = None
        self.cls_model = None
        self.model_names: dict[int, str] = {}
        self.cls_names: dict[int, str] = {}
        self.fruit_class_ids: set[int] = set(FALLBACK_FRUIT_CLASS_IDS)

        self._build_ui()
        threading.Thread(target=self._load_model, daemon=True).start()
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
        self.result_box.insert("1.0", T_WAIT_DETECT)
        self.result_box.configure(state=tk.DISABLED)
        self.gimbal_controls = GimbalControls(side, self.root, self._set_status)
        ttk.Button(side, text=T_SAVE, command=self.save_snapshot).pack(fill=tk.X, padx=16, pady=(4, 8))
        ttk.Button(side, text=T_EXIT, command=self.close).pack(fill=tk.X, padx=16, pady=(0, 14))
        tk.Label(side, textvariable=self.summary_text, bg="#181d22", fg="#9fb0c2", justify=tk.LEFT, font=("Consolas", 10)).pack(anchor="w", padx=16, pady=(0, 16))

    def _load_model(self) -> None:
        try:
            from ultralytics import YOLO
            self.model = YOLO(YOLO_MODEL_PATH)
            names = getattr(self.model, "names", {}) or {}
            self.model_names = {int(k): str(v) for k, v in names.items()}
            ids = {idx for idx, name in self.model_names.items() if name.lower() in FRUIT_CN}
            self.fruit_class_ids = ids or set(FALLBACK_FRUIT_CLASS_IDS)
            status = f"YOLOv8n ready: {Path(YOLO_MODEL_PATH).name}"
        except Exception as exc:
            self.model = None
            status = f"{T_NO_MODEL}: {exc}"
        try:
            if Path(YOLO_CLS_MODEL_PATH).exists():
                self.cls_model = YOLO(YOLO_CLS_MODEL_PATH)
                names = getattr(self.cls_model, "names", {}) or {}
                self.cls_names = {int(k): str(v) for k, v in names.items()}
                status += f" + cls: {Path(YOLO_CLS_MODEL_PATH).name}"
        except Exception as exc:
            self.cls_model = None
            status += f"; cls fail: {exc}"
        self._set_status(status)

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
            if self.model is None:
                time.sleep(0.2)
                continue
            with self.frame_lock:
                frame = None if self.frame is None else self.frame.copy()
            if frame is not None:
                normal = self._normal_frame(frame)
                t0 = time.time()
                detections = self._detect_fruits(normal)
                if not detections:
                    fallback = self._classify_picture(normal)
                    if fallback is None:
                        fallback = self._color_picture_guess(normal)
                    if fallback is not None:
                        detections = [fallback]
                detections, self._stable_signatures = stable_filter(
                    self._stable_signatures,
                    detections,
                    label_fn=lambda d: d.name_cn,
                    box_fn=lambda d: d.box,
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

    def _detect_fruits(self, image: np.ndarray) -> list[FruitDetection]:
        if self.model is None:
            return []
        try:
            results = self.model.predict(image, imgsz=YOLO_IMG_SIZE, conf=CONF_THRESHOLD, classes=sorted(self.fruit_class_ids), verbose=False, device="cpu")
        except Exception as exc:
            self._set_status(f"YOLO error: {exc}")
            return []
        detections: list[FruitDetection] = []
        if not results:
            return detections
        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return detections
        for box in boxes:
            try:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            except Exception:
                continue
            name_en = self.model_names.get(cls_id, str(cls_id)).lower()
            if name_en not in FRUIT_CN:
                continue
            x1 = max(0, min(image.shape[1] - 1, x1)); x2 = max(0, min(image.shape[1] - 1, x2))
            y1 = max(0, min(image.shape[0] - 1, y1)); y2 = max(0, min(image.shape[0] - 1, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            if not box_is_target(image, (x1, y1, x2, y2), min_area=image.shape[0] * image.shape[1] * 0.018, max_area_ratio=0.62, min_side=54, min_aspect=0.35, max_aspect=2.8):
                continue
            detections.append(FruitDetection(name_en, FRUIT_CN[name_en], (x1, y1, x2, y2), conf, ((x1 + x2) // 2, (y1 + y2) // 2), "detect"))
        detections.sort(key=lambda d: d.confidence, reverse=True)
        return detections[:3]

    def _largest_picture_region(self, image: np.ndarray) -> tuple[int, int, int, int]:
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 45, 130)
        kernel = np.ones((7, 7), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_area = 0
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            area = bw * bh
            if area > best_area and area > w * h * 0.06 and bw > 80 and bh > 80:
                best = (x, y, x + bw, y + bh)
                best_area = area
        if best is not None:
            return best
        margin_x = int(w * 0.12)
        margin_y = int(h * 0.12)
        return (margin_x, margin_y, w - margin_x, h - margin_y)

    def _color_picture_guess(self, image: np.ndarray) -> FruitDetection | None:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        sat_mask = cv2.inRange(hsv, np.array((0, 45, 45), dtype=np.uint8), np.array((180, 255, 255), dtype=np.uint8))
        kernel = np.ones((7, 7), np.uint8)
        sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        sat_mask = cv2.morphologyEx(sat_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(sat_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        best_area = 0.0
        h, w = image.shape[:2]
        for c in contours:
            area = cv2.contourArea(c)
            if area < max(2200, w * h * 0.020):
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            if bw < 35 or bh < 35:
                continue
            if not box_is_target(image, (x, y, x + bw, y + bh), min_area=max(2200, w * h * 0.020), max_area_ratio=0.62, min_side=54, min_aspect=0.35, max_aspect=2.8):
                continue
            if area > best_area:
                best = (c, x, y, bw, bh)
                best_area = area
        if best is None:
            return None
        c, x, y, bw, bh = best
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [c], -1, 255, -1)
        mean_hsv = cv2.mean(hsv, mask=mask)
        hue = mean_hsv[0]
        aspect = bw / max(1, bh)
        extent = best_area / max(1, bw * bh)
        name_en = "fruit"
        name_cn = "\u6c34\u679c"
        if hue <= 10 or hue >= 168:
            name_en = "strawberry" if extent < 0.62 or bh > bw * 1.15 else "apple"
            name_cn = FRUIT_CN.get(name_en, name_cn)
        elif 10 < hue <= 24:
            name_en = "orange"
            name_cn = FRUIT_CN.get(name_en, name_cn)
        elif 24 < hue <= 38:
            name_en = "banana" if aspect > 1.35 or aspect < 0.74 else "pineapple"
            name_cn = FRUIT_CN.get(name_en, name_cn)
        elif 38 < hue <= 85:
            name_en = "watermelon" if bw > bh * 1.20 else "pear"
            name_cn = FRUIT_CN.get(name_en, name_cn)
        elif 125 <= hue <= 165:
            name_en = "grape"
            name_cn = FRUIT_CN.get(name_en, name_cn)
        return FruitDetection(name_en, name_cn, (x, y, x + bw, y + bh), 0.20, (x + bw // 2, y + bh // 2), "color")

    def _classify_picture(self, image: np.ndarray) -> FruitDetection | None:
        if self.cls_model is None:
            return None
        x1, y1, x2, y2 = self._largest_picture_region(image)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        try:
            results = self.cls_model.predict(crop, imgsz=YOLO_IMG_SIZE, verbose=False, device="cpu")
        except Exception as exc:
            self._set_status(f"YOLO cls error: {exc}")
            return None
        if not results:
            return None
        probs = getattr(results[0], "probs", None)
        if probs is None:
            return None
        try:
            top5 = probs.top5
            confs = probs.top5conf.tolist()
        except Exception:
            return None
        for cls_id, conf in zip(top5, confs):
            raw = self.cls_names.get(int(cls_id), str(cls_id)).lower().replace(" ", "_")
            for key, cn in FRUIT_CLS_KEYWORDS.items():
                if key in raw and float(conf) >= max(0.12, CONF_THRESHOLD * 0.45):
                    return FruitDetection(raw, cn, (x1, y1, x2, y2), float(conf), ((x1 + x2) // 2, (y1 + y2) // 2), "image")
        return None

    def _annotate(self, image: np.ndarray, detections: list[FruitDetection]) -> np.ndarray:
        out = image.copy()
        draw_target_roi(out)
        for det in detections:
            x1, y1, x2, y2 = det.box
            color = COLOR_BOX_COLOR if det.source == "color" else (FALLBACK_BOX_COLOR if det.source == "image" else BOX_COLOR)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 3)
            label = f"{det.name_en} {det.confidence:.2f}"
            text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.70, 2)
            tw, th = text_size
            y0 = max(0, y1 - th - 16)
            cv2.rectangle(out, (x1, y0), (x1 + tw + 18, y0 + th + 14), color, -1)
            cv2.putText(out, label, (x1 + 9, y0 + th + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (8, 18, 12), 2, cv2.LINE_AA)
        cv2.putText(out, f"FPS {self.fps:.1f}", (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (100, 255, 180), 2, cv2.LINE_AA)
        return out

    def _set_results(self, detections: list[FruitDetection]) -> None:
        if detections:
            lines = [f"{idx}. {d.name_cn}  {d.confidence:.2f}  {T_IMAGE_MODE if d.source == 'image' else ('Color' if d.source == 'color' else 'YOLO')}  ({d.center[0]}, {d.center[1]})" for idx, d in enumerate(detections, 1)]
            text = "\n".join(lines)
        else:
            text = T_NO_FRUIT
        self.result_box.configure(state=tk.NORMAL)
        self.result_box.delete("1.0", tk.END)
        self.result_box.insert("1.0", text)
        self.result_box.configure(state=tk.DISABLED)
        classes = ", ".join(FRUIT_CN.get(self.model_names.get(i, ""), self.model_names.get(i, "")) for i in sorted(self.fruit_class_ids))
        self.summary_text.set(f"device: {CAMERA_DEVICE}\ninput: {CAMERA_WIDTH}x{CAMERA_HEIGHT}\nview: {T_NORMAL_VIEW}\nyolo: {Path(YOLO_MODEL_PATH).name}\nclasses: {classes}\nfps: {self.fps:.1f}\ndet: {self.det_fps:.1f}/s")

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
        path = SNAPSHOT_DIR / time.strftime("fruit_%Y%m%d_%H%M%S.jpg")
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
    FruitRecognitionApp().run()
