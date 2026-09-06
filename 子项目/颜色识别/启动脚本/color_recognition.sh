#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
export COLOR_CAMERA_WIDTH=${COLOR_CAMERA_WIDTH:-1280}
export COLOR_CAMERA_HEIGHT=${COLOR_CAMERA_HEIGHT:-480}
export COLOR_DISPLAY_INTERVAL_MS=${COLOR_DISPLAY_INTERVAL_MS:-110}
export COLOR_CAPTURE_INTERVAL_SEC=${COLOR_CAPTURE_INTERVAL_SEC:-0.035}
export COLOR_DETECT_INTERVAL_SEC=${COLOR_DETECT_INTERVAL_SEC:-0.18}
export COLOR_MIN_AREA=${COLOR_MIN_AREA:-1800}
export COLOR_STABLE_HITS=${COLOR_STABLE_HITS:-2}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/color_recognition.lock"
flock -n 9 || exit 0
exec 8>"$LOCK_DIR/aibox_gimbal_serial.lock"
flock -n 8 || exit 0
v4l2-ctl -d /dev/video41 --set-ctrl=saturation=74 >/dev/null 2>&1 || true
cd /root/robot_arm
exec python3 /root/robot_arm/color_recognition_app.py
