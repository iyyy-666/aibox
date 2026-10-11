from __future__ import annotations

import getpass
import os
from pathlib import Path

import paramiko


HOST = os.environ.get("RK3588_HOST", "192.168.11.106")
USERNAME = os.environ.get("RK3588_USER", "root")
PASSWORD = os.environ.get("RK3588_PASSWORD")
LOCAL_FILE = Path(__file__).resolve().parents[1] / "代码" / "feature_demo" / "adapters" / "vision.py"
REMOTE_FILE = "/root/robot_arm/feature_demo/adapters/vision.py"
REMOTE_TEMP = "/root/robot_arm/feature_demo/adapters/.vision.py.fruit-hold-upload"


def run(client: paramiko.SSHClient, command: str, timeout: int = 30) -> str:
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
    password = PASSWORD or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USERNAME, password=password, timeout=10)
    try:
        with client.open_sftp() as sftp:
            sftp.put(str(LOCAL_FILE), REMOTE_TEMP)
        output = run(
            client,
            f'''set -eu
python3 -m py_compile {REMOTE_TEMP}
stamp=$(date +%Y%m%d-%H%M%S)
backup={REMOTE_FILE}.backup-$stamp
cp -a {REMOTE_FILE} "$backup"
install -m 0644 {REMOTE_TEMP} {REMOTE_FILE}
rm -f {REMOTE_TEMP}
launcher_pid=$(pgrep -f '^python3 -m feature_demo.launcher$' | head -n1)
port=$(ss -ltnp | sed -n "s/.*127.0.0.1:\\([0-9][0-9]*\\).*pid=$launcher_pid.*/\\1/p" | head -n1)
test -n "$port"
curl -fsS -X POST "http://127.0.0.1:$port/api/modules/fruit_recognition/stop"
echo
sleep 1
curl -fsS -X POST "http://127.0.0.1:$port/api/modules/fruit_recognition/start"
echo
sleep 3
curl -fsS "http://127.0.0.1:$port/api/modules/fruit_recognition/status" >/tmp/fruit-hold-status.json
python3 - <<'PY'
import json
payload = json.load(open('/tmp/fruit-hold-status.json', encoding='utf-8'))
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
sha256sum {REMOTE_FILE}
''',
            timeout=60,
        )
        print(output, end="")
    finally:
        client.close()


if __name__ == "__main__":
    main()
