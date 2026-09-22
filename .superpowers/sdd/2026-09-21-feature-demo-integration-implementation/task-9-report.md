# Task 9 Report: Final Regression and Delivery Audit

## Status

**PARTIAL / DEVICE ACCEPTANCE NOT COMPLETE.** Local regression and static gates pass, audit defects were fixed with RED/GREEN evidence, and the unified software was incrementally staged on `192.168.11.106`. Full signed hardware acceptance did not run to completion because the required `/dev/video41` disappeared after a real USB disconnect/re-enumeration and the camera returned as `/dev/video42` and `/dev/video43`. No acceptance marker was written. `--retire-legacy` was not run. `robot-arm.service` is restored to `enabled` and `active`, and the original 14 desktop entries remain unchanged.

## Local Regression Evidence

All commands used `G:\codex\.venv\Scripts\python.exe` from `G:\codex\_aibox-github`.

| Command | Result |
| --- | --- |
| `python -m pytest 子项目\功能演示\代码\tests -q` | `99 passed, 2 dependency deprecation warnings` |
| `python -m pytest 子项目\共享模块与资源\代码\tests -q` | `2 passed` (first collection was blocked by missing local `pyserial`; installed `pyserial 3.5`, then passed) |
| `python -m pytest 子项目\语音简单控制机械臂\代码\tests -q` | `5 passed` |
| `python -m pytest 子项目\手掌追踪\测试 -q` | `21 passed` |
| `python -m pytest 子项目\手掌识别\代码\tests -q` | `12 passed` |
| `python -m pytest 子项目\水果识别\代码\tests -q` | `2 passed` |
| `python -m pytest 子项目\形状识别\代码\tests -q` | `3 passed` |
| `python -m compileall -q 子项目\功能演示\代码` | exit `0` |
| `node --check 子项目\功能演示\代码\feature_demo\web\app.js` | exit `0` |
| `bash -n` on launcher, installer, verifier, hardware hook, and signer | exit `0` |
| `git diff --check` | exit `0`; only Git line-ending notices |

Initial RED evidence found one palm-tracking desktop localization failure and four palm-recognition label failures. Later board-driven RED cases covered complete rollback archives, safe Bash local initialization, the three specified high-risk sequences, a real hardware hook and board-local signer, actual C1 microphone ownership, the `voice_input_test` runtime ID, preserved startup errors, and a bounded window-close cleanup wait.

## Audit Fixes

- Restored Chinese palm/gesture UI labels and the `手掌追踪` legacy desktop label without changing recognition thresholds or algorithms.
- Installer now creates and verifies complete archives of `/root/robot_arm`, `/home/ztl/Desktop`, `/usr/local/bin`, and `/etc/systemd/system` before its first deployment write.
- Added a real API/device/frame/window acceptance hook and a root-only, random-key HMAC-SHA256 signer. The signer was verified on-board with stable signatures for equal payloads and different signatures for different payloads; key permissions are `0600` under a `0700` directory.
- Corrected the first high-risk sequence to `voice_robot_arm -> fruit_recognition`.
- Corrected the clean-boot microphone owner path to `/dev/snd/pcmC1D0c` consistently in runtime verification and deployment checks.
- Corrected the `voice_input_test` registry worker ID and preserved the original startup exception before cleanup events.

## Backup and Deployment

Primary verified rollback directory: `/root/feature-demo-backups/20260921_203346`

| Archive | SHA-256 |
| --- | --- |
| `robot_arm.tar.gz` | `3aaa7fe479e57ca1e6e80bd2f164cc6e1e2702541458d29a0139125277603451` |
| `desktop.tar.gz` | `9dac6057a28501afacb2a9bd2107df8181b7ea50a3044d468a772d0b406713f8` |
| `launchers.tar.gz` | `f2fd1942572abd4a01c0fffd1a3e49fcdc11f20663a70838404075f65a6e1698` |
| `systemd.tar.gz` | `533386b338167bef419ed0f13630c9a084f3c1000e5e4f528179b808a34aed19` |

