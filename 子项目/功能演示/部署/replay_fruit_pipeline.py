from __future__ import annotations

import getpass
import os

import paramiko


COMMAND = r'''cd /root/robot_arm && python3 - <<'PY'
from pathlib import Path

import cv2
import numpy as np

from feature_demo.adapters.vision import build_vision_adapter

adapter = build_vision_adapter('fruit_recognition', legacy_root='/root/robot_arm')
try:
    total = 0
    correct = 0
    misses = []
    wrong = []
    for category in ('apple', 'banana', 'watermelon', 'pineapple', 'strawberry'):
        images = sorted(Path('/root/robot_arm/datasets/fruit_cards/raw', category).rglob('*.jpg'))
        selected = images[::max(1, len(images) // 12)][:12]
        category_correct = 0
        for path in selected:
            image = cv2.imread(str(path))
            stereo = np.concatenate((image, image), axis=1)
            _annotated, payload = adapter.process(stereo)
            results = payload.get('result') or []
            labels = [str(item.get('name_en', '')).lower() for item in results]
            total += 1
            if category in labels:
                correct += 1
                category_correct += 1
            elif not labels:
                misses.append(str(path))
            else:
                wrong.append((str(path), labels))
        print('CATEGORY', category, category_correct, '/', len(selected))
    print('SUMMARY', correct, '/', total)
    print('MISSES', misses)
    print('WRONG', wrong)

    source = cv2.imread(str(sorted(Path('/root/robot_arm/datasets/fruit_cards/raw/apple').rglob('*.jpg'))[36]))
    canvas_shape = source.shape
    for scale in (1.0, 0.75, 0.50, 0.35, 0.25, 0.20, 0.15):
        if scale == 1.0:
            test_image = source.copy()
        else:
            test_image = np.full(canvas_shape, 180, dtype=np.uint8)
            resized = cv2.resize(source, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            y = (canvas_shape[0] - resized.shape[0]) // 2
            x = (canvas_shape[1] - resized.shape[1]) // 2
            test_image[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
        raw = adapter.instance.model.predict(
            test_image, imgsz=640, conf=0.05, verbose=False, device='cpu'
        )[0]
        raw_boxes = [
            {
                'name': adapter.instance.model_names[int(box.cls[0].item())],
                'conf': round(float(box.conf[0].item()), 3),
                'xyxy': [round(float(value), 1) for value in box.xyxy[0].tolist()],
            }
            for box in raw.boxes
        ]
        final = adapter.instance._detect_fruits(test_image)
        print('SCALE', scale, 'RAW', raw_boxes, 'FINAL', [item.name_en for item in final])
        if scale <= 0.25:
            for image_size in (832, 960):
                started = __import__('time').monotonic()
                high_res = adapter.instance.model.predict(
                    test_image,
                    imgsz=image_size,
                    conf=0.05,
                    verbose=False,
                    device='cpu',
                )[0]
                elapsed = __import__('time').monotonic() - started
                candidates = [
                    (
                        adapter.instance.model_names[int(box.cls[0].item())],
                        round(float(box.conf[0].item()), 3),
                    )
                    for box in high_res.boxes
                ]
                print('HIGH_RES', scale, image_size, round(elapsed, 3), candidates)
finally:
    adapter.close()
PY
'''


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.11.106", username="root", password=password, timeout=10)
    try:
        _, stdout, stderr = client.exec_command(COMMAND, timeout=180)
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
