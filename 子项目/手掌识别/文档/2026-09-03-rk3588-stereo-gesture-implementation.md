# RK3588 Stereo Gesture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add robust MediaPipe-based rock-paper-scissors recognition with stereo verification, and share safe stereo/temporal camera utilities across every maintained visual application.

**Architecture:** Extend the existing `vision_targeting.py` with pure, testable stereo frame, candidate matching, tracking, and temporal-voting primitives. Add `hand_landmarks.py` for optional MediaPipe loading and landmark geometry; `palm_recognition_app.py` composes those components with the existing contour method as a fallback. The remaining visual apps use the shared frame split and recovery helpers while retaining their detectors and UI.

**Tech Stack:** Python 3.10, OpenCV 5, NumPy, optional `mediapipe==0.10.18`, Tkinter, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-rk3588-stereo-gesture-design.md`

## Global Constraints

- Maintain `rk3588_vision_voice_opt_20260830/current` as the only source baseline.
- Board target is aarch64/Python 3.10.12/OpenCV 5.0.0 with stereo camera `/dev/video41`.
- MediaPipe is optional; only the palm application imports it and must fall back without a crash.
- Do not install packages automatically from a GUI application.
- Keep one-camera-per-GUI process, existing environment variables, desktop launch behavior, and original recognition models.
- The target directory is not a Git repository; do not attempt commits until the user initializes or supplies a repository.

---

## File Structure

- Create `current/tests/conftest.py`: add `current` to the test import path.
- Create `current/tests/test_vision_targeting.py`: tests for stereo splitting, matching, tracking, and voting.
- Create `current/tests/test_hand_landmarks.py`: synthetic landmark classification and optional-runtime fallback tests.
- Modify `current/vision_targeting.py`: pure stereo and temporal utilities, preserving existing exports.
- Create `current/hand_landmarks.py`: MediaPipe adapter, hand/gesture dataclasses, landmark geometry classifier, and contour fallback interface.
- Modify `current/palm_recognition_app.py`: use landmark detection, stereo verification, tracking, voting, UI diagnostics, and fallback.
- Modify `current/color_recognition_app.py`, `shape_recognition_app.py`, `fruit_recognition_app.py`, `plate_recognition_app.py`, `face_recognition_app.py`: use `split_stereo` rather than local left-frame slicing and reuse camera status helpers where compatible.
- Create `current/camera_view_app.py` and `current/camera_view.sh`: migrate the existing preview app from `rk3588_rebuild` and use `split_stereo`.
- Create `current/requirements-mediapipe.txt`: pin the board-compatible optional dependency.
- Create `current/remote_verify_vision.sh`: syntax, import, dependency, and smoke-check commands for the board.

### Task 1: Test Harness and Stereo Primitives

**Files:**
- Create: `current/tests/conftest.py`
- Create: `current/tests/test_vision_targeting.py`
- Modify: `current/vision_targeting.py`

**Interfaces:**
- Produces `split_stereo(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]`.
- Produces `StereoMatch(matched: bool, score: float, right_box: tuple[int, int, int, int] | None)`.
- Produces `match_stereo_candidate(left_box, right_boxes, image_shape) -> StereoMatch`.
- Produces `BoxTracker.update(box: tuple[int, int, int, int] | None) -> bool` and `TemporalGestureVote.update(label: str | None, *, eligible: bool) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_split_stereo_returns_equal_eyes():
    frame = np.zeros((4, 10, 3), dtype=np.uint8)
    left, right = split_stereo(frame)
    assert left.shape == right.shape == (4, 5, 3)

def test_stereo_match_accepts_same_height_and_rejects_vertical_mismatch():
    assert match_stereo_candidate((100, 80, 60, 80), [(72, 84, 64, 78)], (480, 640, 3)).matched
    assert not match_stereo_candidate((100, 80, 60, 80), [(72, 250, 64, 78)], (480, 640, 3)).matched

