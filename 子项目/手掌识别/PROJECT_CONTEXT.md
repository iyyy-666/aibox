# 手掌识别（双目） - Project Context

更新时间：2026-09-04

## 1. 项目名称

手掌识别（双目）

## 2. 项目位置

G:\codexwork\人工智能实验箱\子项目\手掌识别（双目）

## 3. 项目目的

在双目合成画面中稳定框出手掌，并识别石头、剪刀、布。

## 4. 当前入口文件

代码/palm_recognition_app.py；启动脚本/palm_recognition.sh

## 5. 使用技术栈

Python, Tkinter, OpenCV, MediaPipe Hands 21 点关键点，双目候选校验与时序投票。

## 6. 当前完成状态

MediaPipe Hands 优先检测；右目候选校验与连续 4 帧投票确认石头、剪刀、布。MediaPipe 不可用时保留 OpenCV 轮廓兜底；候选手掌始终显示，避免把“未确定”误报为未检测到手掌。

## 7. 已知 bug / 待优化点

首版只稳定跟踪一个主手掌；首次部署需要安装 `mediapipe==0.10.18`，启动脚本已显式配置其 Python 依赖路径。

## 8. 依赖关系

共享：vision_targeting.py。手势模块：hand_landmarks.py。依赖：mediapipe==0.10.18。硬件：双目摄像头 `/dev/video41`。

## 9. 维护规则

- 修改本软件前先读本文件。
- 代码目录保存从 RK3588 最新运行环境拉取的业务文件副本。
- 启动脚本目录保存 /usr/local/bin 中对应脚本。
- 桌面入口目录保存 /home/ztl/Desktop 中对应 .desktop 文件。
- 公共模块优先查看 子项目/共享模块与资源。
- 涉及硬件的软件，测试前先确认对应麦克风、声卡、摄像头、串口或机械臂已连接。
