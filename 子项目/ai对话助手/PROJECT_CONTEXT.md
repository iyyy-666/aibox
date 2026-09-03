# ai对话助手 - Project Context

更新时间：2026-08-30

## 1. 项目名称

ai对话助手

## 2. 项目位置

G:\codexwork\人工智能实验箱\子项目\ai对话助手

## 3. 项目目的

提供中文语音对话，用户按开始听后说话，停止监听后由本地/配置的大模型回复并播报。

## 4. 当前入口文件

代码/ai_assistant.py；启动脚本/ai_assistant.sh

## 5. 使用技术栈

Python, Tkinter, ASR, LLM, TTS, ALSA

## 6. 当前完成状态

可用但仍需优化输出声音稳定性、对话流畅度和识别准度。

## 7. 已知 bug / 待优化点

历史上出现过闪退、声卡无声、TTS 吞字；需要保持输入输出独立配置。

## 8. 依赖关系

共享：voice_engine.py, audio_playback.py, audio_config.py, speech_context.py。硬件：麦克风、声卡、扬声器。

## 9. 维护规则

- 修改本软件前先读本文件。
- 代码目录保存从 RK3588 最新运行环境拉取的业务文件副本。
- 启动脚本目录保存 /usr/local/bin 中对应脚本。
- 桌面入口目录保存 /home/ztl/Desktop 中对应 .desktop 文件。
- 公共模块优先查看 子项目/共享模块与资源。
- 涉及硬件的软件，测试前先确认对应麦克风、声卡、摄像头、串口或机械臂已连接。
