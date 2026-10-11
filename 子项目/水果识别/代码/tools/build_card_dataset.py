#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import cv2


CLASSES = ("apple", "banana", "watermelon", "pineapple", "strawberry")
MANUAL_BOXES = {
    ("banana", "banana_0002.jpg"): (195.0, 117.0, 539.0, 400.0),
    ("banana", "banana_0003.jpg"): (192.0, 133.0, 560.0, 389.0),
    ("pineapple", "pineapple_0006.jpg"): (192.0, 117.0, 501.0, 413.0),
}
NEGATIVE_IMAGES = {
    ("apple", "apple_0044.jpg"),
    ("apple", "apple_0069.jpg"),
    ("apple", "apple_0070.jpg"),
    ("apple", "apple_0071.jpg"),
    ("apple", "apple_0072.jpg"),
    ("pineapple", "pineapple_0004.jpg"),
    ("pineapple", "pineapple_0005.jpg"),
    ("pineapple", "pineapple_0009.jpg"),
    ("pineapple", "pineapple_0010.jpg"),
}


def yolo_line(class_id: int, box: tuple[float, float, float, float], width: int, height: int) -> str:
    x1, y1, x2, y2 = box
    center_x = ((x1 + x2) / 2.0) / width
    center_y = ((y1 + y2) / 2.0) / height
    box_width = (x2 - x1) / width
    box_height = (y2 - y1) / height
    return f"{class_id} {center_x:.6f} {center_y:.6f} {box_width:.6f} {box_height:.6f}\n"


def build_dataset(raw_root: Path, output: Path) -> dict[str, int]:
    if output.exists():
        shutil.rmtree(output)
    counts = {"train_positive": 0, "val_positive": 0, "train_negative": 0, "val_negative": 0}
    for split in ("train", "val"):
        (output / "images" / split).mkdir(parents=True)
        (output / "labels" / split).mkdir(parents=True)

    for class_id, class_name in enumerate(CLASSES):
        class_root = raw_root / class_name
        for session in sorted(path for path in class_root.iterdir() if path.is_dir()):
            records = json.loads((session / "prelabels.json").read_text(encoding="utf-8"))
            for index, record in enumerate(records):
                source = session / record["file"]
                image = cv2.imread(str(source))
                if image is None:
                    raise RuntimeError(f"Cannot read {source}")
                intended = [
                    item for item in record["detections"] if item["name"].lower() == class_name
                ]
                intended.sort(key=lambda item: item["confidence"], reverse=True)
                box = tuple(intended[0]["xyxy"]) if intended else MANUAL_BOXES.get(
                    (class_name, source.name)
                )
                is_positive = box is not None
                is_negative = (class_name, source.name) in NEGATIVE_IMAGES
                # Keep true empty scenes as negatives. Ambiguous partial or blurred cards are excluded.
                if not is_positive and not is_negative:
                    continue

                split = "val" if index % 6 == 0 or (is_negative and index % 3 == 0) else "train"
                stem = f"{class_name}_{session.name}_{source.stem}"
                destination = output / "images" / split / f"{stem}.jpg"
                shutil.copy2(source, destination)
                label_path = output / "labels" / split / f"{stem}.txt"
                if is_positive:
                    height, width = image.shape[:2]
                    label_path.write_text(
                        yolo_line(class_id, box, width, height), encoding="ascii"
                    )
                    counts[f"{split}_positive"] += 1
                else:
                    label_path.write_text("", encoding="ascii")
                    counts[f"{split}_negative"] += 1

    data_yaml = (
        f"path: {output.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        f"names: {dict(enumerate(CLASSES))}\n"
    )
    (output / "data.yaml").write_text(data_yaml, encoding="utf-8")
    (output / "dataset_summary.json").write_text(
        json.dumps(counts, indent=2), encoding="utf-8"
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_dataset(args.raw_root, args.output), indent=2))


if __name__ == "__main__":
    main()
