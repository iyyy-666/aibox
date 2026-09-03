#!/usr/bin/env python3
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from tkinter import ttk
import tkinter as tk

import cv2
import numpy as np


CAMERA_DEVICE = os.getenv("CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("CAMERA_DISPLAY_INTERVAL_MS", "95"))
CAPTURE_INTERVAL_SEC = float(os.getenv("CAMERA_CAPTURE_INTERVAL_SEC", "0.025"))
SHARPEN_AMOUNT = float(os.getenv("CAMERA_SHARPEN_AMOUNT", "0.16"))
SNAPSHOT_DIR = Path(os.getenv("CAMERA_SNAPSHOT_DIR", "/root/robot_arm/assets/camera_snapshots"))


class CameraViewApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("\u6444\u50cf\u5934\u753b\u9762")
        self.root.geometry("1180x720")
        self.root.minsize(960, 560)
        self.root.configure(bg="#121417")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.mode = tk.StringVar(value="fusion")
        self.status_text = tk.StringVar(value="\u6b63\u5728\u6253\u5f00\u6444\u50cf\u5934...")
        self.metric_text = tk.StringVar(value="-")

        self.running = True
        self.cap: cv2.VideoCapture | None = None
        self.frame: np.ndarray | None = None
        self.frame_lock = threading.Lock()
        self.photo: tk.PhotoImage | None = None
        self.fps = 0.0
        self.last_frame_time = 0.0
        self.last_view: np.ndarray | None = None

        self._build_ui()
        threading.Thread(target=self._capture_loop, daemon=True).start()
        self._update_view()

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#1d2228", height=54)
        top.pack(side=tk.TOP, fill=tk.X)
        top.pack_propagate(False)

        tk.Label(
            top,
            text="\u6444\u50cf\u5934\u753b\u9762",
            bg="#1d2228",
            fg="#f3f6fa",
            font=("Microsoft YaHei", 16, "bold"),
        ).pack(side=tk.LEFT, padx=(16, 18))

        tk.Label(
            top,
            textvariable=self.status_text,
            bg="#1d2228",
            fg="#aeb8c5",
            font=("Microsoft YaHei", 10),
        ).pack(side=tk.LEFT)

        body = tk.Frame(self.root, bg="#121417")
        body.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(body, bg="#080a0d", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 8), pady=12)

        panel = tk.Frame(body, bg="#181c21", width=248)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        panel.pack_propagate(False)

        tk.Label(panel, text="\u753b\u9762\u6a21\u5f0f", bg="#181c21", fg="#eef3f8", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", padx=16, pady=(16, 8))
        modes = [
            ("\u6b63\u5e38\u753b\u9762", "fusion"),
            ("\u5de6\u773c\u753b\u9762", "left"),
            ("\u53f3\u773c\u753b\u9762", "right"),
            ("\u539f\u59cb\u53cc\u76ee", "raw"),
        ]
        for text, value in modes:
            ttk.Radiobutton(panel, text=text, variable=self.mode, value=value).pack(anchor="w", padx=18, pady=4)

        ttk.Button(panel, text="\u4fdd\u5b58\u5f53\u524d\u753b\u9762", command=self.save_snapshot).pack(fill=tk.X, padx=16, pady=(18, 8))
        ttk.Button(panel, text="\u9000\u51fa", command=self.close).pack(fill=tk.X, padx=16, pady=4)

        tk.Label(panel, text="\u72b6\u6001", bg="#181c21", fg="#eef3f8", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", padx=16, pady=(24, 8))
        tk.Label(panel, textvariable=self.metric_text, bg="#181c21", fg="#aeb8c5", justify=tk.LEFT, font=("Consolas", 10)).pack(anchor="w", padx=16)

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
                    self._set_status(f"\u6444\u50cf\u5934\u6253\u5f00\u5931\u8d25: {CAMERA_DEVICE}")
                    retry_at = time.time() + 2.0
                    continue
                self._set_status(f"\u5df2\u6253\u5f00 {CAMERA_DEVICE}  {CAMERA_WIDTH}x{CAMERA_HEIGHT}@{CAMERA_FPS}")

            ok, frame = self.cap.read()
            if not ok or frame is None:
                self._set_status("\u8bfb\u53d6\u753b\u9762\u5931\u8d25\uff0c\u6b63\u5728\u91cd\u8bd5...")
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

    def _split_stereo(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h, w = frame.shape[:2]
        mid = w // 2
        left = frame[:, :mid]
        right = frame[:, mid:w]
        if left.shape[:2] != right.shape[:2]:
            right = cv2.resize(right, (left.shape[1], left.shape[0]), interpolation=cv2.INTER_AREA)
        return left, right

    def _shift_x(self, image: np.ndarray, pixels: int) -> np.ndarray:
        if pixels == 0:
            return image
        h, w = image.shape[:2]
        matrix = np.float32([[1, 0, pixels], [0, 1, 0]])
        return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def _enhance(self, image: np.ndarray) -> np.ndarray:
        amount = max(0.0, min(0.40, SHARPEN_AMOUNT))
        if amount <= 0.01:
            return image
        blur = cv2.GaussianBlur(image, (0, 0), 1.1)
        return cv2.addWeighted(image, 1.0 + amount, blur, -amount, 0)

    def _compose_frame(self, frame: np.ndarray) -> np.ndarray:
        left, right = self._split_stereo(frame)
        mode = self.mode.get()
        if mode == "left":
            return self._enhance(left.copy())
        if mode == "right":
            return self._enhance(right.copy())
        if mode == "raw":
            return frame.copy()

        return self._enhance(left.copy())

    def _draw_overlay(self, rgb: np.ndarray) -> np.ndarray:
        label = {
            "fusion": "\u6b63\u5e38\u753b\u9762",
            "left": "\u5de6\u773c",
            "right": "\u53f3\u773c",
            "raw": "\u539f\u59cb\u53cc\u76ee",
        }.get(self.mode.get(), "")
        cv2.rectangle(rgb, (10, 10), (310, 56), (10, 14, 18), -1)
        cv2.putText(rgb, f"FPS {self.fps:.1f}", (20, 39), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (120, 255, 185), 2, cv2.LINE_AA)
        self.metric_text.set(
            f"device: {CAMERA_DEVICE}\n"
            f"input: {CAMERA_WIDTH}x{CAMERA_HEIGHT}\n"
            f"mode: {label}\n"
            f"view: left eye normal\n"
            f"fps: {self.fps:.1f}"
        )
        return rgb

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()

        self.canvas.delete("all")
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())

        if frame is None:
            self.canvas.create_text(cw // 2, ch // 2, fill="#dfe7f2", font=("Microsoft YaHei", 16), text="\u7b49\u5f85\u6444\u50cf\u5934\u753b\u9762")
        else:
            view = self._compose_frame(frame)
            self.last_view = view.copy()
            view = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            h, w = view.shape[:2]
            scale = min(cw / w, ch / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            view = cv2.resize(view, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            view = self._draw_overlay(view)
            header = f"P6 {nw} {nh} 255\n".encode("ascii")
            self.photo = tk.PhotoImage(data=header + view.tobytes(), format="PPM")
            self.canvas.create_image(cw // 2, ch // 2, image=self.photo, anchor=tk.CENTER)

        if self.running:
            self.root.after(DISPLAY_INTERVAL_MS, self._update_view)

    def save_snapshot(self) -> None:
        if self.last_view is None:
            self._set_status("\u8fd8\u6ca1\u6709\u53ef\u4fdd\u5b58\u7684\u753b\u9762")
            return
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOT_DIR / time.strftime("camera_%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(str(path), self.last_view, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        self._set_status(f"\u5df2\u4fdd\u5b58: {path}")

    def close(self) -> None:
        self.running = False
        if self.cap is not None:
            self.cap.release()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    CameraViewApp().run()
