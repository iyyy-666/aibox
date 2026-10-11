# AIBox Device Service 接口与资源模型

版本：0.1（设计草案）  
日期：2026-10-08

## 1. 定位

AIBox Device Service 是实验箱硬件、模型与运行状态的唯一所有者。AIBox Studio、学生 Runner 和现有“功能演示”最终都通过该服务访问设备，任何客户端都不直接打开串口、V4L2、ALSA、GPIO 或 NPU 模型。

第一阶段迁移期间，“功能演示”尚未全部接入服务时，双方必须使用同一组跨进程锁；完成迁移后删除兼容锁层，以 Device Service 会话为唯一仲裁机制。

## 2. 组件

```text
Device Service
├── IPC Gateway          鉴权、协议版本、请求路由
├── Session Manager      会话、租约、取消和失联回收
├── Resource Manager     原子申请、互斥、依赖和占用者信息
├── Task Manager         短任务、持续任务、超时和停止
├── Event Gateway        状态、结果和高频数据通知
├── Frame Broker         摄像头最新帧共享内存
├── Model Manager        RKNN/ONNX 模型加载、缓存和回收
├── Error Translator     稳定错误码与中文消息参数
└── Hardware Adapters    机械臂、摄像头、云台、雷达、音频等
```

适配器只实现内部接口，不暴露给学生。硬件型号或协议变化不得影响 `aibox` 公开 API。

## 3. 传输与鉴权

- 控制通道使用 Unix Domain Socket，不监听 TCP 端口。
- 低频命令和事件使用长度前缀 JSON，避免换行和半包歧义。
- 摄像头帧使用共享内存环形缓冲区；控制通道只传递槽位、尺寸、像素格式和帧序号。
- socket 文件权限限制为专用用户组，并校验 Linux peer credentials。
- Runner 使用单会话短期令牌；Studio 和“功能演示”使用各自应用身份。
- 每个请求都包含 `protocol`、`request_id`、`client_id`、`session_id` 和 `operation`。

示例请求：

```json
{
  "protocol": 1,
  "request_id": "01J...",
  "client_id": "aibox-runner",
  "session_id": "01J...",
  "operation": "vision.color",
  "params": {}
}
```

示例响应：

```json
{
  "protocol": 1,
  "request_id": "01J...",
  "ok": true,
  "result": {"label": "红色"}
}
```

失败响应包含稳定 `code`、学生可翻译的 `message_key`、可选参数和是否可重试，不返回驱动堆栈。

## 4. 会话协议

### 4.1 创建

`session.create` 输入：

- 客户端身份和当前实验稳定 ID。
- 允许的 `capabilities`。
- 需要原子申请的 `resources`。
- 会话类型：`oneshot` 或 `observe`。
- 租约和心跳参数。

服务端先校验能力到资源的映射，再一次性申请全部资源。任何资源不可用时整个申请失败，不允许只占用一部分。

### 4.2 生命周期

```text
CREATING -> ACTIVE -> CANCELLING -> CLOSED
    |          |             |
    +-------> FAILED <-------+
                   -> ORPHANED -> RECLAIMING -> CLOSED
```

- 客户端每 2 秒发送心跳，建议 6 秒无心跳标记为 `ORPHANED`。
- 失联后先执行设备安全停止，再释放资源。
- `session.cancel` 和 `session.close` 幂等，可重复调用。
- 会话关闭后令牌立刻失效，迟到命令返回 `SESSION_CLOSED`。

## 5. 资源模型

### 5.1 基础资源

| 资源 | 模式 | 说明 |
|---|---|---|
| `camera` | 独占采集、可共享只读帧 | 由一个采集拥有者统一设置格式 |
| `gimbal` | 独占 | 任何跟踪或预置姿态会改变物理方向 |
| `robot` | 独占 | 机械臂动作串行化，停止优先 |
| `lidar` | 独占采集、可共享只读扫描 | A1M8 串口只由服务打开一次 |
| `microphone` | 独占 | 避免录音竞争 |
| `speaker` | 独占 | 避免音频混播 |
| `asr` | 共享模型、独占任务 | 与 microphone 联合申请 |
| `tts` | 共享模型、独占播放 | 与 speaker 联合申请 |
| `llm` | 排队或独占任务 | 根据实机内存策略配置 |
| `npu` | 调度资源 | 由 Model Manager 控制并发和显存/内存预算 |

“共享”只表示服务内部可以复用数据或模型，不代表客户端可以绕过会话直接访问设备。

### 5.2 能力依赖

| 能力 | 必需资源 |
|---|---|
| `arm.*` | `robot` |
| `camera.show/close` | `camera` |
| `vision.*`、`face.detect`、`hand.detect/gesture` | `camera`, `npu` |
| `hand.track` | `camera`, `gimbal`, `npu` |
| `voice.listen` | `microphone`, `asr` |
| `voice.speak` | `speaker`, `tts` |
| `ai.chat` | `llm`, `npu`（由部署配置决定） |
| `lidar.*` | `lidar` |

综合实验必须在创建会话时提交依赖并集。例如“机械臂打开后说话”原子申请 `robot`、`speaker` 和 `tts`，防止动作完成后才发现扬声器被占用。

机械臂适配器必须执行独立于客户端的安全校验：舵机编号只能为 1 至 6，绝对 PWM
只能为 `800–2200`，单次微调只能为 `-100` 至 `100` 且调整后的目标仍须在安全
范围内。越界请求返回 `SAFETY_LIMIT`，不得静默截断后继续运动。预设动作和动作组
也必须在加载时逐舵机校验相同范围。

