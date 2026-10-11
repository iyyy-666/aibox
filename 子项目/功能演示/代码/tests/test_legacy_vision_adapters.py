from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

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


def test_shape_adapter_uses_left_eye_and_exposes_only_public_result_fields():
    left = np.full((4, 6, 3), 11, dtype=np.uint8)
    right = np.full((4, 6, 3), 222, dtype=np.uint8)
    stereo = np.concatenate((left, right), axis=1)
    detection = SimpleNamespace(
        name="Square",
        name_cn="正方形",
        box=(1, 1, 5, 3),
        center=(3, 2),
        confidence=0.92,
        area=8.0,
        vertices=4,
        contour=np.array([[[1, 1]], [[5, 1]], [[5, 3]], [[1, 3]]]),
        signature="Square:1:1:1",
    )
    seen = []
    instance = SimpleNamespace(
        _normal_frame=lambda frame: frame[:, :6],
        _detect_shapes=lambda frame: seen.append(frame) or [detection],
        _stabilize=lambda items: items,
        _annotate=lambda frame, _detections: frame,
        _last_raw_count=0,
    )
    adapter = LegacyVisionAdapter(
        "shape_recognition",
        SimpleNamespace(),
        instance,
        LegacyVisionSpec("unused.py", "Unused", "shape"),
    )

    annotated, result = adapter.process(stereo)

    np.testing.assert_array_equal(seen[0], left)
    np.testing.assert_array_equal(annotated, left)
    assert result == {
        "result": [
            {
                "name": "Square",
                "name_cn": "正方形",
                "box": [1, 1, 5, 3],
                "center": [3, 2],
                "confidence": 0.92,
            }
        ]
    }


def test_sorting_drops_a_composite_frame_returned_by_legacy_annotation():
    left = np.full((4, 6, 3), 11, dtype=np.uint8)
    right = np.full((4, 6, 3), 222, dtype=np.uint8)
    stereo = np.concatenate((left, right), axis=1)
    module = SimpleNamespace(
        split_stereo=lambda frame: (frame[:, :6], frame[:, 6:]),
    )
    instance = SimpleNamespace(
        _detect_color=lambda _frame: None,
        _annotate=lambda _frame, _detected: stereo,
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


def test_sorting_annotates_the_left_eye_as_a_full_single_camera_frame():
    left = np.full((4, 6, 3), 11, dtype=np.uint8)
    right = np.full((4, 6, 3), 222, dtype=np.uint8)
    stereo = np.concatenate((left, right), axis=1)
    annotation_inputs = []

    def annotate(frame, _detected):
        annotation_inputs.append(frame.copy())
        return frame

    module = SimpleNamespace(
        split_stereo=lambda frame: (frame[:, :6], frame[:, 6:]),
    )
    instance = SimpleNamespace(
        _detect_color=lambda _frame: None,
        _annotate=annotate,
    )
    adapter = LegacyVisionAdapter(
        "object_sorting",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "sorting"),
    )

    annotated, _result = adapter.process(stereo)

    assert annotation_inputs[0].shape == stereo.shape
    assert np.all(annotation_inputs[0][:, :6] == 11)
    assert np.all(annotation_inputs[0][:, 6:] == 11)
    assert annotated.shape == left.shape


def test_face_adapter_skips_haar_when_opencv_build_omits_cascade(monkeypatch):
    class LegacyFace:
        def _load_dnn(self):
            return "dnn"

        def _load_yunet(self):
            return "yunet"

        def _load_cascades(self):
            raise AttributeError("CascadeClassifier is unavailable")

    fake_module = SimpleNamespace(
        FaceRecognitionApp=LegacyFace,
        cv2=SimpleNamespace(),
    )
    monkeypatch.setattr(
        "feature_demo.adapters.vision._load_legacy_module",
        lambda _spec, _legacy_root: fake_module,
    )

    adapter = build_vision_adapter("face_detection", legacy_root="unused")

    assert adapter.instance.dnn == "dnn"
    assert adapter.instance.yunet == "yunet"
    assert adapter.instance.face_detectors == []


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


