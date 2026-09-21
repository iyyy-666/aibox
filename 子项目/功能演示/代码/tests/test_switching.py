from feature_demo.models import ModuleState
from tests.test_manager import manager, verifier, workers


def test_twenty_sequential_switches_release_every_module(manager):
    sequence = ["color_recognition", "voice_input_test", "robot_button"] * 7
    for module_id in sequence[:20]:
        manager.start_module(module_id)
        result = manager.stop_module(module_id)
        assert result.state == ModuleState.IDLE
        assert manager.active_module is None
