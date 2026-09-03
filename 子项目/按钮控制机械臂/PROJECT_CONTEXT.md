# 按钮控制机械臂 - Project Context

更新时间：2026-08-30

## 1. 项目名称

按钮控制机械臂

## 2. 项目位置

G:\codexwork\人工智能实验箱\子项目\按钮控制机械臂

## 3. 项目目的

通过按钮和前端页面控制机械臂各舵机、夹爪、预设姿态和动作序列。

## 4. 当前入口文件

代码/button_control_app.py；代码/frontend/button.html；启动脚本/button_control.sh

## 5. 使用技术栈

Python, FastAPI, HTML, 串口, 机械臂舵机 PWM

## 6. 当前完成状态

可用，仍需注意舵机限位和卡墙保护。

## 7. 已知 bug / 待优化点

机械臂碰到边界时可能卡住；后续需继续完善安全限位和教学模式保护。

## 8. 依赖关系

共享：robot.py, serial_driver.py, config.py, stages.json, last_servo_pwms.json。硬件：机械臂控制板。

## 9. 维护规则

- 修改本软件前先读本文件。
- 代码目录保存从 RK3588 最新运行环境拉取的业务文件副本。
- 启动脚本目录保存 /usr/local/bin 中对应脚本。
- 桌面入口目录保存 /home/ztl/Desktop 中对应 .desktop 文件。
- 公共模块优先查看 子项目/共享模块与资源。
- 涉及硬件的软件，测试前先确认对应麦克风、声卡、摄像头、串口或机械臂已连接。
