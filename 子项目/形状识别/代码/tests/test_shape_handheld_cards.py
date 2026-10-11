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

from shape_recognition_app import SHAPE_POLYGON, SHAPE_SQUARE, SHAPE_TRIANGLE, ShapeRecognitionApp


def _rotated_card_with_triangle() -> np.ndarray:
    image = np.full((480, 640, 3), 28, dtype=np.uint8)
    card = np.array([[205, 85], [485, 145], [430, 390], [150, 330]], dtype=np.int32)
    cv2.fillConvexPoly(image, card, (245, 245, 245))
    triangle = np.array([[320, 145], [235, 310], [400, 330]], dtype=np.int32)
    cv2.fillConvexPoly(image, triangle, (25, 60, 215))
    return image


def _card_with_small_triangle() -> np.ndarray:
    image = np.full((480, 640, 3), 30, dtype=np.uint8)
    cv2.rectangle(image, (170, 90), (470, 390), (245, 245, 245), -1)
    triangle = np.array([[320, 195], [287, 260], [353, 260]], dtype=np.int32)
    cv2.fillConvexPoly(image, triangle, (30, 70, 215))
    return image


def test_rotated_card_background_is_not_mistaken_for_the_shape() -> None:
    app = ShapeRecognitionApp.__new__(ShapeRecognitionApp)

    detections = app._detect_shapes(_rotated_card_with_triangle())

    assert detections
    assert detections[0].name == SHAPE_TRIANGLE


def test_shape_is_visible_after_two_matching_frames() -> None:
    app = ShapeRecognitionApp.__new__(ShapeRecognitionApp)
    app._stable_signatures = {}
    detections = app._detect_shapes(_rotated_card_with_triangle())

    assert app._stabilize(detections) == []
    assert app._stabilize(detections)


def test_small_shape_printed_on_card_is_not_discarded() -> None:
    app = ShapeRecognitionApp.__new__(ShapeRecognitionApp)

    detections = app._detect_shapes(_card_with_small_triangle())

    assert detections
    assert detections[0].name == SHAPE_TRIANGLE


def test_rotated_square_uses_rotated_bounding_box_ratio() -> None:
    app = ShapeRecognitionApp.__new__(ShapeRecognitionApp)

    name, confidence = app._classify_shape(
        4,
        circularity=0.78,
        aspect=1.42,
        extent=0.62,
        solidity=0.99,
        rotated_aspect=1.03,
        side_ratio=0.96,
        max_angle_cosine=0.04,
    )

    assert name == SHAPE_SQUARE
    assert confidence >= 0.80


def test_polygon_confidence_reaches_detection_threshold() -> None:
    app = ShapeRecognitionApp.__new__(ShapeRecognitionApp)

    name, confidence = app._classify_shape(
        7,
        circularity=0.58,
        aspect=1.20,
        extent=0.72,
        solidity=0.94,
        rotated_aspect=1.18,
    )

    assert name == SHAPE_POLYGON
    assert confidence >= 0.66


def test_irregular_quadrilateral_is_not_classified_as_square() -> None:
    app = ShapeRecognitionApp.__new__(ShapeRecognitionApp)

    name, _confidence = app._classify_shape(
        4,
        circularity=0.70,
        aspect=1.04,
        extent=0.72,
        solidity=0.98,
        rotated_aspect=1.05,
        side_ratio=0.58,
        max_angle_cosine=0.46,
    )

    assert name != SHAPE_SQUARE
