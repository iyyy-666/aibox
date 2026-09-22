from feature_demo.registry import MODULES, get_module
from feature_demo.app import _default_worker_factory
from feature_demo.workers.assistant import AssistantWorker
from feature_demo.workers.runtime import create_worker


EXPECTED_MODULE_IDS = [
    "ai_assistant",
    "object_sorting",
    "plate_recognition",
    "palm_recognition",
    "palm_tracking",
    "voice_input_test",
    "fruit_recognition",
    "color_recognition",
    "face_detection",
    "robot_button",
    "nursery_rhyme",
    "shape_recognition",
    "voice_robot_arm",
]

VISUAL_MODULE_IDS = {
    "object_sorting",
    "plate_recognition",
    "palm_recognition",
    "palm_tracking",
    "fruit_recognition",
    "color_recognition",
    "face_detection",
    "shape_recognition",
}

DIRECTIONAL_COMMANDS = {
    "gimbal_up",
    "gimbal_down",
    "gimbal_left",
    "gimbal_right",
}


def test_registry_contains_exactly_the_confirmed_modules():
    assert [item.module_id for item in MODULES] == EXPECTED_MODULE_IDS


def test_camera_and_gimbal_are_not_standalone_modules():
    ids = {item.module_id for item in MODULES}
    assert "camera_view" not in ids
    assert "gimbal_control" not in ids


def test_visual_modules_expose_only_directional_gimbal_commands():
    visual_modules = {item.module_id for item in MODULES if item.visual}
    assert visual_modules == VISUAL_MODULE_IDS
    for item in MODULES:
        if item.visual:
            assert DIRECTIONAL_COMMANDS <= set(item.commands)
            assert "gimbal_center" not in item.commands


def test_get_module_rejects_unknown_module():
    try:
        get_module("camera_view")
    except KeyError as exc:
        assert exc.args == ("camera_view",)
    else:
        raise AssertionError("get_module must reject unknown module IDs")


def test_voice_input_registry_uses_the_runtime_worker_identifier():
    assert get_module("voice_input_test").worker == "voice_input_test"


def test_ai_assistant_registry_worker_reaches_process_and_runtime_factory():
    module = get_module("ai_assistant")

    process = _default_worker_factory(module)
    runtime_worker = create_worker(module.worker, event_sink=lambda _event: None)

    assert module.worker == "ai_assistant"
    assert process._command[-1] == "ai_assistant"
    assert isinstance(runtime_worker, AssistantWorker)
