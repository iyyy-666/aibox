# Radar Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent Slamtec A1M8 raw-scan radar detection module to the existing feature-demo application without changing existing robot, voice, camera, or gimbal behavior.

**Architecture:** The feature uses a small A1M8 serial driver, pure scan-region/baseline comparison logic, and a dedicated worker process managed by the existing `ModuleManager`. The UI sends three commands (`build_baseline`, `start_detection`, `stop_detection`) and renders worker status details; no robot command is triggered.

**Tech Stack:** Python 3.10, pyserial, FastAPI, PyWebView, native HTML/CSS/JavaScript, pytest.

**Spec:** User-provided radar detection requirements in the current conversation.

## Global Constraints

- Use raw A1M8 scan packets; do not use camera screenshots or OpenCV image recognition.
- Do not assume `/dev/ttyUSB0`; discover stable serial-by-id paths and USB/ACM fallbacks.
- No radar must not prevent application startup.
- Baseline uses multiple frames and detection uses configurable region, thresholds, sampling count, and consecutive confirmation count.
- Do not control or modify existing mechanical-arm behavior.
- Stop must close the serial port and join the radar thread before worker exit.
- Real-hardware claims require a successful A1M8 packet read on RK3588; simulated tests must be labelled as simulated.

---

### Task 1: Radar protocol and detection core

**Files:**
- Create: `子项目/功能演示/代码/feature_demo/radar/__init__.py`
- Create: `子项目/功能演示/代码/feature_demo/radar/protocol.py`
- Create: `子项目/功能演示/代码/feature_demo/radar/detection.py`
- Test: `子项目/功能演示/代码/tests/test_radar_core.py`

**Interfaces:**
- `ScanPoint(angle_deg: float, distance_mm: float, quality: int)`
- `DetectionRegion(min_angle_deg, max_angle_deg, min_distance_mm, max_distance_mm)`
- `RadarConfig` with `baseline_frames`, `confirmation_frames`, `change_distance_mm`, `change_ratio`, and `sample_period_s`
- `parse_scan_nodes(data: bytes) -> tuple[ScanPoint, ...]`
- `BaselineComparator.build_baseline(frames)` and `.compare(frame) -> DetectionResult`
- `ConfirmationState.update(has_object) -> bool`

- [ ] Write failing tests for valid/invalid A1M8 node decoding, region filtering, multi-frame median baseline, distance/ratio change scoring, and consecutive confirmation.
- [ ] Run `pytest 子项目/功能演示/代码/tests/test_radar_core.py -v` and verify the new tests fail because the radar package is absent.
- [ ] Implement the smallest pure-Python protocol and comparison core; reject malformed frames without crashing.
- [ ] Run the focused tests and verify they pass.

### Task 2: Device discovery and worker lifecycle

**Files:**
- Create: `子项目/功能演示/代码/feature_demo/radar/device.py`
- Create: `子项目/功能演示/代码/feature_demo/workers/radar.py`
- Modify: `子项目/功能演示/代码/feature_demo/workers/runtime.py`
- Modify: `子项目/功能演示/代码/feature_demo/registry.py`
- Modify: `子项目/功能演示/代码/feature_demo/resources.py`
- Test: `子项目/功能演示/代码/tests/test_radar_worker.py`
- Modify: `子项目/功能演示/代码/tests/test_registry.py`

**Interfaces:**
- `discover_radar_ports() -> tuple[str, ...]` ordered by `/dev/serial/by-id`, `/dev/ttyUSB*`, `/dev/ttyACM*`.
- `A1M8Device.open()`, `.iter_scans(stop_event)`, `.close()`.
- `RadarWorker.start()`, `.command(name, payload)`, `.stop()`.

- [ ] Write failing tests for port discovery, missing radar startup, command validation, simulated scans, baseline creation, start/stop, and no surviving reader thread.
- [ ] Run the focused worker tests and verify the expected failures.
- [ ] Implement serial access lazily with pyserial, use the A1M8 `0xA5 0x20` scan command and `0xA5 0x25` stop command, and expose simulated input only through explicit test injection.
- [ ] Register `radar_detection` with resources `("radar",)` and commands `build_baseline`, `start_detection`, and `stop_detection`; do not add robot resources or commands.
- [ ] Run focused tests plus existing worker/runtime tests.

### Task 3: Feature-demo UI and API contract

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/web/index.html`
- Modify: `子项目/功能演示/代码/feature_demo/web/app.js`
- Modify: `子项目/功能演示/代码/feature_demo/web/styles.css`
- Create or modify: `子项目/功能演示/代码/tests/test_radar_frontend_contract.py`

**Interfaces:**
- Render radar status from worker details: connection, baseline, detection lifecycle, result, region, change score, threshold, and confirmation progress.
- Send only the three radar commands through the existing `/api/modules/{module_id}/commands/{command}` endpoint.

- [ ] Write failing DOM-contract tests for the new module name, controls, status fields, and absence of robot controls.
- [ ] Run the frontend tests and verify they fail before UI integration.
- [ ] Add a radar-specific command workspace using the existing native frontend patterns and Chinese labels.
- [ ] Run frontend contract tests and existing frontend tests.

### Task 4: Local verification and RK3588 deployment

**Files:**
- Create: `子项目/功能演示/部署/deploy_radar_detection.py`
- Modify: `子项目/功能演示/README.md`
- Test: `子项目/功能演示/代码/tests/test_radar_deployment.py`

- [ ] Write failing deployment-script tests for named-file uploads, backup creation, py_compile, and no automatic robot action.
- [ ] Implement an explicit deployment script using `RK3588_HOST`, `RK3588_PASSWORD`, and SFTP; never embed credentials.
- [ ] Run the full local test suite and Python compilation checks.
- [ ] Create a timestamped remote backup, upload only named radar/feature-demo files, compile on RK3588, and restart only the feature-demo service if required.
- [ ] On RK3588 verify the CP2102 path can open and receive A1M8 scan packets, then test baseline, empty region, occupied region, and clean stop.
- [ ] Report separately which checks are simulated/local and which are real-hardware checks.

---
