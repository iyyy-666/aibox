#!/bin/bash
set -euo pipefail

export PYTHONPATH=/opt/aibox-studio/src:/opt/aibox-studio/vendor
export AIBOX_WORKSPACE_ROOT=/home/ztl/Documents/AIBoxStudio/cn.aibox.basic-ai
export AIBOX_DEVICE_MODE=hardware
export AIBOX_ARM_SOCKET=/run/aibox-device/arm.sock
export PYTHONIOENCODING=utf-8
exec python3 -m aibox_studio.app "$@"