def test_tracking_tries_right_eye_after_left_eye_miss():
    left = np.zeros((4, 6, 3), dtype=np.uint8)
    right = np.ones((4, 6, 3), dtype=np.uint8)
    calls = []

    def detect_left(image):
        calls.append(("left", image))
        return []

    def detect_right(image):
        calls.append(("right", image))
        return [SimpleNamespace(box=(1, 1, 2, 2), landmarks=np.zeros((21, 2)))]

    module = SimpleNamespace(
        split_stereo=lambda _frame: (left, right),
        CONTROL_INTERVAL_MS=100,
    )
    instance = SimpleNamespace(
        hand_detector=SimpleNamespace(detect=detect_left),
        right_hand_detector=SimpleNamespace(detect=detect_right),
        target_lock=SimpleNamespace(update=lambda boxes: boxes[0], clear=lambda: None),
        controller=SimpleNamespace(stop=lambda: None),
        gimbal=SimpleNamespace(disconnect=lambda: None),
        tracking_enabled=False,
        current_box=None,
        image_size=(6, 4),
        _annotate=lambda image, _box: image,
    )
    adapter = LegacyVisionAdapter(
        "palm_tracking",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "tracking"),
    )

    annotated, result = adapter.process(object())

    assert len(calls) == 2
    assert calls[0] == ("left", left)
    assert calls[1] == ("right", right)
    assert annotated is right
    assert instance.current_box == (1, 1, 2, 2)
    np.testing.assert_array_equal(instance.current_landmarks, np.zeros((21, 2)))
    assert result["tracking"] is False


def test_palm_recognition_annotates_the_eye_used_for_detection():
    left = np.zeros((4, 6, 3), dtype=np.uint8)
    right = np.ones((4, 6, 3), dtype=np.uint8)
    instance = SimpleNamespace()
    instance._detect_hands = (
        lambda _left, _right: setattr(instance, "_last_detection_eye", "right") or []
    )
    instance._normal_frame = lambda _frame: left
    instance._annotate = lambda image, _detections: image
    module = SimpleNamespace(split_stereo=lambda _frame: (left, right))
    adapter = LegacyVisionAdapter(
        "palm_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "palm"),
    )

    annotated, _result = adapter.process(object())

    assert annotated is right


def test_plate_adapter_reports_a_valid_detection_without_two_frame_delay():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detection = SimpleNamespace(
        plate="浙A8K5D2",
        color="Blue Plate",
        vehicle_type="Fuel Vehicle",
        box=(133, 150, 453, 276),
        confidence=0.99,
        source="HyperLPR3",
    )
    module = SimpleNamespace(
        stable_filter=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("valid plate results must not be delayed")
        ),
        STABLE_HITS=2,
    )
    instance = SimpleNamespace(
        _normal_frame=lambda value: value,
        _recognize_plates=lambda _image: [detection],
        _stable_signatures={},
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "plate_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "plate"),
    )

    _annotated, result = adapter.process(frame)

    assert result["result"][0]["plate"] == "浙A8K5D2"


def test_fruit_adapter_reports_a_specific_fruit_without_two_frame_delay():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detection = SimpleNamespace(
        name_en="apple",
        name_cn="Apple",
        box=(180, 110, 440, 370),
        confidence=0.91,
        center=(310, 240),
        source="image",
    )
    module = SimpleNamespace(
        stable_filter=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("valid fruit results must not be delayed")
        ),
        STABLE_HITS=2,
    )
    instance = SimpleNamespace(
        model=object(),
        _normal_frame=lambda value: value,
        _detect_fruits=lambda _image: [detection],
        _classify_picture=lambda _image: None,
        _color_picture_guess=lambda _image: None,
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "fruit_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "fruit"),
    )

    _annotated, result = adapter.process(frame)

    assert result["result"][0]["name_cn"] == "Apple"
    assert result["model_loaded"] is True


def test_fruit_adapter_throttles_yolo_but_keeps_video_results_and_fps(monkeypatch):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detection = SimpleNamespace(
        name_en="banana",
        name_cn="Banana",
        box=(180, 110, 440, 370),
        confidence=0.91,
        center=(310, 240),
        source="detect",
    )
    inference_calls = []
    times = iter((10.0, 10.6, 10.7, 11.0, 11.6))
    monkeypatch.setattr(
        "feature_demo.adapters.vision.time.monotonic", lambda: next(times)
    )
    instance = SimpleNamespace(
        model=object(),
        fps=0.0,
        _normal_frame=lambda value: value,
        _detect_fruits=lambda image: inference_calls.append(image) or [detection],
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "fruit_recognition",
        SimpleNamespace(DETECT_INTERVAL_SEC=0.18),
        instance,
        LegacyVisionSpec("unused.py", "Unused", "fruit"),
    )

    adapter.process(frame)
    _annotated, cached = adapter.process(frame)

    assert len(inference_calls) == 1
    assert cached["result"][0]["name_en"] == "banana"
    assert instance.fps == pytest.approx(1.0 / 0.7)

    adapter.process(frame)

    assert len(inference_calls) == 2


