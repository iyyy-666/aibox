from __future__ import annotations

import numpy as np

import hand_landmarks
from hand_landmarks import HandLandmarkDetector, classify_rps


def make_hand(*, index: bool, middle: bool, ring: bool, pinky: bool) -> np.ndarray:
    points = np.zeros((21, 2), dtype=np.float32)
    points[0] = (100, 210)
    for extended, (mcp, pip, dip, tip), x in zip(
        (index, middle, ring, pinky),
        ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20)),
        (55, 90, 125, 160),
    ):
        points[mcp] = (x, 170)
        points[pip] = (x, 125)
        if extended:
            points[dip] = (x, 85)
            points[tip] = (x, 45)
        else:
            points[dip] = (x + 28, 145)
            points[tip] = (x + 38, 165)
    return points


def test_classify_rps_identifies_rock_scissors_and_paper() -> None:
    assert classify_rps(make_hand(index=False, middle=False, ring=False, pinky=False))[0] == "rock"
    assert classify_rps(make_hand(index=True, middle=True, ring=False, pinky=False))[0] == "scissors"
    assert classify_rps(make_hand(index=True, middle=True, ring=True, pinky=True))[0] == "paper"


def test_classify_rps_does_not_force_unknown_pose_into_rps() -> None:
    label, confidence = classify_rps(make_hand(index=True, middle=False, ring=True, pinky=False))

    assert label is None
    assert confidence == 0.0


def test_detector_gracefully_reports_missing_mediapipe(monkeypatch) -> None:
    monkeypatch.setattr(hand_landmarks, "mp", None)

    detector = HandLandmarkDetector()

    assert not detector.available
    assert detector.error
    assert detector.detect(np.zeros((100, 100, 3), dtype=np.uint8)) == []
