# Feature Demo Final Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all fifteen final review findings without weakening hardware gates or changing the approved fruit/shape algorithms.

**Architecture:** Keep the existing API/manager/worker-process layering, but make control commands explicitly preemptive while ordinary commands remain serialized. Reconcile worker death and resource state at manager boundaries, use OS-owned process locks and process-group cleanup, expose real visual actions in the UI, and make acceptance evidence cryptographically bind the deployed code and hook.

**Tech Stack:** Python 3, FastAPI, threading/subprocess, Bash, vanilla JavaScript, pytest.

**Spec:** Parent-approved A-E design in the Task 9 final branch fix wave; the design details are captured in the task interfaces below.

## Global Constraints

- Every behavior change starts with a focused failing test and a recorded RED result.
- Student-facing state, error, and timeout messages are Chinese.
- Existing English nursery-rhyme lyrics remain valid content; UI labels remain Chinese.
- Do not change fruit/shape thresholds, ROI, or algorithm behavior.
- Do not run board apt, reboot, full acceptance, or legacy retirement.
- Final board state remains old service enabled/active, new service disabled/inactive, 14 legacy desktop entries, and no acceptance marker.

---

### Task 1: Runtime Identity, Voice Grammar, and Composite Readiness

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/registry.py`
- Modify: `子项目/功能演示/代码/feature_demo/workers/runtime.py`
- Modify: `子项目/功能演示/代码/feature_demo/workers/voice.py`
- Test: `子项目/功能演示/代码/tests/test_registry.py`
- Test: `子项目/功能演示/代码/tests/test_worker_entry.py`
- Test: `子项目/功能演示/代码/tests/test_voice_workers.py`
- Test: `子项目/功能演示/代码/tests/test_robot_workers.py`

**Interfaces:**
- Registry worker IDs are accepted unchanged by `create_worker(worker_id, event_sink=...)`.
- Non-robot voice workers set `use_command_grammar = False` and `set_commands({})`; robot voice keeps its command map.
- Object sorting filters component `ready` events and emits exactly one composite `ready` after robot and vision startup succeed.

- [x] Add tests that traverse registry to default process command to runtime factory, assert voice grammar configuration, and assert no ready event precedes a camera startup failure.
- [x] Run the four focused files and record RED.
- [x] Change `assistant` to `ai_assistant`, configure grammar explicitly, translate remaining timeout errors, and filter internal ready events.
- [x] Re-run the focused files to GREEN.

### Task 2: Preemptive Command Control and Worker Supervision

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/manager.py`
- Modify: `子项目/功能演示/代码/feature_demo/workers/runtime.py`
- Modify: `子项目/功能演示/代码/feature_demo/worker.py`
- Modify: `子项目/功能演示/代码/feature_demo/web/app.js`
- Test: `子项目/功能演示/代码/tests/test_manager.py`
- Test: `子项目/功能演示/代码/tests/test_worker_entry.py`
- Test: `子项目/功能演示/代码/tests/test_worker_process.py`
- Test: `子项目/功能演示/代码/tests/test_frontend_contract.py`

**Interfaces:**
- `PREEMPTIVE_COMMANDS` identifies interrupt/stop commands shared by manager, runtime, and frontend contract.
- Manager validates under its lifecycle lock but does not hold that lock across worker I/O; ordinary commands use a separate serialization lock, preemptive commands bypass it.
- Runtime reads stdin continuously, runs ordinary commands under one lock, and runs preemptive commands concurrently with correlated replies.
- `snapshot()` reconciles a dead running worker through `stop()` and `ResourceVerifier`; verified release becomes failed/cleared, unknown or busy becomes cleanup_failed and blocks starts.

- [x] Add concurrent long-command/interrupt/stop tests, dead-worker reconciliation tests, and frontend control-state tests.
- [x] Run the focused files and record RED.
- [x] Implement the separate command/control paths and lifecycle reconciliation with Chinese failures.
- [x] Re-run focused tests to GREEN.

