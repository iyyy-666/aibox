# 人脸识别（双目） - Project Context

更新时间：2026-08-30

## 1. 项目名称

人脸识别（双目）

## 2. 项目位置

G:\codexwork\人工智能实验箱\子项目\人脸识别（双目）

## 3. 项目目的

在双目合成画面中框出人脸。

## 4. 当前入口文件

代码/face_recognition_app.py；启动脚本/face_recognition.sh

## 5. 使用技术栈

Python, Tkinter, OpenCV DNN/YuNet

## 6. 当前完成状态

可用，精度已调过但仍可继续优化。

## 7. 已知 bug / 待优化点

光照和距离会影响人脸框稳定性。

## 8. 依赖关系

共享：vision_targeting.py。模型见 model_manifest.txt。硬件：双目摄像头。

## 9. 维护规则

- 修改本软件前先读本文件。
- 代码目录保存从 RK3588 最新运行环境拉取的业务文件副本。
- 启动脚本目录保存 /usr/local/bin 中对应脚本。
- 桌面入口目录保存 /home/ztl/Desktop 中对应 .desktop 文件。
- 公共模块优先查看 子项目/共享模块与资源。
- 涉及硬件的软件，测试前先确认对应麦克风、声卡、摄像头、串口或机械臂已连接。
