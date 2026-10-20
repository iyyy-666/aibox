# SDK与平台同步（2026-10-20）

## 来源与修改范围

工作目录：`G:/codexwork/人工智能实验箱/子项目/学生编程平台`。
`src` 来自本次从板端 `/opt/aibox-studio/src` 提取的新鲜副本。
基线归档：`综合升级20261020/student-board-before.tar.gz`。
没有把 `_aibox-github` 的旧源码覆盖到该副本。
旧仓库只作为只读测试资料来源，复制了五个相关测试文件并更新课程数量断言。
未连接SSH、未部署、未操作任何硬件。

## 最终修改

- `src/aibox_studio/resources/basic-ai/templates/voice_transport_plan.py`：仅使用既有 `Voice` 的模拟输入；四种完整单一口令白名单；打印六步流程；不调用机械臂。
- `src/aibox_studio/resources/basic-ai/experiments.json`：追加第九篇、第十七章、实验57 `integrated.voice-transport.01`；原56个ID、编号和模板保持兼容。
- `src/aibox_studio/resources/basic-ai/manifest.json`：课程版本0.2.0，数量57。
- `src/aibox_studio/sdk_help.py`：实际SDK能力、模拟边界、完整口令、六步综合体验、软件时序限制。
- `src/aibox_studio/app.py`：顶部添加“SDK帮助”按钮，显示上述帮助文本。
- `examples/voice_transport_plan.py`：可读可运行的同版示例。
- `README.md`：更新57个课程数量与实际硬件/模拟边界，移除所有设备均为模拟的过时表述。
- `docs/07-综合实验与SDK实际边界.md`：课程入口、公共接口和设备能力说明。
- `tests/test_integrated_transport_course.py`：11项新增测试。
- `tests/test_course_catalog.py`：保留原课程验证，数量更新到57并检查新实验权限。
- 其他复制的测试：`test_bundled_course_execution.py`、`test_simulated_sdk.py`、`test_hardware_arm_sdk.py`、`test_code_policy.py`。

## 公共API核实结论

`src/aibox/__init__.py` 和 `src/aibox_device/arm_service.py` 未修改。
本次未新增 transport、曝光、完成反馈等学生公共API。

- `Arm.pose(name: str) -> None`：直立、放平。
- `Arm.action(name: str) -> None`：抓取、搬运、左转移、右转移。
- `Arm.command(name: str) -> None`：直立、放平、抓取、搬运、复位、停止、张开、闭合、右转移、左转移。
- `open()/half_open()/close()/reset()/stop()`：返回 None。
- `servo(joint: int, pwm: int) -> None`：关节1至6，PWM800至2200。
- `adjust(joint: int, delta: int = 30) -> None`：非零增量-100至100。
- `Voice.listen(timeout: int = 8) -> str`：读取模拟环境变量，默认“张开”；未录音。
- `Voice.speak(text: str) -> None`、`Voice.stop() -> None`：仅模拟事件。
- `Camera.show()/close()`：仅模拟画面事件。
- `Vision.color()/fruit()/classify()/shape() -> str`：固定模拟结果。
- Face、Hand、Lidar、AI也仅模拟。

硬件模式仅让Arm通过Unix socket连接设备服务；结果不提供物理位置、成功搬运证据。
同姿态保持去重是服务缓存。不能把服务返回或缓存描述成传感器确认。
完整源码和精确模板路径已发送给教材代理，供SDK大全和教材统一引用。

## 验证

在该工作目录执行 `python -m pytest -q`：**95项通过**，含原有56个模板加新模板共57个逐项策略/模拟执行。
本机Python3.14.6；未使用真实设备。
新增四种有效颜色和六种拒绝输入测试，在环境变量hardware模式下禁止socket创建，确认模板不触发设备指令。
对全部37个Python源码执行 `ast.parse(..., feature_version=(3,10))` 全部通过。
此为Python3.10语法兼容检查，不等同于板端运行或Qt界面验证。

没有在本机启动Qt界面，顶部帮助按钮需由主代理按授权在板端检查显示。
`pyproject.toml` 当前Python>=3.11元数据未调整：源码语法支持3.10，实际启动器直接python3加载源码，元数据不影响本次启动。
若后续需要pip安装到系统Python3.10，应另行结合vendor PySide6来源核实依赖后修正安装要求。

## 部署交接

主代理可用此副本打包`src`并部署到`/opt/aibox-studio/src`，随包保留examples、docs作为交付材料。
`sdk_help.py`是Python模块，无需新增非代码资源打包规则；模板和课程JSON已在既有package-data覆盖范围。
新课程仅授权 `voice.listen`，无robot资源或Arm capability；默认模拟文字“张开”会提示口令未匹配。
学生可改写text为“搬运红色积木到传送带”查看计划，帮助中已说明。
真实功能演示与学生SDK模拟教学须分别如实标记，不能用本次通过的离线测试宣称硬件联调完成。
