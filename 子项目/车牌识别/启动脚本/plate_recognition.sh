#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONPATH="/root/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"
export PLATE_CAMERA_WIDTH=${PLATE_CAMERA_WIDTH:-1280}
export PLATE_CAMERA_HEIGHT=${PLATE_CAMERA_HEIGHT:-480}
export PLATE_DISPLAY_INTERVAL_MS=${PLATE_DISPLAY_INTERVAL_MS:-80}
export PLATE_CAPTURE_INTERVAL_SEC=${PLATE_CAPTURE_INTERVAL_SEC:-0.025}
export PLATE_DETECT_INTERVAL_SEC=${PLATE_DETECT_INTERVAL_SEC:-0.22}
export PLATE_MIN_AREA=${PLATE_MIN_AREA:-1600}
export PLATE_STABLE_HITS=${PLATE_STABLE_HITS:-2}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/plate_recognition.lock"
flock -n 9 || exit 0
exec 8>"$LOCK_DIR/aibox_gimbal_serial.lock"
flock -n 8 || exit 0
v4l2-ctl -d /dev/video41 --set-ctrl=saturation=74 >/dev/null 2>&1 || true
cd /root/robot_arm
exec python3 /root/robot_arm/plate_recognition_app.py
