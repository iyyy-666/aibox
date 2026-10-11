# AIBox Studio Runner 安全执行协议

版本：0.1（设计草案）  
日期：2026-10-08

## 1. 职责

Runner 是桌面主程序与学生 Python 代码之间的安全边界，负责校验、隔离执行、输出采集、取消和清理。它不直接操作硬件；学生代码中的 `aibox` 通过受控本地 RPC 调用 Device Service。

威胁模型按“学生可能有意或无意编写危险代码”设计。AST 白名单用于给出教学提示，不作为唯一安全措施；真正的边界由独立进程、操作系统沙箱、资源限制和 Device Service 鉴权共同组成。

## 2. 进程与信任边界

```text
AIBox Studio 主进程
  -> Runner Manager（可信）
    -> bubblewrap 沙箱
      -> aibox-runner（低权限）
        -> 学生代码（不可信）
        -> aibox SDK（受控 RPC 客户端）
              |
              -> 仅访问会话专用 Unix Socket

AIBox Device Service（可信、独立 systemd 服务）
```

主界面不得在自身进程调用 `exec()`、`eval()` 或导入学生文件。Runner 崩溃不得导致主界面或 Device Service 崩溃。

## 3. 启动协议

每次点击“运行”创建新的 `run_id` 和 Runner 进程，不复用上一次解释器状态。

1. Studio 从课程包读取实验权限，保存当前编辑内容的运行快照。
2. Runner Manager 执行 UTF-8、大小、语法和 AST 教学校验。
3. Studio 向 Device Service 创建会话，提交实验 ID、能力和资源集合。
4. Device Service 原子申请资源并返回短期 `session_token` 与会话 socket。
5. Runner Manager 建立沙箱，将只读运行时、只读 SDK、运行快照和会话 socket 映射进去。
6. Runner 发送 `ready` 后开始计时并执行学生代码。
7. 启动任一步失败时撤销会话并释放已申请资源。

`run_id`、`session_id` 和 `session_token` 每次运行唯一。令牌只允许调用当前实验声明的能力，并在 Runner 退出或停止后立即失效。

## 4. 教学校验

### 4.1 允许内容

- 变量、数值、字符串、布尔值、列表、元组和字典。
- 条件、受限循环、函数定义和 `print()`。
- `from aibox import ...`，以及当前实验声明的 `time`、`math`、`random`。
- 当前实验 `capabilities` 中允许的方法调用。

### 4.2 拒绝内容

- 未声明导入、相对导入、动态导入和通配符导入。
- `eval`、`exec`、`compile`、`open`、`input`、`breakpoint`、`help`、`globals`、`locals`、`vars`。
- 双下划线名称或属性、反射、元类和运行时对象遍历。
- 文件、网络、进程、线程、信号、共享内存和原始设备访问。
- 未声明的 `aibox` 类、方法或参数形式。
- 机械臂舵机编号、PWM 或微调步长超出 SDK 固定安全范围。

校验失败返回 `CODE_NOT_ALLOWED`，包含学生代码行号、简短原因和修改建议，不显示校验器内部堆栈。

AST 校验不能证明 Python 安全。即使代码通过校验，也必须进入操作系统沙箱。

## 5. 操作系统沙箱

建议使用 `bubblewrap` 配置独立的 mount、PID、IPC、UTS 和 network namespace：

- 根文件系统最小化且只读。
- 不绑定 `/dev` 中的摄像头、串口、GPIO、音频和 USB 设备节点。
- 不提供网络接口和 DNS 配置。
- 只读绑定 Python 运行时、标准库的允许子集和 `aibox` SDK。
- 只读绑定本次运行快照；只写绑定独立临时目录。
- 只绑定会话专用 Device Service socket，不绑定系统 D-Bus 或其他服务 socket。
- 设置 `no_new_privs`，使用无特权用户运行；生产镜像中不提供编译器和包管理器。

学生保存操作由 Studio 执行，不向学生进程开放任意文件写入。`Image.save(name)` 由 Device Service 校验简单文件名后写入指定学生目录。

## 6. 资源限制

第一版建议默认值如下，最终数值需在 RK3588 实机压测后固化：

