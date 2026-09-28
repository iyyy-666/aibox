# Radar Scan Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make RK3588 A1M8 scan geometry match the laptop upper-computer view and make baseline creation depend on valid complete rotations instead of a misaligned byte stream.

**Architecture:** Keep the lightweight Python serial backend. Add a stateful legacy-node stream parser, validate and consume the seven-byte A1 scan descriptor before parsing nodes, buffer complete rotations in the radar worker, and expose readiness and transport metrics to a laptop-compatible polar canvas.

**Tech Stack:** Python 3.10, pyserial, FastAPI worker events, native HTML/CSS/JavaScript Canvas, pytest, Playwright, Paramiko deployment.

**Spec:** `docs/superpowers/specs/2026-09-28-radar-scan-alignment-design.md`

## Global Constraints

- Use raw A1M8 scan packets; do not use camera screenshots, OpenCV, SLAM, or object classification.
- Keep the stable CP2102 by-id path discovery and never hardcode `/dev/ttyUSB0`.
- Do not modify or trigger mechanical-arm, voice, camera, or gimbal behavior.
- Do not treat missing or invalid radar data as “固定位置不存在物块”.
- Keep the implementation pure Python and browser-native; do not add the Slamtec C++ SDK in this change.
- The scan plot uses 0 degrees at the top, 90 degrees at the right, clockwise-positive angles, and a fixed 8000 mm range.
- Entering the module starts scanning once; only leaving the module sends stop and closes the serial port.
- Real-hardware completion requires valid descriptor, point-rate, complete-rotation, baseline, and clean-stop evidence from RK3588.

---

### Task 1: Stateful A1M8 protocol stream parser

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/radar/protocol.py`
- Modify: `子项目/功能演示/代码/tests/test_radar_core.py`

**Interfaces:**
- Consumes: arbitrary byte chunks beginning at any stream boundary after the scan descriptor.
- Produces: `parse_scan_node(data: bytes) -> ScanPoint | None` and `A1ScanStreamParser.feed(data: bytes) -> tuple[ScanPoint, ...]`.
- Preserves: `parse_scan_nodes(data: bytes) -> tuple[ScanPoint, ...]` for existing callers and tests.

- [ ] **Step 1: Add failing parser tests**

Add tests covering a node split across reads, a garbage-byte prefix, and recovery after one dropped/malformed byte:

```python
def test_stream_parser_handles_split_nodes_and_recovers_alignment():
    parser = A1ScanStreamParser()
    first = node(10.0, 500, start=True)
    second = node(20.0, 700)

    assert parser.feed(b"\xff" + first[:3]) == ()
    points = parser.feed(first[3:] + second)

    assert [(p.angle_deg, p.distance_mm) for p in points] == [(10.0, 500.0), (20.0, 700.0)]


def test_stream_parser_discards_one_bad_byte_then_finds_next_node():
    parser = A1ScanStreamParser()

    points = parser.feed(node(30.0, 600) + b"\x00" + node(40.0, 800))

    assert [point.angle_deg for point in points] == [30.0, 40.0]
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```powershell
cd 子项目/功能演示/代码
pytest tests/test_radar_core.py -q
```

Expected: collection or import fails because `A1ScanStreamParser` and `parse_scan_node` do not exist.

- [ ] **Step 3: Implement strict node validation and byte-level resynchronization**

Implement one-node validation and a buffered parser. The start bit and inverse start bit must differ, the angle check bit must be set, angle must be below 360 degrees, and distance must be non-zero:

```python
def parse_scan_node(data: bytes) -> ScanPoint | None:
    if len(data) != 5:
        return None
    quality_flags, angle_low, angle_high, distance_low, distance_high = data
    start = quality_flags & 0x01
    inverse_start = (quality_flags >> 1) & 0x01
    if start == inverse_start or (angle_low & 0x01) != 1:
        return None
    angle_deg = (((angle_high << 8) | angle_low) >> 1) / 64.0
    distance_mm = ((distance_high << 8) | distance_low) / 4.0
    if not 0 <= angle_deg < 360 or distance_mm <= 0:
        return None
    return ScanPoint(angle_deg, distance_mm, quality_flags >> 2, bool(start))


class A1ScanStreamParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> tuple[ScanPoint, ...]:
        self._buffer.extend(data)
        points: list[ScanPoint] = []
        while len(self._buffer) >= 5:
            point = parse_scan_node(bytes(self._buffer[:5]))
            if point is None:
                del self._buffer[0]
                continue
            del self._buffer[:5]
            points.append(point)
        return tuple(points)
```

Make `parse_scan_nodes` call `parse_scan_node` for each already-aligned five-byte record so its current strict-length contract remains unchanged.

- [ ] **Step 4: Run protocol tests**

Run `pytest tests/test_radar_core.py -q`.

