#!/bin/sh
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
CAMERA_DEVICE=${SORTING_CAMERA_DEVICE:-/dev/video41}
export SORTING_CAMERA_DEVICE="$CAMERA_DEVICE"
export SORTING_CAMERA_WIDTH=${SORTING_CAMERA_WIDTH:-1280}
export SORTING_CAMERA_HEIGHT=${SORTING_CAMERA_HEIGHT:-480}
export SORTING_CAMERA_FPS=${SORTING_CAMERA_FPS:-30}
export AIBOX_GIMBAL_POSITION_STATE=${AIBOX_GIMBAL_POSITION_STATE:-/tmp/aibox_gimbal_position.json}
v4l2-ctl -d "$CAMERA_DEVICE" --set-ctrl=power_line_frequency=1 >/dev/null 2>&1 || true
v4l2-ctl -d "$CAMERA_DEVICE" --set-ctrl=exposure_dynamic_framerate=0 >/dev/null 2>&1 || true
v4l2-ctl -d "$CAMERA_DEVICE" --set-ctrl=saturation=112 >/dev/null 2>&1 || true
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 8>"$LOCK_DIR/sorting_camera.lock"
flock -n 8 || exit 0
exec 7>"$LOCK_DIR/aibox_gimbal_serial.lock"
flock -n 7 || exit 0
exec /usr/bin/python3 /root/robot_arm/sorting_app.py
