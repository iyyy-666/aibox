from __future__ import annotations

import importlib.util
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


@dataclass(frozen=True, slots=True)
class LegacyVisionSpec:
    filename: str
    class_name: str
    mode: str


LEGACY_VISION_SPECS = {
    "object_sorting": LegacyVisionSpec("sorting_app.py", "SortingApp", "sorting"),
    "plate_recognition": LegacyVisionSpec("plate_recognition_app.py", "PlateRecognitionApp", "plate"),
    "palm_recognition": LegacyVisionSpec("palm_recognition_app.py", "PalmRecognitionApp", "palm"),
    "palm_tracking": LegacyVisionSpec("palm_tracking_app.py", "PalmTrackingApp", "tracking"),
    "fruit_recognition": LegacyVisionSpec("fruit_recognition_app.py", "FruitRecognitionApp", "fruit"),
    "color_recognition": LegacyVisionSpec("color_recognition_app.py", "ColorRecognitionApp", "color"),
    "face_detection": LegacyVisionSpec("face_recognition_app.py", "FaceRecognitionApp", "face"),
    "shape_recognition": LegacyVisionSpec("shape_recognition_app.py", "ShapeRecognitionApp", "shape"),
}


def _load_legacy_module(spec: LegacyVisionSpec, legacy_root: str | Path) -> ModuleType:
    root = Path(legacy_root)
    path = root / spec.filename
    if not path.is_file():
        raise RuntimeError(f"找不到原功能算法文件：{path}")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    module_name = f"feature_demo_legacy_{path.stem}"
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"无法加载原功能算法：{path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    return module


def _plain_value(value: Any) -> Any:
    if is_dataclass(value):
        data = asdict(value)
    elif hasattr(value, "__dict__"):
        data = vars(value)
    elif isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    else:
        return value
    clean = {}
    for key, item in data.items():
        if key in {"contour"}:
            continue
        if isinstance(item, tuple):
            clean[key] = list(item)
        elif isinstance(item, (str, int, float, bool)) or item is None:
            clean[key] = item
    return clean