### Task 3: OS Locking, Process Groups, Resource Verification, and Tracking Serialization

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/manager.py`
- Modify: `子项目/功能演示/代码/feature_demo/worker.py`
- Modify: `子项目/功能演示/代码/feature_demo/resources.py`
- Modify: `子项目/功能演示/代码/feature_demo/adapters/vision.py`
- Modify: `子项目/功能演示/代码/feature_demo/workers/vision.py`
- Test: `子项目/功能演示/代码/tests/test_manager.py`
- Test: `子项目/功能演示/代码/tests/test_worker_process.py`
- Test: `子项目/功能演示/代码/tests/test_resources.py`
- Test: `子项目/功能演示/代码/tests/test_legacy_vision_adapters.py`

**Interfaces:**
- `ProcessLock` holds a nonblocking OS file lock on an open descriptor; its file persists and its contents never determine ownership.
- `WorkerProcess.pids` enumerates the saved process group, and `stop()` terminates the group even after the leader exits.
- Device probes return `True`, `False`, or `None`; `None` is reported as unverified and fails cleanup.
- Palm tracking automatic movement and manual steps share the adapter lock and generation; a manual step pauses the active tracking generation before serial output.

- [ ] Add actual multiprocess lock contention, leader-dead/group-live, fuser failure/timeout, and controlled thread-interleaving tests.
- [ ] Run focused tests and record RED.
- [ ] Implement OS lock ownership, saved pgid cleanup, tri-state verification, and tracking serialization.
- [ ] Re-run focused tests to GREEN.

### Task 4: Visual Primary Actions and Snapshot Download

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/web/index.html`
- Modify: `子项目/功能演示/代码/feature_demo/web/app.js`
- Modify: `子项目/功能演示/代码/feature_demo/web/styles.css`
- Test: `子项目/功能演示/代码/tests/test_frontend_contract.py`

**Interfaces:**
- Visual workspace includes a module-specific action region populated from non-gimbal commands.
- `save_snapshot` downloads the currently displayed frame as a JPEG and never calls the command endpoint.
- While an ordinary request is pending, preemptive controls remain enabled.

- [ ] Add source/runtime contract tests for visual action rendering, local snapshot download, and preemptive control availability.
- [ ] Run frontend tests and record RED.
- [ ] Implement the visual action region, snapshot download, and per-command disabled state.
- [ ] Re-run frontend tests and `node --check` to GREEN.

### Task 5: Deployment Configuration and Acceptance Integrity

**Files:**
- Modify: `子项目/功能演示/部署/feature-demo.service`
- Modify: `子项目/功能演示/部署/install_feature_demo.sh`
- Modify: `子项目/功能演示/启动脚本/feature_demo.sh`
- Modify: `子项目/功能演示/部署/verify_feature_demo.sh`
- Modify: `子项目/功能演示/部署/hardware_acceptance_hook.sh`
- Test: `子项目/功能演示/代码/tests/test_deployment.py`
- Test: `子项目/功能演示/代码/tests/test_launcher.py`

**Interfaces:**
- Installer deploys `/etc/default/feature-demo` from `voice.conf`; service loads it and launcher provides the same fallback source for direct launches.
- Regular module hooks receive `FEATURE_DEMO_API_URL="$API_URL"`.
- Gimbal verification trusts correlated command ACK and verifies release at stop, without requiring persistent serial ownership.
- Window-close requires a `running` start response and hook-side active/status/resource verification before closing.
- Each module lifecycle produces `evidence=<module>:primary_behavior`; the verifier validates and records every evidence line.
- Marker payload includes verifier hash, deterministic application-package hash, hook hash, board identity, and results hash. Installer removes the old marker after deploying changed artifacts.

- [ ] Add Bash behavior tests for URL inheritance, ACK-only gimbal checks, failed window start, missing primary evidence, stale deployed hashes, and voice configuration installation/loading.
- [ ] Run deployment/launcher tests and record RED.
- [ ] Implement the minimal hook, verifier, installer, service, and launcher changes.
- [ ] Re-run deployment/launcher tests to GREEN.

### Task 6: Final Verification, Report, Deployment, and Commit

**Files:**
- Modify: `.superpowers/sdd/2026-09-21-feature-demo-integration-implementation/task-9-report.md`

- [ ] Run all focused suites, the unified suite, affected legacy suites, compileall, Node syntax, all five shell syntax checks, and `git diff --check`.
- [ ] Append all fifteen RED/GREEN results and design decisions to the Task 9 report.
- [ ] Commit the tested local changes.
- [ ] Incrementally deploy only changed production/configuration files and compare hashes.
- [ ] Read-only verify service states, 14 desktop entries, and absent marker; record camera/dpkg blockers.
