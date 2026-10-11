from __future__ import annotations

import getpass
import os
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parent
FILES = {
    ROOT / "arm_prepower_upright.py": "/tmp/arm_prepower_upright.py",
    ROOT / "aibox-arm-prepower-upright.service": "/tmp/aibox-arm-prepower-upright.service",
    ROOT / "99-aibox-arm-prepower.rules": "/tmp/99-aibox-arm-prepower.rules",
}


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
        sftp = client.open_sftp()
        try:
            for source, target in FILES.items():
                sftp.put(str(source), target)
        finally:
            sftp.close()

        command = r'''set -eu
test "$(systemctl is-active robot-arm.service 2>/dev/null || true)" != active
test "$(systemctl is-active feature-demo.service 2>/dev/null || true)" != active
if fuser -s /dev/esp32_arm 2>/dev/null; then
  echo '机械臂串口当前被占用，拒绝安装和预置。' >&2
  exit 1
fi
stamp=$(date +%Y%m%d_%H%M%S)
backup=/root/arm-prepower-backups/$stamp
mkdir -p "$backup"
test ! -e /usr/local/sbin/arm_prepower_upright.py || cp -a /usr/local/sbin/arm_prepower_upright.py "$backup/"
test ! -e /etc/systemd/system/aibox-arm-prepower-upright.service || cp -a /etc/systemd/system/aibox-arm-prepower-upright.service "$backup/"
test ! -e /etc/udev/rules.d/99-aibox-arm-prepower.rules || cp -a /etc/udev/rules.d/99-aibox-arm-prepower.rules "$backup/"
install -m0755 /tmp/arm_prepower_upright.py /usr/local/sbin/arm_prepower_upright.py
install -m0644 /tmp/aibox-arm-prepower-upright.service /etc/systemd/system/aibox-arm-prepower-upright.service
install -m0644 /tmp/99-aibox-arm-prepower.rules /etc/udev/rules.d/99-aibox-arm-prepower.rules
systemctl daemon-reload
udevadm control --reload-rules
systemctl enable aibox-arm-prepower-upright.service >/dev/null
systemctl start aibox-arm-prepower-upright.service
systemctl show aibox-arm-prepower-upright.service -p ActiveState -p Result -p ExecMainStatus
cat /var/lib/aibox-arm/prepower-state.json
if fuser -s /dev/esp32_arm 2>/dev/null; then
  echo '预置完成后串口仍被占用。' >&2
  exit 1
fi
echo "BACKUP=$backup"
'''
        _, stdout, stderr = client.exec_command(command, timeout=60)
        output = stdout.read().decode("utf-8", errors="replace")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        print(output, end="")
        if errors:
            print(errors, end="")
        if status:
            raise SystemExit(status)
    finally:
        client.close()


if __name__ == "__main__":
    main()
