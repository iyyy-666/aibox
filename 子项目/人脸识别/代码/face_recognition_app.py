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

from vision_targeting import box_is_target, draw_target_roi, split_stereo


CAMERA_DEVICE = os.getenv("FACE_CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("FACE_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("FACE_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("FACE_CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("FACE_DISPLAY_INTERVAL_MS", "160"))
CAPTURE_INTERVAL_SEC = float(os.getenv("FACE_CAPTURE_INTERVAL_SEC", "0.055"))
DETECT_INTERVAL_SEC = float(os.getenv("FACE_DETECT_INTERVAL_SEC", "1.10"))
DETECT_SCALE = float(os.getenv("FACE_DETECT_SCALE", "0.38"))
CASCADE_PATH = os.getenv("FACE_CASCADE_PATH", "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml")
DNN_PROTO = os.getenv("FACE_DNN_PROTO", "/root/robot_arm/models/face_dnn/deploy.prototxt")
DNN_MODEL = os.getenv("FACE_DNN_MODEL", "/root/robot_arm/models/face_dnn/res10_300x300_ssd_iter_140000_fp16.caffemodel")
DNN_CONF_THRESHOLD = float(os.getenv("FACE_DNN_CONF_THRESHOLD", "0.68"))
USE_DNN = os.getenv("FACE_USE_DNN", "1").strip().lower() in {"1", "true", "yes", "on"}
YUNET_MODEL = os.getenv("FACE_YUNET_MODEL", "/root/robot_arm/models/face_detection_yunet_2023mar.onnx")
YUNET_INPUT_WIDTH = int(os.getenv("FACE_YUNET_INPUT_WIDTH", "320"))
YUNET_INPUT_HEIGHT = int(os.getenv("FACE_YUNET_INPUT_HEIGHT", "320"))
YUNET_SCORE_THRESHOLD = float(os.getenv("FACE_YUNET_SCORE_THRESHOLD", "0.78"))
YUNET_NMS_THRESHOLD = float(os.getenv("FACE_YUNET_NMS_THRESHOLD", "0.30"))
USE_YUNET = os.getenv("FACE_USE_YUNET", "0").strip().lower() in {"1", "true", "yes", "on"}
SNAPSHOT_DIR = Path(os.getenv("FACE_SNAPSHOT_DIR", "/root/robot_arm/assets/face_snapshots"))
CASCADE_PATHS = [
    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_alt2.xml",
    "/usr/share/opencv4/lbpcascades/lbpcascade_frontalface_improved.xml",
]


class FaceRecognitionApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("人脸识别")
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
        self.faces: list[tuple[int, int, int, int, float]] = []
        self.face_lock = threading.Lock()
        self.photo: tk.PhotoImage | None = None
        self.last_view: np.ndarray | None = None
        self.fps = 0.0
        self.last_frame_time = 0.0
        self.dnn = self._load_dnn()
        self.yunet = self._load_yunet()
        self.face_detectors = self._load_cascades()

        self._build_ui()
        if not self.face_detectors and self.yunet is None and self.dnn is None:
            self.status_text.set("人脸模型加载失败")
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._detect_loop, daemon=True).start()
        self._update_view()

    def _load_dnn(self):
        if not USE_DNN or not Path(DNN_PROTO).exists() or not Path(DNN_MODEL).exists():
            return None
        try:
            net = cv2.dnn.readNetFromCaffe(DNN_PROTO, DNN_MODEL)
            net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            return net
        except Exception:
            return None

    def _load_yunet(self):
        if not USE_YUNET or not Path(YUNET_MODEL).exists() or not hasattr(cv2, "FaceDetectorYN_create"):
            return None
        try:
            return cv2.FaceDetectorYN_create(
                YUNET_MODEL,
                "",
                (YUNET_INPUT_WIDTH, YUNET_INPUT_HEIGHT),
                YUNET_SCORE_THRESHOLD,
                YUNET_NMS_THRESHOLD,
                5000,
            )
        except Exception:
            return None

    def _load_cascades(self) -> list[cv2.CascadeClassifier]:
        paths = [CASCADE_PATH, *CASCADE_PATHS]
        detectors: list[cv2.CascadeClassifier] = []
        seen: set[str] = set()
        for path in paths:
            if path in seen or not Path(path).exists():
                continue
            seen.add(path)
            detector = cv2.CascadeClassifier(path)
            if not detector.empty():
                detectors.append(detector)
        return detectors

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#1c2228", height=54)
        top.pack(side=tk.TOP, fill=tk.X)
        top.pack_propagate(False)

        tk.Label(top, text="人脸识别", bg="#1c2228", fg="#f5f7fa", font=("Microsoft YaHei", 16, "bold")).pack(side=tk.LEFT, padx=(16, 18))
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
            if frame is not None and (self.dnn is not None or self.yunet is not None or self.face_detectors):
                normal = self._normal_frame(frame)
                faces = self._detect_dnn(normal)
                if not faces:
                    faces = self._detect_yunet(normal)
                if not faces:
                    faces = self._detect_haar(normal)
                with self.face_lock:
                    self.faces = faces
            time.sleep(DETECT_INTERVAL_SEC)

    def _detect_dnn(self, image: np.ndarray) -> list[tuple[int, int, int, int, float]]:
        if self.dnn is None:
            return []
        h, w = image.shape[:2]
        blob = cv2.dnn.blobFromImage(image, 1.0, (300, 300), (104.0, 177.0, 123.0), swapRB=False, crop=False)
        try:
            self.dnn.setInput(blob)
            detections = self.dnn.forward()
        except Exception:
            self.dnn = None
            return []
        results: list[tuple[int, int, int, int, float]] = []
        for i in range(detections.shape[2]):
            score = float(detections[0, 0, i, 2])
            if score < DNN_CONF_THRESHOLD:
                continue
            x1 = int(detections[0, 0, i, 3] * w)
            y1 = int(detections[0, 0, i, 4] * h)
            x2 = int(detections[0, 0, i, 5] * w)
            y2 = int(detections[0, 0, i, 6] * h)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            bw, bh = x2 - x1, y2 - y1
            if bw > 32 and bh > 32 and box_is_target(image, (x1, y1, x2, y2), min_area=w * h * 0.010, max_area_ratio=0.46, min_side=34, min_aspect=0.55, max_aspect=1.75):
                results.append((x1, y1, bw, bh, score))
        return self._merge_faces(results)

    def _detect_yunet(self, image: np.ndarray) -> list[tuple[int, int, int, int, float]]:
        if self.yunet is None:
            return []
        h, w = image.shape[:2]
        resized = cv2.resize(image, (YUNET_INPUT_WIDTH, YUNET_INPUT_HEIGHT), interpolation=cv2.INTER_AREA)
        try:
            self.yunet.setInputSize((YUNET_INPUT_WIDTH, YUNET_INPUT_HEIGHT))
            _, faces = self.yunet.detect(resized)
        except Exception:
            self.yunet = None
            return []
        if faces is None:
            return []
        sx = w / float(YUNET_INPUT_WIDTH)
        sy = h / float(YUNET_INPUT_HEIGHT)
        results: list[tuple[int, int, int, int, float]] = []
        for face in faces:
            x, y, fw, fh = face[:4]
            score = float(face[-1]) if len(face) >= 15 else 0.0
            x1 = max(0, int(x * sx))
            y1 = max(0, int(y * sy))
            bw = min(w - x1, int(fw * sx))
            bh = min(h - y1, int(fh * sy))
            if bw > 28 and bh > 28 and score >= YUNET_SCORE_THRESHOLD and box_is_target(image, (x1, y1, x1 + bw, y1 + bh), min_area=w * h * 0.010, max_area_ratio=0.46, min_side=34, min_aspect=0.55, max_aspect=1.75):
                results.append((x1, y1, bw, bh, score))
        return results

    def _detect_haar(self, image: np.ndarray) -> list[tuple[int, int, int, int, float]]:
        if not self.face_detectors:
            return []
        small = cv2.resize(image, (0, 0), fx=DETECT_SCALE, fy=DETECT_SCALE, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        raw_faces: list[tuple[int, int, int, int]] = []
        for detector in self.face_detectors:
            faces = detector.detectMultiScale(
                gray,
                scaleFactor=1.08,
                minNeighbors=4,
                minSize=(24, 24),
                flags=cv2.CASCADE_SCALE_IMAGE,
            )
            raw_faces.extend(tuple(map(int, face)) for face in faces)
        inv_scale = 1.0 / max(0.1, DETECT_SCALE)
        scaled = [
            (int(x * inv_scale), int(y * inv_scale), int(w * inv_scale), int(h * inv_scale), 0.0)
            for x, y, w, h in raw_faces
        ]
        h, w = image.shape[:2]
        scaled = [
            face for face in scaled
            if box_is_target(image, (face[0], face[1], face[0] + face[2], face[1] + face[3]), min_area=w * h * 0.012, max_area_ratio=0.46, min_side=38, min_aspect=0.60, max_aspect=1.65)
        ]
        return self._merge_faces(scaled)

    def _merge_faces(self, faces: list[tuple[int, int, int, int, float]]) -> list[tuple[int, int, int, int, float]]:
        merged: list[tuple[int, int, int, int, float]] = []
        for face in sorted(faces, key=lambda item: item[2] * item[3], reverse=True):
            x, y, w, h, score = face
            duplicate = False
            for mx, my, mw, mh, _ in merged:
                ix1, iy1 = max(x, mx), max(y, my)
                ix2, iy2 = min(x + w, mx + mw), min(y + h, my + mh)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                union = w * h + mw * mh - inter
                if union > 0 and inter / union > 0.35:
                    duplicate = True
                    break
            if not duplicate:
                merged.append(face)
        return merged[:4]

    def _annotate(self, image: np.ndarray, faces: list[tuple[int, int, int, int, float]]) -> np.ndarray:
        out = image.copy()
        draw_target_roi(out)
        for idx, (x, y, w, h, score) in enumerate(faces, 1):
            cv2.rectangle(out, (x, y), (x + w, y + h), (60, 220, 120), 3)
            label = f"Face {idx}" if score <= 0 else f"Face {idx} {score:.2f}"
            text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.72, 2)
            tw, th = text_size
            y0 = max(0, y - th - 16)
            cv2.rectangle(out, (x, y0), (x + tw + 18, y0 + th + 14), (60, 220, 120), -1)
            cv2.putText(out, label, (x + 9, y0 + th + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (10, 18, 12), 2, cv2.LINE_AA)
        cv2.putText(out, f"FPS {self.fps:.1f}", (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (100, 255, 180), 2, cv2.LINE_AA)
        return out

    def _set_results(self, faces: list[tuple[int, int, int, int, float]]) -> None:
        if faces:
            lines = []
            for idx, (x, y, w, h, score) in enumerate(faces, 1):
                conf = "" if score <= 0 else f"  置信度{score:.2f}"
                lines.append(f"{idx}. 人脸  位置({x + w // 2}, {y + h // 2})  大小({w}x{h}){conf}")
            text = "\n".join(lines)
        else:
            text = "未检测到人脸"
        self.result_box.configure(state=tk.NORMAL)
        self.result_box.delete("1.0", tk.END)
        self.result_box.insert("1.0", text)
        self.result_box.configure(state=tk.DISABLED)
        self.summary_text.set(f"device: {CAMERA_DEVICE}\ninput: {CAMERA_WIDTH}x{CAMERA_HEIGHT}\nview: 正常画面\nfaces: {len(faces)}\nfps: {self.fps:.1f}")

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()
        with self.face_lock:
            faces = list(self.faces)

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        if frame is None:
            self.canvas.create_text(cw // 2, ch // 2, fill="#dfe7f2", font=("Microsoft YaHei", 16), text="等待摄像头画面")
        else:
            normal = self._normal_frame(frame)
            view = self._annotate(normal, faces)
            self.last_view = view.copy()
            rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            scale = min(cw / w, ch / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            header = f"P6 {nw} {nh} 255\n".encode("ascii")
            self.photo = tk.PhotoImage(data=header + rgb.tobytes(), format="PPM")
            self.canvas.create_image(cw // 2, ch // 2, image=self.photo, anchor=tk.CENTER)
            self._set_results(faces)

        if self.running:
            self.root.after(DISPLAY_INTERVAL_MS, self._update_view)

    def save_snapshot(self) -> None:
        if self.last_view is None:
            self._set_status("还没有可保存的画面")
            return
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOT_DIR / time.strftime("face_%Y%m%d_%H%M%S.jpg")
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
    FaceRecognitionApp().run()
