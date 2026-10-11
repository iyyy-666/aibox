from __future__ import annotations

import base64
import getpass
import json
import os
from pathlib import Path

import paramiko


COMMAND = r'''set -u
echo VIDEO_DEVICES
echo PYTHON_RUNTIMES
for python_bin in /usr/bin/python3 /usr/local/bin/python3; do
  if [ -x "$python_bin" ]; then
    "$python_bin" - <<'PY' || true
import importlib.util
import sys
print(sys.executable, sys.version.split()[0], {
    name: bool(importlib.util.find_spec(name))
    for name in ('cv2', 'numpy', 'ultralytics', 'fastapi')
})
PY
  fi
done
v4l2-ctl --list-devices 2>/dev/null || true
for device in /dev/video41 /dev/video42; do
  echo FORMATS=$device
  v4l2-ctl -d "$device" --list-formats-ext 2>/dev/null | head -n 30 || true
done
launcher_pid=$(pgrep -f '^python3 -m feature_demo.launcher$' | head -n1)
echo LAUNCHER_PID=$launcher_pid
pgrep -af 'feature_demo.worker.*fruit_recognition' || true
worker_pid=$(pgrep -f '^/usr/bin/python3 -m feature_demo.workers fruit_recognition$' | head -n1)
if [ -n "$worker_pid" ]; then
  ps -o user=,group=,pid=,cmd= -p "$worker_pid"
  echo WORKER_CWD=$(readlink -f /proc/$worker_pid/cwd)
  echo WORKER_ENV
  tr '\0' '\n' < /proc/$worker_pid/environ | grep -E '^(FRUIT_|AIBOX_|PYTHON|HOME=)' || true
fi
echo ROOT_AI_PATHS
/usr/bin/python3 - <<'PY' || true
import importlib.util
import importlib.metadata
for name in ('ultralytics', 'torch'):
    spec = importlib.util.find_spec(name)
    print(name, None if spec is None else spec.origin)
try:
    print('ULTRALYTICS_REQUIRES', importlib.metadata.requires('ultralytics'))
except Exception as exc:
    print('ULTRALYTICS_REQUIRES_ERROR', repr(exc))
PY
du -sh /root/.local/lib/python3.10/site-packages 2>/dev/null || true
ports=$(ss -ltnp | sed -n "s/.*127.0.0.1:\([0-9][0-9]*\).*pid=$launcher_pid.*/\1/p")
for port in $ports; do
  if curl -fsS --max-time 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    echo API_PORT=$port
    curl -fsS --max-time 8 "http://127.0.0.1:$port/api/modules/fruit_recognition/status" >/tmp/fruit-status.json || true
    python3 - <<'PY'
import base64
import json

path = "/tmp/fruit-status.json"
try:
    payload = json.load(open(path, encoding="utf-8"))
except Exception as exc:
    print("STATUS_ERROR=" + repr(exc))
else:
    details = payload.get("details") or {}
    frame = details.pop("frame_jpeg_base64", None)
    if frame:
        open("/tmp/fruit-current.jpg", "wb").write(base64.b64decode(frame))
    summary = {
        "state": payload.get("state"),
        "pid": payload.get("pid"),
        "alive": payload.get("alive"),
        "frame_sequence": details.get("frame_sequence"),
        "result": details.get("result"),
        "message": details.get("message"),
        "model_loaded": details.get("model_loaded"),
        "recognition_status": details.get("recognition_status"),
        "model_classes": details.get("model_classes"),
    }
    print("FRUIT_STATUS=" + json.dumps(summary, ensure_ascii=False))
PY
  fi
done
echo FRUIT_LOG
journalctl -u feature-demo.service -n 120 --no-pager 2>/dev/null | grep -i -E 'fruit|yolo|error|traceback' | tail -n 40 || true
'''


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.11.106", username="root", password=password, timeout=10)
    try:
        _, stdout, stderr = client.exec_command(COMMAND, timeout=30)
        output = stdout.read().decode("utf-8", errors="replace")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        print(output, end="")
        local_frame = Path(__file__).resolve().parents[1] / "output" / "fruit-current.jpg"
        local_frame.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.open_sftp().get("/tmp/fruit-current.jpg", str(local_frame))
            print(f"FRAME_PATH={local_frame}")
        except OSError:
            print("FRAME_PATH=unavailable")
        if errors:
            print(errors, end="")
        raise SystemExit(status)
    finally:
        client.close()


if __name__ == "__main__":
    main()
