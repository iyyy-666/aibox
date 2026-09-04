from __future__ import annotations

import numpy as np
import pytest

from vision_targeting import (
    BoxTracker,
    TemporalGestureVote,
    match_stereo_candidate,
    split_stereo,
)


def test_split_stereo_returns_equal_eyes() -> None:
    frame = np.zeros((4, 10, 3), dtype=np.uint8)

    left, right = split_stereo(frame)

    assert left.shape == right.shape == (4, 5, 3)


def test_split_stereo_rejects_non_stereo_frame() -> None:
    with pytest.raises(ValueError, match="stereo"):
        split_stereo(np.zeros((4, 1, 3), dtype=np.uint8))


def test_stereo_match_accepts_same_height_and_rejects_vertical_mismatch() -> None:
    accepted = match_stereo_candidate(
        (100, 80, 60, 80), [(72, 84, 64, 78)], (480, 640, 3)
    )
    rejected = match_stereo_candidate(
        (100, 80, 60, 80), [(72, 250, 64, 78)], (480, 640, 3)
    )

    assert accepted.matched
    assert accepted.right_box == (72, 84, 64, 78)
    assert not rejected.matched


def test_box_tracker_rejects_distant_box_and_expires_after_misses() -> None:
    tracker = BoxTracker(iou_threshold=0.3, hold_misses=2)

    assert tracker.update((10, 10, 50, 50))
    assert tracker.update((16, 12, 50, 50))
    assert not tracker.update((250, 250, 50, 50))
    assert tracker.update(None)
    assert not tracker.update(None)


def test_vote_requires_four_eligible_frames_and_holds_three_losses() -> None:
    voter = TemporalGestureVote(confirm_hits=4, hold_misses=3)

    assert [voter.update("rock", eligible=True) for _ in range(4)][-1] == "rock"
    assert [voter.update(None, eligible=False) for _ in range(3)][-1] == "rock"
    assert voter.update(None, eligible=False) is None
