#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
export FACE_CAMERA_WIDTH=${FACE_CAMERA_WIDTH:-1280}
export FACE_CAMERA_HEIGHT=${FACE_CAMERA_HEIGHT:-480}
export FACE_DISPLAY_INTERVAL_MS=${FACE_DISPLAY_INTERVAL_MS:-160}
export FACE_CAPTURE_INTERVAL_SEC=${FACE_CAPTURE_INTERVAL_SEC:-0.055}
export FACE_DETECT_INTERVAL_SEC=${FACE_DETECT_INTERVAL_SEC:-1.10}
export FACE_DETECT_SCALE=${FACE_DETECT_SCALE:-0.38}
export FACE_USE_DNN=${FACE_USE_DNN:-1}
export FACE_DNN_CONF_THRESHOLD=${FACE_DNN_CONF_THRESHOLD:-0.68}
export FACE_YUNET_INPUT_WIDTH=${FACE_YUNET_INPUT_WIDTH:-320}
export FACE_YUNET_INPUT_HEIGHT=${FACE_YUNET_INPUT_HEIGHT:-320}
export FACE_YUNET_SCORE_THRESHOLD=${FACE_YUNET_SCORE_THRESHOLD:-0.78}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/face_recognition.lock"
flock -n 9 || exit 0
exec 8>"$LOCK_DIR/aibox_gimbal_serial.lock"
flock -n 8 || exit 0
v4l2-ctl -d /dev/video41 --set-ctrl=saturation=74 >/dev/null 2>&1 || true
cd /root/robot_arm
exec python3 /root/robot_arm/face_recognition_app.py
