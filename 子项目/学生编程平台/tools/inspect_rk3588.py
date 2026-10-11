from __future__ import annotations

import getpass
import os
from pathlib import Path

import paramiko


COMMAND = r'''set -eu
dpkg-query -W -f='${Status} ${Version}\n' libxcb-cursor0
runuser -u ztl -- env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus gio set /home/ztl/Desktop/AIBox学生编程平台.desktop metadata::trusted true
runuser -u ztl -- env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus gio info -a metadata::trusted /home/ztl/Desktop/AIBox学生编程平台.desktop
sleep 4
pkill -TERM -u ztl -f '^python3 -m aibox_studio.app' 2>/dev/null || true
sleep 2
runuser -u ztl -- env DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000 sh -c 'nohup /usr/local/bin/aibox-studio >/tmp/aibox-studio-ztl.log 2>&1 &'
sleep 5
echo DEVICE_SERVICE
systemctl is-active aibox-arm-device.service
ls -l /run/aibox-device/arm.sock
runuser -u ztl -- python3 - <<'PY'
import json
import socket
client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
client.settimeout(2)
client.connect('/run/aibox-device/arm.sock')
client.sendall(b'{"command":"stop","payload":{}}\n')
response = json.loads(client.makefile('r', encoding='utf-8').readline())
client.close()
assert response.get('ok') is True, response
print('NO_MOTION_HANDSHAKE_OK')
PY
echo ROBOT_SERIAL_OWNER
fuser -v /dev/esp32_arm 2>&1 || true
echo PROCESS
pgrep -a -u ztl -f '^python3 -m aibox_studio.app' || { cat /tmp/aibox-studio-ztl.log; exit 1; }
echo LOG
cat /tmp/aibox-studio-ztl.log
runuser -u ztl -- env DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000 PYTHONPATH=/opt/aibox-studio/vendor python3 - <<'PY'
from PySide6.QtWidgets import QApplication
application = QApplication([])
image = application.primaryScreen().grabWindow(0)
if image.isNull() or not image.save('/tmp/aibox-studio-screen.png'):
    raise SystemExit('screen capture failed')
print(image.width(), image.height())
PY
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
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if errors:
            print(errors, end="")
        if status == 0:
            destination = Path(__file__).resolve().parents[1] / "output" / "rk3588" / "aibox-studio-screen.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            sftp = client.open_sftp()
            try:
                sftp.get("/tmp/aibox-studio-screen.png", str(destination))
            finally:
                sftp.close()
            print(f"SCREENSHOT={destination}")
        raise SystemExit(status)
    finally:
        client.close()


if __name__ == "__main__":
    main()