Expected: all radar core tests pass.

- [ ] **Step 5: Commit the parser change**

```powershell
git add -- 子项目/功能演示/代码/feature_demo/radar/protocol.py 子项目/功能演示/代码/tests/test_radar_core.py
git commit -m "fix: resynchronize A1M8 scan node stream"
```

### Task 2: Descriptor validation and complete-rotation framing

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/radar/device.py`
- Modify: `子项目/功能演示/代码/tests/test_radar_core.py`

**Interfaces:**
- Consumes: serial response to `A5 20`.
- Produces: `SCAN_DESCRIPTOR = bytes.fromhex("a55a0500004081")`, `A1M8Device.diagnostics -> dict`, and complete non-empty rotations from `iter_scans(stop_event)`.
- Raises: `RadarProtocolError` with distinct Chinese messages for no descriptor and invalid descriptor.

- [ ] **Step 1: Extend `FakeSerial` and write failing device tests**

Make `FakeSerial` return queued chunks and add tests that prove the descriptor can be split across reads, never enters node parsing, and only complete rotations are yielded:

```python
def test_device_consumes_split_descriptor_and_yields_only_complete_rotation():
    descriptor = bytes.fromhex("a55a0500004081")
    payload = node(0.0, 500, start=True) + node(90.0, 600) + node(1.0, 550, start=True)
    serial = FakeSerial(reads=[descriptor[:3], descriptor[3:] + payload])
    device = A1M8Device(
        ports=("/dev/radar",),
        serial_factory=lambda *_args, **_kwargs: serial,
        motor_start_delay_s=0,
    )
    stop = threading.Event()

    assert device.open() is True
    frame = next(device.iter_scans(stop))

    assert [point.angle_deg for point in frame] == [0.0, 90.0]
    assert device.diagnostics["descriptor_valid"] is True
```

Add invalid-descriptor and leading-partial-rotation tests. Keep the existing assertion that the only startup write is `A5 20`.

- [ ] **Step 2: Run focused tests and confirm the descriptor test fails**

Run:

```powershell
pytest tests/test_radar_core.py -q
```

Expected: the seven-byte descriptor is still passed into five-byte parsing or diagnostics are absent.

- [ ] **Step 3: Implement descriptor state and full-frame output**

Add `_read_exact(7, stop_event)` that tolerates partial reads, validate the exact descriptor fields, then create `A1ScanStreamParser`. Ignore points until the first `scan_start`; when the next `scan_start` arrives, yield the accumulated frame and begin the new one. Maintain monotonic counters for bytes received, valid points, complete rotations, last frame size, and last frame timestamp.

Do not send a second scan command from `iter_scans`. Preserve DTR/RTS pre-open configuration and the single `A5 25` write in `close()`.

- [ ] **Step 4: Run device and core tests**

Run `pytest tests/test_radar_core.py -q`.

Expected: descriptor, resynchronization, frame-boundary, DTR/RTS, and close tests pass.

- [ ] **Step 5: Commit device framing**

```powershell
git add -- 子项目/功能演示/代码/feature_demo/radar/device.py 子项目/功能演示/代码/tests/test_radar_core.py
git commit -m "fix: validate A1M8 descriptor before framing scans"
```

### Task 3: Rotation buffer, readiness, diagnostics, and baseline lifecycle

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/workers/radar.py`
- Modify: `子项目/功能演示/代码/feature_demo/radar/detection.py`
- Modify: `子项目/功能演示/代码/tests/test_radar_worker.py`
- Modify: `子项目/功能演示/代码/tests/test_radar_core.py`

**Interfaces:**
- Consumes: complete rotation tuples from `A1M8Device.iter_scans` and `A1M8Device.diagnostics`.
- Produces scan events containing `data_ready`, `valid_rotations`, `required_rotations`, `bytes_per_second`, `points_per_second`, `rotations_per_second`, `last_rotation_points`, and `last_rotation_age_ms`.
- `build_baseline` waits on a `threading.Condition` over a bounded `deque`, using the newest `baseline_frames` complete rotations.

- [ ] **Step 1: Add failing readiness and baseline-buffer tests**

Update `FakeDevice` with a diagnostics property and add tests for readiness before/after five complete rotations, baseline waiting until 12 rotations, and explicit region-empty failure:

```python
def test_worker_reports_ready_only_after_five_valid_rotations():
    events = []
    frame = tuple(ScanPoint(float(angle), 1000.0, 15) for angle in range(260, 281))
    device = FakeDevice([frame])
    worker = RadarWorker(
        device_factory=lambda: device,
        event_sink=events.append,
        minimum_frame_points=1,
        readiness_frames=5,
        sample_period_s=0.001,
    )

    worker.start()
    wait_until(lambda: any(event.get("valid_rotations", 0) >= 5 for event in events))
    worker.stop()

    assert any(event.get("data_ready") is True for event in events)
```

