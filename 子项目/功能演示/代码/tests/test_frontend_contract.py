from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup


WEB_DIR = Path(__file__).resolve().parents[1] / "feature_demo" / "web"


@pytest.fixture
def web_document():
    return BeautifulSoup((WEB_DIR / "index.html").read_text(encoding="utf-8"), "html.parser")


@pytest.fixture
def app_javascript():
    return (WEB_DIR / "app.js").read_text(encoding="utf-8")


def test_shell_has_only_feature_demo_navigation(web_document):
    navigation = web_document.select_one("nav")

    assert navigation.select_one('[data-nav="feature-demo"]')
    assert len(navigation.select("a, button")) == 1
    assert "系统设置" not in navigation.get_text()
    assert "帮助中心" not in navigation.get_text()
    assert "关于我们" not in navigation.get_text()


def test_home_exposes_module_grid_without_standalone_camera_or_gimbal(web_document):
    assert web_document.select_one('[data-view="home"]')
    assert web_document.select_one('[data-module-grid]')
    text = web_document.get_text(" ", strip=True)
    assert "摄像头画面" not in text
    assert "云台控制" not in text


def test_module_shell_has_visible_exit_and_status_region(web_document):
    module_view = web_document.select_one('[data-view="module"]')

    assert module_view.select_one('[data-action="exit-module"]')
    assert module_view.select_one('[aria-live="polite"]')


def test_exit_confirmation_has_only_continue_and_exit_actions(web_document):
    dialog = web_document.select_one('[data-exit-dialog]')
    labels = [button.get_text(strip=True) for button in dialog.select("button")]

    assert labels == ["继续演示", "退出功能"]


def test_home_has_no_start_request_on_load(app_javascript):
    initial_section = app_javascript.split("async function openModule", 1)[0]

    assert "/start" not in initial_section
    assert "loadModules" in initial_section


def test_nonvisual_modules_render_real_payload_controls(app_javascript):
    for module_id in ("ai_assistant", "voice_input_test", "nursery_rhyme", "robot_button", "voice_robot_arm"):
        assert module_id in app_javascript
    assert "song_id: \"twinkle\"" in app_javascript
    assert "song_id: \"two_tigers\"" in app_javascript
    assert "servo_id" in app_javascript
    assert "data-assistant-text" in app_javascript
    assert "gimbal_center" not in app_javascript


def test_nonvisual_controls_are_grouped_labeled_and_responsive(app_javascript):
    styles = (WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert "<fieldset" in app_javascript
    assert "<legend>" in app_javascript
    assert "<label for=" in app_javascript
    assert 'aria-live="polite"' in app_javascript
    assert "nonvisual-controls" in app_javascript
    assert ".nonvisual-controls" in styles
    assert "align-items: flex-start" in styles
    assert "overflow-y: auto" in styles
    assert "max-height: calc(100dvh" in styles


def test_nonvisual_worker_details_have_dedicated_outputs(app_javascript):
    for field in ("details.raw", "details.normalized", "details.dialogue", "details.song", "details.lyrics", "details.voice_result"):
        assert field in app_javascript
    for target in ("[data-raw]", "[data-normalized]", "[data-dialogue]", "[data-current-song]", "[data-lyrics]", "[data-voice-result]"):
        assert target in app_javascript


def test_assistant_rejects_empty_questions_and_commands_disable_in_flight(app_javascript):
    assert "请输入要发送的问题" in app_javascript
    assert "const assistantText" in app_javascript
    assert "control.disabled = true" in app_javascript
    assert "control.disabled = false" in app_javascript
    assert "finally" in app_javascript