Every archive passed `tar -tzf`. The successful hardened installer also created `/root/feature-demo-backups/20260921_204922`. The incremental deployment preserved the existing robot-arm tree/models/assets, installed the unified package and staged desktop entry, and left `feature-demo.service` disabled/inactive. Rollback is to extract the four primary archives at `/`, run `systemctl daemon-reload`, and start `robot-arm.service`.

## Device Evidence and Acceptance Checklist

- [x] Clean boot performed; locale remained `zh_CN.UTF-8`.
- [x] API registry returned the exact 13 module IDs.
- [x] One visible PyWebView window titled `功能演示` was observed with `xdotool`.
- [x] With legacy service temporarily stopped, homepage held no camera, actual microphone, robot, or gimbal device.
- [x] Local manager tests cover mutual exclusion, idempotency, and verified cleanup.
- [x] Registry/frontend contracts expose four directional gimbal commands and no center command; a real `gimbal_left` API command returned HTTP 200.
- [x] Chinese UI/voice contracts and all affected legacy algorithm suites pass.
- [x] Automated frontend contracts cover `1366x768`, `1600x900`, and `1920x1080`.
- [ ] All 13 physical module lifecycles: not completed.
- [ ] Three high-risk physical sequences: corrected in verifier but not completed.
- [ ] Twenty physical switches with owner checks after every stop: not completed.
- [ ] Signed active-window-close acceptance: a real `robot_button` worker owned `/dev/esp32_arm`, the real window closed, the application exited, and owners eventually cleared; the hook's original 10-second wait timed out, so no signed pass was recorded. The wait is now 20 seconds for the next run.
- [ ] Unique Chinese desktop entry: intentionally not activated because full signed acceptance failed. The staged entry exists at `/usr/local/share/feature-demo/功能演示.desktop`.

## Device Blockers and Logs

1. Camera: after initially producing a running visual worker, `/dev/video41` disappeared. Kernel log recorded `USB disconnect` and `uvcvideo ... Failed to resubmit video URB (-19)`; the DECXIN camera re-enumerated as `/dev/video42` and `/dev/video43`. The fixed worker reports `无法打开摄像头 /dev/video41。` and cleans up. This blocks visual lifecycles, high-risk sequences, and 20-switch acceptance.
2. Voice: clean boot enumerated the XFM-DP-V0.0.18 capture device as card 1, not card 5. The corrected worker selected `dsnoop:CARD=XFMDPV0018,DEV=0` and loaded the Chinese Vosk model, but did not reach ready within the bounded 12-second probe; it was terminated and left no microphone owner.
3. Package management: `xdotool` and `libxdo3` are installed, but their apt transaction exposed an existing boot configuration inconsistency. `dpkg --audit` reports `initramfs-tools` incompletely configured and a pending `flash-kernel` trigger. `/var/log/apt/term.log` shows generation of `/boot/initrd.img-5.15.0-1105-raspi`, `Warning: root device does not exist`, and `Unsupported platform 'ztl, A588'`, while the running kernel is `6.1.118`. No further apt/dpkg mutation was attempted and the board was not rebooted again.
4. Final safety state: `robot-arm.service` is `enabled/active` (PID `637870` at final check) and again owns `/dev/esp32_arm`; `feature-demo.service` remains disabled/inactive; all 14 original desktop entries remain present.

Because the device acceptance checklist is incomplete, legacy retirement is gated off and no claim of final product acceptance is made.

## Fix Round 1

### RED/GREEN Evidence

The initial focused RED command covered `test_worker_process.py`, `test_worker_entry.py`, and the three deployment regressions for JSON payloads, resource release, and sequence cleanup. It failed as expected with `7 failed, 4 passed`: the startup error was overwritten by `stopped`, `WorkerProcess` had no command timeout/correlation, runtime replies lacked request IDs, the shell payload gained an extra `}`, idle resources returned failure, and a failed verification skipped module stop.

Additional tests were added before implementation for mismatched and correlated error replies, command timeout, API `ok:false`, and nursery-rhyme speaker ownership. The expanded RED run failed with `11 failed, 4 passed` for those missing behaviors. After implementation, the focused three-file suite passed with `29 passed`.

The full feature-demo suite passed with `110 passed` and two dependency deprecation warnings. Affected legacy suites also passed: shared resources `2`, voice robot arm `5`, palm tracking `21`, palm recognition `12`, fruit recognition `2`, and shape recognition `3` tests. `compileall`, JavaScript syntax, all five shell syntax checks, and `git diff --check` exited `0`; Git emitted only line-ending notices.

