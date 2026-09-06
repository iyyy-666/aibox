#!/usr/bin/env python3
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np

from vision_targeting import split_stereo


CAMERA_DEVICE = os.getenv("CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("CAMERA_DISPLAY_INTERVAL_MS", "33"))
CAPTURE_INTERVAL_SEC = float(os.getenv("CAMERA_CAPTURE_INTERVAL_SEC", "0.025"))
SNAPSHOT_DIR = Path(os.getenv("CAMERA_SNAPSHOT_DIR", "/root/robot_arm/assets/camera_snapshots"))
USE_HARDWARE_DECODER = os.getenv("CAMERA_USE_HARDWARE_DECODER", "1").strip().lower() in {"1", "true", "yes", "on"}


def gstreamer_capture_pipeline() -> str:
    return (
        f"v4l2src device={CAMERA_DEVICE} ! image/jpeg,width={CAMERA_WIDTH},height={CAMERA_HEIGHT},"
        f"framerate={CAMERA_FPS}/1 ! mppjpegdec ! videoconvert ! video/x-raw,format=BGR ! "
        "appsink name=sink sync=false max-buffers=1 drop=true"
    )


class CameraViewApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("\u6444\u50cf\u5934\u753b\u9762")
        self.root.geometry("1180x720")
        self.root.minsize(960, 560)
        self.root.configure(bg="#111417")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.running = True
        self.mode = tk.StringVar(value="left")
        self.status_text = tk.StringVar(value="\u6b63\u5728\u6253\u5f00\u6444\u50cf\u5934...")
        self.cap: cv2.VideoCapture | None = None
        self.frame: np.ndarray | None = None
        self.frame_lock = threading.Lock()
        self.photo: tk.PhotoImage | None = None
        self.last_view: np.ndarray | None = None
        self._build_ui()
        threading.Thread(target=self._capture_loop, daemon=True).start()
        self._update_view()

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#1c2228", height=54)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="\u6444\u50cf\u5934\u753b\u9762", bg="#1c2228", fg="#f5f7fa", font=("Microsoft YaHei", 16, "bold")).pack(side=tk.LEFT, padx=16)
        tk.Label(top, textvariable=self.status_text, bg="#1c2228", fg="#aeb8c5").pack(side=tk.LEFT)
        body = tk.Frame(self.root, bg="#111417")
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, bg="#080a0d", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 8), pady=12)
        panel = tk.Frame(body, bg="#181d22", width=220)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        panel.pack_propagate(False)
        for text, value in (("\u666e\u901a\u753b\u9762", "left"), ("\u5de6\u76ee", "left"), ("\u53f3\u76ee", "right"), ("\u539f\u59cb\u53cc\u76ee", "raw")):
            ttk.Radiobutton(panel, text=text, variable=self.mode, value=value).pack(anchor="w", padx=16, pady=8)
        ttk.Button(panel, text="\u4fdd\u5b58\u5f53\u524d\u753b\u9762", command=self.save_snapshot).pack(fill=tk.X, padx=16, pady=(20, 8))
        ttk.Button(panel, text="\u9000\u51fa", command=self.close).pack(fill=tk.X, padx=16)

    def _open_camera(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _capture_loop(self) -> None:
        if USE_HARDWARE_DECODER and self._capture_hardware_loop():
            return
        self._set_status("硬件解码不可用，已切换为兼容采集")
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
                self._set_status(f"\u5df2\u6253\u5f00 {CAMERA_DEVICE} {CAMERA_WIDTH}x{CAMERA_HEIGHT}@{CAMERA_FPS}")
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.cap.release()
                self.cap = None
                self._set_status("\u8bfb\u53d6\u753b\u9762\u5931\u8d25\uff0c\u6b63\u5728\u91cd\u8bd5...")
                continue
            with self.frame_lock:
                self.frame = frame
            time.sleep(CAPTURE_INTERVAL_SEC)

    def _capture_hardware_loop(self) -> bool:
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst

            Gst.init(None)
            pipeline = Gst.parse_launch(gstreamer_capture_pipeline())
            sink = pipeline.get_by_name("sink")
            pipeline.set_state(Gst.State.PLAYING)
            self._set_status(f"已打开 {CAMERA_DEVICE} 硬件解码 {CAMERA_WIDTH}x{CAMERA_HEIGHT}@{CAMERA_FPS}")
            while self.running:
                sample = sink.emit("try-pull-sample", Gst.SECOND)
                if sample is None:
                    break
                buffer = sample.get_buffer()
                ok, mapping = buffer.map(Gst.MapFlags.READ)
                if not ok:
                    continue
                try:
                    frame = np.frombuffer(mapping.data, dtype=np.uint8).reshape(CAMERA_HEIGHT, CAMERA_WIDTH, 3).copy()
                finally:
                    buffer.unmap(mapping)
                with self.frame_lock:
                    self.frame = frame
            return not self.running
        except Exception:
            return False
        finally:
            if "pipeline" in locals():
                pipeline.set_state(Gst.State.NULL)

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_text.set(text))

    def _compose_frame(self, frame: np.ndarray) -> np.ndarray:
        mode = self.mode.get()
        if mode == "raw":
            return frame.copy()
        left, right = split_stereo(frame)
        return right if mode == "right" else left

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()
        self.canvas.delete("all")
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if frame is None:
            self.canvas.create_text(width // 2, height // 2, fill="#dfe7f2", font=("Microsoft YaHei", 16), text="\u7b49\u5f85\u6444\u50cf\u5934\u753b\u9762")
        else:
            view = self._compose_frame(frame)
            self.last_view = view.copy()
            rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            scale = min(width / rgb.shape[1], height / rgb.shape[0])
            size = (max(1, int(rgb.shape[1] * scale)), max(1, int(rgb.shape[0] * scale)))
            rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            self.photo = tk.PhotoImage(data=f"P6 {size[0]} {size[1]} 255\n".encode("ascii") + rgb.tobytes(), format="PPM")
            self.canvas.create_image(width // 2, height // 2, image=self.photo, anchor=tk.CENTER)
        if self.running:
            self.root.after(DISPLAY_INTERVAL_MS, self._update_view)

    def save_snapshot(self) -> None:
        if self.last_view is None:
            self._set_status("\u8fd8\u6ca1\u6709\u53ef\u4fdd\u5b58\u7684\u753b\u9762")
            return
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOT_DIR / time.strftime("camera_%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(str(path), self.last_view)
        self._set_status(f"\u5df2\u4fdd\u5b58: {path}")

    def close(self) -> None:
        self.running = False
        if self.cap is not None:
            self.cap.release()
        self.root.after(80, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    CameraViewApp().run()