def test_fruit_adapter_holds_a_single_frame_detection_then_clears(monkeypatch):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detection = SimpleNamespace(
        name_en="apple",
        name_cn="Apple",
        box=(180, 110, 440, 370),
        confidence=0.91,
        center=(310, 240),
        source="detect",
    )
    detector_results = iter(([detection], [], []))
    clock = iter((100.0, 100.0, 102.0, 102.0, 106.0, 106.0))
    monkeypatch.setattr(
        "feature_demo.adapters.vision.time.monotonic", lambda: next(clock)
    )
    instance = SimpleNamespace(
        model=object(),
        _normal_frame=lambda value: value,
        _detect_fruits=lambda _image: next(detector_results),
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "fruit_recognition",
        SimpleNamespace(),
        instance,
        LegacyVisionSpec("unused.py", "Unused", "fruit"),
    )

    _annotated, detected = adapter.process(frame)
    _annotated, held = adapter.process(frame)
    _annotated, cleared = adapter.process(frame)

    assert detected["result"][0]["name_en"] == "apple"
    assert held["result"][0]["name_en"] == "apple"
    assert cleared["result"] == []


def test_fruit_adapter_uses_yolo_box_instead_of_fixed_reference_region():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    yolo_detection = SimpleNamespace(
        name_en="apple",
        name_cn="Apple",
        box=(265, 175, 405, 355),
        confidence=0.61,
        center=(335, 265),
        source="detect",
    )
    fixed_reference = SimpleNamespace(
        name_en="apple",
        name_cn="Apple",
        box=(128, 168, 544, 446),
        confidence=0.99,
        center=(336, 307),
        source="reference",
    )
    instance = SimpleNamespace(
        model=object(),
        _normal_frame=lambda value: value,
        _match_reference_fruit=lambda _image: fixed_reference,
        _detect_fruits=lambda _image: [yolo_detection],
        _classify_picture=lambda _image: (_ for _ in ()).throw(
            AssertionError("pure YOLO mode must not run image classification")
        ),
        _color_picture_guess=lambda _image: (_ for _ in ()).throw(
            AssertionError("pure YOLO mode must not guess by color")
        ),
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "fruit_recognition",
        SimpleNamespace(),
        instance,
        LegacyVisionSpec("unused.py", "Unused", "fruit"),
    )

    _annotated, result = adapter.process(frame)

    assert result["result"][0]["box"] == [265, 175, 405, 355]
    assert result["result"][0]["source"] == "detect"


def test_fruit_adapter_does_not_replace_yolo_with_picture_classification():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    weak_detection = SimpleNamespace(
        name_en="banana",
        name_cn="Banana",
        box=(180, 110, 440, 370),
        confidence=0.23,
        center=(310, 240),
        source="detect",
    )
    picture_detection = SimpleNamespace(
        name_en="apple",
        name_cn="Apple",
        box=(160, 90, 460, 390),
        confidence=0.72,
        center=(310, 240),
        source="image",
    )
    instance = SimpleNamespace(
        model=object(),
        _normal_frame=lambda value: value,
        _detect_fruits=lambda _image: [weak_detection],
        _classify_picture=lambda _image: (_ for _ in ()).throw(
            AssertionError("pure YOLO mode must not run image classification")
        ),
        _color_picture_guess=lambda _image: None,
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "fruit_recognition",
        SimpleNamespace(),
        instance,
        LegacyVisionSpec("unused.py", "Unused", "fruit"),
    )

    _annotated, result = adapter.process(frame)

    assert result["result"][0]["name_cn"] == "Banana"


def test_plate_adapter_normalizes_camera_frame_before_recognition():
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    normalized = np.ones((4, 6, 3), dtype=np.uint8)
    recognition_inputs = []
    fake_cv2 = SimpleNamespace(
        IMWRITE_JPEG_QUALITY=1,
        IMREAD_COLOR=2,
        imencode=lambda *_args, **_kwargs: (True, b"jpeg"),
        imdecode=lambda encoded, mode: normalized,
    )
    module = SimpleNamespace(cv2=fake_cv2)
    instance = SimpleNamespace(
        _normal_frame=lambda value: value,
        _recognize_plates=lambda image: recognition_inputs.append(image) or [],
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "plate_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "plate"),
    )

    adapter.process(frame)

    assert recognition_inputs[0] is normalized


def test_plate_adapter_keeps_the_last_result_during_a_brief_model_miss(monkeypatch):
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    detection = SimpleNamespace(
        plate="浙AD56321",
        color="Green Plate",
        vehicle_type="Electric Vehicle",
        box=(1, 1, 5, 3),
        confidence=0.99,
        source="HyperLPR3",
    )
    batches = iter(([detection], [], []))
    times = iter((10.0, 11.0))
    monkeypatch.setattr("feature_demo.adapters.vision.time.monotonic", lambda: next(times))
    module = SimpleNamespace(cv2=SimpleNamespace())
    instance = SimpleNamespace(
        _normal_frame=lambda value: value,
        _recognize_plates=lambda _image: next(batches),
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "plate_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "plate"),
    )

    adapter.process(frame)
    _annotated, result = adapter.process(frame)

    assert result["result"][0]["plate"] == "浙AD56321"


