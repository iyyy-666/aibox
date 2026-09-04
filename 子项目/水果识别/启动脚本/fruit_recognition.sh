#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONPATH="/root/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"
export PYTHONNOUSERSITE=1
export FRUIT_CAMERA_WIDTH=${FRUIT_CAMERA_WIDTH:-1280}
export FRUIT_CAMERA_HEIGHT=${FRUIT_CAMERA_HEIGHT:-480}
export FRUIT_DISPLAY_INTERVAL_MS=${FRUIT_DISPLAY_INTERVAL_MS:-70}
export FRUIT_CAPTURE_INTERVAL_SEC=${FRUIT_CAPTURE_INTERVAL_SEC:-0.025}
export FRUIT_DETECT_INTERVAL_SEC=${FRUIT_DETECT_INTERVAL_SEC:-0.18}
export FRUIT_YOLO_IMG_SIZE=${FRUIT_YOLO_IMG_SIZE:-512}
export FRUIT_CONF=${FRUIT_CONF:-0.28}
export FRUIT_STABLE_HITS=${FRUIT_STABLE_HITS:-2}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/fruit_recognition.lock"
flock -n 9 || exit 0
v4l2-ctl -d /dev/video41 --set-ctrl=saturation=74 >/dev/null 2>&1 || true
cd /root/robot_arm
exec python3 /root/robot_arm/fruit_recognition_app.py
