from __future__ import annotations

import getpass
import hashlib
import os
from pathlib import Path

import paramiko


HOST = os.environ.get("RK3588_HOST", "192.168.11.106")
USERNAME = os.environ.get("RK3588_USER", "root")
PASSWORD = os.environ.get("RK3588_PASSWORD")
LOCAL_MODEL = Path(__file__).resolve().parents[4] / "output" / "fruit_cards_yolov8n_v1.pt"
REMOTE_MODEL = "/root/robot_arm/models/fruit/fruit_veg_yolov8n.pt"
REMOTE_TEMP = "/root/robot_arm/models/fruit/.fruit_cards_yolov8n_v1.upload"


def run(client: paramiko.SSHClient, command: str, timeout: int = 60) -> str:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    errors = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status != 0:
        raise RuntimeError(errors or output or f"remote command failed: {status}")
    if errors:
        print(errors, end="")
    return output


def main() -> None:
    expected_sha = hashlib.sha256(LOCAL_MODEL.read_bytes()).hexdigest()
    password = PASSWORD or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USERNAME, password=password, timeout=10)
    try:
        with client.open_sftp() as sftp:
            sftp.put(str(LOCAL_MODEL), REMOTE_TEMP)
        output = run(
            client,
            f'''set -eu
actual=$(sha256sum {REMOTE_TEMP} | awk '{{print $1}}')
test "$actual" = "{expected_sha}"
stamp=$(date +%Y%m%d-%H%M%S)
backup={REMOTE_MODEL}.backup-$stamp
cp -a {REMOTE_MODEL} "$backup"
install -m 0644 {REMOTE_TEMP} {REMOTE_MODEL}
rm -f {REMOTE_TEMP}
cd /root/robot_arm
python3 - <<'PY'
from ultralytics import YOLO
model = YOLO('/root/robot_arm/models/fruit/fruit_veg_yolov8n.pt')
print('MODEL_NAMES=' + repr(model.names))
PY
launcher_pid=$(pgrep -f '^python3 -m feature_demo.launcher$' | head -n1)
port=$(ss -ltnp | sed -n "s/.*127.0.0.1:\\([0-9][0-9]*\\).*pid=$launcher_pid.*/\\1/p" | head -n1)
test -n "$port"
curl -fsS -X POST "http://127.0.0.1:$port/api/modules/fruit_recognition/stop" >/dev/null
sleep 1
curl -fsS -X POST "http://127.0.0.1:$port/api/modules/fruit_recognition/start" >/dev/null
sleep 4
curl -fsS "http://127.0.0.1:$port/api/modules/fruit_recognition/status" >/tmp/fruit-card-model-status.json
python3 - <<'PY'
import json
payload = json.load(open('/tmp/fruit-card-model-status.json', encoding='utf-8'))
details = payload.get('details') or {{}}
details.pop('frame_jpeg_base64', None)
print('STATUS=' + json.dumps({{
    'state': payload.get('state'),
    'module_id': payload.get('module_id'),
    'frame_sequence': details.get('frame_sequence'),
    'result': details.get('result'),
}}, ensure_ascii=False))
PY
echo BACKUP="$backup"
sha256sum {REMOTE_MODEL}
''',
            timeout=90,
        )
        print(output, end="")
    finally:
        client.close()


if __name__ == "__main__":
    main()
