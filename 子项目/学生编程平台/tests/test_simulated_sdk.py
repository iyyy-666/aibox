import pytest

from aibox import AI, Arm, Camera, Lidar, SafetyError, Vision, Voice, simulation_events


def test_arm_emits_existing_feature_demo_action():
    simulation_events.clear()

    Arm().pose("直立")

    assert simulation_events[-1] == {
        "type": "robot.state",
        "action": "直立",
        "message": "机械臂执行：直立",
    }


@pytest.mark.parametrize("pwm", [799, 2201])
def test_arm_rejects_pwm_outside_hardware_safe_range(pwm):
    with pytest.raises(SafetyError, match="800 至 2200"):
        Arm().servo(1, pwm)


def test_arm_rejects_joint_outside_six_servos():
    with pytest.raises(SafetyError, match="1 至 6"):
        Arm().adjust(7, 30)


def test_camera_show_opens_only_the_live_view():
    simulation_events.clear()

    Camera().show()

    assert simulation_events[-1]["type"] == "frame.updated"
    assert simulation_events[-1]["mode"] == "live"


def test_arm_command_uses_only_feature_demo_command_set():
    simulation_events.clear()

    Arm().command("右转移")

    assert simulation_events[-1]["action"] == "右转移"
    with pytest.raises(SafetyError, match="不支持"):
        Arm().command("随便转动")


def test_voice_speak_emits_offline_sound_card_event():
    simulation_events.clear()

    Voice().speak("欢迎使用人工智能实验箱")

    assert simulation_events[-1] == {
        "type": "audio.state",
        "state": "played",
        "text": "欢迎使用人工智能实验箱",
        "message": "声卡播放：欢迎使用人工智能实验箱",
    }


def test_vision_and_lidar_return_stable_teaching_values():
    simulation_events.clear()

    color = Vision().color()
    lidar = Lidar()
    lidar.show()

    assert color == "红色"
    assert lidar.get_distance() == 860.0
    assert {event["type"] for event in simulation_events} >= {
        "result.updated",
        "radar.scan",
    }


def test_local_ai_returns_an_offline_answer():
    answer = AI().chat("什么是人工智能？")

    assert "人工智能" in answer

