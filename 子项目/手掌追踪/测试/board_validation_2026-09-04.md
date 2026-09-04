# Board Validation Record - 2026-09-04

## Non-motion deployment verification

- Local test environment: `.venv` with Python 3.14.6, pytest 9.1.1, NumPy 2.5.2, and OpenCV 5.0.0.
- Local automated result: 16 passed.
- Uploaded without starting the application: `hand_landmarks.py`, `vision_targeting.py`, `palm_tracking_control.py`, `palm_tracking_serial.py`, `palm_tracking_app.py`, `palm_tracking.sh`, `palm_tracking.desktop`, and `palm_tracking.svg`.
- Board device checks passed: `/dev/video41` and `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00` exist.
- Board syntax check passed: `palm_tracking_app.py`, `palm_tracking_control.py`, and `palm_tracking_serial.py` compile with board Python 3.
- Desktop entry and icon checks passed: `/home/ztl/Desktop/palm_tracking.desktop` and `/root/robot_arm/assets/icons/palm_tracking.svg` exist.
- Process check passed: no `palm_tracking_app.py` process was running during validation.

## Physical acceptance pending

No camera preview, serial movement, calibration, or tracking command has been run by this validation. The remaining acceptance requires the user physically present at the cloud platform to supervise 4-PWM axis-direction calibration and the hand-tracking test sequence.
