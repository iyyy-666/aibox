from __future__ import annotations

import getpass
import os

import paramiko


COMMAND = r'''cd /root/robot_arm && python3 - <<'PY'
from pathlib import Path

import cv2
from ultralytics import YOLO
import fruit_recognition_app as fruit_app

model_path = Path('/root/robot_arm/models/fruit/fruit_veg_yolov8n.pt')
print('MODEL=', model_path, model_path.exists(), model_path.stat().st_size if model_path.exists() else 0)
apple_images = sorted(Path('/root/robot_arm/datasets/fruit_cards/raw/apple').rglob('*.jpg'))
print('APPLE_IMAGE_COUNT=', len(apple_images))
if not apple_images:
    raise SystemExit(2)
image_path = apple_images[len(apple_images) // 2]
image = cv2.imread(str(image_path))
print('IMAGE=', image_path, None if image is None else image.shape)
model = YOLO(str(model_path))
print('NAMES=', model.names)
for conf in (0.20, 0.10, 0.05):
    result = model.predict(image, imgsz=640, conf=conf, verbose=False, device='cpu')[0]
    boxes = []
    for box in result.boxes:
        cls_id = int(box.cls[0].item())
        boxes.append({
            'name': str(model.names[cls_id]),
            'confidence': round(float(box.conf[0].item()), 4),
            'xyxy': [round(float(v), 1) for v in box.xyxy[0].tolist()],
        })
    print('CONF', conf, 'BOXES', boxes)

instance = fruit_app.FruitRecognitionApp.__new__(fruit_app.FruitRecognitionApp)
instance.model = model
instance.model_names = {int(k): str(v) for k, v in model.names.items()}
instance.fruit_class_ids = {
    idx for idx, name in instance.model_names.items()
    if name.lower() in fruit_app.FRUIT_CN
}
instance._set_status = lambda text: print('STATUS=', text)
for category in ('apple', 'banana', 'watermelon', 'pineapple', 'strawberry'):
    images = sorted(Path('/root/robot_arm/datasets/fruit_cards/raw', category).rglob('*.jpg'))
    if not images:
        print('PIPELINE', category, 'NO_IMAGE')
        continue
    sample_path = images[len(images) // 2]
    sample = cv2.imread(str(sample_path))
    detections = instance._detect_fruits(sample)
    print('PIPELINE', category, sample_path.name, [
        {
            'name': item.name_en,
            'confidence': round(item.confidence, 4),
            'box': item.box,
        }
        for item in detections
    ])

current_path = Path('/tmp/fruit-current.jpg')
if current_path.exists():
    current = cv2.imread(str(current_path))
    print('CURRENT_IMAGE=', current.shape)
    for image_size in (640, 832, 960, 1280):
        for confidence in (0.20, 0.10, 0.05, 0.01):
            result = model.predict(
                current,
                imgsz=image_size,
                conf=confidence,
                verbose=False,
                device='cpu',
            )[0]
            boxes = [
                {
                    'name': str(model.names[int(box.cls[0].item())]),
                    'confidence': round(float(box.conf[0].item()), 4),
                    'xyxy': [round(float(value), 1) for value in box.xyxy[0].tolist()],
                }
                for box in result.boxes
            ]
            print('CURRENT_RAW', image_size, confidence, boxes)
    print('CURRENT_PIPELINE', [
        {
            'name': item.name_en,
            'confidence': round(item.confidence, 4),
            'box': item.box,
        }
        for item in instance._detect_fruits(current)
    ])
PY
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
