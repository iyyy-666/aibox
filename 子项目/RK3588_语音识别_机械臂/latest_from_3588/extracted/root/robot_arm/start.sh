#!/bin/bash
# 启动前绑定CH340驱动
echo 1a86 7523 > /sys/bus/usb-serial/drivers/cp210x/new_id 2>/dev/null
sleep 1
chmod 666 /dev/ttyUSB0 2>/dev/null

cd /root/robot_arm
exec python3 server.py

