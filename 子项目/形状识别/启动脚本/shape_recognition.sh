#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
export SHAPE_CAMERA_WIDTH=${SHAPE_CAMERA_WIDTH:-1280}
export SHAPE_CAMERA_HEIGHT=${SHAPE_CAMERA_HEIGHT:-480}
export SHAPE_DISPLAY_INTERVAL_MS=${SHAPE_DISPLAY_INTERVAL_MS:-80}
export SHAPE_CAPTURE_INTERVAL_SEC=${SHAPE_CAPTURE_INTERVAL_SEC:-0.025}
export SHAPE_DETECT_INTERVAL_SEC=${SHAPE_DETECT_INTERVAL_SEC:-0.14}
export SHAPE_MIN_AREA=${SHAPE_MIN_AREA:-2200}
export SHAPE_STABLE_HITS=${SHAPE_STABLE_HITS:-3}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/shape_recognition.lock"
flock -n 9 || exit 0
exec 8>"$LOCK_DIR/aibox_gimbal_serial.lock"
flock -n 8 || exit 0
v4l2-ctl -d /dev/video41 --set-ctrl=saturation=74 >/dev/null 2>&1 || true
cd /root/robot_arm
exec python3 /root/robot_arm/shape_recognition_app.py
