import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from voice_engine import dbfs_percent, clamp_level, trigger_confirmed


def test_clamp_level_prevents_display_overflow() -> None:
    assert clamp_level(-0.2) == 0.0
    assert clamp_level(0.45) == 0.45
    assert clamp_level(2.0) == 1.0


def test_dbfs_percent_stays_in_display_range() -> None:
    assert dbfs_percent(0.0) == 0
    assert dbfs_percent(1.0) == 100
    assert 0 < dbfs_percent(0.1) < 100


def test_trigger_requires_consecutive_frames() -> None:
    assert not trigger_confirmed(0, True, required_frames=3)
    assert not trigger_confirmed(1, True, required_frames=3)
    assert trigger_confirmed(2, True, required_frames=3)
    assert not trigger_confirmed(2, False, required_frames=3)
