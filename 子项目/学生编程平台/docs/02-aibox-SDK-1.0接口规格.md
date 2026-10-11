# aibox SDK 1.0 接口规格

版本：1.0-draft  
依据：`AI智能试验箱应用实训教程_完整版.docx`

## 1. 设计原则

- 教材中的对象名和方法名是学生 API 合同。
- 构造对象不连接硬件；第一次调用功能时按需申请资源。
- 所有公开方法使用同步、直观的 Python 写法。
- 底层并发、串口、设备路径、模型和 RPC 对学生不可见。
- 识别不到目标不是程序异常，返回清晰的空结果。
- 设备异常抛出 `AIBoxError` 的子类，由平台显示中文提示。

## 2. 通用约定

### 2.1 导入

```python
from aibox import Arm, Camera, Vision, Face, Hand, Voice, AI, Lidar
```

公开包不得导出驱动、设备地址、模型路径或内部客户端。

### 2.2 返回值

- 文本识别优先返回中文 `str`。
- 数量返回 `int`，距离返回毫米单位的 `float`。
- 动作成功返回 `None`，失败抛出中文产品异常。
- 无识别结果统一返回空字符串 `""`；不返回 `None`，降低初学者判断难度。
- 持续显示类方法返回 `None`，效果出现在平台右侧。

### 2.3 生命周期

- 同一运行会话内，对象可以重复使用。
- 学生点击停止时，平台可以取消任何阻塞调用。
- Runner 退出或失联时，设备服务强制释放该会话资源。
- `close()` 和 `stop()` 必须幂等，可重复调用。

## 3. 异常类型

```python
AIBoxError
├─ DeviceNotFoundError
├─ DeviceBusyError
├─ OperationTimeoutError
├─ SafetyError
└─ ModelError
```

教材模板不要求学生捕获这些异常；平台负责转换成中文提示。

## 4. Arm 机械臂

```python
from aibox import Arm

arm = Arm()
arm.reset()
arm.pose("直立")
arm.open()
arm.half_open()
arm.close()
arm.action("抓取")
arm.adjust(1, 30)
arm.servo(1, 1500)
arm.stop()
```

| 方法 | 参数 | 返回 | 行为 |
|---|---|---|---|
| `reset()` | 无 | `None` | 回到教材定义的安全初始姿态 |
| `pose(name)` | `"直立"` 或 `"放平"` | `None` | 执行功能演示已有的预设姿态 |
| `open()` | 无 | `None` | 打开夹爪 |
| `half_open()` | 无 | `None` | 夹爪移动到半开位置 |
| `close()` | 无 | `None` | 闭合夹爪 |
| `action(name)` | 白名单动作名 `str` | `None` | 执行“抓取”“搬运”“左转移”或“右转移”动作组 |
| `command(name)` | 功能演示命令名 `str` | `None` | 执行语音实验使用的固定命令 |
| `adjust(joint, delta=30)` | 关节1至6、增量-100至100 | `None` | 按 PWM 小步微调指定舵机 |
| `servo(joint, pwm)` | 关节1至6、PWM 800至2200 | `None` | 高级实验设置单个舵机的安全目标值 |
| `stop()` | 无 | `None` | 立即请求停止当前动作 |

`command(name)` 只接受现有功能演示的十个命令：`直立`、`放平`、`抓取`、
`搬运`、`复位`、`停止`、`张开`、`闭合`、`右转移`、`左转移`。它主要用于
语音控制实验；普通机械臂实验优先使用含义更明确的 `pose()`、`action()`、
`open()` 和 `close()`。

安全规则：动作串行执行；任何时刻停止优先于普通动作。`servo()` 只能设置单个
舵机且超出 `800–2200` 时抛出 `SafetyError`，不静默截断；`adjust()` 既校验单次
步长，也校验调整后的目标值。安全范围由设备配置固化，学生不能修改或绕过。

## 5. Camera 摄像头

```python
from aibox import Camera

camera = Camera()
camera.show()
camera.close()
```

| 方法 | 参数 | 返回 | 行为 |
|---|---|---|---|
| `show()` | 无 | `None` | 在右侧显示实时画面，非阻塞 |
| `close()` | 无 | `None` | 停止画面并释放摄像头 |

`show()` 自动完成设备申请和打开。第一版不教授摄像头参数、拍照保存、图像文件
处理或设备选择；学生只学习调用实时画面。点击平台“停止”时即使没有调用
`close()`，也会自动释放摄像头。

## 6. Vision 视觉识别

```python
from aibox import Vision

vision = Vision()
print(vision.color())
print(vision.fruit())
print(vision.classify())
print(vision.shape())
```

| 方法 | 返回 | 无结果 | 右侧效果 |
|---|---|---|---|
| `color()` | 颜色中文名称 `str` | `""` | 实时画面、目标框、颜色 |
| `fruit()` | 水果中文名称 `str` | `""` | 实时画面、目标框、水果名 |
| `classify()` | 类别中文名称 `str` | `""` | 实时画面、类别和置信度 |
| `shape()` | 形状中文名称 `str` | `""` | 实时画面、轮廓和形状名 |