## 6. 冲突策略

- 不抢占其他前台应用的正常会话；返回 `RESOURCE_BUSY` 和占用者的产品名称。
- 停止、安全故障和管理员维护命令具有最高优先级。
- 第一版不排队等待物理设备，避免学生误以为程序无响应；界面提示先退出占用功能后重试。
- 同一会话内重复申请相同资源幂等。
- 多资源申请按 Resource Manager 内部固定顺序执行，并在失败时整体回滚，避免死锁。

当“功能演示”正在占用摄像头时，学生平台显示“摄像头正在被功能演示使用，请先退出该功能”，不得强制关闭对方进程。

## 7. 命令与任务语义

- 每个命令有唯一 `request_id`，客户端重试同一请求时服务返回原结果，不能重复执行机械动作。
- 短操作同步返回；耗时操作返回 `task_id`，通过事件报告状态。
- 同一机械臂会话中的普通动作串行执行。
- `task.cancel` 幂等；安全停止不进入普通任务队列。
- 调用超时只表示客户端不再等待，服务端仍必须确认任务是否已停止，不能假设超时等于取消成功。

任务状态：`QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`、`CANCELLING`、`CANCELLED`。

## 8. 事件与高频数据

事件统一包含 `session_id`、`sequence`、`timestamp_monotonic_ns` 和 `type`：

| 事件 | 主要内容 |
|---|---|
| `frame.updated` | 帧序号、共享内存槽位、尺寸、格式、叠加元数据 |
| `radar.scan` | 角度距离点、扫描序号和质量状态 |
| `result.updated` | 标签、置信度和显示文本 |
| `robot.state` | 动作、忙碌、停止和故障状态 |
| `audio.state` | 录音、识别、合成和播放状态 |
| `assistant.token` | 本地 AI 增量文本，可选启用 |
| `session.error` | 稳定错误码和消息参数 |
| `session.closed` | 关闭原因和资源清理结果 |

慢客户端只接收摄像头“最新帧”，不积压所有视频帧。控制事件必须可靠有序；视频和雷达高频更新允许丢弃旧数据。

## 9. 模型管理

- 模型清单记录模型 ID、版本、SHA-256、后端、内存预算和兼容硬件。
- RKNN 为 RK3588 首选后端，ONNX Runtime 作为明确支持的后备，不在一次任务中静默切换导致结果漂移。
- 模型按需加载；内存不足时仅回收无活动引用的模型。
- 多个能力复用同一模型时使用引用计数，任何会话不得卸载其他会话正在使用的模型。
- 模型缺失、损坏和后端不兼容分别记录维护原因，对学生统一映射为可理解的模型启动失败提示。

## 10. 安全停止与恢复

停止顺序按物理风险确定：

1. 机械臂和云台停止运动。
2. 取消扬声器播放和麦克风采集。
3. 停止持续推理、摄像头和雷达流。
4. 释放模型引用、共享内存和资源锁。
5. 关闭会话并记录清理结果。

服务启动时执行恢复检查：清理孤儿共享内存和过期锁，探测设备状态，并将机械臂置于“需确认”而非自动运动状态。服务崩溃重启后不得自动恢复之前的动作任务。

## 11. 错误合同

| 错误码 | 含义 |
|---|---|
| `INVALID_REQUEST` | 协议字段或参数错误 |
| `UNSUPPORTED_PROTOCOL` | IPC 主版本不兼容 |
| `AUTH_FAILED` | 客户端或会话令牌无效 |
| `CAPABILITY_DENIED` | 当前实验未授权该能力 |
| `SESSION_CLOSED` | 会话已结束 |
| `DEVICE_NOT_FOUND` | 所需设备不存在 |
| `RESOURCE_BUSY` | 资源被其他会话占用 |
| `CAMERA_NO_FRAME` | 暂无有效画面 |
| `MODEL_LOAD_FAILED` | 模型无法加载 |
| `ROBOT_BLOCKED` | 机械动作未完成或检测到阻塞 |
| `SAFETY_LIMIT` | 舵机编号、PWM 或微调步长超出安全范围 |
| `OPERATION_TIMEOUT` | 设备操作超时 |
| `CANCELLED` | 操作被停止 |
| `INTERNAL_ERROR` | 未分类服务错误，仅维护日志含详情 |

错误码在 1.x 协议内不重定义；新增错误码时旧客户端必须能回退为通用中文提示。

## 12. 服务部署与可观测性

- 使用 systemd 启动、自动重启和限制权限，服务不以桌面用户身份运行。
- 配置位于 `/etc/aibox-studio/`，运行状态位于 `/var/lib/aibox-studio/`。
- 健康检查包含协议版本、适配器状态、资源占用和模型清单，不触发机械动作。
- 日志记录请求 ID、会话状态、耗时、错误码和资源变化，不默认记录图像、录音和对话正文。
- 维护工具只读显示设备健康与占用者；危险测试动作必须是单独的维修流程，不进入学生界面。

## 13. 验收条件

- Studio 与“功能演示”同时请求同一独占资源时，只允许一方成功且提示明确。
- 多资源申请失败后无部分资源残留。
- 重复提交同一机械动作请求不会执行两次。
- 客户端异常退出后，租约到期能停止任务并释放全部资源。
- 摄像头持续 30 分钟不发生无界内存增长，慢 UI 不造成帧队列堆积。
- A1M8 连续运行 30 分钟后可正常停止并重新打开串口。
- Device Service 重启后不自动继续机械动作，健康检查不移动硬件。
- 断网时机械臂、摄像头、雷达、语音和本地 AI 的所有服务接口正常工作。

