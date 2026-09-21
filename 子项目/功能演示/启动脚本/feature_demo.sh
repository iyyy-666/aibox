#!/bin/sh
set -eu

APP_DIR="/opt/aibox/feature-demo/code"
export PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m feature_demo.launcher
