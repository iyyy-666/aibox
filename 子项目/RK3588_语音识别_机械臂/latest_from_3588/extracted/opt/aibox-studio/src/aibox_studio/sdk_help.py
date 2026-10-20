"""Help text for the SDK actually shipped with the student platform."""

SDK_HELP = """当前学生 SDK 与设备状态

机械臂：仅在硬件模式下通过设备服务执行真实动作；模拟模式只记录事件。
arm.pose(name)：直立、放平。
arm.action(name)：抓取、搬运、左转移、右转移。
arm.open() / half_open() / close() / reset() / stop()。
arm.servo(joint, pwm)：关节1至6，PWM 800至2200。
arm.adjust(joint, delta=30)：非零微调量，范围-100至100。
以上方法返回 None；指令返回不代表传感器验证物理到位。

Voice.listen(timeout=8) -> str：目前读取模拟文字，默认“张开”。
Voice.speak(text) / stop()：目前产生模拟事件，不调用声卡。
Camera.show() / close()：目前产生模拟画面事件。
Vision.color() / fruit() / classify() / shape()：目前返回固定模拟结果。
Face、Hand、Lidar、AI 当前也使用模拟数据。
硬件模式仅启用机械臂，不会把上述接口变为真实视觉或语音。

综合实验57：语音搬运规划（模拟）。只接受红色、绿色、蓝色、黄色的
完整单一口令“搬运红色积木到传送带”，打印六步计划，不发送动作。
默认模拟文字为“张开”，因此默认运行会提示口令未匹配。
可在代码中把 text = Voice().listen(timeout=8).strip() 改成
text = "搬运红色积木到传送带"，观察规划结果。

真实综合体验：进入“功能演示”的语音搬运综合实验。
使用通用固定动作组，颜色用于视觉确认，并非按物体坐标抓取。
legacy_timed 模式等待驱动空闲后再等1秒，再恢复直立；
这是软件时序，未验证物理到位，也不代表物体成功搬运。
学生 SDK 未新增 transport、曝光调节或动作完成反馈 API。
"""
