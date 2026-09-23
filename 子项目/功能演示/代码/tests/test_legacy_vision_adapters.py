from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np

from feature_demo.adapters.vision import (
    LEGACY_VISION_SPECS,
    LegacyVisionAdapter,
    LegacyVisionSpec,
    build_vision_adapter,
)


def test_all_eight_visual_modules_have_legacy_algorithm_mappings():
    assert set(LEGACY_VISION_SPECS) == {
        "object_sorting",
        "plate_recognition",
        "palm_recognition",
        "palm_tracking",
        "fruit_recognition",
        "color_recognition",
        "face_detection",
        "shape_recognition",
    }


def test_adapter_build_does_not_call_legacy_tk_constructor(monkeypatch):
    constructor_calls = []

    class LegacyApp:
        def __init__(self):
            constructor_calls.append("tk-window")

        def _normal_frame(self, frame):
            return frame

        def _detect_colors(self, frame):
            return []

        def _annotate(self, frame, detections):
            return frame

    fake_module = type("LegacyModule", (), {"ColorRecognitionApp": LegacyApp})
    monkeypatch.setattr(
        "feature_demo.adapters.vision._load_legacy_module",
        lambda spec, legacy_root: fake_module,
    )

    adapter = build_vision_adapter("color_recognition", legacy_root="unused")
    annotated, result = adapter.process("frame")

    assert constructor_calls == []
    assert annotated == "frame"
    assert result["result"] == []


def test_sorting_returns_only_annotated_left_eye():
    left = np.full((4, 6, 3), 11, dtype=np.uint8)
    right = np.full((4, 6, 3), 222, dtype=np.uint8)
    stereo = np.concatenate((left, right), axis=1)
    module = SimpleNamespace(
        split_stereo=lambda frame: (frame[:, :6], frame[:, 6:]),
    )
    instance = SimpleNamespace(
        _detect_color=lambda _frame: None,
        _annotate=lambda frame, _detected: frame,
    )
    adapter = LegacyVisionAdapter(
        "object_sorting",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "sorting"),
    )

    annotated, _result = adapter.process(stereo)

    assert annotated.shape == left.shape
    assert np.all(annotated == 11)


def test_manual_gimbal_step_waits_for_automatic_move_and_pauses_tracking():
    automatic_started = threading.Event()
    release_automatic = threading.Event()
    manual_started = threading.Event()

    class TargetLock:
        def update(self, boxes):
            return boxes[0]

        def clear(self):
            return None

    class Controller:
        def update(self, current_box, image_size, now):
            return SimpleNamespace(
                state="tracking",
                yaw_delta_pwm=4,
                pitch_delta_pwm=5,
            )

        def stop(self):
            return None

    class Gimbal:
        def move(self, yaw, pitch, interval):
            automatic_started.set()
            release_automatic.wait(timeout=2)
            return True, "ok"

        def disconnect(self):
            return None

    frame = SimpleNamespace(shape=(480, 640, 3))
    module = SimpleNamespace(
        split_stereo=lambda value: (value, value),
        CONTROL_INTERVAL_MS=100,
    )
    instance = SimpleNamespace(
        hand_detector=SimpleNamespace(
            detect=lambda image: [SimpleNamespace(box=(1, 2, 3, 4))]
        ),
        target_lock=TargetLock(),
        controller=Controller(),
        gimbal=Gimbal(),
        tracking_enabled=True,
        current_box=None,
        image_size=(640, 480),
        _annotate=lambda image, box: image,
    )
    adapter = LegacyVisionAdapter(
        "palm_tracking",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "tracking"),
    )

    automatic_result = {}

    def run_automatic():
        _annotated, evidence = adapter.process(frame)
        automatic_result.update(evidence)

    automatic = threading.Thread(target=run_automatic)
    automatic.start()
    assert automatic_started.wait(timeout=1)

    result = {}

    def run_manual():
        result.update(
            adapter.manual_gimbal_step(
                lambda: manual_started.set() or {"ok": True}
            )
        )

    manual = threading.Thread(target=run_manual)
    manual.start()

    assert manual_started.wait(timeout=0.1) is False
    release_automatic.set()
    automatic.join(timeout=1)
    manual.join(timeout=1)

    assert manual_started.is_set()
    assert result == {"ok": True}
    assert automatic_result["tracking_action"] == {
        "state": "moved",
        "yaw_delta_pwm": 4,
        "pitch_delta_pwm": 5,
    }
    assert instance.tracking_enabled is False
