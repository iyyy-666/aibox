from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

try:
    import mediapipe as mp
except ImportError:
    mp = None


Box = tuple[int, int, int, int]
LONG_FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))


@dataclass(frozen=True)
class HandObservation:
    box: Box
    landmarks: np.ndarray
    gesture: str | None
    confidence: float
    source: str = "mediapipe"


def _joint_angle(points: np.ndarray, mcp: int, pip: int, tip: int) -> float:
    first = points[mcp] - points[pip]
    second = points[tip] - points[pip]
    first_norm = float(np.linalg.norm(first))
    second_norm = float(np.linalg.norm(second))
    if first_norm < 1e-4 or second_norm < 1e-4:
        return 0.0
    cosine = float(np.dot(first, second) / (first_norm * second_norm))
    return math.degrees(math.acos(float(np.clip(cosine, -1.0, 1.0))))


def finger_is_extended(landmarks: np.ndarray, finger: tuple[int, int, int, int]) -> bool:
    mcp, pip, _dip, tip = finger
    return _joint_angle(landmarks, mcp, pip, tip) >= 145.0


def classify_rps(landmarks: np.ndarray) -> tuple[str | None, float]:
    if landmarks.shape != (21, 2):
        return None, 0.0
    extended = [finger_is_extended(landmarks, finger) for finger in LONG_FINGERS]
    if extended == [False, False, False, False]:
        return "rock", 0.80
    if extended == [True, True, False, False]:
        return "scissors", 0.86
    if extended == [True, True, True, True]:
        return "paper", 0.88
    return None, 0.0


class HandLandmarkDetector:
    def __init__(self) -> None:
        self._hands = None
        self.available = False
        self.error = ""
        if mp is None:
            self.error = "MediaPipe is not installed"
            return
        try:
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.60,
                min_tracking_confidence=0.55,
            )
            self.available = True
        except Exception as exc:
            self.error = f"MediaPipe initialization failed: {exc}"

    def detect(self, image: np.ndarray) -> list[HandObservation]:
        if not self.available or self._hands is None:
            return []
        try:
            result = self._hands.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        except Exception as exc:
            self.available = False
            self.error = f"MediaPipe inference failed: {exc}"
            return []
        if not result.multi_hand_landmarks:
            return []

        height, width = image.shape[:2]
        observations: list[HandObservation] = []
        for hand in result.multi_hand_landmarks:
            points = np.array([(item.x * width, item.y * height) for item in hand.landmark], dtype=np.float32)
            min_xy = np.floor(points.min(axis=0)).astype(int)
            max_xy = np.ceil(points.max(axis=0)).astype(int)
            padding = max(8, int(max(max_xy - min_xy) * 0.12))
            x1, y1 = np.maximum((0, 0), min_xy - padding)
            x2, y2 = np.minimum((width - 1, height - 1), max_xy + padding)
            if x2 <= x1 or y2 <= y1:
                continue
            gesture, confidence = classify_rps(points)
            observations.append(
                HandObservation((int(x1), int(y1), int(x2 - x1), int(y2 - y1)), points, gesture, confidence)
            )
        return observations

    def close(self) -> None:
        if self._hands is not None:
            self._hands.close()
            self._hands = None