def test_vote_requires_four_eligible_frames_and_holds_three_losses():
    voter = TemporalGestureVote(confirm_hits=4, hold_misses=3)
    assert [voter.update("rock", eligible=True) for _ in range(4)][-1] == "rock"
    assert [voter.update(None, eligible=False) for _ in range(3)][-1] == "rock"
    assert voter.update(None, eligible=False) is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd current; python3 -m pytest tests/test_vision_targeting.py -v`

Expected: FAIL because the new symbols are unavailable.

- [ ] **Step 3: Implement the minimal pure utilities**

```python
def split_stereo(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if frame.ndim != 3 or frame.shape[1] < 2:
        raise ValueError("expected a side-by-side stereo BGR frame")
    mid = frame.shape[1] // 2
    return frame[:, :mid].copy(), frame[:, mid:mid + mid].copy()

class TemporalGestureVote:
    def __init__(self, confirm_hits: int = 4, hold_misses: int = 3) -> None: ...
    def update(self, label: str | None, *, eligible: bool) -> str | None: ...
```

Use normalized vertical-center distance, area ratio, and positive bounded horizontal disparity in `match_stereo_candidate`. Keep tracker state per instance; do not use module globals.

- [ ] **Step 4: Run tests to verify pass**

Run: `cd current; python3 -m pytest tests/test_vision_targeting.py -v`

Expected: PASS.

### Task 2: Landmark Geometry and Optional MediaPipe Adapter

**Files:**
- Create: `current/tests/test_hand_landmarks.py`
- Create: `current/hand_landmarks.py`

**Interfaces:**
- Produces `HandObservation(box, landmarks, gesture, confidence, source)`.
- Produces `classify_rps(landmarks: np.ndarray) -> tuple[str | None, float]`.
- Produces `HandLandmarkDetector.detect(image: np.ndarray) -> list[HandObservation]`.
- `HandLandmarkDetector.available` is `False` and `error` is populated when MediaPipe cannot be imported or initialized.

- [ ] **Step 1: Write failing synthetic-landmark tests**

```python
def test_classify_rps_identifies_scissors_from_extended_index_and_middle():
    landmarks = make_hand(index=True, middle=True, ring=False, pinky=False)
    assert classify_rps(landmarks)[0] == "scissors"

def test_classify_rps_does_not_force_unknown_pose_into_rps():
    landmarks = make_hand(index=True, middle=False, ring=True, pinky=False)
    assert classify_rps(landmarks)[0] is None

def test_detector_gracefully_reports_missing_mediapipe(monkeypatch):
    monkeypatch.setattr(hand_landmarks, "mp", None)
    detector = HandLandmarkDetector()
    assert not detector.available
    assert detector.detect(np.zeros((100, 100, 3), np.uint8)) == []
```

`make_hand` must construct 21 normalized points with each long finger's MCP, PIP, DIP, and TIP placed either successively outward (extended) or folded back toward the wrist (bent).

- [ ] **Step 2: Run tests to verify failure**

Run: `cd current; python3 -m pytest tests/test_hand_landmarks.py -v`

Expected: FAIL because `hand_landmarks` does not exist.

- [ ] **Step 3: Implement landmark classification and lazy runtime loading**

```python
LONG_FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))

def classify_rps(landmarks: np.ndarray) -> tuple[str | None, float]:
    extended = [finger_is_extended(landmarks, ids) for ids in LONG_FINGERS]
    if extended == [False, False, False, False]: return "rock", 0.80
    if extended == [True, True, False, False]: return "scissors", 0.86
    if extended == [True, True, True, True]: return "paper", 0.88
    return None, 0.0
```

Import MediaPipe inside detector initialization, configure `max_num_hands=1`, and convert all landmark coordinates into left-eye pixels. Generate the box from landmark min/max coordinates plus a clipped 12% padding. Catch import and inference exceptions, preserve the error string, and return an empty list.

- [ ] **Step 4: Run tests to verify pass**

Run: `cd current; python3 -m pytest tests/test_hand_landmarks.py -v`

Expected: PASS on both hosts with and without MediaPipe installed.

### Task 3: Palm Application Integration and Traditional Fallback

**Files:**
- Modify: `current/palm_recognition_app.py`
- Modify: `current/palm_recognition.sh`
- Test: `current/tests/test_palm_pipeline.py`

**Interfaces:**
- Consumes `split_stereo`, `match_stereo_candidate`, `BoxTracker`, `TemporalGestureVote`, `HandLandmarkDetector`, and `HandObservation`.
- Produces `PalmRecognitionApp._detect_hands(left, right) -> list[HandDetection]` and displays source/stereo/stability diagnostics.

- [ ] **Step 1: Write failing pipeline tests with fakes**

```python
def test_palm_pipeline_only_confirms_when_stereo_match_and_vote_pass(app, fake_detector):
    app.hand_detector = fake_detector.with_gesture("paper", box=(120, 90, 80, 110))
    right = candidate_image_for_box((88, 92, 78, 108))
    assert app._detect_hands(left_image(), right) == []
    assert app._detect_hands(left_image(), right) == []
    assert app._detect_hands(left_image(), right) == []
    assert app._detect_hands(left_image(), right)[0].gesture == "布"

