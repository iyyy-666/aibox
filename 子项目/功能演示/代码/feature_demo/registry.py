from __future__ import annotations

from .models import ModuleDefinition


GIMBAL_COMMANDS = (
    "gimbal_up",
    "gimbal_down",
    "gimbal_left",
    "gimbal_right",
)


def _visual(
    module_id: str,
    name: str,
    description: str,
    worker: str,
    commands: tuple[str, ...] = (),
    resources: tuple[str, ...] = ("camera", "gimbal"),
) -> ModuleDefinition:
    return ModuleDefinition(
        module_id=module_id,
        name=name,
        description=description,
        category="视觉识别",
        worker=worker,
        resources=resources,
        commands=commands + GIMBAL_COMMANDS,
        visual=True,
    )


MODULES = (
    ModuleDefinition(
        module_id="ai_assistant",
        name="AI 对话助手",
        description="通过文字或语音与本地人工智能模型进行中文对话。",
        category="人工智能",
        worker="assistant",
        resources=("microphone", "speaker", "asr", "llm", "tts"),
        commands=("ask", "start_listening", "stop_listening", "interrupt"),
    ),
    _visual(
        "object_sorting",
        "物体分拣",
        "识别红蓝物块并控制机械臂完成分类搬运。",
        "object_sorting",
        commands=("prepare", "start_sorting", "pause_sorting", "stop_sorting"),
        resources=("camera", "gimbal", "robot"),
    ),
    _visual(
        "plate_recognition",
        "车牌识别",
        "识别画面中的车牌颜色、号码与车辆类型。",
        "plate_recognition",
        commands=("save_snapshot",),
    ),
    _visual(
        "palm_recognition",
        "手掌与手势识别",
        "检测手掌并识别石头、剪刀、布手势。",
        "palm_recognition",
        commands=("save_snapshot",),
    ),
    _visual(
        "palm_tracking",
        "手掌跟踪",
        "识别手掌位置并控制云台进行自动跟踪。",
        "palm_tracking",
        commands=("start_tracking", "stop_tracking"),
    ),
    ModuleDefinition(
        module_id="voice_input_test",
        name="语音输入测试",
        description="查看麦克风采集、原始识别文本与规范化结果。",
        category="语音交互",
        worker="voice_input",
        resources=("microphone", "asr"),
        commands=("start_listening", "stop_listening"),
    ),
    _visual(
        "fruit_recognition",
        "水果识别",
        "识别常见水果实物或图片并显示中文名称。",
        "fruit_recognition",
        commands=("save_snapshot",),
    ),
    _visual(
        "color_recognition",
        "颜色识别",
        "检测目标物体并显示其主要颜色。",
        "color_recognition",
        commands=("save_snapshot",),
    ),
    _visual(
        "face_detection",
        "人脸检测",
        "实时检测双目摄像头画面中的人脸。",
        "face_detection",
        commands=("save_snapshot",),
    ),
    ModuleDefinition(
        module_id="robot_button",
        name="按钮控制机械臂",
        description="通过按钮控制机械臂姿态、关节与夹爪。",
        category="机械臂",
        worker="robot_button",
        resources=("robot",),
        commands=("pose", "sequence", "joint_step", "gripper", "stop_motion"),
    ),
    ModuleDefinition(
        module_id="nursery_rhyme",
        name="语音儿歌播放",
        description="通过中文语音选择并播放试验箱中的儿歌。",
        category="语音交互",
        worker="nursery_rhyme",
        resources=("microphone", "speaker", "asr", "tts"),
        commands=("start_listening", "stop_listening", "play", "stop_playback"),
    ),
    _visual(
        "shape_recognition",
        "形状识别",
        "识别画面中的圆形、三角形和矩形等几何形状。",
        "shape_recognition",
        commands=("save_snapshot",),
    ),
    ModuleDefinition(
        module_id="voice_robot_arm",
        name="语音控制机械臂",
        description="识别中文控制指令并驱动机械臂执行动作。",
        category="机械臂",
        worker="voice_robot_arm",
        resources=("microphone", "asr", "robot"),
        commands=("start_listening", "stop_listening", "stop_motion"),
    ),
)

_MODULES_BY_ID = {module.module_id: module for module in MODULES}


def get_module(module_id: str) -> ModuleDefinition:
    return _MODULES_BY_ID[module_id]
