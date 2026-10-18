# 语音控制搬运物块：开发交付记录

日期：2026-10-18。工作目录：`G:\codexwork\人工智能实验箱\子项目\功能演示`。

## 当前状态

### 语音响应提速（2026-10-18）

已部署两项修正并重启到首页：

1. 修复板端共享 `voice_engine.py` 中 `_record_utterance()` 的结束检测缩进错误。原先静音判断位于“尚未开始说话”分支，开始讲话后无法正常由静音退出，常拖到新模块的8秒录音上限。现改为讲话后检查结束，保持既有0.58秒静音阈值、短停顿兼容和8秒上限，不缩短完整指令的容纳长度。
2. 为新搬运模块增加 `CachedEngineFactory`，停止监听仍关闭PCM并结束监听线程；下次开启复用同一VoiceEngine及其已加载模型。没有自动打开麦克风，没有更换模型或依赖。首次模型加载仍需等待。

本地104项相关测试通过，独立审查未发现重要回归。板端真实前后版本的录音方法使用同一段模拟PCM（1.5秒讲话后静音），录制音频从8.0秒降为2.3秒，后者含预录和0.58秒尾部静音。这是算法/模拟测试，不能当成麦克风端到端识别速度。实际大模型加载基准在90秒内未完成，没有获得可报告的加载/推理加速倍数；该测试已结束。用户仍需用真实语音复测。

本次新增 `代码/feature_demo/workers/transport_voice.py`，修改 `transport_runtime.py` 注入模块内模型缓存，并维护共享引擎工作副本 `代码/voice_engine.py`。板端备份：`/root/aibox_backups/voice-speedup-20261018-162645`。记录：`output/voice-speedup-deployment.json`、`voice-speedup-tests.xml`、`voice-speedup-board-verification.json`。

