#!/bin/bash
while [ "$(systemctl is-active ztl-wifibt)" != active ] || [ "$(systemctl show -p SubState --value ztl-wifibt)" != exited ]; do sleep 1; done
sudo killall rtk_hciattach
sudo rtk_hciattach -n -s 115200 /dev/ttyS8 rtk_h5