def test_palm_pipeline_uses_contour_fallback_when_landmarks_unavailable(app):
    app.hand_detector = unavailable_detector()
    assert app._detector_mode == "fallback"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd current; python3 -m pytest tests/test_palm_pipeline.py -v`

Expected: FAIL because the application has a single-image contour-only API.

- [ ] **Step 3: Implement the two-stage pipeline**

Replace local `_normal_frame` slicing with `split_stereo`. Run `HandLandmarkDetector` on left; use a right-eye skin/motion contour list only for `match_stereo_candidate`. Convert `rock`, `scissors`, `paper` to existing Chinese labels only after a successful stereo match and vote. When detector is unavailable or raises, execute the existing `_skin_mask`, contour and convexity path, but subject it to the same right-eye and voting gates. Extend `HandDetection` with `source`, `stereo_verified`, and `stable` fields; annotate and side panel must show all three.

Set shell defaults `PALM_STABLE_HITS=4` and `PALM_HOLD_MISSES=3`. Add `PALM_MEDIAPIPE_ENABLED=1`; `0` forces fallback for diagnosis.

- [ ] **Step 4: Run focused tests and syntax check**

Run: `cd current; python3 -m pytest tests/test_palm_pipeline.py tests/test_hand_landmarks.py -v; python3 -m py_compile palm_recognition_app.py hand_landmarks.py vision_targeting.py`

Expected: PASS and no compiler output.

### Task 4: Migrate Remaining Maintained Recognition Apps

**Files:**
- Modify: `current/color_recognition_app.py`
- Modify: `current/shape_recognition_app.py`
- Modify: `current/fruit_recognition_app.py`
- Modify: `current/plate_recognition_app.py`
- Modify: `current/face_recognition_app.py`
- Test: `current/tests/test_visual_app_imports.py`

**Interfaces:**
- Consumes `split_stereo` and existing `target_roi`, `box_is_target`, `stable_filter`, `draw_target_roi` exports.
- Produces unchanged public application classes and existing detector output dataclasses.

- [ ] **Step 1: Write failing import and split-delegation tests**

```python
@pytest.mark.parametrize("module_name", [
    "color_recognition_app", "shape_recognition_app", "fruit_recognition_app",
    "plate_recognition_app", "face_recognition_app",
])
def test_visual_app_imports_without_camera(module_name):
    assert importlib.import_module(module_name)

