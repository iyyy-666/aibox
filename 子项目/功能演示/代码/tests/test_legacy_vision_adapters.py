from __future__ import annotations

from feature_demo.adapters.vision import LEGACY_VISION_SPECS, build_vision_adapter


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
