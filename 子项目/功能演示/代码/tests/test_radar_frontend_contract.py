from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "feature_demo" / "web"


def test_radar_module_is_rendered_by_the_existing_command_workspace():
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'moduleId === "radar_detection"' in app
    assert "建立基准" in app
    assert "开始检测" in app
    assert "停止检测" in app
    assert "雷达状态" in app
    assert "当前变化程度" in app
    assert "data-radar-canvas" in app
    assert "固定位置存在物块" in app
    assert "固定位置不存在物块" in app
    assert "雷达数据无效" in app
    assert "是否搬运" in app


def test_radar_is_not_rendered_as_a_camera_or_robot_module():
    app = (WEB / "app.js").read_text(encoding="utf-8")

    radar_block = app.split('moduleId === "radar_detection"', 1)[1].split('return `<fieldset', 1)[0]
    assert "data-camera-frame" not in radar_block
    assert "robot_button" not in radar_block


def test_radar_frontend_contract_has_scan_rendering_and_manual_confirmation_only():
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert "drawRadarScan" in app
    assert "RADAR_MAX_DISTANCE_MM = 8000" in app
    assert "Math.sin(angleRad)" in app
    assert "-Math.cos(angleRad)" in app
    assert "radar_data_valid" in app
    assert "data-radar-readiness" in app
    assert "data-radar-byte-rate" in app
    assert "data-radar-point-rate" in app
    assert "data-radar-rotation-rate" in app
    assert "data-radar-last-frame" in app
    assert "data-radar-confirm" in app
    assert "radar-workspace" in app
    assert "radar-mode" in app
    assert "sequence\"" not in app.split('moduleId === "radar_detection"', 1)[1].split("if (moduleId ===", 1)[0]


def test_radar_commands_are_gated_by_worker_readiness():
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'control.dataset.command === "build_baseline" && !appState.radarDataReady' in app
    assert 'control.dataset.command === "start_detection" && !appState.radarBaselineReady' in app
    assert "details.data_ready === true" in app
    assert "details.baseline_ready === true" in app


def test_radar_keeps_the_last_scan_and_worker_errors_visible():
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'if (!Array.isArray(details.points)) return;' in app
    assert 'renderWorkerDetails({ type: "error", message: error.message })' in app