def test_each_app_uses_shared_splitter():
    for path in APP_SOURCES:
        assert "from vision_targeting import" in path.read_text(encoding="utf-8")
        assert "split_stereo(" in path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd current; python3 -m pytest tests/test_visual_app_imports.py -v`

Expected: FAIL because applications still implement local `_normal_frame` slicing.

- [ ] **Step 3: Apply the narrowly scoped migration**

In each app import `split_stereo` from `vision_targeting` and implement `_normal_frame` as `return split_stereo(frame)[0]`. Do not alter existing detector thresholds, labels, model loading order, Tk layouts, snapshots, or shell environment variables. Keep existing detection-stability logic intact.

- [ ] **Step 4: Run regression checks**

Run: `cd current; python3 -m pytest tests/test_visual_app_imports.py tests/test_vision_targeting.py -v; python3 -m py_compile *_app.py vision_targeting.py`

Expected: PASS and no compiler output.

### Task 5: Restore and Modernize Camera Preview

**Files:**
- Create: `current/camera_view_app.py`
- Create: `current/camera_view.sh`
- Create: `current/tests/test_camera_view.py`

**Interfaces:**
- Consumes `split_stereo(frame)`.
- Produces `CameraViewApp._compose_frame(frame) -> np.ndarray` for `left`, `right`, and `raw` modes.

- [ ] **Step 1: Write failing preview composition tests**

```python
def test_preview_left_and_right_modes_use_the_expected_eye(monkeypatch):
    app = CameraViewApp.__new__(CameraViewApp)
    app.mode = FakeVar("left")
    frame = stereo_frame(left_value=30, right_value=210)
    assert int(app._compose_frame(frame).mean()) == 30
    app.mode = FakeVar("right")
    assert int(app._compose_frame(frame).mean()) == 210
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd current; python3 -m pytest tests/test_camera_view.py -v`

Expected: FAIL because the preview application is absent from the maintenance baseline.

- [ ] **Step 3: Migrate the preview source from the recovery package**

Copy the camera preview behavior from `rk3588_rebuild/latest_changes/root/robot_arm/camera_view_app.py`, but import and use `split_stereo` instead of its private `_split_stereo`. Copy its matching shell launcher, retaining `flock`, `/dev/video41`, and camera environment defaults. Do not add MediaPipe to this application.

- [ ] **Step 4: Run tests and syntax check**

Run: `cd current; python3 -m pytest tests/test_camera_view.py -v; python3 -m py_compile camera_view_app.py`

Expected: PASS and no compiler output.

### Task 6: Board Dependency and Deployment Verification

**Files:**
- Create: `current/requirements-mediapipe.txt`
- Create: `current/remote_verify_vision.sh`
- Modify: `docs/superpowers/specs/2026-09-03-rk3588-stereo-gesture-design.md`

**Interfaces:**
- `requirements-mediapipe.txt` contains exactly `mediapipe==0.10.18`.
- `remote_verify_vision.sh` exits nonzero on failed syntax/import checks and never starts two camera GUIs.

- [ ] **Step 1: Write failing deployment-file tests**

```python
def test_mediapipe_pin_and_remote_verifier_exist():
    assert REQUIREMENTS.read_text().strip() == "mediapipe==0.10.18"
    script = VERIFIER.read_text()
    assert "python3 -m py_compile" in script
    assert "import mediapipe" in script
    assert "/dev/video41" in script
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd current; python3 -m pytest tests/test_deployment_files.py -v`

Expected: FAIL because deployment files do not exist.

- [ ] **Step 3: Create explicit deployment artifacts**

Set `requirements-mediapipe.txt` to `mediapipe==0.10.18`. In `remote_verify_vision.sh`, run `python3 -m pip install -r requirements-mediapipe.txt` only when the operator explicitly invokes this script, then run `python3 -c 'import mediapipe, cv2'`, `python3 -m py_compile` over all camera apps, and print `v4l2-ctl --list-devices`. Update the design document with the exact operator-invoked installation command.

- [ ] **Step 4: Verify artifacts locally and on the board**

Run locally: `cd current; python3 -m pytest tests/test_deployment_files.py -v`

Run on RK3588 after copying `current` to `/root/robot_arm`: `cd /root/robot_arm && bash remote_verify_vision.sh`

Expected: local PASS; board output includes the MediaPipe and OpenCV import success, `/dev/video41`, and successful syntax checks.

### Task 7: Full Regression and Manual Acceptance

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-rk3588-stereo-gesture-design.md`
- Test: `current/tests/`

**Interfaces:**
- Consumes all prior components.
- Produces a documented test record for the target device.

- [ ] **Step 1: Run the complete automated suite**

Run: `cd current; python3 -m pytest tests -v; python3 -m py_compile *_app.py vision_targeting.py hand_landmarks.py`

Expected: all tests PASS and no compiler output.

- [ ] **Step 2: Perform board-level smoke tests one application at a time**

Run each launcher separately on the RK3588: `palm_recognition.sh`, `color_recognition.sh`, `shape_recognition.sh`, `fruit_recognition.sh`, `plate_recognition.sh`, `face_recognition.sh`, then `camera_view.sh`. Before starting the next launcher, close the previous GUI and verify `fuser /dev/video41` has no stale process.

- [ ] **Step 3: Perform hand-gesture acceptance checks**

At indoor normal light, present one hand centered in the left eye at 30-80 cm for each gesture. For rock, scissors, and paper: hold for at least four detection frames, verify a landmark-based hand box, `MediaPipe` source, `stereo verified` state, and a stable Chinese label. Repeat with a 20-degree hand rotation, the opposite hand, and a cluttered background. Temporarily set `PALM_MEDIAPIPE_ENABLED=0` and verify fallback source is shown and the application remains responsive.

- [ ] **Step 4: Record results**

Append the exact board Python/OpenCV/MediaPipe versions, camera device mapping, each launcher result, and any failed acceptance condition to the spec document's new `Validation Record` section. Do not claim all checks pass until every command and gesture check has been observed.
