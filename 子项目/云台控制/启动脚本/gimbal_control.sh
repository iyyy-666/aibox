#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/run/user/1000/gdm/Xauthority}
export GIMBAL_BACKEND=serial
export GIMBAL_SERIAL_PROTOCOL=pwm
export GIMBAL_SERIAL_BAUD=115200
export GIMBAL_STEP=30
export GIMBAL_MOVE_TIME_MS=350
export GIMBAL_SERIAL_REQUIRE_ACK=1
export GIMBAL_SERIAL_PORTS=/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00,/dev/ttyACM0
export AIBOX_GIMBAL_POSITION_STATE=${AIBOX_GIMBAL_POSITION_STATE:-/tmp/aibox_gimbal_position.json}
LOCK_DIR=${XDG_RUNTIME_DIR:-/tmp}
exec 8>"$LOCK_DIR/aibox_gimbal_serial.lock"
flock -n 8 || exit 0
exec /usr/bin/python3 /root/robot_arm/gimbal_control_app.py
