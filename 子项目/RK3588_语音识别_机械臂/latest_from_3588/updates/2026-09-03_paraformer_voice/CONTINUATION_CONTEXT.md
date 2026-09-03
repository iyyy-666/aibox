# 2026-09-03 Voice Update

## Current State

- RK3588 device: `192.168.11.109`, root access is configured in the deployment scripts.
- Paraformer quantized ONNX model is installed on the device at `/root/sherpa_models/paraformer-large-int8`.
- `voice_engine.py` uses `paraformer` by default and supports the `funasr-onnx` runtime.
- The robot server systemd override is `/etc/systemd/system/robot-arm.service.d/voice.conf`.
- The voice control server must be restarted after Python or systemd changes.

## Latest Behavior

- Voice control and AI assistant use Paraformer quantized ONNX.
- Robot actions keep only the newest command while an action is running.
- After motion ends, the newest pending command runs.
- When idle for 20 seconds, the robot returns to `直立`.
- Command extraction supports sentences and common ASR errors, including single-character errors for all registered actions.
- Voice commands `停止` and `复位` were removed from the robot voice command table.
- The `抓取位` button is hidden from the button-control frontend.

## Verification

- Remote Python compile passed.
- Remote voice regression tests passed: `16/16`.
- `/api/voice/start` returned success with backend `paraformer` after fixing the systemd environment override.

## Important Files

- `robot_arm/voice_engine.py`
- `robot_arm/server.py`
- `robot_arm/config.py`
- `robot_arm/test_voice_tuning.py`
- `frontend/index.html`
- `frontend/button.html`
- `frontend/voice.html`
- `systemd/voice.conf`
- `_deploy_voice_patch/`

## Next Session Checklist

1. Read this file and the parent `PROJECT_CONTEXT.md`.
2. Check `/tmp/robot_server.log` and `/tmp/robot_voice_timing.log` on the device before changing behavior.
3. Confirm `systemctl status robot-arm.service` and `/api/status` before testing.
4. Do not overwrite older `latest_from_3588` snapshots; create a dated update directory.
