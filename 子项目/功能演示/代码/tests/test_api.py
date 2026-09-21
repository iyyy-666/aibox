from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from feature_demo.api import create_app
from feature_demo.manager import ModuleManager
from feature_demo.resources import ReleaseReport
from tests.fakes.fake_worker import FakeWorker


class CleanVerifier:
    def verify(self, module, worker_pids):
        return ReleaseReport(ok=True)


@pytest.fixture
def manager(tmp_path):
    return ModuleManager(
        worker_factory=lambda module: FakeWorker(module.module_id),
        verifier=CleanVerifier(),
        lock_path=tmp_path / "api.lock",
    )


@pytest.fixture
def client(manager):
    return TestClient(create_app(manager))


def test_health_check(client):
    assert client.get("/health").json() == {"ok": True}


def test_root_serves_the_single_window_interface(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "功能演示" in response.text


def test_home_listing_does_not_start_a_module(client, manager):
    response = client.get("/api/modules")

    assert response.status_code == 200
    assert len(response.json()["modules"]) == 13
    assert manager.active_module is None


def test_start_conflict_returns_409(client):
    assert client.post("/api/modules/color_recognition/start").status_code == 200

    response = client.post("/api/modules/shape_recognition/start")

    assert response.status_code == 409
    assert response.json()["detail"] == "已有功能正在运行，请先退出当前功能。"


def test_stop_waits_for_cleanup_result(client):
    client.post("/api/modules/color_recognition/start")

    response = client.post("/api/modules/color_recognition/stop")

    assert response.status_code == 200
    assert response.json()["state"] == "idle"


def test_unknown_module_returns_404(client):
    response = client.post("/api/modules/camera_view/start")

    assert response.status_code == 404
    assert response.json()["detail"] == "功能不存在。"


def test_unregistered_command_returns_400(client):
    client.post("/api/modules/color_recognition/start")

    response = client.post(
        "/api/modules/color_recognition/commands/gimbal_center", json={}
    )

    assert response.status_code == 400
    assert "不支持的命令" in response.json()["detail"]


def test_active_endpoint_reports_idle_without_starting_hardware(client, manager):
    response = client.get("/api/modules/active")

    assert response.status_code == 200
    assert response.json()["module_id"] is None
    assert response.json()["state"] == "idle"
    assert manager.active_module is None


def test_module_status_rejects_a_different_active_module(client):
    client.post("/api/modules/color_recognition/start")

    response = client.get("/api/modules/shape_recognition/status")

    assert response.status_code == 409
    assert response.json()["detail"] == "该功能当前未运行。"


def test_registered_command_is_forwarded_to_active_worker(client):
    client.post("/api/modules/color_recognition/start")

    response = client.post(
        "/api/modules/color_recognition/commands/gimbal_left",
        json={"amount": 30},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "command": "gimbal_left"}


def test_frame_endpoint_returns_no_content_until_worker_has_a_frame(client):
    client.post("/api/modules/color_recognition/start")

    response = client.get("/api/modules/color_recognition/frame")

    assert response.status_code == 204
    assert response.content == b""


def test_websocket_sends_current_module_snapshot(client):
    client.post("/api/modules/color_recognition/start")

    with client.websocket_connect("/ws/modules/color_recognition") as socket:
        snapshot = socket.receive_json()

    assert snapshot["module_id"] == "color_recognition"
    assert snapshot["state"] == "running"