### Fixes and Deployment

- `WorkerProcess` now assigns a unique request ID, waits up to a bounded command timeout for the matching worker reply, ignores unrelated replies, returns the physical result, and raises for correlated errors or `ok:false`. Stop requests are written directly and do not wait for a command result.
- Startup state is one-shot: the first `ready` or startup `error` is retained separately from the live snapshot, so a subsequent cleanup `stopped` event cannot hide the original failure.
- Worker runtime command results and errors echo the incoming request ID.
- The hardware hook preserves explicit JSON payloads, requires API command responses with `ok` exactly `true`, returns success explicitly when resources are released, includes the playback device in release checks, and waits for speaker ownership after nursery-rhyme playback starts.
- Each started high-risk-sequence module runs under an EXIT cleanup guard. Verification, command, frame, stop, or release failure triggers a stop request and a bounded release check before the failure propagates.

Only the three changed production files were incrementally deployed: `/root/robot_arm/feature_demo/worker.py`, `/root/robot_arm/feature_demo/workers/runtime.py`, and `/usr/local/bin/feature_demo_hardware_acceptance.sh`. Board and local SHA-256 values matched for all three. No apt/dpkg mutation, reboot, full acceptance, or legacy retirement was performed.

### Final Device Safety State

- `robot-arm.service`: `enabled` / `active`
- `feature-demo.service`: `disabled` / `inactive`
- Legacy desktop entries: `14`, unchanged
- `/var/lib/feature-demo/full-acceptance.marker`: absent

The external camera blocker remains: `/dev/video41` is absent and the camera is enumerated as `/dev/video42` and `/dev/video43`. The existing package-management blocker also remains: `initramfs-tools` is incompletely configured and the `flash-kernel` trigger is pending. No corrective package action was attempted.

## Fix Round 2

The review identified a Bash context bug: because `verify_running_module` and `run_sequence_step` were used on the left side of `||`, callers could disable inherited `errexit`. Later successful commands then masked failed frame, gimbal, or speaker checks.

A parameterized behavioral test was added first for `fruit_recognition` frame failure, `face_detection` gimbal-command failure, and `nursery_rhyme` speaker-owner failure. All three RED cases failed because the sequence returned success, while their traces confirmed a stop request still occurred. The first minimal propagation change exposed the outer `run_sequence` masking boundary; adding explicit propagation there completed the fix.

Every critical state, frame, command, and device-owner check in `verify_running_module` now returns immediately on failure, and successful completion returns explicitly. `run_sequence` also returns when a module step fails, independent of caller `set -e` state. The focused regression passed `3`, the complete deployment file passed `22`, and the full unified suite passed `113` with the same two dependency deprecation warnings. `bash -n` and `git diff --check` exited `0`.

Only `/usr/local/bin/feature_demo_hardware_acceptance.sh` was incrementally deployed; its local and board SHA-256 values matched. No full acceptance, reboot, package operation, or legacy retirement was run. Final board state remained `robot-arm.service` enabled/active, `feature-demo.service` disabled/inactive, 14 legacy desktop entries, and no full-acceptance marker. The camera and dpkg blockers documented above remain unchanged.

## Final Stabilization Round

All fifteen final review findings were closed without changing the approved fruit or shape recognition behavior:

1. Registry worker IDs now round-trip through the runtime factory.
2. Non-robot voice workers explicitly disable command grammar; robot voice retains its commands.
3. Object sorting emits one composite readiness event only after both components start.
4. Ordinary commands are serialized while stop and interrupt commands remain preemptive.
5. Unexpected worker death is reconciled with stop and release verification before another start.
6. The singleton lock uses an OS-owned nonblocking descriptor lock and keeps the lock file.
7. Worker cleanup retains the process-group ID and terminates surviving descendants after leader exit.
8. Device probing is tri-state; missing probe evidence is unverified and blocks cleanup.
9. Palm tracking and manual gimbal writes share a lock and tracking generation.
10. Every visual module renders its non-gimbal primary actions.
11. Snapshot saving downloads the displayed JPEG locally without issuing a worker command.
12. Pending ordinary requests leave preemptive controls enabled.
13. Voice configuration is installed into `/etc/default/feature-demo` and loaded by service and direct launches.
14. Hardware hooks receive the configured API URL, trust correlated gimbal ACKs, and require primary-behavior evidence plus verified window-close state.
15. Acceptance markers bind verifier, deterministic application package, hook, board identity, and results hashes; deployment invalidates old markers.

