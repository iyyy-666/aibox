from __future__ import annotations

from dataclasses import dataclass

from feature_demo.app import build_application
from feature_demo.launcher import open_main_window
from feature_demo.models import ModuleState
from feature_demo.registry import get_module


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self):
        self.events = type("Events", (), {"closing": FakeEvent()})()


class FakeWebView:
    def __init__(self):
        self.windows = []
        self.start_calls = 0

    def create_window(self, title, url, **options):
        window = FakeWindow()
        self.windows.append((title, url, options, window))
        return window

    def start(self):
        self.start_calls += 1


@dataclass
class FakeShutdownResult:
    state: ModuleState = ModuleState.IDLE


class FakeManager:
    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1
        return FakeShutdownResult()


def test_build_application_does_not_create_a_worker(tmp_path):
    worker_calls = []

    app, manager = build_application(
        worker_factory=lambda module: worker_calls.append(module),
        lock_path=tmp_path / "feature-demo.lock",
    )

    assert app.title == "功能演示"
    assert manager.active_module is None
    assert worker_calls == []


def test_build_application_pins_one_camera_path_for_worker_and_verifier(
    tmp_path, monkeypatch
):
    selected = "/dev/custom-capture"
    monkeypatch.setenv("AIBOX_CAMERA_DEVICE", selected)

    _app, manager = build_application(lock_path=tmp_path / "feature-demo.lock")
    worker = manager._worker_factory(get_module("color_recognition"))

    assert worker._environment["AIBOX_CAMERA_DEVICE"] == selected
    assert manager._verifier._device_paths["camera"] == (selected,)


def test_open_main_window_creates_one_chinese_window_and_starts_event_loop():
    webview = FakeWebView()
    manager = FakeManager()

    open_main_window(webview, "http://127.0.0.1:18080", manager)

    assert len(webview.windows) == 1
    assert webview.windows[0][0] == "功能演示"
    assert webview.windows[0][1] == "http://127.0.0.1:18080"
    assert webview.start_calls == 1


def test_window_close_runs_manager_shutdown_before_allowing_exit():
    webview = FakeWebView()
    manager = FakeManager()

    open_main_window(webview, "http://127.0.0.1:18080", manager)
    close_handler = webview.windows[0][3].events.closing.handlers[0]

    assert close_handler() is True
    assert manager.shutdown_calls == 1
