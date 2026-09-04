# 手掌追踪 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone RK3588 desktop application that keeps one detected palm near the center of the left stereo-camera image through ACK-verified, slow PWM gimbal adjustments.

**Architecture:** Keep visual capture and Tkinter drawing in `palm_tracking_app.py`; keep target selection, smoothing, deadband, speed limiting, timeout logic, and pure state transitions in `palm_tracking_control.py`; isolate every physical serial write behind `palm_tracking_serial.py`. The GUI supplies only the latest valid palm box and executes a controller output at a fixed interval, so detection frequency never causes uncontrolled command frequency.

**Tech Stack:** Python 3.10, Tkinter, OpenCV, MediaPipe, NumPy, pyserial, pytest, Bash, freedesktop `.desktop` launchers.

**Spec:** `G:\codexwork\人工智能实验箱\子项目\手掌追踪\设计文档\2026-09-04-rk3588-palm-tracking-design.md`

## Global Constraints

- Save every source, test, launcher, desktop entry, icon, design, and deployment artifact under `G:\codexwork\人工智能实验箱\子项目\手掌追踪`.
- Deploy application files to `/root/robot_arm`; desktop entry to `/home/ztl/Desktop`; launcher to `/usr/local/bin`.
- Use `/dev/video41` as 1280x480 MJPG stereo input and display/control from the 640x480 left eye.
- Use `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00` first, 115200 baud, the existing ASCII PWM protocol, horizontal servo ID 1, vertical servo ID 2, and required ACK.
- Enforce PWM values from 500 through 2500 inclusive. Do not command auto-center on start, stop, failure, or exit.
- Limit physical tracking speed to approximately 20 degrees/second through a configurable PWM-per-degree value, minimum command interval, and maximum per-command step.
- Stop producing commands after 0.5 seconds without a valid locked palm. Never send serial output from unit tests.
- Only one GUI may access `/dev/video41` at a time. Use a distinct `flock` lock file.
- This project folder is not a Git repository. Do not invent commits; record verification output in the task handoff instead.

---

## File Structure

- `代码/hand_landmarks.py`: copied, unmodified dependency from the working hand-recognition implementation.
- `代码/vision_targeting.py`: copied, unmodified stereo split and geometry dependency.
- `代码/palm_tracking_control.py`: pure target-lock and PWM-command decision engine with no Tkinter, OpenCV capture, or serial access.
- `代码/palm_tracking_serial.py`: ACK-verified serial connection, ASCII command framing, and two-axis state holder.
- `代码/palm_tracking_app.py`: Tkinter camera UI, worker threads, hand detection, locked-target coordination, canvas overlay, and start/stop UI state.
- `启动脚本/palm_tracking.sh`: desktop-safe environment, lock, camera configuration, serial defaults, and application startup.
- `桌面入口/palm_tracking.desktop`: “手掌追踪” AIBOX desktop entry.
- `桌面入口/palm_tracking.svg`: desktop icon asset copied to the board icon directory during deployment.
- `测试/conftest.py`: add `代码/` to `sys.path`.
- `测试/test_palm_tracking_control.py`: deterministic controller and target-lock tests.
- `测试/test_palm_tracking_serial.py`: frame encoding and ACK/error behavior using a fake serial object.
- `测试/test_palm_tracking_app.py`: GUI-independent start gating and detection-selection tests.
- `测试/test_deployment_files.py`: launcher and desktop-entry contract tests.
- `deploy_to_rk3588.py`: explicit upload and read-only post-deploy verification script; it must not start tracking or move the gimbal.

### Task 1: Establish Project-Local Dependencies and Test Harness

**Files:**
- Create: `代码/hand_landmarks.py`
- Create: `代码/vision_targeting.py`
- Create: `测试/conftest.py`
- Create: `测试/test_project_layout.py`

**Interfaces:**
- Consumes: current known-good `/root/robot_arm/hand_landmarks.py` and `/root/robot_arm/vision_targeting.py` equivalents.
- Produces: imports `HandLandmarkDetector`, `HandObservation`, `split_stereo`, and `BoxTracker` available to all later tasks.

- [ ] **Step 1: Write the failing layout/import test**

```python
def test_tracking_dependencies_import():
    import hand_landmarks
    import vision_targeting

    assert hasattr(hand_landmarks, "HandLandmarkDetector")
    assert callable(vision_targeting.split_stereo)
```

