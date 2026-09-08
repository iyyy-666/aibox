import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("ai_assistant.py")


def load_module():
    spec = importlib.util.spec_from_file_location("ai_assistant_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normal_questions_are_not_treated_as_greetings():
    module = load_module()

    assert module.is_fast_greeting("你好")
    assert not module.is_fast_greeting("请介绍一下人工智能")
    assert not module.is_fast_greeting("1+1等于多少")


def test_launcher_uses_preload_and_fifty_percent_output():
    launcher = MODULE_PATH.with_name("..") / "启动脚本" / "ai_assistant.sh"
    text = launcher.resolve().read_text(encoding="utf-8")
    assert "AI_LLM_PRELOAD=${AI_LLM_PRELOAD:-1}" in text
    assert "amixer -c 0 sset PCM 50% unmute" in text
