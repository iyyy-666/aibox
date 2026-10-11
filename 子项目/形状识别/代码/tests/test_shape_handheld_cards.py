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

from shape_recognition_app import (
    SHAPE_CIRCLE,
    SHAPE_PENTAGON,
    SHAPE_POLYGON,
    SHAPE_RECTANGLE,
    SHAPE_SQUARE,
    SHAPE_STAR,
    SHAPE_TRIANGLE,
    ShapeRecognitionApp,
)

SHAPE_PARALLELOGRAM = "Parallelogram"


def _card_canvas() -> np.ndarray:
    image = np.full((480, 640, 3), 32, dtype=np.uint8)
    cv2.rectangle(image, (80, 45), (560, 435), (246, 246, 246), -1)
    return image


def _card_with_polygon(points: np.ndarray, color=(30, 70, 215)) -> np.ndarray:
    image = _card_canvas()
    cv2.fillPoly(image, [points.astype(np.int32)], color)
    return image


def _regular_polygon(center: tuple[int, int], radius: int, sides: int, rotation: float) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, sides, endpoint=False) + np.deg2rad(rotation)
    return np.column_stack(
        (center[0] + radius * np.cos(angles), center[1] + radius * np.sin(angles))
    ).astype(np.int32)


def _rotated_box(center: tuple[int, int], size: tuple[int, int], angle: float) -> np.ndarray:
    return cv2.boxPoints((center, size, angle)).astype(np.int32)


def _names(image: np.ndarray) -> list[str]:
    app = ShapeRecognitionApp.__new__(ShapeRecognitionApp)
    return [item.name for item in app._detect_shapes(image)]


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


def test_rotated_square_is_detected_from_image() -> None:
    image = _card_with_polygon(_rotated_box((320, 240), (150, 150), 33))

    assert _names(image) == [SHAPE_SQUARE]


def test_rotated_rectangle_is_detected_from_image() -> None:
    image = _card_with_polygon(_rotated_box((320, 240), (220, 105), -27))

    assert _names(image) == [SHAPE_RECTANGLE]


def test_left_slanting_parallelogram_is_detected_from_image() -> None:
    points = np.array([[245, 150], [430, 150], [385, 330], [200, 330]])

    assert _names(_card_with_polygon(points)) == [SHAPE_PARALLELOGRAM]


def test_right_slanting_parallelogram_is_detected_from_image() -> None:
    points = np.array([[210, 150], [395, 150], [440, 330], [255, 330]])

    assert _names(_card_with_polygon(points)) == [SHAPE_PARALLELOGRAM]


def test_circle_is_detected_from_image() -> None:
    image = _card_canvas()
    cv2.circle(image, (320, 240), 92, (30, 70, 215), -1, cv2.LINE_AA)

    assert _names(image) == [SHAPE_CIRCLE]


def test_ellipse_is_not_detected_as_circle() -> None:
    image = _card_canvas()
    cv2.ellipse(image, (320, 240), (125, 66), 24, 0, 360, (30, 70, 215), -1)

    assert SHAPE_CIRCLE not in _names(image)


def test_rounded_rectangle_is_not_detected_as_circle() -> None:
    image = _card_canvas()
    color = (30, 70, 215)
    cv2.rectangle(image, (254, 165), (386, 315), color, -1)
    cv2.rectangle(image, (220, 199), (420, 281), color, -1)
    for center in ((254, 199), (386, 199), (254, 281), (386, 281)):
        cv2.circle(image, center, 34, color, -1)

    assert SHAPE_CIRCLE not in _names(image)


def test_five_point_star_is_detected_from_image() -> None:
    center = np.array([320.0, 240.0])
    points = []
    for index in range(10):
        radius = 112 if index % 2 == 0 else 47
        angle = np.deg2rad(-90 + index * 36)
        points.append(center + radius * np.array([np.cos(angle), np.sin(angle)]))

    assert _names(_card_with_polygon(np.array(points))) == [SHAPE_STAR]


def test_regular_pentagon_is_detected_from_image() -> None:
    points = _regular_polygon((320, 245), 112, 5, -90)

    assert _names(_card_with_polygon(points)) == [SHAPE_PENTAGON]


def test_irregular_pentagon_is_not_detected_as_regular_pentagon() -> None:
    points = np.array([[320, 125], [470, 190], [410, 350], [260, 330], [180, 185]])

    assert SHAPE_PENTAGON not in _names(_card_with_polygon(points))


def test_trapezoid_is_not_detected_as_square() -> None:
    points = np.array([[245, 150], [395, 150], [455, 330], [185, 330]])

    assert SHAPE_SQUARE not in _names(_card_with_polygon(points))


def test_rhombus_is_not_detected_as_square() -> None:
    points = np.array([[320, 125], [445, 240], [320, 355], [195, 240]])

    assert SHAPE_SQUARE not in _names(_card_with_polygon(points))


def test_blank_paper_does_not_return_a_shape() -> None:
    assert _names(_card_canvas()) == []


def test_small_printed_square_is_detected() -> None:
    image = _card_with_polygon(_rotated_box((385, 285), (46, 46), 18))

    assert _names(image) == [SHAPE_SQUARE]


def test_shape_on_left_side_of_card_is_detected() -> None:
    image = _card_with_polygon(_rotated_box((180, 245), (72, 72), -14))

    assert _names(image) == [SHAPE_SQUARE]


def test_stable_shape_survives_one_missing_frame() -> None:
    app = ShapeRecognitionApp.__new__(ShapeRecognitionApp)
    app._stable_signatures = {}
    detections = app._detect_shapes(
        _card_with_polygon(_rotated_box((320, 240), (150, 150), 20))
    )

    assert app._stabilize(detections) == []
    assert app._stabilize(detections)
    assert app._stabilize([])