- [ ] **Step 2: Run the test to verify it fails before the copies exist**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试/test_project_layout.py -v`

Expected: FAIL with an import error for `hand_landmarks` or `vision_targeting`.

- [ ] **Step 3: Copy the exact known-good dependency modules and create the path hook**

Copy the current `hand_landmarks.py` and `vision_targeting.py` from the established stereo-gesture project into `代码/` without changing their interfaces. Create `测试/conftest.py`:

```python
from pathlib import Path
import sys

CODE_DIR = Path(__file__).resolve().parents[1] / "代码"
sys.path.insert(0, str(CODE_DIR))
```

- [ ] **Step 4: Run import and stereo-split tests**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试/test_project_layout.py -v`

Expected: PASS without requiring an attached camera or an installed MediaPipe runtime.

- [ ] **Step 5: Record the copied source revision and test result in the task handoff**

Record the source paths, file hashes, and pytest result. Do not create a Git commit because this project directory is unmanaged.

### Task 2: Implement and Test the Pure Tracking Controller

**Files:**
- Create: `代码/palm_tracking_control.py`
- Create: `测试/test_palm_tracking_control.py`

**Interfaces:**
- Consumes: `Box = tuple[int, int, int, int]`, timestamps supplied by the GUI, and camera image size.
- Produces: `TrackingConfig`, `TrackingDecision`, `PalmTargetLock`, and `PalmTrackingController`.
- Exact public API:

```python
@dataclass(frozen=True)
class TrackingConfig:
    deadband_ratio: float = 0.07
    smoothing_alpha: float = 0.35
    control_interval_sec: float = 0.10
    lost_timeout_sec: float = 0.50
    max_degrees_per_second: float = 20.0
    pwm_per_degree: float = 11.11
    min_step_pwm: int = 4
    max_step_pwm: int = 22
    pwm_min: int = 500
    pwm_max: int = 2500
    yaw_sign: int = 1
    pitch_sign: int = 1

@dataclass(frozen=True)
class TrackingDecision:
    yaw_delta_pwm: int = 0
    pitch_delta_pwm: int = 0
    state: str = "idle"
    offset_x: float = 0.0
    offset_y: float = 0.0

class PalmTargetLock:
    def arm(self, boxes: list[Box], image_size: tuple[int, int]) -> Box | None: ...
    def update(self, boxes: list[Box]) -> Box | None: ...
    def clear(self) -> None: ...

class PalmTrackingController:
    def start(self, box: Box, now: float) -> None: ...
    def stop(self) -> None: ...
    def update(self, box: Box | None, image_size: tuple[int, int], now: float) -> TrackingDecision: ...
```

- [ ] **Step 1: Write failing tests for target selection, deadband, steps, clamp, speed, and loss**

```python
def test_arm_chooses_box_nearest_image_center():
    lock = PalmTargetLock()
    assert lock.arm([(5, 5, 50, 50), (290, 220, 80, 80)], (640, 480)) == (290, 220, 80, 80)

def test_deadband_emits_no_pwm_command():
    controller = PalmTrackingController(TrackingConfig())
    controller.start((290, 220, 60, 60), now=0.0)
    assert controller.update((300, 225, 40, 40), (640, 480), now=0.1).yaw_delta_pwm == 0

def test_rate_limit_caps_a_tenth_second_to_twenty_two_pwm():
    controller = PalmTrackingController(TrackingConfig(max_step_pwm=100))
    controller.start((300, 220, 40, 40), now=0.0)
    assert abs(controller.update((580, 220, 40, 40), (640, 480), now=0.1).yaw_delta_pwm) <= 22

def test_loss_after_half_second_stops_control():
    controller = PalmTrackingController(TrackingConfig(lost_timeout_sec=0.5))
    controller.start((300, 220, 40, 40), now=0.0)
    assert controller.update(None, (640, 480), now=0.51).state == "lost"
```

