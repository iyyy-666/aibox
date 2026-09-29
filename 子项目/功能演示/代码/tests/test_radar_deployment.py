from pathlib import Path
import runpy


SCRIPT = Path(__file__).resolve().parents[1].parent / "部署" / "deploy_radar_detection.py"
ROBOT_CONFIG = (
    Path(__file__).resolve().parents[3]
    / "RK3588_语音识别_机械臂"
    / "latest_from_3588"
    / "extracted"
    / "root"
    / "robot_arm"
    / "config.py"
)


def test_radar_deployment_is_explicit_and_does_not_embed_credentials():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "RK3588_HOST" in text
    assert "RK3588_PASSWORD" in text
    assert "backup" in text.lower()
    assert "123456" not in text
    assert "feature_demo" in text
    assert "REMOTE_ROBOT" in text
    assert "ROBOT_SOURCE" in text


def test_radar_deployment_uploads_shared_stop_safety_components():
    namespace = runpy.run_path(str(SCRIPT))
    deployed_files = {path.as_posix() for path in namespace["FILES"]}

    assert {
        "代码/feature_demo/adapters/robot.py",
        "代码/feature_demo/worker.py",
        "代码/feature_demo/manager.py",
    } <= deployed_files


def test_upright_pose_uses_calibrated_transfer_base_position():
    namespace = runpy.run_path(str(ROBOT_CONFIG))

    assert namespace["PRESET_POSES"]["直立"]["pwms"][0] == 1432


def test_radar_deployment_uploads_robot_pose_configuration():
    namespace = runpy.run_path(str(SCRIPT))

    assert namespace["ROBOT_CONFIG_SOURCE"] == ROBOT_CONFIG
    assert namespace["REMOTE_CONFIG"] == "/root/robot_arm/config.py"


def test_radar_deployment_uploads_robot_serial_driver():
    namespace = runpy.run_path(str(SCRIPT))

    assert namespace["SERIAL_DRIVER_SOURCE"] == ROBOT_CONFIG.with_name(
        "serial_driver.py"
    )
    assert namespace["REMOTE_SERIAL_DRIVER"] == "/root/robot_arm/serial_driver.py"
