#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
import tkinter as tk

import cv2
import numpy as np

from vision_targeting import box_is_target, draw_target_roi, split_stereo, stable_filter

CAMERA_DEVICE = os.getenv("PLATE_CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("PLATE_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("PLATE_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("PLATE_CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("PLATE_DISPLAY_INTERVAL_MS", "80"))
CAPTURE_INTERVAL_SEC = float(os.getenv("PLATE_CAPTURE_INTERVAL_SEC", "0.025"))
DETECT_INTERVAL_SEC = float(os.getenv("PLATE_DETECT_INTERVAL_SEC", "0.22"))
MIN_PLATE_AREA = int(os.getenv("PLATE_MIN_AREA", "1600"))
STABLE_HITS = int(os.getenv("PLATE_STABLE_HITS", "2"))
SNAPSHOT_DIR = Path(os.getenv("PLATE_SNAPSHOT_DIR", "/root/robot_arm/assets/plate_snapshots"))

T_TITLE = "\u8f66\u724c\u8bc6\u522b"
T_OPENING = "\u6b63\u5728\u6253\u5f00\u6444\u50cf\u5934..."
T_WAIT = "\u7b49\u5f85\u753b\u9762"
T_RESULT = "\u8bc6\u522b\u7ed3\u679c"
T_SAVE = "\u4fdd\u5b58\u5f53\u524d\u753b\u9762"
T_EXIT = "\u9000\u51fa"
T_WAIT_DETECT = "\u7b49\u5f85\u8bc6\u522b"
T_NO_PLATE = "\u672a\u68c0\u6d4b\u5230\u8f66\u724c"
T_SAVED = "\u5df2\u4fdd\u5b58"
T_NO_SAVE = "\u8fd8\u6ca1\u6709\u53ef\u4fdd\u5b58\u7684\u753b\u9762"
T_CAMERA_FAIL = "\u6444\u50cf\u5934\u6253\u5f00\u5931\u8d25"
T_READ_FAIL = "\u8bfb\u53d6\u753b\u9762\u5931\u8d25\uff0c\u6b63\u5728\u91cd\u8bd5..."
T_OPENED = "\u5df2\u6253\u5f00"
T_NORMAL_VIEW = "\u6b63\u5e38\u753b\u9762"
T_BLUE = "\u84dd\u724c"
T_GREEN = "\u7eff\u724c"
T_UNKNOWN = "\u672a\u77e5"
T_OIL = "\u6cb9\u8f66"
T_EV = "\u7535\u8f66"
T_NUMBER = "\u8f66\u724c\u53f7"
T_COLOR = "\u989c\u8272"
T_TYPE = "\u7c7b\u578b"
T_CONF = "\u7f6e\u4fe1\u5ea6"
T_SOURCE = "\u6765\u6e90"

BOX_BLUE = (245, 120, 40)
BOX_GREEN = (70, 220, 90)
BOX_UNKNOWN = (120, 210, 255)
PLATE_RE = re.compile(r"[\u4e00-\u9fa5][A-Z][A-Z0-9]{4,6}")

@dataclass
class PlateDetection:
    plate: str
    color: str
    vehicle_type: str
    box: tuple[int, int, int, int]
    confidence: float
    source: str

class PlateRecognitionApp:
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
        self.detections: list[PlateDetection] = []
        self.detect_lock = threading.Lock()
        self.photo: tk.PhotoImage | None = None
        self.last_view: np.ndarray | None = None
        self.fps = 0.0
        self.det_fps = 0.0
        self.last_frame_time = 0.0
        self._stable_signatures: dict[str, int] = {}
        self.catcher = None

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

    def _load_model(self) -> None:
        try:
            import hyperlpr3 as lpr3
            self.catcher = lpr3.LicensePlateCatcher(detect_level=lpr3.DETECT_LEVEL_HIGH)
            self._set_status("HyperLPR3 ready")
        except Exception as exc:
            self.catcher = None
            self._set_status(f"LPR model load failed: {exc}")

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
                detections = self._recognize_plates(normal)
                detections, self._stable_signatures = stable_filter(
                    self._stable_signatures,
                    detections,
                    label_fn=lambda d: d.plate or d.color,
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

    def _recognize_plates(self, image: np.ndarray) -> list[PlateDetection]:
        results: list[PlateDetection] = []
        if self.catcher is not None:
            for item in self._run_hyperlpr(image):
                results.append(item)
        seen = {d.box for d in results}
        for candidate in self._color_plate_candidates(image):
            if candidate.box not in seen:
                results.append(candidate)
        results.sort(key=lambda d: (bool(d.plate), d.confidence), reverse=True)
        return results[:5]

    def _run_hyperlpr(self, image: np.ndarray) -> list[PlateDetection]:
        detections: list[PlateDetection] = []
        try:
            raw = self.catcher(image)
        except Exception as exc:
            self._set_status(f"LPR error: {exc}")
            return []
        for item in raw or []:
            try:
                plate = str(item[0]).strip().upper().replace(" ", "")
                conf = float(item[1]) if len(item) > 1 else 0.0
                code = int(item[2]) if len(item) > 2 else -1
                box_raw = item[3] if len(item) > 3 else None
            except Exception:
                continue
            box = self._parse_lpr_box(box_raw, image.shape[1], image.shape[0])
            if box is None:
                box = self._estimate_plate_box(image)
            if not box_is_target(image, box, min_area=MIN_PLATE_AREA, max_area_ratio=0.36, min_side=28, min_aspect=1.6, max_aspect=7.2):
                continue
            color = self._plate_color_name(image, box, code)
            vtype = T_EV if color == T_GREEN else (T_OIL if color == T_BLUE else T_UNKNOWN)
            plate = self._clean_plate_text(plate)
            detections.append(PlateDetection(plate, color, vtype, box, conf, "HyperLPR3"))
        return detections

    def _parse_lpr_box(self, box_raw, w: int, h: int) -> tuple[int, int, int, int] | None:
        if box_raw is None:
            return None
        arr = np.array(box_raw).reshape(-1)
        if arr.size < 4:
            return None
        vals = [int(round(float(v))) for v in arr[:4]]
        x1, y1, x2, y2 = vals
        if x2 < x1 or y2 < y1:
            xs = arr[0::2]; ys = arr[1::2]
            if xs.size and ys.size:
                x1, x2 = int(xs.min()), int(xs.max())
                y1, y2 = int(ys.min()), int(ys.max())
        x1=max(0,min(w-1,x1)); x2=max(0,min(w-1,x2)); y1=max(0,min(h-1,y1)); y2=max(0,min(h-1,y2))
        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)

    def _clean_plate_text(self, text: str) -> str:
        text = text.replace("?", "").replace(".", "").replace("-", "")
        m = PLATE_RE.search(text)
        return m.group(0) if m else text

    def _plate_color_name(self, image: np.ndarray, box: tuple[int, int, int, int], code: int = -1) -> str:
        x1,y1,x2,y2 = box
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return T_UNKNOWN
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, np.array((95, 55, 45), dtype=np.uint8), np.array((135, 255, 255), dtype=np.uint8))
        green = cv2.inRange(hsv, np.array((35, 45, 45), dtype=np.uint8), np.array((90, 255, 255), dtype=np.uint8))
        blue_ratio = float(np.count_nonzero(blue)) / max(1, blue.size)
        green_ratio = float(np.count_nonzero(green)) / max(1, green.size)
        if green_ratio > max(0.12, blue_ratio * 1.25):
            return T_GREEN
        if blue_ratio > max(0.12, green_ratio * 1.25):
            return T_BLUE
        if code in {1, 4, 5, 6, 7}:
            return T_GREEN
        if code == 0:
            return T_BLUE
        return T_UNKNOWN

    def _estimate_plate_box(self, image: np.ndarray) -> tuple[int, int, int, int]:
        cands = self._color_plate_candidates(image)
        if cands:
            return cands[0].box
        h,w = image.shape[:2]
        return (int(w*0.20), int(h*0.38), int(w*0.80), int(h*0.62))

    def _color_plate_candidates(self, image: np.ndarray) -> list[PlateDetection]:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, np.array((95, 50, 45), dtype=np.uint8), np.array((135, 255, 255), dtype=np.uint8))
        green = cv2.inRange(hsv, np.array((35, 40, 45), dtype=np.uint8), np.array((92, 255, 255), dtype=np.uint8))
        items: list[PlateDetection] = []
        for mask, color, vehicle_type in [(blue, T_BLUE, T_OIL), (green, T_GREEN, T_EV)]:
            kernel = np.ones((5, 9), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                area = cv2.contourArea(c)
                if area < MIN_PLATE_AREA:
                    continue
                x,y,w,h = cv2.boundingRect(c)
                ratio = w / max(1, h)
                if ratio < 2.0 or ratio > 6.5 or w < 90 or h < 22:
                    continue
                if not box_is_target(image, (x, y, x + w, y + h), min_area=MIN_PLATE_AREA, max_area_ratio=0.36, min_side=28, min_aspect=1.6, max_aspect=7.2):
                    continue
                items.append(PlateDetection("", color, vehicle_type, (x,y,x+w,y+h), min(0.85, area/(w*h+1)), "Color"))
        items.sort(key=lambda d: (d.box[2]-d.box[0])*(d.box[3]-d.box[1]), reverse=True)
        return items[:3]

    def _box_color(self, color_name: str) -> tuple[int, int, int]:
        if color_name == T_GREEN:
            return BOX_GREEN
        if color_name == T_BLUE:
            return BOX_BLUE
        return BOX_UNKNOWN

    def _annotate(self, image: np.ndarray, detections: list[PlateDetection]) -> np.ndarray:
        out = image.copy()
        draw_target_roi(out)
        for det in detections:
            x1,y1,x2,y2 = det.box
            color = self._box_color(det.color)
            cv2.rectangle(out, (x1,y1), (x2,y2), color, 3)
            label = det.plate if det.plate else ("EV" if det.color == T_GREEN else "OIL" if det.color == T_BLUE else "plate")
            text = f"{label} {det.confidence:.2f}"
            size,_ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.70, 2)
            tw,th=size
            y0=max(0,y1-th-16)
            cv2.rectangle(out, (x1,y0), (x1+tw+18,y0+th+14), color, -1)
            cv2.putText(out, text, (x1+9,y0+th+5), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (8,18,12), 2, cv2.LINE_AA)
        cv2.putText(out, f"FPS {self.fps:.1f}", (14,32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (100,255,180), 2, cv2.LINE_AA)
        return out

    def _set_results(self, detections: list[PlateDetection]) -> None:
        if detections:
            lines=[]
            for idx,d in enumerate(detections,1):
                plate = d.plate if d.plate else T_UNKNOWN
                lines.append(f"{idx}. {T_NUMBER}: {plate}\n   {T_COLOR}: {d.color}\n   {T_TYPE}: {d.vehicle_type}\n   {T_CONF}: {d.confidence:.2f}\n   {T_SOURCE}: {d.source}")
            text="\n\n".join(lines)
        else:
            text=T_NO_PLATE
        self.result_box.configure(state=tk.NORMAL)
        self.result_box.delete("1.0", tk.END)
        self.result_box.insert("1.0", text)
        self.result_box.configure(state=tk.DISABLED)
        self.summary_text.set(f"device: {CAMERA_DEVICE}\ninput: {CAMERA_WIDTH}x{CAMERA_HEIGHT}\nview: {T_NORMAL_VIEW}\nengine: HyperLPR3 + HSV\nfps: {self.fps:.1f}\ndet: {self.det_fps:.1f}/s")

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()
        with self.detect_lock:
            detections = list(self.detections)
        cw=max(1,self.canvas.winfo_width()); ch=max(1,self.canvas.winfo_height())
        self.canvas.delete("all")
        if frame is None:
            self.canvas.create_text(cw//2,ch//2,fill="#dfe7f2",font=("Microsoft YaHei",16),text=T_WAIT)
        else:
            normal=self._normal_frame(frame)
            view=self._annotate(normal,detections)
            self.last_view=view.copy()
            rgb=cv2.cvtColor(view,cv2.COLOR_BGR2RGB)
            h,w=rgb.shape[:2]
            scale=min(cw/w,ch/h)
            nw,nh=max(1,int(w*scale)),max(1,int(h*scale))
            rgb=cv2.resize(rgb,(nw,nh),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
            header=f"P6 {nw} {nh} 255\n".encode("ascii")
            self.photo=tk.PhotoImage(data=header+rgb.tobytes(),format="PPM")
            self.canvas.create_image(cw//2,ch//2,image=self.photo,anchor=tk.CENTER)
            self._set_results(detections)
        if self.running:
            self.root.after(DISPLAY_INTERVAL_MS,self._update_view)

    def save_snapshot(self) -> None:
        if self.last_view is None:
            self._set_status(T_NO_SAVE)
            return
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path=SNAPSHOT_DIR/time.strftime("plate_%Y%m%d_%H%M%S.jpg")
        cv2.imwrite(str(path), self.last_view, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        self._set_status(f"{T_SAVED}: {path}")

    def close(self) -> None:
        self.running=False
        if self.cap is not None:
            self.cap.release()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

if __name__ == "__main__":
    PlateRecognitionApp().run()