### RED/GREEN Evidence

- Tasks 1-2 focused RED cases covered registry/runtime identity, explicit voice grammar, composite readiness, concurrent control, dead-worker reconciliation, and frontend preemptive state. Their focused suites passed after the minimal implementation.
- Task 3 focused RED was `6 failed, 23 passed`: persistent file-lock behavior, saved process-group cleanup, both `fuser` failure modes, unverified release, and tracking/manual interleaving. GREEN was `29 passed`.
- Task 4 focused RED was `2 failed, 12 passed`: the visual action region and local snapshot implementation were absent. GREEN was `14 passed`, and `node --check` exited `0`.
- Task 5 focused RED was `6 failed, 25 passed`: voice configuration deployment/loading, regular-hook API inheritance, ACK-only gimbal verification, failed window start, missing primary evidence, and stale application hashes. GREEN was `31 passed`.

The consolidated local verification passed: the unified feature-demo suite reported `139 passed`; affected legacy suites reported shared resources `2`, voice robot arm `5`, palm tracking `21`, palm recognition `12`, fruit recognition `2`, and shape recognition `3`. `compileall`, Node syntax, all five shell syntax checks, and `git diff --check` exited `0`.

No board package operation, reboot, full acceptance, or retirement was performed. Incremental deployment was limited to 18 changed production and configuration artifacts; every local/deployed SHA-256 pair matched. The pre-deployment copies are under `/root/feature-demo-backups/final-stabilization-20260922_030334`. The final read-only board audit retained `robot-arm.service` enabled/active, `feature-demo.service` disabled/inactive, all 14 legacy desktop entries, and no acceptance marker. `/dev/video41` remains absent while `/dev/video42` and `/dev/video43` are present; `dpkg --audit` still reports incomplete `initramfs-tools` configuration and a pending `flash-kernel` trigger.

## Residual Load-Bearing Fix Round

The four scoped residual findings were reproduced before implementation. The first combined RED run reported `23 failed, 66 passed`: a synchronous sequence held the adapter mutex against emergency stop, the sorting vision component leaked a second `ready`, process-group enumeration failure was treated as empty, and the behavior-evidence matcher/verifier did not exist. Two additional focused RED tests proved that worker snapshots lacked correlatable event history and automatic tracking exposed no acknowledged-motion evidence. The real runtime -> RobotWorker -> RobotAdapter regression now verifies a concurrent `stop_motion` result returns while a blocked sequence exits.

The robot adapter now calls the legacy cancellation path without waiting for the ordinary action mutex; the legacy serial driver remains the serialization boundary for the emergency serial write. Object sorting routes both component sinks through the ready filter and emits one composite `ready` only after robot and camera startup succeed. Worker snapshots retain a bounded sequence-numbered event history without JPEG bytes. The hardware hook uses a pre-action sequence boundary and waits for fresh, module-specific evidence for all 13 modules: assistant reply, speech result, playback start, robot action, sorting result, tracking motion, or non-empty recognition result. Physical robot, sorting, tracking, and audible playback outcomes additionally require an explicit interactive operator confirmation. The verifier rejects unknown modules, label-only evidence, wrong behavior/source, absent or invalid correlation, and missing required operator evidence.

Process-group enumeration now returns unknown separately from empty. On `ps` failure after leader death, cleanup directly attempts TERM/KILL against the retained PGID, retains ownership state, raises an unverifiable-cleanup error, and causes resource verification to fail closed rather than clearing the manager lock.

### Verification

