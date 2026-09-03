#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
export PALM_CAMERA_WIDTH=${PALM_CAMERA_WIDTH:-1280}
export PALM_CAMERA_HEIGHT=${PALM_CAMERA_HEIGHT:-480}
export PALM_DISPLAY_INTERVAL_MS=${PALM_DISPLAY_INTERVAL_MS:-90}
export PALM_CAPTURE_INTERVAL_SEC=${PALM_CAPTURE_INTERVAL_SEC:-0.03}
export PALM_DETECT_INTERVAL_SEC=${PALM_DETECT_INTERVAL_SEC:-0.12}
export PALM_MIN_AREA=${PALM_MIN_AREA:-2600}
export PALM_STABLE_HITS=${PALM_STABLE_HITS:-1}
export PALM_YOLO_MODEL=${PALM_YOLO_MODEL:-/root/robot_arm/models/hand/hand_yolov8n.pt}
export PALM_YOLO_CONF=${PALM_YOLO_CONF:-0.25}
export PALM_YOLO_IMG_SIZE=${PALM_YOLO_IMG_SIZE:-416}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/palm_recognition.lock"
flock -n 9 || exit 0
v4l2-ctl -d /dev/video41 --set-ctrl=saturation=74 >/dev/null 2>&1 || true
cd /root/robot_arm
exec python3 /root/robot_arm/palm_recognition_app.py
