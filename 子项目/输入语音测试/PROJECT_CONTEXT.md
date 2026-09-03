# 输入语音测试 - Project Context

更新时间：2026-08-30

## 1. 项目名称

输入语音测试

## 2. 项目位置

G:\codexwork\人工智能实验箱\子项目\输入语音测试

## 3. 项目目的

独立显示语音识别 RAW/NORMALIZED 结果，用来诊断麦克风到 ASR 的文本一致性。

## 4. 当前入口文件

代码/input_voice_test_app.py；启动脚本/input_voice_test.sh

## 5. 使用技术栈

Python, Tkinter, ALSA, ASR

## 6. 当前完成状态

可用，是排查语音识别问题的优先工具。

## 7. 已知 bug / 待优化点

若 RAW 很不准，应先检查麦克风/ALSA/WAV 质量，不要先硬改词库。

## 8. 依赖关系

共享：voice_engine.py, speech_context.py, audio_config.py。硬件：M260C 麦克风。

## 9. 维护规则

- 修改本软件前先读本文件。
- 代码目录保存从 RK3588 最新运行环境拉取的业务文件副本。
- 启动脚本目录保存 /usr/local/bin 中对应脚本。
- 桌面入口目录保存 /home/ztl/Desktop 中对应 .desktop 文件。
- 公共模块优先查看 子项目/共享模块与资源。
- 涉及硬件的软件，测试前先确认对应麦克风、声卡、摄像头、串口或机械臂已连接。