def test_plate_adapter_retries_the_same_preview_frame_shown_to_the_user():
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    preview = np.full((4, 6, 3), 7, dtype=np.uint8)
    detection = SimpleNamespace(
        plate="浙A8K5D2",
        color="Blue Plate",
        vehicle_type="Fuel Vehicle",
        box=(1, 1, 5, 3),
        confidence=0.99,
        source="HyperLPR3",
    )
    recognition_inputs = []

    def recognize(image):
        recognition_inputs.append(image)
        return [] if len(recognition_inputs) == 1 else [detection]

    module = SimpleNamespace(cv2=SimpleNamespace())
    instance = SimpleNamespace(
        _normal_frame=lambda value: value,
        _recognize_plates=recognize,
        _annotate=lambda image, detections: preview if not detections else image,
    )
    adapter = LegacyVisionAdapter(
        "plate_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "plate"),
    )

    _annotated, result = adapter.process(frame)

    assert len(recognition_inputs) == 2
    assert recognition_inputs[1] is preview
    assert result["result"][0]["plate"] == "浙A8K5D2"


def test_plate_model_loads_on_first_processing_call_not_adapter_construction(monkeypatch):
    load_calls = []

    class LegacyPlate:
        def _load_model(self):
            load_calls.append("load")
            self.catcher = object()
            self.fallback_catcher = object()

        def _normal_frame(self, frame):
            return frame

        def _recognize_plates(self, _frame):
            assert self.catcher is not None
            return []

        def _annotate(self, frame, _detections):
            return frame

    fake_module = SimpleNamespace(PlateRecognitionApp=LegacyPlate, cv2=SimpleNamespace())
    monkeypatch.setattr(
        "feature_demo.adapters.vision._load_legacy_module",
        lambda _spec, _legacy_root: fake_module,
    )

    adapter = build_vision_adapter("plate_recognition", legacy_root="unused")

    assert load_calls == []
    adapter.process(np.zeros((4, 6, 3), dtype=np.uint8))
    assert load_calls == ["load"]


def test_plate_adapter_exposes_model_diagnostics_in_worker_status():
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    module = SimpleNamespace(cv2=SimpleNamespace())
    instance = SimpleNamespace(
        _normal_frame=lambda value: value,
        _recognize_plates=lambda _image: [],
        _annotate=lambda image, _detections: image,
        _last_lpr_debug="raw=[]",
        _last_status="LPR ready",
    )
    adapter = LegacyVisionAdapter(
        "plate_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "plate"),
    )

    _annotated, result = adapter.process(frame)

    assert result["recognition_debug"] == "raw=[]"
    assert result["recognition_status"] == "LPR ready"


def test_plate_adapter_throttles_model_inference_but_keeps_video_results(monkeypatch):
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    detection = SimpleNamespace(
        plate="粤BM739X",
        color="Blue Plate",
        vehicle_type="Fuel Vehicle",
        box=(1, 1, 5, 3),
        confidence=0.99,
        source="HyperLPR3",
    )
    inference_calls = []
    times = iter((10.0, 10.1, 10.5))
    monkeypatch.setattr("feature_demo.adapters.vision.time.monotonic", lambda: next(times))
    module = SimpleNamespace(cv2=SimpleNamespace())
    instance = SimpleNamespace(
        fps=0.0,
        _normal_frame=lambda value: value,
        _recognize_plates=lambda image: inference_calls.append(image) or [detection],
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "plate_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "plate"),
    )

    adapter.process(frame)
    _annotated, result = adapter.process(frame)

    assert len(inference_calls) == 1
    assert result["result"][0]["plate"] == "粤BM739X"
    assert instance.fps == pytest.approx(10.0)

    adapter.process(frame)

    assert len(inference_calls) == 2


def test_plate_adapter_expires_cached_result_between_inference_cycles(monkeypatch):
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    detection = SimpleNamespace(
        plate="粤BM739X",
        color="Blue Plate",
        vehicle_type="Fuel Vehicle",
        box=(1, 1, 5, 3),
        confidence=0.99,
        source="HyperLPR3",
    )
    batches = iter(([detection], [], []))
    times = iter((10.0, 20.0, 20.1))
    monkeypatch.setattr("feature_demo.adapters.vision.time.monotonic", lambda: next(times))
    module = SimpleNamespace(cv2=SimpleNamespace())
    instance = SimpleNamespace(
        fps=0.0,
        _normal_frame=lambda value: value,
        _recognize_plates=lambda _image: next(batches),
        _annotate=lambda image, _detections: image,
    )
    adapter = LegacyVisionAdapter(
        "plate_recognition",
        module,
        instance,
        LegacyVisionSpec("unused.py", "Unused", "plate"),
    )

    adapter.process(frame)
    adapter.process(frame)
    _annotated, result = adapter.process(frame)

    assert result["result"] == []
