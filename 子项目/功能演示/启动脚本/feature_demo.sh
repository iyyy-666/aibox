#!/bin/sh
set -eu

APP_ROOT="/root/robot_arm"
cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export VOICE_LANGUAGE="${VOICE_LANGUAGE:-zh}"
exec python3 -m feature_demo.launcher
