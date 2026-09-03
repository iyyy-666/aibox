# RK3588 语音识别 + 机械臂

更新时间：2026-09-01

## 作用

这是当前主运行快照。它记录 RK3588 上正在用的语音、机械臂、视觉和桌面入口的总览。

## 读法

只看这份文件拿总览；要细节时，再去读对应子项目的文档和快照目录。

## 快照位置

- `latest_from_3588/ai_box_latest_business_code.tar.gz`
- `latest_from_3588/extracted/`
- `latest_from_3588/model_manifest.txt`
- `latest_from_3588/asset_manifest.txt`

## 当前重点模块

- `voice_engine.py`
- `speech_context.py`
- `audio_config.py`
- `server.py`
- `ai_assistant.py`
- `robot.py`
- `serial_driver.py`
- `vision_targeting.py`

## 当前重点问题

- 语音识别完整度
- 音频输入/输出稳定性
- 机械臂串口和舵机安全
- 视觉误检
- 云台串口链路

## 规则

- 修改语音时先看 `voice_engine.py` 和 `audio_config.py`。
- 修改机械臂时注意串口、PWM、卡墙和回位。
- 修改视觉时避免后台继续占用摄像头。
- 修改公共模块时，先确认影响范围。
