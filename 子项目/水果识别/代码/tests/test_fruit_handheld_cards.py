from __future__ import annotations

import sys
import types
from pathlib import Path

import cv2
import numpy as np
import pytest


CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))

gimbal_stub = types.ModuleType("gimbal_controls")
gimbal_stub.GimbalControls = object
sys.modules.setdefault("gimbal_controls", gimbal_stub)

from fruit_recognition_app import FruitDetection, FruitRecognitionApp


class _FakeProbabilities:
    top5 = [0]

    def __init__(self, confidence: float) -> None:
        self.top5conf = np.array([confidence], dtype=np.float32)


class _BrightnessAwareClassifier:
    def predict(self, image: np.ndarray, **_kwargs):
        confidence = 0.70 if float(image.mean()) > 115.0 else 0.02
        return [types.SimpleNamespace(probs=_FakeProbabilities(confidence))]


class _SmallPrintedFruitDetector:
    names = {46: "banana"}

    def predict(self, _image: np.ndarray, **_kwargs):
        box = types.SimpleNamespace(
            cls=np.array([46], dtype=np.float32),
            conf=np.array([0.24], dtype=np.float32),
            xyxy=np.array([[292, 205, 340, 263]], dtype=np.float32),
        )
        return [types.SimpleNamespace(boxes=[box])]


class _EdgeFruitDetector:
    names = {0: "apple"}

    def predict(self, _image: np.ndarray, **_kwargs):
        box = types.SimpleNamespace(
            cls=np.array([0], dtype=np.float32),
            conf=np.array([0.88], dtype=np.float32),
            xyxy=np.array([[8, 140, 120, 300]], dtype=np.float32),
        )
        return [types.SimpleNamespace(boxes=[box])]


class _HighResolutionFallbackDetector:
    names = {0: "apple"}

    def __init__(self) -> None:
        self.image_sizes = []

    def predict(self, _image: np.ndarray, **kwargs):
        image_size = kwargs["imgsz"]
        self.image_sizes.append(image_size)
        if image_size < 960:
            return [types.SimpleNamespace(boxes=[])]
        box = types.SimpleNamespace(
            cls=np.array([0], dtype=np.float32),
            conf=np.array([0.91], dtype=np.float32),
            xyxy=np.array([[296, 216, 320, 240]], dtype=np.float32),
        )
        return [types.SimpleNamespace(boxes=[box])]


class _AppleClassifier:
    def predict(self, _image: np.ndarray, **_kwargs):
        return [types.SimpleNamespace(probs=_FakeProbabilities(0.70))]


def _scene_with_card_and_distracting_border() -> np.ndarray:
    image = np.full((480, 640, 3), 25, dtype=np.uint8)
    cv2.rectangle(image, (8, 8), (631, 471), (230, 230, 230), 5)
    card = np.array([[205, 105], [470, 130], [445, 375], [180, 345]], dtype=np.int32)
    cv2.fillConvexPoly(image, card, (245, 245, 245))
    cv2.circle(image, (325, 235), 72, (20, 30, 210), -1)
    return image


def test_classifier_uses_filled_handheld_card_instead_of_largest_scene_edge() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.cls_model = _BrightnessAwareClassifier()
    app.cls_names = {0: "Granny Smith"}
    app._set_status = lambda _message: None

    detection = app._classify_picture(_scene_with_card_and_distracting_border())

    assert detection is not None
    assert detection.name_cn == "Apple"
    x1, y1, x2, y2 = detection.box
    assert 150 < x1 < 230
    assert 80 < y1 < 150
    assert 420 < x2 < 500
    assert 330 < y2 < 400


def test_classifier_ignores_a_bright_scene_without_a_colored_fruit() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.cls_model = _AppleClassifier()
    app.cls_names = {0: "Granny Smith"}
    app._set_status = lambda _message: None
    empty_scene = np.full((480, 640, 3), 220, dtype=np.uint8)

    detection = app._classify_picture(empty_scene)

    assert detection is None


def test_small_fruit_picture_in_center_is_not_discarded() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.model = _SmallPrintedFruitDetector()
    app.model_names = {46: "banana"}
    app.fruit_class_ids = {46}
    app._set_status = lambda _message: None

    detections = app._detect_fruits(np.full((480, 640, 3), 230, dtype=np.uint8))

    assert len(detections) == 1
    assert detections[0].name_cn == "Banana"


def test_complete_yolo_fruit_near_preview_edge_is_not_discarded() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.model = _EdgeFruitDetector()
    app.model_names = {0: "apple"}
    app.fruit_class_ids = {0}
    app._set_status = lambda _message: None

    detections = app._detect_fruits(np.full((480, 640, 3), 230, dtype=np.uint8))

    assert len(detections) == 1
    assert detections[0].name_cn == "Apple"
    assert detections[0].box == (8, 140, 120, 300)


