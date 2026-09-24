import threading

import numpy as np

from palm_tracking_app import PalmTrackingApp, is_start_ready


def test_start_region_requires_palm_center_near_image_center() -> None:
    assert is_start_ready((280, 200, 80, 80), (640, 480))
    assert is_start_ready((20, 200, 80, 80), (640, 480))
    assert not is_start_ready(None, (640, 480))


def test_start_is_rejected_until_a_center_palm_is_available() -> None:
    app = PalmTrackingApp.__new__(PalmTrackingApp)
    app.current_box = None
    app.image_size = (640, 480)
    app.tracking_enabled = False

    assert not app.start_tracking()


def test_stop_clears_lock_without_sending_center_command() -> None:
    class Lock:
        cleared = False

        def clear(self) -> None:
            self.cleared = True

    class Controller:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    class ButtonText:
        def set(self, _text: str) -> None:
            pass

    app = PalmTrackingApp.__new__(PalmTrackingApp)
    app.tracking_enabled = True
    app.target_lock = Lock()
    app.controller = Controller()
    app.button_text = ButtonText()
    app._set_status = lambda _text: None

    app.stop_tracking("user")

    assert not app.tracking_enabled
    assert app.target_lock.cleared
    assert app.controller.stopped


def test_detection_falls_back_to_independent_right_eye_detector() -> None:
    calls = []

    class LeftDetector:
        def detect(self, image):
            calls.append(("left", int(image[0, 0, 0])))
            return []

    class Observation:
        box = (12, 18, 30, 40)
        landmarks = np.full((21, 2), (20, 24), dtype=np.float32)

    class RightDetector:
        def detect(self, image):
            calls.append(("right", int(image[0, 0, 0])))
            app.running = False
            return [Observation()]

    class TargetLock:
        def update(self, boxes):
            return boxes[0] if boxes else None

    app = PalmTrackingApp.__new__(PalmTrackingApp)
    app.running = True
    app.frame = np.concatenate(
        (
            np.zeros((4, 6, 3), dtype=np.uint8),
            np.ones((4, 6, 3), dtype=np.uint8),
        ),
        axis=1,
    )
    app.frame_lock = threading.Lock()
    app.box_lock = threading.Lock()
    app.hand_detector = LeftDetector()
    app.right_hand_detector = RightDetector()
    app.tracking_enabled = True
    app.target_lock = TargetLock()
    app.current_box = None
    app._set_status = lambda _text: None

    app._detect_loop()

    assert calls == [("left", 0), ("right", 1)]
    assert app._detection_eye == "right"
    assert app.current_box == (12, 18, 30, 40)
    np.testing.assert_array_equal(app.current_landmarks, Observation.landmarks)


def test_annotation_draws_the_detected_hand_landmarks() -> None:
    app = PalmTrackingApp.__new__(PalmTrackingApp)
    app.tracking_enabled = False
    app.current_landmarks = np.full((21, 2), (5, 5), dtype=np.float32)

    annotated = app._annotate(np.zeros((100, 100, 3), dtype=np.uint8), None)

    assert annotated[5, 5].any()
