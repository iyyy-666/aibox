# 综合实验与当前 SDK 实际边界

课程 57（`integrated.voice-transport.01`）位于第九篇、第十七章，使用
`templates/voice_transport_plan.py`。它调用现有 `Voice().listen(timeout=8)`，
仅解析“搬运红色积木到传送带”等四种完整口令，打印六步计划。
支持红色、绿色、蓝色、黄色；否定、多目标、未知颜色、缺少目的地均拒绝。
它不调用 Arm、不发送动作、不进行真实视觉确认。

当前 `Voice.listen` 使用环境变量 `AIBOX_SIM_VOICE_TEXT`，默认值“张开”。
因此默认运行会提示未匹配。学生可直接把模板的 `text` 赋值改成完整口令，
观察规划；教师也可在启动环境设置上述模拟文字。该变量不是麦克风输入。

真实综合体验在功能演示的语音搬运综合实验中完成：

1. 检查设备和工作区域。
2. 初始化摄像头观察位置和机械臂直立姿态。
3. 开始监听并说出完整单一搬运口令。
4. 等待视觉连续确认目标颜色。
5. 执行已有通用固定搬运动作组，颜色用于确认目标，不用于坐标抓取。
6. `legacy_timed` 模式等待驱动空闲后再等1秒，随后恢复直立。

该模式基于软件时序，未验证物理到位，不表示物体已成功搬运。
体验状态字段属于功能演示内部协议，未作为学生公共 SDK 导出。

## 已实现的学生公共接口

`from aibox import Arm, Voice, Camera, Vision`。

| 接口 | 当前行为 |
| --- | --- |
| `Arm().pose(name)` | 只支持“直立”“放平”，返回 None |
| `Arm().action(name)` | 支持“抓取”“搬运”“左转移”“右转移”，返回 None |
| `Arm().open()/half_open()/close()/reset()/stop()` | 夹爪、复位、停止，返回 None |
| `Arm().servo(joint, pwm)` | 关节1至6，PWM 800至2200 |
| `Arm().adjust(joint, delta=30)` | 微调量非零、范围-100至100 |
| `Voice().listen(timeout=8)` | 返回模拟字符串；timeout目前不控制录音 |
| `Voice().speak(text)/stop()` | 模拟事件，不调用声卡 |
| `Camera().show()/close()` | 模拟事件，不操作真实摄像头 |
| `Vision().color()/fruit()/classify()/shape()` | 固定模拟结果 |

机械臂仅在 `AIBOX_DEVICE_MODE=hardware` 时连接机械臂设备服务；其他模式记录模拟事件。
设备服务调用成功、同姿态缓存和 SDK 返回均不是位置传感器反馈。
Face、Hand、Lidar、AI 当前也使用模拟数据。
本次没有增加 transport、曝光控制、动作完成反馈等学生公共 API。

平台顶部“SDK帮助”按钮提供同样的能力边界说明。
