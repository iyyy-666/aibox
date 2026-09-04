# 手掌追踪 - Project Context

更新时间：2026-09-04

## 1. 项目名称

手掌追踪

## 2. 项目位置

G:\codexwork\人工智能实验箱\子项目\手掌追踪

## 3. 项目目的

在 RK3588 双目摄像头画面中锁定一个手掌，通过小幅 PWM 闭环控制二维云台，使该手掌框保持在摄像头画面中心附近。

## 4. 计划入口文件

代码/palm_tracking_app.py；启动脚本/palm_tracking.sh；桌面入口/palm_tracking.desktop。

## 5. 使用技术栈

Python、Tkinter、OpenCV、MediaPipe、串口、STM32 舵机 PWM。

## 6. 当前完成状态

已完成编码、16 项本地自动化测试和无运动板端部署验证；等待现场轴向校准和实体追踪验收。

## 7. 已知约束 / 待验证项

- 摄像头为 `/dev/video41`，双目输入为 1280x480 MJPG，软件使用左目 640x480 画面。
- 云台控制板为 `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5C67040336-if00`；水平舵机 ID 1，俯仰舵机 ID 2。
- 云台通信需要 ACK，PWM 安全范围为 500-2500。
- 最大追踪速度约 20 度/秒；需在实物前执行小幅轴向校验，确认两个轴的方向与 PWM/角度比例。

## 8. 依赖关系

- 复用“手掌识别（双目）”的 `hand_landmarks.py` 和 `vision_targeting.py`。
- 云台通信与参数沿用“云台控制”的 `/usr/local/bin/gimbal_control.sh` 与 `gimbal_control_app.py` 已验证路径。
- 硬件：双目摄像头、二维云台、USB 串口 STM32 控制板。

## 9. 维护规则

- 修改本软件前先读本文件、`设计文档/2026-09-04-rk3588-palm-tracking-design.md` 和 `设计文档/2026-09-04-rk3588-palm-tracking-implementation-plan.md`。
- 代码目录保存从 RK3588 最新运行环境拉取的业务文件副本。
- 启动脚本目录保存 `/usr/local/bin` 中对应脚本。
- 桌面入口目录保存 `/home/ztl/Desktop` 中对应 `.desktop` 文件。
- 涉及云台的测试必须先确认周围无障碍物，并从小步进、低速度开始验证。
- 无运动板端验证记录见 `测试/board_validation_2026-09-04.md`。