| 项目 | 默认限制 |
|---|---|
| 顶层执行时间 | 使用实验 `timeout_seconds`，最大 300 秒 |
| 停止宽限期 | 2 秒协作取消 + 1 秒强制退出 |
| 内存 | 256 MiB；本地模型内存不计入 Runner |
| CPU | 单核运行配额，避免占满桌面 |
| 进程/线程数 | 8 |
| 临时文件 | 16 MiB |
| 标准输出 | 默认 64 KiB，按课程包上限截断 |
| 单行输出 | 4 KiB |
| 打开文件数 | 32 |

限制通过 systemd transient scope 或 cgroup v2、`setrlimit` 和 Runner 自身计数共同实施。达到限制时先取消设备会话，再结束 Runner。

## 7. Runner 与 Studio 消息

Runner 的标准输出不兼作控制协议。控制消息使用独立本地通道，并采用长度前缀 JSON：

```json
{
  "protocol": 1,
  "type": "state",
  "run_id": "01J...",
  "sequence": 12,
  "timestamp_ms": 1791450000000,
  "payload": {"state": "RUNNING"}
}
```

消息类型：

| 类型 | 方向 | 用途 |
|---|---|---|
| `ready` | Runner -> Studio | 沙箱和 SDK 已就绪 |
| `state` | Runner -> Studio | 状态变化 |
| `stdout` | Runner -> Studio | `print()` 输出块 |
| `diagnostic` | Runner -> Studio | 学生可见错误位置和错误码 |
| `effect` | Runner -> Studio | 关联 Device Service 效果流 |
| `cancel` | Studio -> Runner | 请求协作停止 |
| `heartbeat` | 双向 | 检测失联 |
| `finished` | Runner -> Studio | 返回最终状态和统计信息 |

所有消息必须匹配当前 `run_id`，`sequence` 单调递增。旧运行迟到消息直接丢弃，防止快速重复运行时污染界面。

## 8. 状态机

```text
IDLE -> VALIDATING -> ACQUIRING -> STARTING -> RUNNING
           |             |            |           |
           +-----------> FAILED <------+-----------+
                                                   |
                              持续效果存在 --------+-> OBSERVING
                                                   |
任何活动状态 -> STOPPING -> CLEANING -> IDLE / CLEANUP_FAILED
```

- `RUNNING`：学生顶层代码仍在执行。
- `OBSERVING`：顶层代码已结束，持续效果仍由当前会话持有。
- `FAILED`：运行失败，但仍必须经过清理后才能回到 `IDLE`。
- 同一窗口同一时刻只允许一个活动运行；重复点击运行不会创建第二个 Runner。

## 9. 停止与异常清理

停止适用于按钮点击、切换实验、关闭程序、超时、Runner 崩溃和 Studio 失联：

1. Studio 立即禁用运行按钮并显示“正在停止”。
2. Device Service 先收到取消请求，优先停止机械臂、云台、音频和模型任务。
3. Runner 收到 `cancel`，SDK 中阻塞调用抛出内部取消异常。
4. 宽限期结束仍未退出时，对 Runner 进程组发送 `SIGTERM`，随后 `SIGKILL`。
5. Device Service 撤销令牌、停止持续任务并释放会话全部资源。
6. Studio 收到清理结果后回到 `IDLE`；清理失败进入 `CLEANUP_FAILED` 并禁止再次运行相关设备。

机械臂急停请求不等待 Python 进程响应。停止按钮目标是 500 ms 内将停止请求送达 Device Service，但机械结构完成制动时间由硬件验收单独规定。

## 10. 错误呈现与日志

错误分为学生代码错误、权限错误、设备错误和平台错误。学生界面只显示：

```text
第 6 行：变量 result 还没有定义。
建议：请先给 result 赋值，再打印它。
```

语法错误和常见运行异常提供中文解释；底层 Python 堆栈、socket 路径和驱动信息写入 `/var/log/aibox/`。日志不得记录录音内容、摄像头图像、完整学生代码或本地 AI 对话正文，除非进入明确的维护诊断模式。

## 11. 安全验收

- 不能读取 `/etc/shadow`、其他学生文件、模型文件或设备节点。
- 不能创建网络连接、子进程、后台守护进程或逃逸到系统 Python。
- 拒绝导入别名绕过、双下划线遍历、对象反射和动态代码执行。
- 无限循环、递归、内存膨胀和无限输出均能在限制内终止。
- Runner 被 `SIGKILL` 后，Device Service 能在租约到期内释放全部资源。
- 连续运行和停止 100 次，无遗留 Runner、socket、共享内存或资源锁。
- 快速切换实验时，旧 `run_id` 的输出和视频事件不会进入新实验面板。