| Command | Result |
| --- | --- |
| Focused robot/runtime/process/evidence suites | `59 passed` for Python concurrency/resource files and `59 passed` for deployment behavior |
| `python -m pytest 子项目\功能演示\代码\tests -q` | `175 passed`, 2 dependency deprecation warnings |
| Shared resources / voice robot / palm tracking / palm recognition / fruit / shape legacy suites | `2 / 5 / 21 / 12 / 2 / 3 passed` |
| `python -m compileall -q 子项目\功能演示\代码` | exit `0` |
| `node --check 子项目\功能演示\代码\feature_demo\web\app.js` | exit `0` |
| `bash -n` on launcher, installer, verifier, hardware hook, and signer | exit `0` |
| `git diff --check` | exit `0`; only line-ending notices |

The pre-deployment board audit still showed `robot-arm.service` enabled/active, `feature-demo.service` disabled/inactive, 14 legacy desktop entries, no acceptance marker, `/dev/video41` absent, and `/dev/video42` plus `/dev/video43` present. No package operation, reboot, full acceptance, desktop retirement, or service cutover is authorized while that camera blocker remains.

## Final Residual Deployment

The final emergency-stop token propagation and plate-evidence fixes were independently reviewed with no remaining Critical or Important findings. Before deployment, the current board copies were backed up to `/root/feature-demo-backups/final-residual-20260922_150929`. The updated legacy `robot.py` and hardware acceptance hook were installed incrementally; their board SHA-256 values matched the local files (`5813771e...f24b` and `31cef2b9...c4d7`). The final safety audit still showed the legacy service enabled/active, the unified service disabled/inactive, 14 legacy desktop entries, and no acceptance marker. `/dev/video41` remains absent while `/dev/video42` and `/dev/video43` remain present, so no full hardware acceptance or legacy retirement was attempted.

## Stable Camera and Final Board Lifecycle Verification

The camera integration now resolves the stable capture-capable udev link `/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0`, while retaining `/dev/video41` as a compatibility fallback and rejecting metadata-only video nodes by V4L2 capability rather than device number. The camera changes were reviewed with no remaining Critical or Important findings and deployed after backup to `/root/feature-demo-backups/camera-stable-20260922_155647`.

On the board, the unified PyWebView window opened with the Chinese title `功能演示`; the homepage held no camera, microphone, robot, or gimbal device. All 13 registered modules completed a real start/stop lifecycle. The two ASR-heavy modules initially exceeded the 15-second generic startup limit; the reviewed per-module 60-second bound fixed this, and `voice_input_test` and `nursery_rhyme` subsequently reached `running` in 13.0 and 12.7 seconds and stopped with zero busy resources. A 20-switch mixed sequence covering voice, visual, assistant, nursery, robot, sorting, and tracking modules passed; every start returned `running`, every stop returned `idle`, and every post-stop camera/microphone/robot/gimbal owner check was empty. Closing the real window while `robot_button` was active terminated the application and released `/dev/esp32_arm`.

The final lifecycle evidence does not replace the explicit operator evidence required for physical sorting, audible playback, voice-command motion, and automatic hand tracking. Therefore no signed acceptance marker was created and no legacy retirement was performed. The board was restored to the safe state: legacy service enabled/active, unified service disabled/inactive, 14 legacy desktop entries, and no acceptance marker.

Fresh final verification on 2026-09-22 passed the unified suite (`201 passed`) and all affected legacy suites (shared resources `12`, voice robot arm `5`, palm tracking `21`, palm recognition `12`, fruit recognition `2`, shape recognition `3`). Python compilation, JavaScript syntax, all five Bash syntax checks, and `git diff --check` also passed. A read-only board audit confirmed `robot-arm.service` enabled/active, `feature-demo.service` disabled/inactive, 14 legacy entries on the active `ztl` desktop, and no acceptance marker.

### Residual Review Fix Round 2

The scoped re-review found two remaining important gaps. RED used the real shared `RobotArm`: stopping while `set_all_servos` was paused between servo writes returned success and allowed later servo commands after `$DST!` (`1 failed`). The plate evidence RED proved a color-only candidate with an empty `plate` field incorrectly passed while nonempty plate text also passed (`1 failed, 1 passed`).

`RobotArm` now assigns a cancellation generation to motion writes. Each serial motion write validates that generation while holding a robot-level write lock; emergency stop increments the generation and sends `$DST!` under the same lock. Consequently a write already in progress precedes the emergency stop, while every remaining write from the cancelled multi-servo call is rejected. Action definitions, PWM limits, timing values, and serial command formats are unchanged. Plate acceptance now requests the `plate_text` evidence subtype and accepts only a fresh frame containing at least one nonblank recognized `plate` field; color-only candidates are rejected.

