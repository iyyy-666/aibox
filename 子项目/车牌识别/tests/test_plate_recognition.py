from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np


CODE_DIR = Path(__file__).resolve().parents[1] / "代码"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

gimbal_controls = ModuleType("gimbal_controls")
gimbal_controls.GimbalControls = object
sys.modules.setdefault("gimbal_controls", gimbal_controls)

spec = importlib.util.spec_from_file_location(
    "plate_recognition_app_under_test", CODE_DIR / "plate_recognition_app.py"
)
assert spec is not None and spec.loader is not None
plate_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plate_module
spec.loader.exec_module(plate_module)


def make_app(raw_results):
    app = plate_module.PlateRecognitionApp.__new__(plate_module.PlateRecognitionApp)
    app.catcher = lambda _image: raw_results
    app._set_status = lambda _message: None
    return app


def test_hyperlpr_four_corner_box_uses_all_coordinate_pairs():
    app = make_app([])

    box = app._parse_lpr_box(
        [100, 100, 180, 100, 180, 125, 100, 125], w=640, h=480
    )

    assert box == (100, 100, 180, 125)


def test_hyperlpr_keeps_a_readable_small_plate_candidate():
    app = make_app([["粤B12345", 0.93, 0, [220, 190, 290, 210]]])
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    detections = app._run_hyperlpr(image)

    assert len(detections) == 1
    assert detections[0].plate == "粤B12345"
    assert detections[0].box == (220, 190, 290, 210)


def test_hyperlpr_skips_malformed_coordinates_without_raising():
    app = make_app([["粤B12345", 0.93, 0, ["bad", 190, 290, 210]]])
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    assert app._run_hyperlpr(image) == []


def test_hyperlpr_rejects_low_confidence_plate_text():
    app = make_app([["粤B12345", 0.20, 0, [220, 190, 290, 210]]])
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    assert app._run_hyperlpr(image) == []


def test_hyperlpr_rejects_non_finite_or_out_of_range_confidence():
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    for confidence in (float("nan"), float("inf"), 1.01):
        app = make_app([["粤B12345", confidence, 0, [220, 190, 290, 210]]])
        assert app._run_hyperlpr(image) == []


def test_hyperlpr_rejects_text_that_is_not_a_license_plate():
    app = make_app([["HELLO123", 0.93, 0, [220, 190, 290, 210]]])
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    assert app._run_hyperlpr(image) == []


def test_hyperlpr_green_plate_type_is_reported_as_electric_vehicle():
    app = make_app([["粤AD12345", 0.93, 3, [220, 190, 320, 220]]])
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    detections = app._run_hyperlpr(image)

    assert len(detections) == 1
    assert detections[0].color == "Green Plate"
    assert detections[0].vehicle_type == "Electric Vehicle"


def test_color_only_candidate_is_not_reported_as_a_recognized_plate():
    app = make_app([])
    app._color_plate_candidates = lambda _image: [
        plate_module.PlateDetection(
            "", "Blue Plate", "Fuel Vehicle", (156, 0, 464, 136), 0.58, "Color"
        )
    ]
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    assert app._recognize_plates(image) == []


def test_low_level_model_retries_when_high_level_text_is_invalid():
    app = make_app([["沪A粤F8C921", 0.95, 3, [121, 182, 514, 314]]])
    app.fallback_catcher = lambda _image: [
        ["沪AF8C921", 0.93, 3, [108, 183, 520, 313]]
    ]
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    detections = app._recognize_plates(image)

    assert len(detections) == 1
    assert detections[0].plate == "沪AF8C921"
    assert detections[0].confidence == 0.93

