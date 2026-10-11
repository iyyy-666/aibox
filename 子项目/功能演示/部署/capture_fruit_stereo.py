from __future__ import annotations

import getpass
import os
from pathlib import Path

import paramiko


COMMAND = r'''set -eu
launcher_pid=$(pgrep -f '^python3 -m feature_demo.launcher$' | head -n1)
port=$(ss -ltnp | sed -n "s/.*127.0.0.1:\([0-9][0-9]*\).*pid=$launcher_pid.*/\1/p" | head -n1)
test -n "$port"
curl -fsS -X POST "http://127.0.0.1:$port/api/modules/fruit_recognition/stop" >/dev/null
sleep 1
cd /root/robot_arm
python3 - <<'PY'
import cv2
import time

cap = cv2.VideoCapture('/dev/video41', cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)
frame = None
for _ in range(12):
    ok, candidate = cap.read()
    if ok:
        frame = candidate
    time.sleep(0.03)
cap.release()
if frame is None:
    raise SystemExit('camera capture failed')
cv2.imwrite('/tmp/fruit-stereo.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
print('RAW_SHAPE=', frame.shape)
PY
curl -fsS -X POST "http://127.0.0.1:$port/api/modules/fruit_recognition/start" >/dev/null
sleep 2
echo RESTORED
'''


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.11.106", username="root", password=password, timeout=10)
    try:
        _, stdout, stderr = client.exec_command(COMMAND, timeout=40)
        output = stdout.read().decode("utf-8", errors="replace")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        print(output, end="")
        if errors:
            print(errors, end="")
        if status:
            raise SystemExit(status)
        local = Path(__file__).resolve().parents[1] / "output" / "fruit-stereo.jpg"
        local.parent.mkdir(parents=True, exist_ok=True)
        client.open_sftp().get("/tmp/fruit-stereo.jpg", str(local))
        print(f"FRAME_PATH={local}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
