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