Focused GREEN was `1 passed` for the real robot cancellation regression and `2 passed` for plate evidence. The fresh unified suite passed `177` tests with two dependency deprecation warnings. Affected legacy suites passed shared resources `3`, voice robot arm `5`, palm tracking `21`, palm recognition `12`, fruit `2`, and shape `3`. Compileall for both unified and shared code, Node syntax, all five Bash syntax checks, and `git diff --check` exited `0`.

This round is local-only pending scoped review. It has not been deployed. The earlier `4c91b8e` nine-file deployment occurred before this second review request, from backup `/root/feature-demo-backups/residual-fix-20260922_141644`; all nine deployed hashes matched local at that commit.

### Residual Review Fix Round 3

The final scoped review exposed a boundary race not covered by the inter-servo test: a high-level sequence or sorting action could pass its movement check, then stop could advance the generation before the nested low-level method began. Because the nested method captured a new post-stop generation, it could start a fresh servo batch after `$DST!`. Two real `RobotArm` RED cases paused in exactly that gap; both emitted motion after emergency stop (`2 failed, 1 passed`).

Each public robot action now captures one cancellation generation at entry and passes it through every nested `set_servo`, `set_all_servos`, and grouped sorting-stage write. Low-level methods retain compatible public defaults and capture their own generation only for direct callers. The joint-rotation loop also validates one captured generation for each repeated write. Thus an action begun before stop cannot adopt the post-stop generation, while a genuinely new action invoked after stop remains valid. Action definitions, PWM limits, timing, and serial protocol are unchanged.

Focused GREEN was `3 passed`. The fresh unified suite passed `177` tests with two dependency deprecation warnings. Affected legacy suites passed shared resources `5`, voice robot arm `5`, palm tracking `21`, palm recognition `12`, fruit `2`, and shape `3`. Compileall for unified and shared code, Node syntax, all five Bash syntax checks, and `git diff --check` exited `0`. This round remains local-only pending review and has not been deployed.

### Residual Review Fix Round 4

The final direct-call audit found the same generation-adoption window inside `set_servo` and `set_all_servos`: each checked the critical-action guard before capturing its default generation. Two deterministic RED cases paused on that guard, stopped the robot, and then observed a post-stop motion write (`2 failed, 3 passed`). Generation selection now occurs before the guard, while explicitly propagated action tokens remain unchanged. A separate compatibility case confirms that a genuinely new direct action after stop uses the current generation and remains valid.

Review then identified a related state-integrity gap. Generation-stale single, batch, grouped, centered, and repeated joint actions were blocked at the serial boundary but had already changed in-memory or persisted PWM targets; a later hold could therefore replay a cancelled target. The state RED was `5 failed, 3 passed`. Servo state and persistence now commit only after a generation-valid send, `all_center` no longer prewrites its target, repeated joint state commits only after validation, and emergency stop clears active rotation flags. Serial failure return behavior, accepted-command state tracking, PWM limits, action timing, and wire formats remain unchanged.

A subsequent ordering RED reproduced `old send -> stop -> valid new action -> old state commit`: the pre-stop action overwrote the newer action's PWM state after stop (`1 failed, 8 passed`). Generation validation, serial send, and in-memory state commit now share the motion-write lock, so a later generation always wins. The final latency RED delayed PWM persistence and proved that filesystem I/O could hold the motion lock and block `$DST!` (`1 failed, 9 passed`). Persistence now runs after releasing the motion lock and uses a separate persistence lock, preserving file-write order without delaying emergency stop.

Final focused GREEN was `10 passed`. The fresh unified suite passed `177` tests with two dependency deprecation warnings. Affected legacy suites passed shared resources `12`, voice robot arm `5`, palm tracking `21`, palm recognition `12`, fruit `2`, and shape `3`. Compileall for unified and shared code, Node syntax, all five Bash syntax checks, and `git diff --check` exited `0`; Git reported only line-ending notices. This round remains local-only and has not been deployed.
