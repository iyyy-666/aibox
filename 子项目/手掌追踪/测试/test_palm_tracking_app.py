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