第一版不提供通用物体目标检测接口。表中的 `Face.detect()` 和 `Hand.detect()` 是
教材指定的专用检测能力，不代表提供通用 `Vision.detect()`。

## 7. Face 人脸检测

```python
from aibox import Face

face = Face()
count = face.detect()
print(count)
```

| 方法 | 返回 | 行为 |
|---|---|---|
| `detect()` | 人脸数量 `int` | 右侧显示人脸框；无人脸时返回 `0` |

第一版只做人脸检测，不做人脸身份识别，不保存人脸数据。

## 8. Hand 手掌与手势

```python
from aibox import Hand

hand = Hand()
print(hand.detect())
print(hand.gesture())
hand.track()
hand.stop()
```

| 方法 | 返回 | 行为 |
|---|---|---|
| `detect()` | `bool` | 是否检测到手掌 |
| `gesture()` | 手势中文名称 `str` | 返回“石头”“剪刀”“布”等；无结果为 `""` |
| `track()` | `None` | 启动手掌跟踪并在右侧持续显示，非阻塞 |
| `stop()` | `None` | 停止跟踪和云台动作 |

## 9. Voice 离线语音

```python
from aibox import Voice

voice = Voice()
text = voice.listen()
print(text)
voice.speak("你好")
```

| 方法 | 参数 | 返回 | 行为 |
|---|---|---|---|
| `listen(timeout=8)` | 1至30秒 | 识别文字 `str` | 离线录音和ASR；未听清返回 `""` |
| `speak(text)` | 非空文字 | `None` | 离线TTS并播放，支持停止取消 |
| `stop()` | 无 | `None` | 停止录音或播放 |

不允许学生选择声卡、采样率、模型目录或执行外部播放器。

语音控制机械臂只识别功能演示已有命令：`直立`、`放平`、`抓取`、`搬运`、
`复位`、`停止`、`张开`、`闭合`、`右转移`、`左转移`。模板将 `listen()` 的
结果传给 `Arm.command()`，未知文字只提示“未识别到支持的机械臂指令”，不执行动作。

`speak(text)` 将代码中的文字通过实验箱现有 TTS 和声卡输出，完全离线运行。
第一版支持 1 至 200 个字符，空文字或超长文字给出中文参数提示。

## 10. AI 本地对话

```python
from aibox import AI

ai = AI()
answer = ai.chat("什么是人工智能？")
print(answer)
```

| 方法 | 参数 | 返回 | 行为 |
|---|---|---|---|
| `chat(text)` | 1至500字 | 回答 `str` | 调用本地离线模型，不访问互联网 |
| `stop()` | 无 | `None` | 中止当前生成 |

平台固定教学安全提示词、最大输出和超时。第一版不允许学生更换模型、系统提示词或采样参数。

## 11. Lidar 雷达

教材已经使用 `Lidar`，因此公开名称保持不变；内部可以使用 `RadarAdapter`。

```python
from aibox import Lidar

lidar = Lidar()
lidar.show()
distance = lidar.get_distance()
print(distance)
lidar.stop()
```

| 方法 | 参数 | 返回 | 行为 |
|---|---|---|---|
| `start()` | 无 | `None` | 启动A1M8扫描；通常由其他方法自动调用 |
| `show()` | 无 | `None` | 右侧显示雷达扫描，非阻塞 |
| `get_distance()` | 无 | 毫米 `float` | 返回课程固定检测区域内的代表距离；无目标为 `-1.0` |
| `detect()` | 无 | `bool` | 判断固定区域是否发生教材定义的物体变化 |
| `stop()` | 无 | `None` | 停止扫描并释放串口 |

不向学生公开串口、波特率、角度补偿、原始协议或机械臂搬运命令。

## 12. UI事件合同

SDK 调用除返回值外，还向平台发送内部事件：

| 事件 | 用途 |
|---|---|
| `frame.updated` | 更新摄像头最新帧和识别叠加 |
| `radar.scan` | 更新雷达扫描点 |
| `result.updated` | 更新识别文字和置信度 |
| `robot.state` | 更新机械臂动作状态 |
| `audio.state` | 更新监听和播放状态 |
| `assistant.token` | 可选的AI回答增量显示 |
| `session.error` | 显示稳定中文错误码 |

这些事件不属于学生 API，不能从学生代码直接订阅。

## 13. 兼容性规则

- 1.x 版本不得删除或重命名教材已有类和方法。
- 新增可选参数必须有默认值，旧模板无需修改即可运行。
- 返回值类型在 1.x 内保持稳定。
- 底层摄像头、机械臂、模型和雷达实现可以替换。
- 废弃接口至少跨一个教材主版本保留，并在维护日志中提示。

