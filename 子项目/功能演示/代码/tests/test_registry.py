import os

import pytest

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
    "fruit_recognition",
    "color_recognition",
    "face_detection",
    "robot_button",
    "nursery_rhyme",
    "shape_recognition",
    "voice_robot_arm",
    "radar_detection",
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


def test_removed_voice_input_test_is_not_registered_or_launchable():
    with pytest.raises(KeyError):
        get_module("voice_input_test")
    with pytest.raises(ValueError):
        create_worker("voice_input_test", event_sink=lambda _event: None)


def test_ai_assistant_registry_worker_reaches_process_and_runtime_factory():
    module = get_module("ai_assistant")

    process = _default_worker_factory(module)
    runtime_worker = create_worker(module.worker, event_sink=lambda _event: None)

    assert module.worker == "ai_assistant"
    assert process._command[-1] == "ai_assistant"
    assert process._command_timeout == 90.0
    assert process._environment["VOICE_BACKEND"] == "sherpa"
    assert process._environment["VOICE_SENSEVOICE_FALLBACK"] == "0"
    assert isinstance(runtime_worker, AssistantWorker)


def test_production_factory_allows_eager_asr_workers_a_bounded_longer_startup():
    for module_id in ("nursery_rhyme",):
        process = _default_worker_factory(get_module(module_id))

        assert process._start_timeout == 60.0


def test_production_factory_keeps_lightweight_worker_startup_timeout_short():
    process = _default_worker_factory(get_module("color_recognition"))

    assert process._start_timeout == 15.0
    assert process._command_timeout == 15.0


def test_production_factory_isolates_gimbal_position_state_by_runtime_user(monkeypatch):
    monkeypatch.delenv("AIBOX_GIMBAL_POSITION_STATE", raising=False)
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)

    process = _default_worker_factory(get_module("palm_tracking"))

    assert process._environment["AIBOX_GIMBAL_POSITION_STATE"] == (
        "/tmp/aibox_gimbal_position_1000.json"
    )


def test_production_factory_preserves_explicit_gimbal_position_state(monkeypatch):
    selected = "/tmp/custom-gimbal-state.json"
    monkeypatch.setenv("AIBOX_GIMBAL_POSITION_STATE", selected)

    process = _default_worker_factory(get_module("palm_tracking"))

    assert process._environment["AIBOX_GIMBAL_POSITION_STATE"] == selected


def test_radar_module_owns_radar_and_robot_resources_for_manual_transfer():
    module = get_module("radar_detection")
    worker = create_worker(module.worker, event_sink=lambda _event: None, device_factory=lambda: None)

    assert module.resources == ("radar", "robot")
    assert module.commands == (
        "build_baseline",
        "start_detection",
        "stop_detection",
        "transfer",
    )
    assert worker.__class__.__name__ == "RadarWorker"
