#!/bin/sh
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export PYTHONNOUSERSITE=1
CAMERA_DEVICE=${SORTING_CAMERA_DEVICE:-/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera_SN0001-video-index0}
v4l2-ctl -d "$CAMERA_DEVICE" --set-ctrl=power_line_frequency=1 >/dev/null 2>&1 || true
v4l2-ctl -d "$CAMERA_DEVICE" --set-ctrl=exposure_dynamic_framerate=0 >/dev/null 2>&1 || true
v4l2-ctl -d "$CAMERA_DEVICE" --set-ctrl=saturation=112 >/dev/null 2>&1 || true
exec /usr/bin/python3 /root/robot_arm/sorting_app.py