- [ ] **Step 2: Run the controller tests to verify they fail**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试/test_palm_tracking_control.py -v`

Expected: FAIL because `palm_tracking_control` and its public classes do not exist.

- [ ] **Step 3: Implement the smallest deterministic controller**

Implement center-normalized offset calculation from the box center, exponential smoothing, per-axis deadband, proportional PWM step selection, sign inversion, time-based 20 degree/second cap, and clamp. Only return deltas; do not import `serial`, `cv2`, or Tkinter.

```python
allowed = int(config.max_degrees_per_second * config.pwm_per_degree * elapsed)
limit = min(config.max_step_pwm, max(0, allowed))
delta = max(-limit, min(limit, proportional_delta))
```

Return `TrackingDecision(state="centered")` inside the deadband, `state="tracking"` only when a nonzero permitted delta exists, and `state="lost"` after the configured loss timeout.

- [ ] **Step 4: Run controller tests and the complete local test suite**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试/test_palm_tracking_control.py -v && python -m pytest 测试 -v`

Expected: PASS. Assert that neither test imports nor controller calls can open a serial port.

- [ ] **Step 5: Record test output and the chosen default calibration**

Record `pwm_per_degree=11.11`, corresponding to 2000 PWM over 180 degrees, as an initial configurable estimate pending physical calibration.

### Task 3: Implement ACK-Verified Serial Gimbal Client

**Files:**
- Create: `代码/palm_tracking_serial.py`
- Create: `测试/test_palm_tracking_serial.py`

**Interfaces:**
- Consumes: `yaw_delta_pwm`, `pitch_delta_pwm`, current pulse values, and `TrackingConfig` PWM bounds from Task 2.
- Produces: `SerialGimbalClient` with `connect()`, `move(yaw_delta_pwm, pitch_delta_pwm)`, `disconnect()`, and `last_error`.
- Exact public API:

```python
class SerialGimbalClient:
    def __init__(self, *, port: str, baud: int, yaw_id: int, pitch_id: int,
                 pwm_min: int, pwm_max: int, initial_pwm: int = 1500,
                 serial_factory=serial.Serial) -> None: ...
    def connect(self) -> tuple[bool, str]: ...
    def move(self, yaw_delta_pwm: int, pitch_delta_pwm: int, time_ms: int = 100) -> tuple[bool, str]: ...
    def disconnect(self) -> None: ...
```

- [ ] **Step 1: Write failing serial contract tests with a fake serial device**

```python
def test_move_writes_pwm_frame_and_requires_matching_ack(fake_serial):
    client = make_client(fake_serial, ack=b"ACK id=1 pulse=1510\nACK id=2 pulse=1490\n")
    ok, _ = client.move(10, -10, time_ms=100)
    assert ok
    assert b"#001P1510T0100!\r\n" in fake_serial.writes
    assert b"#002P1490T0100!\r\n" in fake_serial.writes

def test_missing_ack_returns_false_and_keeps_last_confirmed_pwm(fake_serial):
    client = make_client(fake_serial, ack=b"")
    ok, _ = client.move(10, 0)
    assert not ok
    assert client.yaw_pwm == 1500
```

- [ ] **Step 2: Run the serial tests to verify they fail**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试/test_palm_tracking_serial.py -v`

Expected: FAIL with module import error.

- [ ] **Step 3: Implement serial framing, ACK parsing, and failure behavior**

Open only the configured by-id path. Encode each required axis using the existing controller’s PWM syntax. Read until both expected `ACK id=<id> pulse=<pwm>` lines appear or a 0.45 second monotonic deadline expires. Update `yaw_pwm` and `pitch_pwm` only after all required ACKs validate. On write, parse, or timeout failure, close the port and return `(False, error)`; do not retry a movement automatically.

- [ ] **Step 4: Run serial and controller tests**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试/test_palm_tracking_serial.py 测试/test_palm_tracking_control.py -v`

Expected: PASS with no access to physical `/dev/tty*` devices.

- [ ] **Step 5: Record the confirmed command contract**

Record the exact command bytes, ACK forms, 0.45 second timeout, and statement that a failed command never changes the tracked PWM state.

### Task 4: Build the Camera UI and Integrate Tracking State

**Files:**
- Create: `代码/palm_tracking_app.py`
- Create: `测试/test_palm_tracking_app.py`

**Interfaces:**
- Consumes: `HandLandmarkDetector`, `split_stereo`, `PalmTargetLock`, `PalmTrackingController`, `SerialGimbalClient`.
- Produces: `PalmTrackingApp`, with `start_tracking()`, `stop_tracking(reason: str)`, `close()`, and no serial write until the user presses the enabled start button.

