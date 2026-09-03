#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
cd /root/robot_arm
exec python3 /root/robot_arm/button_control_app.py
