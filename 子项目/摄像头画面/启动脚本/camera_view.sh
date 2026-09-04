#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
export CAMERA_WIDTH=${CAMERA_WIDTH:-1280}
export CAMERA_HEIGHT=${CAMERA_HEIGHT:-480}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$LOCK_DIR/camera_view.lock"
flock -n 9 || exit 0
cd /root/robot_arm
exec python3 /root/robot_arm/camera_view_app.py