Assert `build_baseline` returns `{"ok": False, "error": "not_ready", ...}` before five valid rotations and `error == "region_empty"` when all buffered frames contain no points in the configured region.

- [ ] **Step 2: Run worker tests and confirm failures**

Run `pytest tests/test_radar_worker.py tests/test_radar_core.py -q`.

Expected: readiness fields, condition-backed buffering, and explicit error codes are absent.

- [ ] **Step 3: Replace the size-three queue with a condition-backed deque**

Use `deque(maxlen=max(baseline_frames, readiness_frames))`, guard it with `threading.Condition`, and append only frames meeting `minimum_frame_points`. Emit scan metrics on each accepted frame. `build_baseline` must:

1. reject disconnected state as `error="disconnected"`;
2. reject fewer than five valid rotations as `error="not_ready"`;
3. wait up to the existing bounded command timeout for 12 buffered rotations;
4. copy the newest 12 rotations while holding the condition lock;
5. release the lock before calling `BaselineComparator.build_baseline`;
6. map an empty detection region to `error="region_empty"`.

Keep `sample_period_s` as event-rate limiting only; it must not alter point angles or distances.

- [ ] **Step 4: Make detection comparison preserve invalid-data state**

Extend `DetectionResult` with `data_valid: bool`. If the current region has no usable comparison buckets, return invalid data and do not update `ConfirmationState`. Preserve median baseline bins and configurable thresholds.

- [ ] **Step 5: Run radar worker and core tests**

Run:

```powershell
pytest tests/test_radar_core.py tests/test_radar_worker.py -q
```

Expected: readiness, buffered baseline, object/no-object confirmation, invalid-region, and clean-thread-stop tests pass.

- [ ] **Step 6: Commit worker lifecycle changes**

```powershell
git add -- 子项目/功能演示/代码/feature_demo/workers/radar.py 子项目/功能演示/代码/feature_demo/radar/detection.py 子项目/功能演示/代码/tests/test_radar_worker.py 子项目/功能演示/代码/tests/test_radar_core.py
git commit -m "fix: build radar baseline from complete rotations"
```

