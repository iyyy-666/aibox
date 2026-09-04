from __future__ import annotations

import os
import threading
import time
import tkinter as tk

import cv2
import numpy as np

from hand_landmarks import HandLandmarkDetector
from palm_tracking_control import Box, PalmTargetLock, PalmTrackingController, TrackingConfig
from palm_tracking_serial import SerialGimbalClient
from vision_targeting import split_stereo


CAMERA_DEVICE = os.getenv("PALM_TRACK_CAMERA_DEVICE", "/dev/video41")
CAMERA_WIDTH = int(os.getenv("PALM_TRACK_CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.getenv("PALM_TRACK_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("PALM_TRACK_CAMERA_FPS", "30"))
DISPLAY_INTERVAL_MS = int(os.getenv("PALM_TRACK_DISPLAY_INTERVAL_MS", "50"))
DETECT_INTERVAL_SEC = float(os.getenv("PALM_TRACK_DETECT_INTERVAL_SEC", "0.08"))
CONTROL_INTERVAL_MS = int(os.getenv("PALM_TRACK_CONTROL_INTERVAL_MS", "100"))


def is_start_ready(box: Box | None, image_size: tuple[int, int]) -> bool:
    del image_size
    return box is not None


class PalmTrackingApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("手掌追踪")
        self.root.geometry("1180x720")
        self.root.minsize(960, 560)
        self.root.configure(bg="#111417")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        config = TrackingConfig(
            deadband_ratio=float(os.getenv("PALM_TRACK_DEADBAND_RATIO", "0.07")),
            smoothing_alpha=float(os.getenv("PALM_TRACK_SMOOTHING_ALPHA", "0.35")),
            control_interval_sec=CONTROL_INTERVAL_MS / 1000.0,
            lost_timeout_sec=float(os.getenv("PALM_TRACK_LOST_TIMEOUT_SEC", "0.5")),
            max_degrees_per_second=float(os.getenv("PALM_TRACK_MAX_DEGREES_PER_SECOND", "80")),
            pwm_per_degree=float(os.getenv("PALM_TRACK_PWM_PER_DEGREE", "11.11")),
            min_step_pwm=int(os.getenv("PALM_TRACK_MIN_STEP_PWM", "4")),
            max_step_pwm=int(os.getenv("PALM_TRACK_MAX_STEP_PWM", "22")),
            yaw_sign=int(os.getenv("PALM_TRACK_YAW_SIGN", "1")),
            pitch_sign=int(os.getenv("PALM_TRACK_PITCH_SIGN", "1")),
        )
        self.controller = PalmTrackingController(config)
        self.target_lock = PalmTargetLock()
        self.gimbal = SerialGimbalClient(
            port=os.getenv("PALM_TRACK_SERIAL_PORT", "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00"),
            baud=int(os.getenv("PALM_TRACK_SERIAL_BAUD", "115200")),
            yaw_id=int(os.getenv("PALM_TRACK_YAW_ID", "1")),
            pitch_id=int(os.getenv("PALM_TRACK_PITCH_ID", "2")),
            pwm_min=int(os.getenv("PALM_TRACK_PWM_MIN", "500")),
            pwm_max=int(os.getenv("PALM_TRACK_PWM_MAX", "2500")),
            initial_pwm=int(os.getenv("PALM_TRACK_INITIAL_PWM", "1500")),
        )
        self.hand_detector = HandLandmarkDetector()
        self.running = True
        self.tracking_enabled = False
        self.frame: np.ndarray | None = None
        self.frame_lock = threading.Lock()
        self.current_box: Box | None = None
        self.box_lock = threading.Lock()
        self.image_size = (CAMERA_WIDTH // 2, CAMERA_HEIGHT)
        self.cap: cv2.VideoCapture | None = None
        self.photo: tk.PhotoImage | None = None
        self.status_text = tk.StringVar(value="正在打开摄像头...")
        self.detail_text = tk.StringVar(value="请将手掌放在画面中央")
        self.button_text = tk.StringVar(value="开始追踪")
        self.start_button: tk.Button | None = None

        self._build_ui()
        threading.Thread(target=self._capture_loop, daemon=True).start()
        threading.Thread(target=self._detect_loop, daemon=True).start()
        self._update_view()
        self.root.after(CONTROL_INTERVAL_MS, self._control_tick)

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg="#1c2228", height=54)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="手掌追踪", bg="#1c2228", fg="#f5f7fa", font=("Microsoft YaHei", 16, "bold")).pack(side=tk.LEFT, padx=(16, 18))
        tk.Label(top, textvariable=self.status_text, bg="#1c2228", fg="#aeb8c5", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)

        body = tk.Frame(self.root, bg="#111417")
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, bg="#080a0d", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 8), pady=12)
        side = tk.Frame(body, bg="#181d22", width=268)
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        side.pack_propagate(False)
        tk.Label(side, text="追踪控制", bg="#181d22", fg="#f1f5f9", font=("Microsoft YaHei", 13, "bold")).pack(anchor="w", padx=16, pady=(18, 12))
        tk.Label(side, textvariable=self.detail_text, bg="#181d22", fg="#aeb8c5", justify=tk.LEFT, wraplength=230, font=("Microsoft YaHei", 11)).pack(anchor="w", padx=16, pady=(0, 18))
        self.start_button = tk.Button(side, textvariable=self.button_text, command=self.toggle_tracking, state=tk.DISABLED, bg="#2a9d68", fg="#ffffff", activebackground="#38b97c", activeforeground="#ffffff", relief=tk.FLAT, font=("Microsoft YaHei", 12, "bold"), padx=12, pady=10)
        self.start_button.pack(fill=tk.X, padx=16, pady=(0, 10))
        tk.Button(side, text="退出", command=self.close, bg="#263039", fg="#e7edf3", activebackground="#394651", activeforeground="#ffffff", relief=tk.FLAT, font=("Microsoft YaHei", 11), padx=12, pady=9).pack(fill=tk.X, padx=16)
        tk.Label(side, text=f"最大速度 {self.controller.config.max_degrees_per_second:g}°/s\n中心区域内自动停止微调\n手掌丢失 0.5 秒后暂停", bg="#181d22", fg="#8393a4", justify=tk.LEFT, font=("Microsoft YaHei", 10)).pack(anchor="w", padx=16, pady=(26, 0))

    def _open_camera(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _capture_loop(self) -> None:
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                self.cap = self._open_camera()
                if not self.cap.isOpened():
                    self._set_status(f"摄像头打开失败：{CAMERA_DEVICE}")
                    time.sleep(1.5)
                    continue
                self._set_status(f"已打开 {CAMERA_DEVICE}")
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self._set_status("读取画面失败，正在重试...")
                self.cap.release()
                self.cap = None
                continue
            with self.frame_lock:
                self.frame = frame

    def _detect_loop(self) -> None:
        while self.running:
            with self.frame_lock:
                frame = None if self.frame is None else self.frame.copy()
            if frame is not None:
                try:
                    left, _right = split_stereo(frame)
                    self.image_size = (left.shape[1], left.shape[0])
                    observations = self.hand_detector.detect(left)
                    boxes = [item.box for item in observations]
                    with self.box_lock:
                        if self.tracking_enabled:
                            self.current_box = self.target_lock.update(boxes)
                        else:
                            self.current_box = boxes[0] if boxes else None
                except Exception as exc:
                    self._set_status(f"手掌检测异常：{exc}")
            time.sleep(DETECT_INTERVAL_SEC)

    def start_tracking(self) -> bool:
        if self.current_box is None or not is_start_ready(self.current_box, self.image_size):
            return False
        locked = self.target_lock.arm([self.current_box], self.image_size)
        if locked is None:
            return False
        self.current_box = locked
        self.controller.start(locked, time.monotonic())
        self.tracking_enabled = True
        self.button_text.set("停止追踪")
        self._set_status("正在追踪")
        return True

    def stop_tracking(self, reason: str) -> None:
        self.tracking_enabled = False
        self.target_lock.clear()
        self.controller.stop()
        self.button_text.set("开始追踪")
        self._set_status("已停止追踪" if reason == "user" else reason)

    def toggle_tracking(self) -> None:
        if self.tracking_enabled:
            self.stop_tracking("user")
        else:
            self.start_tracking()

    def _control_tick(self) -> None:
        if self.running and self.tracking_enabled:
            with self.box_lock:
                box = self.current_box
            if box is not None:
                center_x = box[0] + box[2] / 2.0
                center_y = box[1] + box[3] / 2.0
                offset_x = (center_x - self.image_size[0] / 2.0) / max(1.0, self.image_size[0] / 2.0)
                offset_y = (center_y - self.image_size[1] / 2.0) / max(1.0, self.image_size[1] / 2.0)
                yaw_reversed, pitch_reversed = self.controller.observe_feedback(offset_x=offset_x, offset_y=offset_y)
                if yaw_reversed or pitch_reversed:
                    axes = "水平" if yaw_reversed and not pitch_reversed else "俯仰" if pitch_reversed and not yaw_reversed else "水平和俯仰"
                    self._set_status(f"已自动校正{axes}方向")
            decision = self.controller.update(box, self.image_size, time.monotonic())
            if decision.state == "lost":
                self._set_status("未检测到手掌，等待重新出现")
            elif decision.state == "tracking":
                ok, detail = self.gimbal.move(decision.yaw_delta_pwm, decision.pitch_delta_pwm, CONTROL_INTERVAL_MS)
                if not ok:
                    self.stop_tracking(f"云台通信失败：{detail}")
                else:
                    self._set_status("正在追踪")
            elif decision.state == "centered":
                self._set_status("已保持在画面中心")
        if self.running:
            self.root.after(CONTROL_INTERVAL_MS, self._control_tick)

    def _annotate(self, image: np.ndarray, box: Box | None) -> np.ndarray:
        out = image.copy()
        height, width = out.shape[:2]
        center = (width // 2, height // 2)
        cv2.drawMarker(out, center, (62, 218, 137), cv2.MARKER_CROSS, 36, 2, cv2.LINE_AA)
        x1, y1 = int(width * 0.32), int(height * 0.32)
        x2, y2 = int(width * 0.68), int(height * 0.68)
        cv2.rectangle(out, (x1, y1), (x2, y2), (102, 116, 128), 1)
        if box is not None:
            x, y, box_width, box_height = box
            color = (80, 220, 245) if self.tracking_enabled else (110, 210, 120)
            cv2.rectangle(out, (x, y), (x + box_width, y + box_height), color, 3)
            cv2.putText(out, "TRACKING" if self.tracking_enabled else "PALM", (x, max(24, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
        return out

    def _update_view(self) -> None:
        with self.frame_lock:
            frame = None if self.frame is None else self.frame.copy()
        with self.box_lock:
            box = self.current_box
        self.canvas.delete("all")
        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        if frame is None:
            self.canvas.create_text(canvas_width // 2, canvas_height // 2, fill="#dfe7f2", font=("Microsoft YaHei", 16), text="正在打开摄像头...")
        else:
            left, _right = split_stereo(frame)
            view = self._annotate(left, box)
            rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
            scale = min(canvas_width / rgb.shape[1], canvas_height / rgb.shape[0])
            target = (max(1, int(rgb.shape[1] * scale)), max(1, int(rgb.shape[0] * scale)))
            rgb = cv2.resize(rgb, target, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            self.photo = tk.PhotoImage(data=f"P6 {target[0]} {target[1]} 255\n".encode("ascii") + rgb.tobytes(), format="PPM")
            self.canvas.create_image(canvas_width // 2, canvas_height // 2, image=self.photo, anchor=tk.CENTER)
            if not self.tracking_enabled and self.start_button is not None:
                ready = is_start_ready(box, self.image_size)
                self.start_button.configure(state=tk.NORMAL if ready else tk.DISABLED)
                self.detail_text.set("已检测到手掌，请开始追踪" if ready else "等待手掌进入画面")
            elif self.tracking_enabled:
                self.detail_text.set("手掌框将保持在中心准星附近")
        if self.running:
            self.root.after(DISPLAY_INTERVAL_MS, self._update_view)

    def _set_status(self, text: str) -> None:
        if hasattr(self, "root"):
            self.root.after(0, lambda: self.status_text.set(text))

    def close(self) -> None:
        self.running = False
        if self.tracking_enabled:
            self.stop_tracking("closed")
        self.gimbal.disconnect()
        if self.cap is not None:
            self.cap.release()
        self.root.after(80, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    PalmTrackingApp().run()
