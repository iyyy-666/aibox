#!/bin/sh

DEVICE_MODEL=$(awk -F', ' '{print $2}' /proc/device-tree/model)
echo "Device: $DEVICE_MODEL"


if [ -e /home/ztl/deviceTest.ini ];then
    echo "find the deviceTest.ini file!!!!"
else 
    if [ -e /home/ztl/configs/$DEVICE_MODEL.ini ];then
	ln -s /home/ztl/configs/$DEVICE_MODEL.ini /home/ztl/deviceTest.ini
    else
	ln -s /home/ztl/configs/deviceTest.ini  /home/ztl/deviceTest.ini
    fi
fi

