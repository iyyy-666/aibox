from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

gimbal_stub = types.ModuleType("gimbal_controls")
gimbal_stub.GimbalControls = object
sys.modules.setdefault("gimbal_controls", gimbal_stub)

from color_recognition_app import Detection, merge_red_ranges


def _red(box: tuple[int, int, int, int], area: float = 1600) -> Detection:
    x, y, width, height = box
    return Detection("Red", box, area, (x + width // 2, y + height // 2), (45, 45, 235))


def test_distant_red_objects_remain_separate():
    merged = merge_red_ranges([_red((20, 30, 40, 40)), _red((260, 30, 40, 40))])

    assert len(merged) == 2
    assert {item.box for item in merged} == {(20, 30, 40, 40), (260, 30, 40, 40)}


def test_overlapping_red_ranges_are_merged_as_one_object():
    merged = merge_red_ranges([_red((20, 30, 50, 40)), _red((24, 32, 48, 42))])

    assert len(merged) == 1
    assert merged[0].box == (20, 30, 52, 44)
