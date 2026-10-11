from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

import paramiko


COMMAND = r'''set -u
echo PROCESSES
pgrep -af 'feature_demo|plate_recognition' || true
echo PORT
launcher_pid=$(pgrep -f '^python3 -m feature_demo.launcher$' | head -n1)
ss -ltnp | grep "pid=$launcher_pid" || true
echo HYPERLPR
cd /root/robot_arm && python3 - <<'PY'
import importlib.util
print('hyperlpr3_spec=', importlib.util.find_spec('hyperlpr3'))
if importlib.util.find_spec('hyperlpr3'):
    import hyperlpr3
    print('hyperlpr3_file=', hyperlpr3.__file__)
PY
echo FILES
sha256sum /root/robot_arm/plate_recognition_app.py /root/robot_arm/feature_demo/adapters/vision.py /root/robot_arm/feature_demo/web/app.js /root/robot_arm/feature_demo/web/styles.css 2>/dev/null || true
echo CAMERA
v4l2-ctl --device /dev/esp32_arm --all 2>/dev/null || true
ports=$(ss -ltnp | sed -n "s/.*127.0.0.1:\([0-9][0-9]*\).*pid=$launcher_pid.*/\1/p")
for port in $ports; do
  if curl -fsS --max-time 2 "http://127.0.0.1:$port/health" >/tmp/plate-health.json 2>/dev/null; then
    echo API_PORT=$port
    cat /tmp/plate-health.json
    echo
    curl -fsS --max-time 5 "http://127.0.0.1:$port/api/modules/plate_recognition/status" >/tmp/plate-status.json || true
    API_PORT="$port" python3 - <<'PY'
import base64
import json
import os

path = "/tmp/plate-status.json"
try:
    payload = json.load(open(path, encoding="utf-8"))
except Exception as exc:
    print("STATUS_ERROR=", repr(exc))
else:
    details = payload.get("details") or {}
    frame = details.pop("frame_jpeg_base64", None)
    if frame:
        open("/tmp/plate-current.jpg", "wb").write(base64.b64decode(frame))
    summary = {
        "api_port": int(os.environ["API_PORT"]),
        "state": payload.get("state"),
        "pid": payload.get("pid"),
        "alive": payload.get("alive"),
        "frame_sequence": details.get("frame_sequence"),
        "result": details.get("result"),
    }
    print("PLATE_STATUS=" + json.dumps(summary, ensure_ascii=False))
PY
  fi
done
echo JOURNAL
journalctl -u feature-demo.service -n 80 --no-pager 2>/dev/null || true
'''


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect("192.168.11.106", username="root", password=password, timeout=10)
    try:
        _, stdout, stderr = client.exec_command(COMMAND, timeout=45)
        output = stdout.read().decode("utf-8", errors="replace")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        print(output, end="")
        remote_frame = "/tmp/plate-current.jpg"
        local_frame = Path(__file__).resolve().parents[1] / "output" / "plate-current.jpg"
        local_frame.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.open_sftp().get(remote_frame, str(local_frame))
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
