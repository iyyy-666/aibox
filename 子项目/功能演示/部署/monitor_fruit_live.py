from __future__ import annotations

import getpass
import os
from pathlib import Path

import paramiko


COMMAND = r'''set -eu
launcher_pid=$(pgrep -f '^python3 -m feature_demo.launcher$' | head -n1)
port=$(ss -ltnp | sed -n "s/.*127.0.0.1:\([0-9][0-9]*\).*pid=$launcher_pid.*/\1/p" | head -n1)
test -n "$port"
rm -rf /tmp/fruit-live-monitor
mkdir -p /tmp/fruit-live-monitor
PORT="$port" MONITOR_SECONDS="${MONITOR_SECONDS:-60}" python3 - <<'PY'
import base64
import json
import os
import time
import urllib.request

port = os.environ['PORT']
sample_count = max(1, int(float(os.environ['MONITOR_SECONDS']) * 5))
last_sequence = -1
seen_results = []
for index in range(sample_count):
    try:
        with urllib.request.urlopen(
            f'http://127.0.0.1:{port}/api/modules/fruit_recognition/status',
            timeout=2,
        ) as response:
            payload = json.load(response)
    except Exception as exc:
        print('READ_ERROR', repr(exc), flush=True)
        time.sleep(0.2)
        continue
    details = payload.get('details') or {}
    sequence = details.get('frame_sequence', -1)
    result = details.get('result') or []
    encoded = details.get('frame_jpeg_base64')
    if sequence != last_sequence and encoded:
        open(f'/tmp/fruit-live-monitor/frame-{index:03d}-{sequence}.jpg', 'wb').write(
            base64.b64decode(encoded)
        )
        last_sequence = sequence
    if result:
        seen_results.append((index, sequence, result))
        print('DETECTED', index, sequence, json.dumps(result, ensure_ascii=False), flush=True)
    time.sleep(0.2)
print('SUMMARY', json.dumps({
    'last_sequence': last_sequence,
    'saved_frames': len(os.listdir('/tmp/fruit-live-monitor')),
    'detections': seen_results,
}, ensure_ascii=False), flush=True)
PY
'''


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.11.106", username="root", password=password, timeout=10)
    try:
        if os.environ.get("FRUIT_MONITOR_DOWNLOAD_ONLY") != "1":
            _, stdout, stderr = client.exec_command(COMMAND, timeout=90)
            print(stdout.read().decode("utf-8", errors="replace"), end="")
            errors = stderr.read().decode("utf-8", errors="replace")
            status = stdout.channel.recv_exit_status()
            if errors:
                print(errors, end="")
            if status:
                raise SystemExit(status)
        output_dir = Path(__file__).resolve().parents[1] / "output" / "fruit-live-monitor"
        output_dir.mkdir(parents=True, exist_ok=True)
        for old_frame in output_dir.glob("*.jpg"):
            old_frame.unlink()
        sftp = client.open_sftp()
        try:
            names = sorted(sftp.listdir("/tmp/fruit-live-monitor"))
            for name in names:
                sftp.get(f"/tmp/fruit-live-monitor/{name}", str(output_dir / name))
        finally:
            sftp.close()
        print(f"FRAMES={len(names)} DIR={output_dir}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