- [ ] **Step 1: Write failing GUI-independent behavior tests**

Construct `PalmTrackingApp` through `__new__` with fake button, fake controller, and fake gimbal collaborators. Test the state methods without calling `tk.Tk()`:

```python
def test_start_is_rejected_until_a_center_palm_is_available(app):
    app.current_detection = None
    assert not app.start_tracking()
    assert app.gimbal.moves == []

def test_stop_clears_lock_without_sending_center_command(app):
    app.start_tracking()
    app.stop_tracking("user")
    assert not app.tracking_enabled
    assert app.gimbal.moves == []
```

- [ ] **Step 2: Run the app tests to verify they fail**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试/test_palm_tracking_app.py -v`

Expected: FAIL because `PalmTrackingApp` does not exist.

- [ ] **Step 3: Implement the application around existing camera patterns**

Use `cv2.VideoCapture(..., cv2.CAP_V4L2)` with MJPG, 1280x480, 30 FPS, and buffer size 1. Run capture and hand-detection loops in daemon threads; copy the latest frame under a lock; split left/right with `split_stereo`; use the left hand box for display and target lock. Draw a central crosshair, visible startup region, locked hand box, and concise state text over the video. The right panel must have the start/stop button and status only; the camera canvas remains the primary surface.

At a fixed UI-safe control interval, call `controller.update()`. Call `gimbal.move()` only for a `TrackingDecision` with nonzero deltas. On a `lost` decision, camera error, detector error, or serial error, call `stop_tracking()` or leave tracking armed as specified, but never call a center function or direct PWM reset.

- [ ] **Step 4: Run app, controller, and import checks**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m py_compile 代码/palm_tracking_app.py 代码/palm_tracking_control.py 代码/palm_tracking_serial.py && python -m pytest 测试/test_palm_tracking_app.py 测试/test_palm_tracking_control.py 测试/test_palm_tracking_serial.py -v`

Expected: PASS. Confirm that import does not instantiate the camera, Tk root, or serial port.

- [ ] **Step 5: Record UI state transitions**

Record: opening -> waiting for centered palm -> ready -> tracking -> lost/auto-resume -> stopped/error -> closed, and identify which transitions permit a serial write.

### Task 5: Add Launch, Desktop, Icon, and Deployment Contracts

**Files:**
- Create: `启动脚本/palm_tracking.sh`
- Create: `桌面入口/palm_tracking.desktop`
- Create: `桌面入口/palm_tracking.svg`
- Create: `测试/test_deployment_files.py`
- Create: `deploy_to_rk3588.py`

**Interfaces:**
- Consumes: `palm_tracking_app.py` and the known camera/serial hardware defaults.
- Produces: a one-instance AIBOX desktop app and a deployment command that copies only reviewed project files.

- [ ] **Step 1: Write failing deployment-contract tests**

```python
def test_launcher_uses_a_dedicated_camera_lock_and_safe_serial_defaults():
    text = (ROOT / "启动脚本" / "palm_tracking.sh").read_text(encoding="utf-8")
    assert "palm_tracking.lock" in text
    assert "/dev/video41" in text
    assert "usb-1a86_USB_Single_Serial_5C67040336-if00" in text
    assert "PALM_TRACK_MAX_DEGREES_PER_SECOND=${PALM_TRACK_MAX_DEGREES_PER_SECOND:-20}" in text

def test_desktop_entry_uses_tracking_name_and_launcher():
    text = (ROOT / "桌面入口" / "palm_tracking.desktop").read_text(encoding="utf-8")
    assert "Name[zh_CN]=手掌追踪" in text
    assert "Exec=/usr/local/bin/palm_tracking.sh" in text
```

