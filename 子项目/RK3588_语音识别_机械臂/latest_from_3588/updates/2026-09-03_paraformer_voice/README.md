# Paraformer Voice Update Archive

日期：2026-09-03

这是本次语音模型和机械臂语音行为的可恢复归档，不覆盖旧的 `latest_from_3588` 快照。

## 内容

- `_deploy_voice_patch/`：原始部署补丁目录，按原名保留。
- `files_robot_arm/`：本次更新的机械臂 Python 文件。
- `files_frontend/`：本次更新的前端页面文件。
- `systemd/voice.conf`：Paraformer systemd 覆盖配置。
- `CONTINUATION_CONTEXT.md`：下次继续工作时优先读取的上下文。
- `deploy_voice_tuning.py`：已有部署脚本备份。

## 恢复映射

- `files_robot_arm/voice_engine.py` -> `extracted/root/robot_arm/voice_engine.py`
- `files_robot_arm/server.py` -> `extracted/root/robot_arm/server.py`
- `files_robot_arm/config.py` -> `extracted/root/robot_arm/config.py`
- `files_robot_arm/test_voice_tuning.py` -> `extracted/root/robot_arm/test_voice_tuning.py`
- `files_frontend/*.html` -> `extracted/root/robot_arm/frontend/*.html`
- `systemd/voice.conf` -> `/etc/systemd/system/robot-arm.service.d/voice.conf`

恢复或继续前，先读取 `CONTINUATION_CONTEXT.md`、父级 `PROJECT_CONTEXT.md` 和机械臂子项目 `PROJECT_CONTEXT.md`。
