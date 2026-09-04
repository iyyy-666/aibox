def test_tracking_dependencies_import() -> None:
    import hand_landmarks
    import vision_targeting

    assert hasattr(hand_landmarks, "HandLandmarkDetector")
    assert callable(vision_targeting.split_stereo)