- [ ] **Step 2: Run deployment-contract tests to verify they fail**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试/test_deployment_files.py -v`

Expected: FAIL because launcher and desktop files do not exist.

- [ ] **Step 3: Implement the launcher, desktop entry, icon, and deployment script**

The launcher must set `DISPLAY`, `XAUTHORITY`, Python paths consistent with the working palm-recognition launcher, `PALM_TRACK_CAMERA_DEVICE=/dev/video41`, the by-id serial path, baud 115200, servo IDs 1/2, ACK required, initial PWM 1500, PWM limits 500/2500, max speed 20, and separate yaw/pitch signs defaulting to 1. It must use `flock -n` on `palm_tracking.lock` before starting Python.

The desktop entry must use the title “手掌追踪”, `/usr/local/bin/palm_tracking.sh`, and `/root/robot_arm/assets/icons/palm_tracking.svg`. Create a simple high-contrast SVG using the existing dark AIBOX icon palette and a palm plus centered crosshair motif. `deploy_to_rk3588.py` must upload only named files, run `py_compile`, check launcher/desktop content, and never execute `palm_tracking.sh` or issue a servo command.

- [ ] **Step 4: Run all local tests and static checks**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python -m pytest 测试 -v && bash -n 启动脚本/palm_tracking.sh && python -m py_compile deploy_to_rk3588.py`

Expected: PASS.

- [ ] **Step 5: Record deploy manifest**

Record every source-to-board path and the desktop/icon target paths before any upload.

### Task 6: Deploy Safely and Perform Board/Physical Acceptance

**Files:**
- Modify: `PROJECT_CONTEXT.md`
- Modify: `README.md`
- Modify: `测试/board_validation_2026-09-04.md`

**Interfaces:**
- Consumes: all verified project files and a user physically present at the gimbal.
- Produces: a deployed desktop entry, board verification record, and calibrated yaw/pitch signs and PWM-per-degree values.

- [ ] **Step 1: Run the non-motion deployment script**

Run: `cd 'G:\codexwork\人工智能实验箱\子项目\手掌追踪' && python deploy_to_rk3588.py`

Expected: upload succeeds; board output confirms `py_compile` for all Python files, launcher and desktop entry paths exist, and no tracking process or servo command is started.

- [ ] **Step 2: Verify board device availability without moving hardware**

Run remotely: `test -e /dev/video41 && test -e /dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00 && python3 -m py_compile /root/robot_arm/palm_tracking_app.py /root/robot_arm/palm_tracking_control.py /root/robot_arm/palm_tracking_serial.py`

Expected: exit status 0. Do not open the application while another `/dev/video41` GUI is running.

- [ ] **Step 3: Perform supervised axis-direction calibration**

With the user observing and clear of mechanical travel, use the application’s calibration control to request one 4-PWM, 100-ms yaw movement, then one 4-PWM, 100-ms pitch movement. Ask the user to confirm each observed screen-direction mapping. Set `PALM_TRACK_YAW_SIGN`, `PALM_TRACK_PITCH_SIGN`, and measured `PALM_TRACK_PWM_PER_DEGREE` in the launcher; retain the 500-2500 clamp.

- [ ] **Step 4: Run the physical acceptance sequence**

1. Start the desktop app and verify left-eye camera video, center crosshair, and disabled start button.
2. Hold one palm in the startup region and verify “开始追踪” enables without motion.
3. Start tracking; move the palm slowly left, right, up, and down. Verify each axis corrects toward image center with small PWM steps.
4. Check measured angular speed remains about or below 20 degrees/second and the view does not visibly oscillate in the deadband.
5. Remove the palm for at least 0.5 seconds. Verify commands stop. Re-enter the locked palm and verify automatic resume.
6. Press stop, close the application, then repeat with serial cable unplugged. Verify no auto-center occurs and errors appear without retries that move the cloud platform.

- [ ] **Step 5: Save the acceptance record and update project status**

Write actual calibration values, test date, pass/fail result for each acceptance item, and any observed limitation to `测试/board_validation_2026-09-04.md`. Update `PROJECT_CONTEXT.md` and `README.md` to name the final files and current deployment state.

## Plan Self-Review

- Spec coverage: Tasks 1 and 4 cover stereo camera and hand detection; Task 2 covers locking, smoothing, deadband, 20 degree/second limit, PWM clamp, and loss timeout; Task 3 covers ACK and safe serial failure; Task 4 covers video-first UI and start/stop behavior; Task 5 covers launch/icon/desktop constraints; Task 6 covers deployment and supervised physical calibration.
- Placeholder scan: no deferred implementation markers are present; every test target, public interface, command, and verification result is specified.
- Type consistency: Tasks 2-4 consistently use `(x, y, width, height)` boxes, `TrackingDecision` PWM deltas, and `SerialGimbalClient.move(yaw_delta_pwm, pitch_delta_pwm)`.
