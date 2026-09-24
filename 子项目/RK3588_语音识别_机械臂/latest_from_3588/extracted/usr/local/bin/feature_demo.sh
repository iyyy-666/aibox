#!/bin/sh
set -eu

APP_ROOT="/root/robot_arm"
if [ -r /etc/default/feature-demo ]; then
  set -a
  . /etc/default/feature-demo
  set +a
fi
cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export VOICE_LANGUAGE="${VOICE_LANGUAGE:-zh}"
export AIBOX_GIMBAL_POSITION_STATE="${AIBOX_GIMBAL_POSITION_STATE:-/tmp/aibox_gimbal_position_$(id -u).json}"
exec python3 -m feature_demo.launcher
