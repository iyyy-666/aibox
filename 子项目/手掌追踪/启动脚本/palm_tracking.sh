#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/run/user/1000/gdm/Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
export PYTHONPATH="/root/.local/lib/python3.10/site-packages:/usr/local/lib/python3.10/dist-packages:${PYTHONPATH:-}"
export PALM_TRACK_CAMERA_DEVICE=${PALM_TRACK_CAMERA_DEVICE:-/dev/video41}
export PALM_TRACK_CAMERA_WIDTH=${PALM_TRACK_CAMERA_WIDTH:-1280}
export PALM_TRACK_CAMERA_HEIGHT=${PALM_TRACK_CAMERA_HEIGHT:-480}
export PALM_TRACK_SERIAL_PORT=${PALM_TRACK_SERIAL_PORT:-/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00}
export PALM_TRACK_SERIAL_BAUD=${PALM_TRACK_SERIAL_BAUD:-115200}
export PALM_TRACK_YAW_ID=${PALM_TRACK_YAW_ID:-1}
export PALM_TRACK_PITCH_ID=${PALM_TRACK_PITCH_ID:-2}
export PALM_TRACK_PWM_MIN=${PALM_TRACK_PWM_MIN:-500}
export PALM_TRACK_PWM_MAX=${PALM_TRACK_PWM_MAX:-2500}
export PALM_TRACK_MAX_DEGREES_PER_SECOND=${PALM_TRACK_MAX_DEGREES_PER_SECOND:-80}
export PALM_TRACK_YAW_SIGN=${PALM_TRACK_YAW_SIGN:-1}
export PALM_TRACK_PITCH_SIGN=${PALM_TRACK_PITCH_SIGN:-1}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/palm_tracking.lock"
flock -n 9 || exit 0
v4l2-ctl -d "$PALM_TRACK_CAMERA_DEVICE" --set-ctrl=saturation=74 >/dev/null 2>&1 || true
cd /root/robot_arm
exec python3 /root/robot_arm/palm_tracking_app.py
