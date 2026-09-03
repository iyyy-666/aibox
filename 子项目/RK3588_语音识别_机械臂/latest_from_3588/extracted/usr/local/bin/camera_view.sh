#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
export CAMERA_WIDTH=${CAMERA_WIDTH:-1280}
export CAMERA_HEIGHT=${CAMERA_HEIGHT:-480}
export CAMERA_DISPLAY_INTERVAL_MS=${CAMERA_DISPLAY_INTERVAL_MS:-95}
export CAMERA_CAPTURE_INTERVAL_SEC=${CAMERA_CAPTURE_INTERVAL_SEC:-0.025}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/camera_view.lock"
flock -n 9 || exit 0
v4l2-ctl -d /dev/video41 --set-ctrl=saturation=74 >/dev/null 2>&1 || true
cd /root/robot_arm
exec python3 /root/robot_arm/camera_view_app.py
