# 语音简单控制机械臂 - Project Context

更新时间：2026-08-30

## 1. 项目名称

语音简单控制机械臂

## 2. 项目位置

G:\codexwork\人工智能实验箱\子项目\语音简单控制机械臂

## 3. 项目目的

通过麦克风识别中文指令并控制机械臂执行直立、放平、抓取、搬运、张开、闭合等动作。

## 4. 当前入口文件

代码/voice_control_app.py；代码/frontend/voice.html；启动脚本/voice_control.sh

## 5. 使用技术栈

Python, FastAPI, ALSA, Sherpa-ONNX/Vosk/whisper.cpp, speech_context, 机械臂串口

## 6. 当前完成状态

可用但需持续优化识别准度、短词完整性和响应速度。

## 7. 已知 bug / 待优化点

短指令可能丢字；搬运等词需要模糊词；嘈杂环境影响识别。

## 8. 依赖关系

共享：voice_engine.py, speech_context.py, audio_config.py, robot.py, serial_driver.py, config.py。硬件：M260C 麦克风、机械臂。

## 9. 维护规则

- 修改本软件前先读本文件。
- 代码目录保存从 RK3588 最新运行环境拉取的业务文件副本。
- 启动脚本目录保存 /usr/local/bin 中对应脚本。
- 桌面入口目录保存 /home/ztl/Desktop 中对应 .desktop 文件。
- 公共模块优先查看 子项目/共享模块与资源。
- 涉及硬件的软件，测试前先确认对应麦克风、声卡、摄像头、串口或机械臂已连接。