### Task 4: Laptop-compatible polar scan canvas and one-screen controls

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/web/app.js`
- Modify: `子项目/功能演示/代码/feature_demo/web/styles.css`
- Modify: `子项目/功能演示/代码/tests/test_radar_frontend_contract.py`

**Interfaces:**
- Consumes: scan and diagnostic fields emitted by Task 3.
- Produces: a fixed 8000 mm black polar canvas with clockwise angle transform and readiness-gated baseline control.
- Preserves: the existing module command API and manual-only `data-radar-confirm` behavior.

- [ ] **Step 1: Add failing frontend contract tests**

Assert the implementation contains the fixed range and orientation transform, all diagnostic labels, and readiness control:

```python
assert "RADAR_MAX_DISTANCE_MM = 8000" in app
assert "Math.sin(angleRad)" in app
assert "-Math.cos(angleRad)" in app
assert "data-radar-readiness" in app
assert "data-radar-byte-rate" in app
assert "data-radar-point-rate" in app
assert "data-radar-rotation-rate" in app
assert "data-radar-last-frame" in app
```

Keep the contract that the radar block has no robot `sequence` command.

- [ ] **Step 2: Run frontend tests and confirm failure**

Run `pytest tests/test_radar_frontend_contract.py -q`.

Expected: fixed range, orientation transform, and diagnostics are absent.

- [ ] **Step 3: Render the upper-computer coordinate system**

In `drawRadarScan`, use a square CSS-sized canvas and device-pixel-ratio backing store. Draw a black background, four 2000 mm rings, 30-degree spokes and labels. Convert each raw point with:

```javascript
const angleRad = point.angle_deg * Math.PI / 180;
const radius = Math.min(point.distance_mm, RADAR_MAX_DISTANCE_MM) / RADAR_MAX_DISTANCE_MM * plotRadius;
const x = centerX + Math.sin(angleRad) * radius;
const y = centerY - Math.cos(angleRad) * radius;
```

Draw raw valid points in cyan without interpolation. Draw the latest angle ray separately and render the configurable detection-region outline without recoloring points.

- [ ] **Step 4: Add readiness and transport diagnostics**

Render `有效扫描 X/5`, byte rate, point rate, Hz/RPM, last frame point count, and age. Disable the baseline button until `data_ready === true`; keep start detection unavailable until `baseline_ready === true`. Error messages from the worker must remain visible instead of being replaced by “不存在物块”.

- [ ] **Step 5: Make the radar workspace fit one screen**

Use stable grid tracks: a square canvas area and a fixed-width status/control column. Keep controls visible at common RK3588 desktop heights and remove vertical scrolling from the radar workspace only. Do not change other modules' scrolling behavior.

- [ ] **Step 6: Run frontend and API contract tests**

Run:

```powershell
pytest tests/test_radar_frontend_contract.py tests/test_api.py -q
```

Expected: radar rendering, manual confirmation, command API, and unrelated API tests pass.

- [ ] **Step 7: Commit frontend alignment**

```powershell
git add -- 子项目/功能演示/代码/feature_demo/web/app.js 子项目/功能演示/代码/feature_demo/web/styles.css 子项目/功能演示/代码/tests/test_radar_frontend_contract.py
git commit -m "feat: align radar plot with A1M8 upper computer"
```

### Task 5: Local regression and browser verification

**Files:**
- Create: `output/radar-scan-desktop.png`
- Source changes: none; a browser verification failure returns execution to the owning task before this task is rerun.

**Interfaces:**
- Consumes: completed local implementation.
- Produces: passing full suite and a desktop screenshot proving the module is complete, nonblank, and does not require vertical scrolling.

- [ ] **Step 1: Run the complete test suite**

Run:

```powershell
cd 子项目/功能演示/代码
pytest -q
```

Expected: all tests pass; the existing Starlette/httpx deprecation warning may remain.

- [ ] **Step 2: Compile all modified Python modules**

Run:

```powershell
python -m py_compile feature_demo/radar/protocol.py feature_demo/radar/device.py feature_demo/radar/detection.py feature_demo/workers/radar.py
```

Expected: exit code 0 with no output.

- [ ] **Step 3: Start the local application and inspect with Playwright**

Start the existing launcher on an unused local port, open the radar module, inject a scan event only through the browser test harness, and capture `output/radar-scan-desktop.png`. Verify canvas pixels are nonblack where points and grid are expected, 0 degrees is top, 90 degrees is right, controls are visible, and `document.documentElement.scrollHeight <= window.innerHeight` for the radar view.

- [ ] **Step 4: Re-run focused tests after any browser-discovered fix**

Run `pytest tests/test_radar_frontend_contract.py tests/test_api.py -q`.

Expected: pass.

### Task 6: RK3588 deployment and real A1M8 acceptance

**Files:**
- Use: `子项目/功能演示/部署/deploy_radar_detection.py`
- Verify with: `子项目/功能演示/代码/tests/test_radar_deployment.py`
- Source changes: none; a deployment-contract failure returns execution to the task that owns the missing file or behavior.

**Interfaces:**
- Consumes: locally verified named radar files and `RK3588_PASSWORD` from environment.
- Produces: timestamped remote backup, deployed files, remote compile result, restarted feature-demo process, and real scan diagnostics.

- [ ] **Step 1: Verify deployment targets before upload**

Run `pytest tests/test_radar_deployment.py -q`, then confirm the process working directory is `/root/robot_arm`, Python imports `/root/robot_arm/feature_demo`, and the stable CP2102 path resolves to a `ttyUSB` device. Confirm no other process has the radar serial port open.

- [ ] **Step 2: Back up and upload only named files**

Run the deployment script with `RK3588_HOST=192.168.11.106`, `RK3588_USER=root`, and the supplied password in `RK3588_PASSWORD`. The script must create a timestamped backup before upload and must not upload tests, credentials, or unrelated modules.

- [ ] **Step 3: Compile remotely and restart only feature demo**

Run remote `python3 -m py_compile` for the four modified Python modules, then terminate the current `python3 -m feature_demo.launcher` process gracefully and start the same launcher from `/root/robot_arm`. Do not restart the board or any robot service.

- [ ] **Step 4: Verify real transport metrics**

Enter the radar module and record:

- descriptor valid;
- non-zero bytes per second;
- non-zero valid points per second;
- stable complete rotations per second consistent with the physical RPM;
- last rotation contains a plausible number of points;
- radar continues rotating while the module stays open.

If any metric is zero, stop and diagnose that boundary before baseline testing.

- [ ] **Step 5: Compare scan geometry with the laptop reference**

Verify that the major wall/object contours appear at the same clockwise angle and approximately the same distance as the supplied laptop screenshot. Do not require identical instantaneous points, but reject mirrored, rotated, uniformly scaled, or sparse/malformed geometry.

- [ ] **Step 6: Verify baseline and object states**

With the detection region empty, wait for `有效扫描 5/5`, build the 12-rotation baseline, and confirm success. Place and remove the object in the configured region and verify the UI changes after three consecutive complete rotations in each direction.

- [ ] **Step 7: Verify clean stop and regressions**

Exit the module and confirm the serial descriptor is closed and the radar reader thread ends. Open at least one existing non-radar module to ensure feature-demo lifecycle behavior remains intact. Record the remote backup path and final process PID.

---