class LegacyVisionAdapter:
    def __init__(self, module_id: str, module: ModuleType, instance: object, spec: LegacyVisionSpec) -> None:
        self.module_id = module_id
        self.module = module
        self.instance = instance
        self.spec = spec
        self._last_control_at = 0.0
        self._sorting_observer = None

    def set_sorting_observer(self, observer) -> None:
        self._sorting_observer = observer

    def process(self, frame):
        mode = self.spec.mode
        if mode == "sorting":
            normal, _ = self.module.split_stereo(frame)
            detected = self.instance._detect_color(normal)
            if self._sorting_observer is not None:
                self._sorting_observer(None if detected is None else detected[0])
            return self.instance._annotate(normal, detected), {"result": _plain_value(detected)}
        if mode == "tracking":
            return self._process_tracking(frame)

        normal = self.instance._normal_frame(frame)
        if mode == "color":
            detections = self.instance._detect_colors(normal)
            stable_filter = getattr(self.module, "stable_filter", None)
            if callable(stable_filter):
                detections, self.instance._stable_signatures = stable_filter(
                    self.instance._stable_signatures,
                    detections,
                    label_fn=lambda item: item.name,
                    box_fn=lambda item: (item.box[0], item.box[1], item.box[0] + item.box[2], item.box[1] + item.box[3]),
                    image_shape=normal.shape,
                    stable_hits=self.module.STABLE_HITS,
                )
        elif mode == "shape":
            raw = self.instance._detect_shapes(normal)
            self.instance._last_raw_count = len(raw)
            detections = self.instance._stabilize(raw)
        elif mode == "fruit":
            detections = self.instance._detect_fruits(normal) if self.instance.model is not None else []
            if not detections:
                fallback = self.instance._classify_picture(normal)
                if fallback is None:
                    fallback = self.instance._color_picture_guess(normal)
                detections = [fallback] if fallback is not None else []
            detections, self.instance._stable_signatures = self.module.stable_filter(
                self.instance._stable_signatures,
                detections,
                label_fn=lambda item: item.name_cn,
                box_fn=lambda item: item.box,
                image_shape=normal.shape,
                stable_hits=self.module.STABLE_HITS,
            )
        elif mode == "plate":
            detections = self.instance._recognize_plates(normal)
            detections, self.instance._stable_signatures = self.module.stable_filter(
                self.instance._stable_signatures,
                detections,
                label_fn=lambda item: item.plate or item.color,
                box_fn=lambda item: item.box,
                image_shape=normal.shape,
                stable_hits=self.module.STABLE_HITS,
            )
        elif mode == "face":
            detections = self.instance._detect_dnn(normal)
            if not detections:
                detections = self.instance._detect_yunet(normal)
            if not detections:
                detections = self.instance._detect_haar(normal)
        elif mode == "palm":
            left, right = self.module.split_stereo(frame)
            normal = left
            detections = self.instance._detect_hands(left, right)
        else:
            raise RuntimeError(f"未知的视觉适配模式：{mode}")
        annotated = self.instance._annotate(normal, detections)
        return annotated, {"result": [_plain_value(item) for item in detections]}

    def _process_tracking(self, frame):
        left, _ = self.module.split_stereo(frame)
        self.instance.image_size = (left.shape[1], left.shape[0])
        observations = self.instance.hand_detector.detect(left)
        boxes = [item.box for item in observations]
        if self.instance.tracking_enabled:
            self.instance.current_box = self.instance.target_lock.update(boxes)
        else:
            self.instance.current_box = boxes[0] if boxes else None
        now = time.monotonic()
        if self.instance.tracking_enabled and self.instance.current_box is not None and now - self._last_control_at >= self.module.CONTROL_INTERVAL_MS / 1000.0:
            decision = self.instance.controller.update(self.instance.current_box, self.instance.image_size, now)
            if decision.state == "tracking":
                ok, detail = self.instance.gimbal.move(decision.yaw_delta_pwm, decision.pitch_delta_pwm, self.module.CONTROL_INTERVAL_MS)
                if not ok:
                    self.stop_tracking()
                    raise RuntimeError(f"云台通信失败：{detail}")
            self._last_control_at = now
        annotated = self.instance._annotate(left, self.instance.current_box)
        return annotated, {"result": "已检测到手掌" if self.instance.current_box else "未检测到手掌", "tracking": self.instance.tracking_enabled}

    def command(self, name: str, payload: dict) -> dict:
        if self.spec.mode == "tracking":
            if name == "start_tracking":
                box = self.instance.current_box
                if box is None:
                    return {"ok": False, "message": "请先将手掌放入画面。"}
                locked = self.instance.target_lock.arm([box], self.instance.image_size)
                if locked is None:
                    return {"ok": False, "message": "手掌目标未能锁定。"}
                self.instance.current_box = locked
                self.instance.controller.start(locked, time.monotonic())
                self.instance.tracking_enabled = True
                return {"ok": True, "message": "已开始手掌跟踪。"}
            if name == "stop_tracking":
                self.stop_tracking()
                return {"ok": True, "message": "已停止手掌跟踪。"}
        if name == "save_snapshot":
            return {"ok": False, "message": "截图由统一界面保存。"}
        raise ValueError(f"不支持的视觉命令：{name}")

    def stop_tracking(self) -> None:
        if self.spec.mode != "tracking":
            return
        self.instance.tracking_enabled = False
        self.instance.target_lock.clear()
        self.instance.controller.stop()
        self.instance.gimbal.disconnect()

    def close(self) -> None:
        if self.spec.mode == "tracking":
            self.stop_tracking()
            self.instance.gimbal.disconnect()
        hand_detector = getattr(self.instance, "hand_detector", None)
        close = getattr(hand_detector, "close", None)
        if callable(close):
            close()


