from __future__ import annotations

import getpass
import os

import paramiko


COMMAND = r'''set -u
echo DEVICE
ls -l /dev/esp32_arm 2>&1 || true
readlink -f /dev/esp32_arm 2>/dev/null || true
udevadm info --query=property --name /dev/esp32_arm 2>/dev/null | grep -E '^(DEVNAME|DEVLINKS|ID_VENDOR_ID|ID_MODEL_ID|ID_SERIAL|ID_PATH)=' || true
echo OWNERS
fuser -v /dev/esp32_arm 2>&1 || true
echo PROCESSES
pgrep -af 'robot|feature_demo|aibox_studio' || true
echo SERVICES
systemctl is-enabled robot-arm.service 2>/dev/null || true
systemctl is-active robot-arm.service 2>/dev/null || true
systemctl is-enabled feature-demo.service 2>/dev/null || true
systemctl is-active feature-demo.service 2>/dev/null || true
echo LAST_PWMS
cat /root/robot_arm/last_servo_pwms.json 2>/dev/null || echo MISSING
echo UPRIGHT
cd /root/robot_arm && python3 - <<'PY'
from config import PRESET_POSES
print(repr(PRESET_POSES.get('直立')))
PY
echo DRIVER_SENTINEL
grep -nE 'def set_all_servos|pwm.*-1|last_pwms|hold_current_position' /root/robot_arm/robot.py || true
echo UNITS
systemctl cat robot-arm.service 2>/dev/null || true
systemctl cat feature-demo.service 2>/dev/null || true
'''


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        os.environ.get("RK3588_HOST", "192.168.11.106"),
        username=os.environ.get("RK3588_USER", "root"),
        password=password,
        timeout=10,
    )
    try:
        _, stdout, stderr = client.exec_command(COMMAND, timeout=30)
        output = stdout.read().decode("utf-8", errors="replace")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        print(output, end="")
        if errors:
            print(errors, end="")
        raise SystemExit(status)
    finally:
        client.close()


if __name__ == "__main__":
    main()
