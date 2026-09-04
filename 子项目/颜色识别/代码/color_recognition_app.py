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


CAMERA_DEVICE = os.getenv("COLOR_CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("COLOR_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("COLOR_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("COLOR_CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("COLOR_DISPLAY_INTERVAL_MS", "110"))
CAPTURE_INTERVAL_SEC = float(os.getenv("COLOR_CAPTURE_INTERVAL_SEC", "0.035"))
DETECT_INTERVAL_SEC = float(os.getenv("COLOR_DETECT_INTERVAL_SEC", "0.18"))
MIN_AREA = int(os.getenv("COLOR_MIN_AREA", "1800"))
STABLE_HITS = int(os.getenv("COLOR_STABLE_HITS", "2"))
SNAPSHOT_DIR = Path(os.getenv("COLOR_SNAPSHOT_DIR", "/root/robot_arm/assets/color_snapshots"))


@dataclass
class Detection:
    name: str
    box: tuple[int, int, int, int]
    area: float
    center: tuple[int, int]
    bgr: tuple[int, int, int]


COLOR_RANGES = [
    ("Red", ((0, 70, 70), (10, 255, 255)), (45, 45, 235)),
    ("Red", ((170, 70, 70), (180, 255, 255)), (45, 45, 235)),
    ("Orange", ((11, 80, 80), (24, 255, 255)), (0, 150, 255)),
    ("Yellow", ((25, 70, 80), (36, 255, 255)), (0, 225, 255)),
    ("Green", ((37, 45, 45), (85, 255, 255)), (80, 210, 80)),
    ("Cyan", ((86, 45, 60), (99, 255, 255)), (210, 210, 40)),
    ("Blue", ((100, 55, 45), (130, 255, 255)), (235, 120, 45)),
    ("Purple", ((131, 45, 45), (155, 255, 255)), (210, 70, 210)),
    ("Pink", ((156, 45, 80), (169, 255, 255)), (210, 90, 235)),
]


def merge_red_ranges(items: list[Detection]) -> list[Detection]:
    red = [d for d in items if d.name == "Red"]
    others = [d for d in items if d.name != "Red"]
    if len(red) <= 1:
        return items
    contours = []
    for d in red:
        x, y, w, h = d.box
        contours.append(np.array([[[x, y]], [[x + w, y]], [[x + w, y + h]], [[x, y + h]]], dtype=np.int32))
    x, y, w, h = cv2.boundingRect(np.vstack(contours))
    area = float(sum(d.area for d in red))
    merged = Detection("Red", (x, y, w, h), area, (x + w // 2, y + h // 2), (45, 45, 235))
    return others + [merged]


class ColorRecognitionApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("颜色识别")
        self.root.geometry("1180x720")
        self.root.minsize(960, 560)
        self.root.configure(bg="#111417")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status_text = tk.StringVar(value="正在打开摄像头...")
        self.summary_text = tk.StringVar(value="等待画面")
        self.running = True
        self.cap: cv2.VideoCapture | None = None
        self.frame: np.ndarray | None = None
        self.frame_lock = threading.Lock()
        self.photo: tk.PhotoImage | None = None
        self.last_view: np.ndarray | None = None
        self.detections: list[Detection] = []
        self.detect_lock = threading.Lock()
        self._stable_signatures: dict[str, int] = {}
        self.fps = 0.0
        self.last_frame_time = 0.0

        self._build_ui()
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._detect_loop, daemon=True).start()
        self._update_view()

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#1c2228", height=54)
        top.pack(side=tk.TOP, fill=tk.X)
        top.pack_propagate(False)

        tk.Label(top, text="颜色识别", bg="#1c2228", fg="#f5f7fa", font=("Microsoft YaHei", 16, "bold")).pack(side=tk.LEFT, padx=(16, 18))
        tk.Label(top, textvariable=self.status_text, bg="#1c2228", fg="#aeb8c5", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)

        body = tk.Frame(self.root, bg="#111417")
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, bg="#080a0d", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 8), pady=12)

        side = tk.Frame(body, bg="#181d22", width=260)
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        side.pack_propagate(False)
        tk.Label(side, text="识别结果", bg="#181d22", fg="#f1f5f9", font=("Microsoft YaHei", 13, "bold")).pack(anchor="w", padx=16, pady=(16, 10))
        self.result_box = tk.Text(side, height=18, bg="#0f1317", fg="#e8eef5", insertbackground="#e8eef5", relief=tk.FLAT, font=("Microsoft YaHei", 11), wrap=tk.WORD)
        self.result_box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        self.result_box.insert("1.0", "等待识别")
        self.result_box.configure(state=tk.DISABLED)
        ttk.Button(side, text="保存当前画面", command=self.save_snapshot).pack(fill=tk.X, padx=16, pady=(4, 8))
        ttk.Button(side, text="退出", command=self.close).pack(fill=tk.X, padx=16, pady=(0, 14))
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
                    self._set_status(f"摄像头打开失败: {CAMERA_DEVICE}")
                    retry_at = time.time() + 2.0
                    continue
                self._set_status(f"已打开 {CAMERA_DEVICE}  {CAMERA_WIDTH}x{CAMERA_HEIGHT}@{CAMERA_FPS}")

            ok, frame = self.cap.read()
            if not ok or frame is None:
                self._set_status("读取画面失败，正在重试...")
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
                detections = self._detect_colors(normal)
                detections, self._stable_signatures = stable_filter(
                    self._stable_signatures,
                    detections,
                    label_fn=lambda d: d.name,
                    box_fn=lambda d: (d.box[0], d.box[1], d.box[0] + d.box[2], d.box[1] + d.box[3]),
                    image_shape=normal.shape,
                    stable_hits=STABLE_HITS,
                )
                with self.detect_lock:
                    self.detections = detections
            time.sleep(DETECT_INTERVAL_SEC)

    def _detect_colors(self, image: np.ndarray) -> list[Detection]:
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        kernel = np.ones((5, 5), np.uint8)
        results: list[Detection] = []
        for name, (lower, upper), bgr in COLOR_RANGES:
            mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < MIN_AREA:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                if w < 20 or h < 20:
                    continue
                if not box_is_target(image, (x, y, x + w, y + h), min_area=max(MIN_AREA, image.shape[0] * image.shape[1] * 0.006), max_area_ratio=0.45, min_side=34):
                    continue
                results.append(Detection(name, (x, y, w, h), area, (x + w // 2, y + h // 2), bgr))
        results = merge_red_ranges(results)
        results.sort(key=lambda d: d.area, reverse=True)
        return results[:4]

    def _annotate(self, image: np.ndarray, detections: list[Detection]) -> np.ndarray:
        out = image.copy()
        draw_target_roi(out)
        for det in detections:
            x, y, w, h = det.box
            cv2.rectangle(out, (x, y), (x + w, y + h), det.bgr, 3)
            text_size, _ = cv2.getTextSize(det.name, cv2.FONT_HERSHEY_SIMPLEX, 0.72, 2)
            tw, th = text_size
            y0 = max(0, y - th - 16)
            cv2.rectangle(out, (x, y0), (x + tw + 18, y0 + th + 14), det.bgr, -1)
            cv2.putText(out, det.name, (x + 9, y0 + th + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(out, f"FPS {self.fps:.1f}", (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (100, 255, 180), 2, cv2.LINE_AA)
        return out

    def _set_results(self, detections: list[Detection]) -> None:
        if detections:
            lines = [f"{idx}. {d.name}  位置({d.center[0]}, {d.center[1]})" for idx, d in enumerate(detections, 1)]
            text = "\n".join(lines)
        else:
            text = "未检测到明显颜色物品"
        self.result_box.configure(state=tk.NORMAL)
        self.result_box.delete("1.0", tk.END)
        self.result_box.insert("1.0", text)
        self.result_box.configure(state=tk.DISABLED)
        self.summary_text.set(f"device: {CAMERA_DEVICE}\ninput: {CAMERA_WIDTH}x{CAMERA_HEIGHT}\nview: 正常画面\nfps: {self.fps:.1f}")

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()
        with self.detect_lock:
            detections = list(self.detections)

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        if frame is None:
            self.canvas.create_text(cw // 2, ch // 2, fill="#dfe7f2", font=("Microsoft YaHei", 16), text="等待摄像头画面")
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
            self._set_status("还没有可保存的画面")
            return
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOT_DIR / time.strftime("color_%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(str(path), self.last_view, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        self._set_status(f"已保存: {path}")

    def close(self) -> None:
        self.running = False
        if self.cap is not None:
            self.cap.release()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ColorRecognitionApp().run()
