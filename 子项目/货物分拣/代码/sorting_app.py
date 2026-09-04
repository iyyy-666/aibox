#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from urllib.error import URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from vision_targeting import box_is_target, draw_target_roi, split_stereo
from sorting_gimbal import SortingGimbal


CAMERA_DEVICE = os.getenv(
    "SORTING_CAMERA_DEVICE",
    "/dev/video41",
)
CAMERA_WIDTH = int(os.getenv("SORTING_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("SORTING_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("SORTING_CAMERA_FPS", "30"))
CAPTURE_INTERVAL_SEC = float(os.getenv("SORTING_CAPTURE_INTERVAL_SEC", "0.03"))
DETECT_INTERVAL_SEC = float(os.getenv("SORTING_DETECT_INTERVAL_SEC", "0.06"))
MIN_AREA = int(os.getenv("SORTING_MIN_AREA", "700"))
STABLE_FRAMES = int(os.getenv("SORTING_STABLE_FRAMES", "2"))
STABLE_WINDOW = int(os.getenv("SORTING_STABLE_WINDOW", "5"))
STABLE_HITS = int(os.getenv("SORTING_STABLE_HITS", "2"))
API_BASE = os.getenv("SORTING_API_BASE", "http://127.0.0.1:8000")
RED = "\u7ea2\u8272"
BLUE = "\u84dd\u8272"
COLOR_LABELS = {RED: "RED", BLUE: "BLUE"}


def api_post(path: str) -> tuple[bool, str]:
    try:
        req = Request(API_BASE + path, method="POST")
        with urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("success")), str(payload.get("error", ""))
    except (OSError, URLError, TimeoutError) as exc:
        return False, str(exc)


class SortingApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("货物分拣（单目）")
        self.root.geometry("1180x720")
        self.root.minsize(960, 560)
        self.root.configure(bg="#111417")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.running = True
        self.pose_ready = False
        self.gimbal_ready = False
        self.sort_enabled = False
        self.paused = False
        self.action_busy = False
        self.cap: cv2.VideoCapture | None = None
        self.frame: np.ndarray | None = None
        self.view: np.ndarray | None = None
        self.frame_lock = threading.Lock()
        self.detection_lock = threading.Lock()
        self.detection: tuple[str, tuple[int, int, int, int], float] | None = None
        self.candidate_color = ""
        self.candidate_count = 0
        self.fps = 0.0
        self.last_frame_at = 0.0

        self.status_text = tk.StringVar(value="摄像头待机，按开始分拣")
        self.detect_text = tk.StringVar(value="等待识别")
        self._build_ui()
        threading.Thread(target=self._prepare_gimbal, daemon=True).start()

        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._detect_loop, daemon=True).start()
        self.root.after(80, self._update_view)

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#1c2228", height=56)
        top.pack(side=tk.TOP, fill=tk.X)
        top.pack_propagate(False)
        tk.Label(
            top,
            text="货物分拣（单目）",
            bg="#1c2228",
            fg="#f5f7fa",
            font=("Microsoft YaHei", 16, "bold"),
        ).pack(side=tk.LEFT, padx=(16, 18))
        tk.Label(
            top,
            textvariable=self.status_text,
            bg="#1c2228",
            fg="#aeb8c5",
            font=("Microsoft YaHei", 10),
        ).pack(side=tk.LEFT)

        body = tk.Frame(self.root, bg="#111417")
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, bg="#080a0d", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 8), pady=12)

        side = tk.Frame(body, bg="#181d22", width=270)
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        side.pack_propagate(False)
        tk.Label(
            side,
            text="分拣控制",
            bg="#181d22",
            fg="#f1f5f9",
            font=("Microsoft YaHei", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(16, 10))

        self.ready_btn = ttk.Button(side, text="就绪", command=self.ready_robot)
        self.ready_btn.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.start_btn = ttk.Button(side, text="开始分拣", command=self.start_sorting, state=tk.DISABLED)
        self.start_btn.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.pause_btn = ttk.Button(side, text="暂停", command=self.toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.stop_btn = ttk.Button(side, text="停止", command=self.stop_sorting, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.restore_btn = ttk.Button(side, text="恢复", command=self.restore_robot)
        self.restore_btn.pack(fill=tk.X, padx=16, pady=(0, 16))

        tk.Label(
            side,
            text="识别结果",
            bg="#181d22",
            fg="#f1f5f9",
            font=("Microsoft YaHei", 13, "bold"),
        ).pack(anchor="w", padx=16, pady=(0, 8))
        tk.Label(
            side,
            textvariable=self.detect_text,
            justify=tk.LEFT,
            anchor="nw",
            bg="#0f1317",
            fg="#dce7f3",
            font=("Microsoft YaHei", 12),
            height=5,
        ).pack(fill=tk.X, padx=16, pady=(0, 16))

        tk.Label(
            side,
            text="分拣规则\n蓝色物块 → 右转移\n红色物块 → 左转移\n\n一次开始只处理一个物块",
            justify=tk.LEFT,
            anchor="nw",
            bg="#181d22",
            fg="#9fb0c2",
            font=("Microsoft YaHei", 10),
        ).pack(fill=tk.X, padx=16)

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
                    time.sleep(0.25)
                    continue
                self.cap = self._open_camera()
                if not self.cap.isOpened():
                    self._set_status("单目摄像头打开失败")
                    retry_at = time.time() + 2.0
                    continue
                self._set_status("单目摄像头已连接，等待开始")

            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.cap.release()
                self.cap = None
                self._set_status("摄像头读取失败，正在重试")
                time.sleep(0.4)
                continue

            now = time.time()
            if self.last_frame_at:
                instant = 1.0 / max(0.001, now - self.last_frame_at)
                self.fps = self.fps * 0.85 + instant * 0.15 if self.fps else instant
            self.last_frame_at = now
            with self.frame_lock:
                self.frame = frame
            time.sleep(CAPTURE_INTERVAL_SEC)

    def _detect_loop(self) -> None:
        while self.running:
            with self.frame_lock:
                frame = None if self.frame is None else self.frame.copy()

            if frame is not None and not self.paused and not self.action_busy:
                left, _right = split_stereo(frame)
                detected = self._detect_color(left)
                with self.detection_lock:
                    self.detection = detected
                self._handle_candidate(detected)
            else:
                with self.detection_lock:
                    self.detection = None
                self.candidate_color = ""
                self.candidate_count = 0

            time.sleep(DETECT_INTERVAL_SEC)

    def _detect_color(self, frame: np.ndarray):
        small = frame
        scale = 1.0
        h0, w0 = frame.shape[:2]
        if w0 > 800:
            scale = 800.0 / w0
            small = cv2.resize(frame, (800, max(1, int(h0 * scale))), interpolation=cv2.INTER_AREA)

        blur = cv2.GaussianBlur(small, (5, 5), 0)
        hsv = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)
        b, g, r = cv2.split(blur)
        red_dominant = (
            (r.astype(np.uint16) > g.astype(np.uint16) * 6 // 5)
            & (r.astype(np.uint16) > b.astype(np.uint16) * 6 // 5)
            & (r > 50)
        ).astype(np.uint8) * 255
        blue_dominant = (
            (b.astype(np.uint16) > r.astype(np.uint16) * 11 // 10)
            & (b.astype(np.uint16) > g.astype(np.uint16) * 11 // 10)
            & (b > 45)
        ).astype(np.uint8) * 255
        masks = {
            RED: cv2.bitwise_or(
                cv2.bitwise_or(
                    cv2.inRange(hsv, np.array((0, 45, 45), np.uint8), np.array((18, 255, 255), np.uint8)),
                    cv2.inRange(hsv, np.array((156, 45, 45), np.uint8), np.array((180, 255, 255), np.uint8)),
                ),
                red_dominant,
            ),
            BLUE: cv2.bitwise_or(
                cv2.inRange(
                    hsv,
                    np.array((85, 35, 35), np.uint8),
                    np.array((142, 255, 255), np.uint8),
                ),
                blue_dominant,
            ),
        }
        kernel = np.ones((5, 5), np.uint8)
        best = None
        for color, mask in masks.items():
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < MIN_AREA * scale * scale:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                if w < 18 or h < 18:
                    continue
                if not box_is_target(
                    small,
                    (x, y, x + w, y + h),
                    min_area=max(MIN_AREA * scale * scale, small.shape[0] * small.shape[1] * 0.004),
                    max_area_ratio=0.45,
                    min_side=24,
                ):
                    continue
                box = (int(x / scale), int(y / scale), int(w / scale), int(h / scale))
                candidate = (color, box, float(area / (scale * scale)))
                if best is None or candidate[2] > best[2]:
                    best = candidate
        return best

    def _handle_candidate(self, detected) -> None:
        color = "" if detected is None else detected[0]
        if not color:
            self.candidate_color = ""
            self.candidate_count = 0
            return
        if color == self.candidate_color:
            self.candidate_count += 1
        else:
            self.candidate_color = color
            self.candidate_count = 1
        if self.sort_enabled and self.candidate_count >= STABLE_HITS:
            self.action_busy = True
            threading.Thread(target=self._run_sort, args=(color,), daemon=True).start()

    def _run_sort(self, color: str) -> None:
        side = "right" if color == BLUE else "left"
        self._set_status(f"识别到{color}，正在分拣")
        ok, error = api_post(f"/api/robot/sorting/{side}")
        self.sort_enabled = False
        self.paused = False
        self.action_busy = False
        self.candidate_color = ""
        self.candidate_count = 0
        self.pose_ready = True if ok else False
        self._set_status("本次分拣完成，已回到就绪状态" if ok else f"分拣失败：{error or '机械臂未执行'}")
        self.root.after(0, lambda: self._set_ready_state(True if ok else False))

    def ready_robot(self) -> None:
        if self.action_busy or not self.gimbal_ready:
            self._set_status("请等待云台归位完成")
            return
        self._set_status("正在进入就绪姿态")
        threading.Thread(target=self._ready_robot_async, daemon=True).start()

    def _ready_robot_async(self) -> None:
        self.sort_enabled = False
        self.paused = False
        self.candidate_color = ""
        self.candidate_count = 0
        ok, error = api_post("/api/robot/sorting/ready")
        self.pose_ready = bool(ok)
        self.root.after(0, lambda: self._set_ready_state(self.pose_ready))
        self._set_status("已进入就绪姿态" if ok else f"就绪失败：{error or '机械臂未执行'}")

    def start_sorting(self) -> None:
        if self.sort_enabled or self.action_busy or not self.pose_ready or not self.gimbal_ready:
            return
        self.sort_enabled = True
        self.paused = False
        self.candidate_color = ""
        self.candidate_count = 0
        self._set_ready_state(True)
        self._set_status("开始分拣，等待红色或蓝色物块")

    def restore_robot(self) -> None:
        if self.action_busy:
            return
        threading.Thread(target=self._restore_robot_async, daemon=True).start()

    def _restore_robot_async(self) -> None:
        self.sort_enabled = False
        self.paused = False
        self.action_busy = True
        self.pose_ready = False
        self.candidate_color = ""
        self.candidate_count = 0
        self._set_status("正在恢复到直立+夹爪半开")
        ok, error = api_post("/api/robot/all_center")
        self.action_busy = False
        self.root.after(0, lambda: self._set_ready_state(False))
        self._set_status("已恢复到直立+夹爪半开" if ok else f"恢复失败：{error or '机械臂未执行'}")

    def toggle_pause(self) -> None:
        if not self.sort_enabled:
            return
        self.paused = not self.paused
        self.pause_btn.configure(text="恢复" if self.paused else "暂停")
        self._set_status("已暂停识别" if self.paused else "继续识别红蓝物块")

    def stop_sorting(self) -> None:
        self.sort_enabled = False
        self.paused = False
        self.action_busy = False
        self.pose_ready = False
        self.candidate_color = ""
        self.candidate_count = 0
        api_post("/api/robot/stop")
        self._set_ready_state(False)
        self._set_status("已停止，机械臂保持当前位置")

    def _set_buttons(self, active: bool) -> None:
        self.start_btn.configure(state=tk.DISABLED if active else tk.NORMAL)
        self.pause_btn.configure(state=tk.NORMAL if active else tk.DISABLED, text="暂停")
        self.stop_btn.configure(state=tk.NORMAL if active else tk.DISABLED)
        self.ready_btn.configure(state=tk.DISABLED if active else tk.NORMAL)

    def _set_ready_state(self, ready: bool) -> None:
        self.ready_btn.configure(state=tk.DISABLED if self.sort_enabled or self.action_busy else tk.NORMAL)
        self.start_btn.configure(state=tk.NORMAL if ready and not self.action_busy and not self.sort_enabled else tk.DISABLED)
        self.pause_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.DISABLED)
        self.restore_btn.configure(state=tk.NORMAL if not self.action_busy and not self.sort_enabled else tk.DISABLED)

    def _prepare_gimbal(self) -> None:
        self.action_busy = True
        self._set_status("正在检查云台分拣视角")
        ok, detail = SortingGimbal().move_to_target(self._set_status)
        self.gimbal_ready = ok
        self.action_busy = False
        self.root.after(0, lambda: self._set_ready_state(ok))
        self._set_status(f"云台已到分拣视角：{detail}" if ok else f"云台归位失败：{detail}")

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status_text.set(text))

    def _annotate(self, frame: np.ndarray, detected) -> np.ndarray:
        out = frame.copy()
        left_width = out.shape[1] // 2
        left = out[:, :left_width]
        draw_target_roi(left)
        if detected is not None:
            color, (x, y, w, h), _ = detected
            draw_color = (40, 40, 230) if color == RED else (230, 100, 40)
            cv2.rectangle(left, (x, y), (x + w, y + h), draw_color, 4)
            cv2.putText(left, COLOR_LABELS.get(color, "COLOR"), (x, max(35, y - 12)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, draw_color, 3, cv2.LINE_AA)
        cv2.line(out, (left_width, 0), (left_width, out.shape[0]), (92, 104, 116), 2)
        cv2.putText(out, "LEFT", (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 255, 180), 2, cv2.LINE_AA)
        cv2.putText(out, "RIGHT", (left_width + 16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 255, 180), 2, cv2.LINE_AA)
        cv2.putText(out, f"FPS {self.fps:.1f}", (16, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 255, 180), 2, cv2.LINE_AA)
        return out

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()
        with self.detection_lock:
            detected = self.detection

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        if frame is None:
            self.canvas.create_text(cw // 2, ch // 2, fill="#dfe7f2", font=("Microsoft YaHei", 16), text="等待单目摄像头画面")
        else:
            view = self._annotate(frame, detected)
            self.view = view
            rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            scale = min(cw / w, ch / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            ppm = f"P6 {nw} {nh} 255\n".encode("ascii") + rgb.tobytes()
            self.photo = tk.PhotoImage(data=ppm, format="PPM")
            self.canvas.create_image(cw // 2, ch // 2, image=self.photo, anchor=tk.CENTER)
            if detected is None:
                self.detect_text.set("未识别到红色或蓝色物块")
            else:
                self.detect_text.set(f"当前识别：{detected[0]}\n稳定命中：{self.candidate_count}/{STABLE_HITS}\n画面标注：{COLOR_LABELS.get(detected[0], 'COLOR')}")

        if self.running:
            self.root.after(80, self._update_view)

    def close(self) -> None:
        self.running = False
        if self.action_busy:
            api_post("/api/robot/stop")
        if self.cap is not None:
            self.cap.release()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    SortingApp().run()
