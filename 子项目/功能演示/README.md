# 功能演示

2026-10-18 新增“语音控制搬运物块”，已按用户授权以按钮模块的软件时序完成判据部署到 RK3588。已验证蓝色实物识别，实际搬运尚未触发；无物理到位反馈。状态、测试及文件清单见 [VOICE_TRANSPORT.md](VOICE_TRANSPORT.md)。

人工智能试验箱的统一演示软件。最终产品在一个窗口内提供 14 个 AI、硬件与传感器功能，并通过统一生命周期管理避免摄像头、麦克风和串口冲突。

设计与实施文档：

- `../../docs/superpowers/specs/2026-09-21-feature-demo-integration-design.md`
- `../../docs/superpowers/plans/2026-09-21-feature-demo-integration-implementation.md`
- `../../docs/superpowers/plans/2026-09-28-radar-detection-implementation.md`

“雷达检测”使用 A1M8 原始串口扫描数据，在可配置的角度/距离区域内建立多帧无物块基准，再通过距离变化和连续帧确认输出“有物块/无物块”。它不会调用摄像头或机械臂；没有可读雷达时模块仍可启动并显示未连接。

本地测试使用仓库工作区虚拟环境：

```powershell
& 'G:\codex\.venv\Scripts\python.exe' -m pytest '子项目/功能演示/代码/tests' -v
```
