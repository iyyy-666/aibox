from __future__ import annotations

import numpy as np

from hand_landmarks import HandObservation
from palm_recognition_app import PalmRecognitionApp
from vision_targeting import BoxTracker, TemporalGestureVote


class FakeDetector:
    available = True
    error = ""

    def detect(self, _image: np.ndarray) -> list[HandObservation]:
        return [
            HandObservation(
                box=(120, 90, 80, 110),
                landmarks=np.zeros((21, 2), dtype=np.float32),
                gesture="paper",
                confidence=0.88,
            )
        ]


class UnavailableDetector:
    available = False
    error = "MediaPipe is not installed"

    def detect(self, _image: np.ndarray) -> list[HandObservation]:
        return []


class UnknownGestureDetector(FakeDetector):
    def detect(self, _image: np.ndarray) -> list[HandObservation]:
        return [
            HandObservation(
                box=(120, 90, 80, 110),
                landmarks=np.zeros((21, 2), dtype=np.float32),
                gesture=None,
                confidence=0.0,
            )
        ]


def make_app(detector) -> PalmRecognitionApp:
    app = PalmRecognitionApp.__new__(PalmRecognitionApp)
    app.hand_detector = detector
    app.use_mediapipe = True
    app._tracker = BoxTracker(iou_threshold=0.3, hold_misses=3)
    app._voter = TemporalGestureVote(confirm_hits=4, hold_misses=3)
    app._candidate_boxes = lambda _image: [(88, 92, 78, 108)]
    app._fallback_detections = lambda _image: []
    return app


def test_palm_pipeline_only_confirms_when_stereo_match_and_vote_pass() -> None:
    app = make_app(FakeDetector())
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    assert not app._detect_hands(image, image)[0].stable
    assert not app._detect_hands(image, image)[0].stable
    assert not app._detect_hands(image, image)[0].stable
    detection = app._detect_hands(image, image)[0]

    assert detection.gesture == "布"
    assert detection.source == "MediaPipe"
    assert detection.stereo_verified
    assert detection.stable


def test_palm_pipeline_keeps_pending_box_when_stereo_is_not_verified() -> None:
    app = make_app(FakeDetector())
    app._candidate_boxes = lambda _image: []
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    detection = app._detect_hands(image, image)[0]

    assert detection.gesture == "布"
    assert not detection.stereo_verified
    assert not detection.stable


def test_palm_pipeline_displays_landmark_box_when_gesture_is_unknown() -> None:
    app = make_app(UnknownGestureDetector())
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    detection = app._detect_hands(image, image)[0]

    assert detection.gesture == "\u624b\u638c"
    assert detection.source == "MediaPipe"
    assert not detection.stable


def test_palm_pipeline_uses_contour_fallback_when_landmarks_unavailable() -> None:
    app = make_app(UnavailableDetector())
    app._fallback_detections = lambda _image: [("rock", (120, 90, 80, 110), 0.7, 0)]
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    assert app._detector_mode == "fallback"
    detection = app._detect_hands(image, image)[0]
    assert detection.gesture == "\u77f3\u5934"
    assert detection.source == "Contour"
    assert not detection.stable
