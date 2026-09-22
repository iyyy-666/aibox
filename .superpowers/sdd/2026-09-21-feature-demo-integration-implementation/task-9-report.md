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
