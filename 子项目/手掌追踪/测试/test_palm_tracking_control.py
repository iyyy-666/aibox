from palm_tracking_control import PalmTargetLock, PalmTrackingController, TrackingConfig


def test_arm_chooses_box_nearest_image_center() -> None:
    lock = PalmTargetLock()

    assert lock.arm([(5, 5, 50, 50), (290, 220, 80, 80)], (640, 480)) == (290, 220, 80, 80)


def test_lock_rejects_distant_replacement_box() -> None:
    lock = PalmTargetLock()
    lock.arm([(290, 220, 80, 80)], (640, 480))

    assert lock.update([(20, 20, 80, 80)]) is None


def test_deadband_emits_no_pwm_command() -> None:
    controller = PalmTrackingController(TrackingConfig())
    controller.start((290, 220, 60, 60), now=0.0)

    decision = controller.update((300, 225, 40, 40), (640, 480), now=0.1)

    assert decision.state == "centered"
    assert decision.yaw_delta_pwm == 0
    assert decision.pitch_delta_pwm == 0


def test_rate_limit_caps_a_tenth_second_to_twenty_two_pwm() -> None:
    controller = PalmTrackingController(TrackingConfig(max_step_pwm=100, smoothing_alpha=1.0))
    controller.start((300, 220, 40, 40), now=0.0)

    decision = controller.update((580, 220, 40, 40), (640, 480), now=0.1)

    assert decision.state == "tracking"
    assert 0 < abs(decision.yaw_delta_pwm) <= 22


def test_axis_sign_reverses_yaw_command() -> None:
    controller = PalmTrackingController(TrackingConfig(yaw_sign=-1, smoothing_alpha=1.0))
    controller.start((300, 220, 40, 40), now=0.0)

    assert controller.update((580, 220, 40, 40), (640, 480), now=0.1).yaw_delta_pwm < 0


def test_feedback_reverses_axis_when_a_command_increases_error() -> None:
    controller = PalmTrackingController(TrackingConfig(smoothing_alpha=1.0))
    controller.start((300, 220, 40, 40), now=0.0)
    controller.update((500, 220, 40, 40), (640, 480), now=0.1)

    reversed_axes = controller.observe_feedback(offset_x=0.75, offset_y=0.0)

    assert reversed_axes == (True, False)
    assert controller.yaw_sign == -1


def test_loss_after_half_second_stops_control() -> None:
    controller = PalmTrackingController(TrackingConfig(lost_timeout_sec=0.5))
    controller.start((300, 220, 40, 40), now=0.0)

    assert controller.update(None, (640, 480), now=0.51).state == "lost"


def test_stop_returns_idle_without_motion() -> None:
    controller = PalmTrackingController(TrackingConfig())
    controller.start((300, 220, 40, 40), now=0.0)
    controller.stop()

    decision = controller.update((580, 220, 40, 40), (640, 480), now=0.1)

    assert decision.state == "idle"
    assert decision.yaw_delta_pwm == 0
