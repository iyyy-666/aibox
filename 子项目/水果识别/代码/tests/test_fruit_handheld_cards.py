from __future__ import annotations

import sys
import types
from pathlib import Path

import cv2
import numpy as np


CODE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_DIR))

gimbal_stub = types.ModuleType("gimbal_controls")
gimbal_stub.GimbalControls = object
sys.modules.setdefault("gimbal_controls", gimbal_stub)

from fruit_recognition_app import FruitRecognitionApp


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


def test_small_fruit_picture_in_center_is_not_discarded() -> None:
    app = FruitRecognitionApp.__new__(FruitRecognitionApp)
    app.model = _SmallPrintedFruitDetector()
    app.model_names = {46: "banana"}
    app.fruit_class_ids = {46}
    app._set_status = lambda _message: None

    detections = app._detect_fruits(np.full((480, 640, 3), 230, dtype=np.uint8))

    assert len(detections) == 1
    assert detections[0].name_cn == "Banana"
