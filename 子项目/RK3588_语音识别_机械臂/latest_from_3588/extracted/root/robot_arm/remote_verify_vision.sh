#!/bin/bash
set -euo pipefail

cd /root/robot_arm
python3 -m pip install -r requirements-mediapipe.txt
python3 - <<'PY'
import cv2
import mediapipe
print("opencv", cv2.__version__)
print("mediapipe", mediapipe.__version__)
PY
python3 -m py_compile \
  vision_targeting.py hand_landmarks.py palm_recognition_app.py \
  color_recognition_app.py shape_recognition_app.py fruit_recognition_app.py \
  plate_recognition_app.py face_recognition_app.py camera_view_app.py
v4l2-ctl --list-devices
test -e /dev/video41
echo "vision verification passed: /dev/video41"