def _initialize_instance(module: ModuleType, spec: LegacyVisionSpec) -> object:
    legacy_class = getattr(module, spec.class_name)
    instance = legacy_class.__new__(legacy_class)
    instance.fps = 0.0
    instance.det_fps = 0.0
    instance._set_status = lambda text: None
    mode = spec.mode
    if mode in {"color", "shape", "fruit", "plate"}:
        instance._stable_signatures = {}
    if mode == "shape":
        instance._last_raw_count = 0
    elif mode == "fruit":
        instance.model = None
        instance.cls_model = None
        instance.model_names = {}
        instance.cls_names = {}
        instance.fruit_class_ids = set(module.FALLBACK_FRUIT_CLASS_IDS)
        instance._load_model()
    elif mode == "plate":
        instance.catcher = None
        instance._load_model()
    elif mode == "face":
        instance.dnn = instance._load_dnn()
        instance.yunet = instance._load_yunet()
        instance.face_detectors = instance._load_cascades()
    elif mode == "palm":
        instance.use_mediapipe = module.USE_MEDIAPIPE
        instance.hand_detector = module.HandLandmarkDetector()
        instance._tracker = module.BoxTracker(hold_misses=module.HOLD_MISSES)
        instance._voter = module.TemporalGestureVote(confirm_hits=module.STABLE_HITS, hold_misses=module.HOLD_MISSES)
    elif mode == "tracking":
        config = module.TrackingConfig(
            deadband_ratio=float(os.getenv("PALM_TRACK_DEADBAND_RATIO", "0.07")),
            smoothing_alpha=float(os.getenv("PALM_TRACK_SMOOTHING_ALPHA", "0.35")),
            control_interval_sec=module.CONTROL_INTERVAL_MS / 1000.0,
            lost_timeout_sec=float(os.getenv("PALM_TRACK_LOST_TIMEOUT_SEC", "0.5")),
            max_degrees_per_second=float(os.getenv("PALM_TRACK_MAX_DEGREES_PER_SECOND", "80")),
            pwm_per_degree=float(os.getenv("PALM_TRACK_PWM_PER_DEGREE", "11.11")),
            min_step_pwm=int(os.getenv("PALM_TRACK_MIN_STEP_PWM", "4")),
            max_step_pwm=int(os.getenv("PALM_TRACK_MAX_STEP_PWM", "22")),
            yaw_sign=int(os.getenv("PALM_TRACK_YAW_SIGN", "-1")),
            pitch_sign=int(os.getenv("PALM_TRACK_PITCH_SIGN", "-1")),
        )
        instance.controller = module.PalmTrackingController(config)
        instance.target_lock = module.PalmTargetLock()
        instance.gimbal = module.SerialGimbalClient(
            port=os.getenv("PALM_TRACK_SERIAL_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"),
            baud=int(os.getenv("PALM_TRACK_SERIAL_BAUD", "115200")),
            yaw_id=int(os.getenv("PALM_TRACK_YAW_ID", "1")),
            pitch_id=int(os.getenv("PALM_TRACK_PITCH_ID", "2")),
            pwm_min=int(os.getenv("PALM_TRACK_PWM_MIN", "500")),
            pwm_max=int(os.getenv("PALM_TRACK_PWM_MAX", "2500")),
            initial_pwm=int(os.getenv("PALM_TRACK_INITIAL_PWM", "1500")),
        )
        instance.hand_detector = module.HandLandmarkDetector()
        instance.tracking_enabled = False
        instance.current_box = None
        instance.image_size = (module.CAMERA_WIDTH // 2, module.CAMERA_HEIGHT)
    elif mode == "sorting":
        instance.paused = False
        instance.action_busy = False
        instance.candidate_color = ""
        instance.candidate_count = 0
    return instance


def build_vision_adapter(module_id: str, *, legacy_root: str | Path | None = None) -> LegacyVisionAdapter:
    try:
        spec = LEGACY_VISION_SPECS[module_id]
    except KeyError as exc:
        raise ValueError(f"未知的视觉功能：{module_id}") from exc
    root = legacy_root or os.getenv("AIBOX_LEGACY_ROOT", "/root/robot_arm")
    module = _load_legacy_module(spec, root)
    instance = _initialize_instance(module, spec)
    return LegacyVisionAdapter(module_id, module, instance, spec)