def test_small_fruit_uses_high_resolution_fallback_when_standard_pass_misses() -> None:
    detector = _HighResolutionFallbackDetector()
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.model = detector
    app.model_names = {0: "apple"}
    app.fruit_class_ids = {0}
    app._set_status = lambda _message: None

    detections = app._detect_fruits(np.full((480, 640, 3), 230, dtype=np.uint8))

    assert detector.image_sizes == [640, 960]
    assert len(detections) == 1
    assert detections[0].name_cn == "Apple"
    assert detections[0].box == (296, 216, 320, 240)


def test_high_resolution_fallback_is_throttled_between_empty_frames() -> None:
    detector = _HighResolutionFallbackDetector()
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.model = detector
    app.model_names = {0: "apple"}
    app.fruit_class_ids = {0}
    app._set_status = lambda _message: None
    image = np.full((480, 640, 3), 230, dtype=np.uint8)

    app._detect_fruits(image)
    app._detect_fruits(image)

    assert detector.image_sizes == [640, 960, 640]


def test_high_resolution_fallback_interval_starts_after_slow_inference(
    monkeypatch,
) -> None:
    detector = _HighResolutionFallbackDetector()
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.model = detector
    app.model_names = {0: "apple"}
    app.fruit_class_ids = {0}
    app._set_status = lambda _message: None
    image = np.full((480, 640, 3), 230, dtype=np.uint8)
    clock = iter((10.0, 11.0, 11.1))
    monkeypatch.setattr(
        "fruit_recognition_app.time.monotonic", lambda: next(clock)
    )

    app._detect_fruits(image)
    app._detect_fruits(image)

    assert detector.image_sizes == [640, 960, 640]


def test_classifier_refines_a_low_confidence_detector_box() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.cls_model = _AppleClassifier()
    app.cls_names = {0: "Granny Smith"}
    app._set_status = lambda _message: None
    detection = FruitDetection(
        "banana", "Banana", (220, 140, 420, 340), 0.23, (320, 240), "detect"
    )
    image = np.full((480, 640, 3), 230, dtype=np.uint8)

    refined = app._classify_detected_fruits(image, [detection])

    assert refined is not None
    assert refined.name_cn == "Apple"
    assert refined.confidence == pytest.approx(0.70)


def test_reference_card_match_overrides_general_photo_models(tmp_path, monkeypatch) -> None:
    reference = np.full((240, 180, 3), 245, dtype=np.uint8)
    cv2.circle(reference, (90, 125), 48, (20, 30, 220), -1)
    cv2.putText(reference, "APPLE", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 20, 20), 2)
    assert cv2.imwrite(str(tmp_path / "apple_01.jpg"), reference)
    monkeypatch.setattr("fruit_recognition_app.FRUIT_REFERENCE_DIR", tmp_path)
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)

    detection = app._match_reference_fruit(reference)

    assert detection is not None
    assert detection.name_en == "apple"
    assert detection.source == "reference"


def test_reference_card_does_not_match_its_static_background(tmp_path, monkeypatch) -> None:
    reference = np.full((480, 640, 3), (175, 185, 195), dtype=np.uint8)
    cv2.rectangle(reference, (84, 50), (563, 433), (30, 30, 30), 1)
    for x in range(100, 600, 70):
        cv2.line(reference, (x, 65), (x, 180), (90, 90, 90), 2)
        cv2.circle(reference, (x, 160), 14, (120, 120, 120), 2)
    cv2.putText(reference, "STATIC ROOM", (150, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 40, 40), 2)
    cv2.rectangle(reference, (240, 200), (460, 398), (245, 245, 245), -1)
    cv2.circle(reference, (350, 300), 58, (20, 30, 220), -1)
    cv2.putText(reference, "APPLE", (275, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (20, 20, 20), 2)
    empty_frame = np.full((480, 640, 3), (175, 185, 195), dtype=np.uint8)
    cv2.rectangle(empty_frame, (84, 50), (563, 433), (30, 30, 30), 1)
    for x in range(100, 600, 70):
        cv2.line(empty_frame, (x, 65), (x, 180), (90, 90, 90), 2)
        cv2.circle(empty_frame, (x, 160), 14, (120, 120, 120), 2)
    cv2.putText(empty_frame, "STATIC ROOM", (150, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 40, 40), 2)
    assert cv2.imwrite(str(tmp_path / "apple_01.jpg"), reference)
    monkeypatch.setattr("fruit_recognition_app.FRUIT_REFERENCE_DIR", tmp_path)
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)

    detection = app._match_reference_fruit(empty_frame)

    assert detection is None


def test_color_fallback_does_not_report_a_generic_fruit_for_blue_background() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(image, (220, 140), (420, 340), (255, 100, 0), -1)

    detection = app._color_picture_guess(image)

    assert detection is None


def test_color_fallback_ignores_a_colored_region_touching_the_frame_edge() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(image, (320, 0), (470, 384), (0, 255, 255), -1)

    detection = app._color_picture_guess(image)

    assert detection is None


def test_color_fallback_ignores_a_colored_region_below_the_handheld_area() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.rectangle(image, (120, 310), (340, 400), (0, 255, 255), -1)

    detection = app._color_picture_guess(image)

    assert detection is None
