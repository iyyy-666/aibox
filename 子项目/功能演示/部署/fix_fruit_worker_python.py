from __future__ import annotations

import getpass
import os

import paramiko


COMMAND = r'''set -eu
source_dir=/root/.local/lib/python3.10/site-packages
target_dir=/usr/local/lib/python3.10/dist-packages
test -d "$source_dir/ultralytics"
runuser -u ztl -- env HOME=/home/ztl PYTHONPATH="$source_dir:/root/robot_arm" /usr/bin/python3 - <<'PY'
from ultralytics import YOLO
model = YOLO('/root/robot_arm/models/fruit/fruit_veg_yolov8n.pt')
print('ZTL_MODEL_NAMES_WITH_PATH=' + repr(model.names))
PY
mkdir -p "$target_dir"
stamp=$(date +%Y%m%d-%H%M%S)
backup=/root/fruit-python-backups/$stamp
mkdir -p "$backup"
for pattern in ultralytics ultralytics-*.dist-info ultralytics_thop ultralytics_thop-*.dist-info torchvision torchvision-*.dist-info; do
  for existing in $target_dir/$pattern; do
    [ -e "$existing" ] || continue
    cp -a "$existing" "$backup/"
  done
done
cp -a "$source_dir/ultralytics" "$target_dir/"
for pattern in ultralytics-*.dist-info ultralytics_thop ultralytics_thop-*.dist-info torchvision torchvision-*.dist-info; do
  for item in $source_dir/$pattern; do
    [ -e "$item" ] || continue
    cp -a "$item" "$target_dir/"
  done
done
chmod -R a+rX "$target_dir/ultralytics" "$target_dir"/ultralytics*.dist-info 2>/dev/null || true
chmod -R a+rX "$target_dir/torchvision" "$target_dir"/torchvision*.dist-info 2>/dev/null || true
runuser -u ztl -- env HOME=/home/ztl /usr/bin/python3 - <<'PY'
from ultralytics import YOLO
model = YOLO('/root/robot_arm/models/fruit/fruit_veg_yolov8n.pt')
print('ZTL_MODEL_NAMES=' + repr(model.names))
PY
launcher_pid=$(pgrep -f '^python3 -m feature_demo.launcher$' | head -n1)
port=$(ss -ltnp | sed -n "s/.*127.0.0.1:\([0-9][0-9]*\).*pid=$launcher_pid.*/\1/p" | head -n1)
test -n "$port"
curl -fsS -X POST "http://127.0.0.1:$port/api/modules/fruit_recognition/stop" >/dev/null
sleep 1
curl -fsS -X POST "http://127.0.0.1:$port/api/modules/fruit_recognition/start" >/dev/null
sleep 6
curl -fsS "http://127.0.0.1:$port/api/modules/fruit_recognition/status" >/tmp/fruit-python-fix-status.json
python3 - <<'PY'
import json
payload = json.load(open('/tmp/fruit-python-fix-status.json', encoding='utf-8'))
details = payload.get('details') or {}
details.pop('frame_jpeg_base64', None)
print('STATUS=' + json.dumps({
    'state': payload.get('state'),
    'module_id': payload.get('module_id'),
    'frame_sequence': details.get('frame_sequence'),
    'result': details.get('result'),
    'model_loaded': details.get('model_loaded'),
    'recognition_status': details.get('recognition_status'),
    'model_classes': details.get('model_classes'),
}, ensure_ascii=False))
PY
echo BACKUP="$backup"
'''


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.11.106", username="root", password=password, timeout=10)
    try:
        _, stdout, stderr = client.exec_command(COMMAND, timeout=120)
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if errors:
            print(errors, end="")
        raise SystemExit(status)
    finally:
        client.close()


if __name__ == "__main__":
    main()