NPU审计：板端存在RKNPU驱动v0.9.8和`/usr/lib/librknnrt.so`；现有语音模型目录未发现RKNN模型。本轮**未启用NPU**，没有改依赖版本。NPU加速需要兼容的RKNN语音模型和RKNN版运行支持；官方提供[RKNN安装说明](https://k2-fsa.github.io/sherpa/onnx/rknn/install.html)及[RK3588中文SenseVoice/Zipformer模型](https://k2-fsa.github.io/sherpa/onnx/rknn/models.html)，可在隔离环境适配、对比中文完整指令准确率和推理耗时后再接入。

### 退出与直立接续热修复（2026-10-18）

用户反馈退出失败，并要求搬运结束 1 秒后恢复直立。实际原因是原驱动 `_mov_end` 在末步时间后还有 1 秒忙碌缓冲；原接续太早，`execute_pose('直立')` 被拒绝，状态机随后锁定；退出拒绝又被 `WorkerProcess` 转成异常，导致接口报错。

已部署修正：原搬运动作组正常返回后，等原驱动软件忙碌标记结束，再额外等待 **1 秒**，调用现有直立姿态。只给 `RobotAdapter` 增加读取/等待原忙碌标记的方法，不修改既有动作。软件时序仍不代表物理反馈。

退出时，活动动作仍禁止退出，控制性拒绝返回继续运行而不是 HTTP 500；已结束的异常任务在软件模式下、后台动作线程结束且驱动空闲后允许退出，保留错误结果，不伪称搬运成功。当前旧版本卡住的异常任务已清理，未重放搬运指令。

验证：本地 **99 项相关测试通过**；板端实际 `RobotArm` + 模拟串口/时钟验证，空闲后等待 1 秒，随后直立指令被接受。没有为这次验证打开真实机械臂串口。热修复备份：`/root/aibox_backups/transport-recovery-fix-20261018-160308`。证据：`output/transport-recovery-fix-tests.xml`、`transport-recovery-board-verification.json`。软件已重启至首页，修正后完整实物流程待用户复测。

**已部署到 RK3588 `192.168.11.104` 并重启统一演示软件，当前停留首页。用户已进行实物搬运尝试；本次修复未自动重放，修复后的完整流程待复测。**

用户本轮明确允许“沿用按钮模块的软件完成判据”。部署启用 `AIBOX_TRANSPORT_COMPLETION_MODE=legacy_timed`：仍调用按钮模块的同一条“搬运”动作组，动作组正常返回后等待配置中的末步时长，再执行原有直立；软件时序结束不表示物理到位，页面全程明确显示这一限制。未改变既有动作轨迹或其他模块判据。

部署前通过既有分拣摄像头画面，在板端隔离候选代码中确认蓝色实物被识别。实物偏青蓝且工作台反光，因此新增模块兼容分拣模块的蓝色 HSV 范围，并分离深色倒影、接受立方体可见多面轮廓。没有为测试重复打开摄像头，也没有触发搬运。

部署后检查：健康接口正常、新入口注册、首页无活动模块、软件时序配置生效、读取既有动作配置的 preflight 通过。最新测试 **58 passed**，另有两条既有依赖弃用提示。备份路径：`/root/aibox_backups/voice-transport-before-20261018-155140`，包含完整旧包和原环境配置。部署结果见 `output/deployment-result.json`，测试见 `output/transport-deployment-tests.xml`。

以下初版审计和 175 项回归记录保留；其中“未部署”和默认反馈门禁描述为此前状态，当前以本节及用户本轮授权为准。

已使用用户授权的 ztl 账号连接 `192.168.11.104`（主机名 RK3588），只读检查正在运行的统一演示软件、机械臂服务和设备节点；没有执行摄像头定位、机械臂动作、麦克风采集或服务重启。

板端源代码保存于 `G:\codexwork\人工智能实验箱\板端基线\2026-10-18`。本工作副本以这份实际运行代码为基线，原有本地子项目、配置、模型和板端程序保留。测试和部署脚本从既有本地版本补齐，其中部分测试早于板端版本，见下文。

## 仍缺少的硬件能力

1. **动作完成反馈**：实际 `/root/robot_arm/serial_driver.py` 的发送成功表示串口 write/flush 成功。`RobotArm.execute_pose()` 随即返回；`execute_sequence('搬运')` 按现有阶段执行后，末步释放指令也仅发送并短暂等待。`/opt/aibox-studio/src/aibox_device/arm_service.py` 同样只转发这两个返回值，没有额外到位反馈。因此不能把 `ok=True` 或软件 `is_moving=False` 当作物理动作完成，更不能补一个固定延时后宣布成功。
2. **实物校准与语义确认**：复用 HSV 分割后增加轮廓约束和固定区域检查，可以剔除整片背景、细线、圆斑、空心和凹形标记；同色同尺寸的实心平面方形标记仍可能与物块正面相同。当前二维算法不能保证识别物块的厚度或实物身份，仍需标定实际取料区域，并补充可验证的物块确认依据及负样本验证。

未显式配置软件时序模式或真实反馈插件时，`TransportMotionAdapter.preflight()` 仍在任何新增机械臂动作前拒绝初始化。当前开发板已按用户授权显式开启软件时序模式；没有宣称新增了物理反馈能力。

## 新增源文件

- `代码/feature_demo/workers/transport.py`：中文完整指令解析、单任务状态机、初始化保护、监听代次、连续帧确认、超时、异常锁定与退出保护。
- `代码/feature_demo/workers/transport_runtime.py`：组合既有视觉、语音、云台和机械臂能力。
- `代码/feature_demo/adapters/transport_vision.py`：复用颜色检测与分拣视角，增加独立物块轮廓确认。
- `代码/feature_demo/adapters/transport_motion.py`：只调用原有姿态和搬运指令，要求另有真实完成确认。
- `代码/tests/test_transport*.py`：五个测试文件，54 项测试。

## 修改的已有源文件（相对板端基线）

- `代码/feature_demo/registry.py`：追加 `voice_transport`，占用 camera/gimbal/robot/microphone/asr，只开放开启和停止监听。
- `代码/feature_demo/workers/runtime.py`：增加新 Worker 工厂分支。
- `代码/feature_demo/app.py`：只给新模块子进程设置默认 8 秒最大语句采集时间，避免原有 3.2 秒短指令窗口截断完整句子。其他模块环境不变。
- `代码/feature_demo/adapters/robot.py`：热修复新增软件忙碌状态读取/等待方法，仅新模块调用，避免接续姿态被原有忙碌保护拒绝。
- `代码/feature_demo/manager.py`：仅新模块退出前调用 `prepare_exit`，活动或未确认结束的轨迹返回继续运行，保留资源占有，避免通用 5 秒退出超时强杀机械臂任务。
- `代码/feature_demo/web/app.js`：新增模块控件和实时状态；固定区域模式隐藏手动云台控制；初始化阶段明确显示尚未完成。
- `代码/feature_demo/web/styles.css`：只增加新模块的布局和状态样式。

未改变既有分拣、语音控制机械臂、视觉算法或机械臂轨迹文件。没有安装或更新依赖，没有提交或推送。部署为上述 10 个源文件的增量安装，未覆盖其他模块文件。

## 复用的真实接口

| 能力 | 真实调用 |
| --- | --- |
| 分拣摄像头定位 | `GimbalAdapter.move_to(*SORTING_GIMBAL_TARGET)`，目标直接引用原有环境配置，默认 `(1200, 1110)` |
| 摄像头采集及实时画面 | `create_vision_worker()`、`VisionWorker`、原有 `_configured_camera()` 和 JPEG 输出 |
| 分拣标准视角及区域 | 原 `sorting_app.py` 的 `split_stereo()`、`box_is_target()` |
| 四种颜色候选 | `build_vision_adapter('color_recognition')` 返回实例的 `_detect_colors()`、`COLOR_RANGES`、`_annotate()` |
| 离线语音采集识别 | `VoiceWorker('ai_assistant', ...)` 的通用语音模式；仅启用 ASR/PCM，不创建 AssistantWorker，不调用对话模型，不绑定机械臂适配器；`use_command_grammar=False`、空短指令表 |
| 直立 | `RobotAdapter.command('pose', {'name': '直立'})` |
| 通用搬运 | `RobotAdapter.command('sequence', {'name': '搬运'})`，红绿黄蓝共享同一条已有动作 |

没有新增云端语音 API、动态抓取坐标或按颜色区分的轨迹。

## 按钮和任务生命周期

进入模块不监听。进程就绪与硬件初始化分开：只有摄像头定位和直立完成反馈都成功，才能开启监听。启动直立一旦发送，未确认完成时也禁止退出；后续故障不会伪装成初始化成功。

点击“开启监听”后异步加载原有引擎，真正启动后才显示“正在监听”。重复点击不创建第二个会话。页面显示语音原文、颜色、物块确认和任务阶段。引擎启动失败或运行出错会显示“监听错误”，过期的启动成功结果不能覆盖错误状态。

只接受完整、单一颜色的搬运指令，例如“搬运蓝色物块到传送带上”“请把红色物块搬运到传送带上”。拒绝缺项、否定、多个颜色、提问及追加其他动作的指令。

每个监听会话最多接受一条有效指令。收到后停止该会话，麦克风关闭后才启用本次视觉确认，避免关闭期间的旧识别结果触发动作。检测使用新鲜连续帧；空帧、多目标、位置变化或摄像头异常会撤销确认，超时回到等待。默认等待 4 秒、连续 3 帧。

点击“停止监听”立即使语音代次失效，停止本模块采集，取消未提交的检测任务；已开始的搬运和后续确认恢复直立继续完成，不发送急停。初始化模型加载期间，关闭资源可能等待加载调用返回，此时显示“正在停止”，不提前宣称已释放。搬运中、恢复中或动作状态不明时拒绝退出，阻止新模块同时接管硬件。

搬运完成反馈成功后才调用直立，直立也确认完成后才显示“搬运完成，机械臂已恢复直立”。若反馈失败则保持任务锁定，等待人工处理；当前没有提供猜测位置的自动故障恢复按钮。

## 配置和完成反馈接入

- `AIBOX_TRANSPORT_DETECT_SECONDS`：检测超时秒数，默认 `4`。
- `AIBOX_TRANSPORT_STABLE_HITS`：连续确认帧数，默认 `3`。
- `AIBOX_TRANSPORT_UTTERANCE_SECONDS`：新模块子进程语句采集上限，默认 `8`。
- `AIBOX_TRANSPORT_COMPLETION_MODE=legacy_timed`：用户明确授权的软件阶段时序模式；从既有配置读取直立时间和搬运末步时间，只有原指令返回成功才等待并接续；不表示物理到位。
- `AIBOX_TRANSPORT_PICK_ROI`：可选 `[x1,y1,x2,y2]` 归一化实物检测区域，必须结合既有固定取料位置标定。未设置时沿用分拣区域边距，不代表已完成取料标定。
- `AIBOX_TRANSPORT_COMPLETION_PLUGIN=包名:函数名`：**本次新增的扩展接口，并非现有驱动已有接口**。函数接收 `(command, payload, result)`，必须依据实际可靠的完成反馈，在动作明确完成时返回 `True`，其余情况返回 `False` 或抛异常。须有硬件侧超时和反馈关联，不能以固定时间、发送成功或缓存 PWM 替代。当前未提供或启用真实实现。

## 实际验证结果

本地环境使用既有 `G:\codex\.venv\Scripts\python.exe`，无新增依赖。

- 新模块 54 项测试全部通过：解析、四颜色到同一搬运轨迹、非法指令、启动失败、停止/重启/旧回调、重复触发、检测超时、背景轮廓负样本、相机/动作状态保护、初始化直立保护、失败锁定、Web 控件状态、应用健康与首页、ASR 通用模式、PCM 释放、20 次模块切换。
- 相关软件回归最终结果：**175 passed，5 deselected，2 warnings**。包含上述新模块测试；两个 warning 是既有 TestClient 依赖弃用提示，未更改版本。
- 5 项排除均来自既有版本不匹配：4 项旧测试仍要求板端已经移除的 `voice_input_test` 或对应页面节点，已实际执行并失败；另 1 项原有手掌云台测试要求手动步进立即关闭服务，板端实现不满足，实际运行也失败。没有修改原业务来迎合这些旧测试。保留 `output/transport-software-tests.xml`、`transport-baseline-mismatches.xml` 和最终报告。
- `python -m compileall -q feature_demo`、`node --check feature_demo/web/app.js` 通过。
- 已只读确认板端 `/dev/esp32_arm -> ttyUSB0`、双目摄像头稳定节点指向 `video41`、麦克风 `XFMDPV0018` 和两个控制器串口存在。这只证明枚举存在，不代表硬件功能验收。

测试入口：在 `代码` 目录运行：

```powershell
& 'G:\codex\.venv\Scripts\python.exe' -m pytest tests/test_transport.py tests/test_transport_safety.py tests/test_transport_vision.py tests/test_transport_integration.py tests/test_transport_frontend.py -q
```

机器可读报告：`output/transport-module-tests.xml`（54项）、`output/transport-final-tests.xml`（175项）。这些都是软件/模拟测试，不是真实搬运测试。

独立代码审查发现并修复了启动直立的退出保护、关闭麦克风期间旧目标确认残留两项问题，已用失败后修复的回归测试验证。

本地候选包：`output/voice-transport-candidate-20261018.tar.gz`；源文件变更及 SHA-256 清单：`output/voice-transport-changes.json`。打包时检查相对板端基线恰好修改上述 6 个既有源文件，新增 4 个源文件，其他既有源文件逐字节保留。源代码已通过隔离暂存校验后增量部署到板端。

## 后续硬件验收

先接入和验证动作完成反馈，并完成取料 ROI、尺寸和实物负样本校准，再进行部署与联调。逐项验证摄像头定位、直立到位、长句识别、四颜色目标确认、单次搬运至固定传送带、释放完成、恢复直立、动作中停止监听及拒绝退出。未连接可靠反馈前，不应启用真实自动流程。
