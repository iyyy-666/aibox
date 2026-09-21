from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "部署"


def test_desktop_has_single_chinese_entry():
    entry = (ROOT / "桌面入口" / "功能演示.desktop").read_text(encoding="utf-8")
    assert "Name=功能演示" in entry
    assert "Exec=/usr/local/bin/feature_demo.sh" in entry


def test_launcher_enters_robot_arm_root_before_importing_unified_package():
    launcher = (ROOT / "启动脚本" / "feature_demo.sh").read_text(encoding="utf-8")

    assert 'APP_ROOT="/root/robot_arm"' in launcher
    assert 'cd "$APP_ROOT"' in launcher
    assert 'PYTHONPATH="$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"' in launcher


def test_installer_backs_up_targeted_files_and_keeps_existing_robot_arm_resources():
    script = (DEPLOY / "install_feature_demo.sh").read_text(encoding="utf-8")

    assert "tar -czf" in script
    assert "/root/robot_arm" in script
    assert 'cp -a "$SOURCE_DIR/代码/feature_demo/." "$APP_ROOT/feature_demo/"' in script
    assert "LEGACY_DESKTOP_ENTRIES" in script
    assert "backup_file" in script
    assert "robot-arm.service" in script
    assert "VOICE_LANGUAGE=zh" in script
    assert "ROLLBACK_DIR" in script
    assert "systemctl enable --now feature-demo.service" not in script
    assert "systemctl disable --now robot-arm.service" not in script
    assert "Activation after verification" in script


def test_installer_archives_the_entire_robot_arm_before_copying_unified_package():
    script = (DEPLOY / "install_feature_demo.sh").read_text(encoding="utf-8")

    archive = 'tar -czf "$ROLLBACK_DIR/robot_arm.tar.gz" "$APP_ROOT"'
    copy = 'cp -a "$SOURCE_DIR/代码/feature_demo/." "$APP_ROOT/feature_demo/"'
    assert archive in script
    assert script.index(archive) < script.index(copy)


def test_service_and_verifier_are_deployable():
    assert "ExecStart=/usr/local/bin/feature_demo.sh" in (DEPLOY / "feature-demo.service").read_text(encoding="utf-8")
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")
    assert "fuser" in verifier
    assert "MODULE_IDS" in verifier
    assert "20" in verifier
    assert "--retire-legacy" in verifier
    assert "systemctl disable --now robot-arm.service" in verifier
    assert "check_websocket" in verifier
    assert 'find_spec("websockets")' in verifier
    assert 'find_spec("wsproto")' in verifier


def test_full_acceptance_is_required_before_the_legacy_service_can_be_retired():
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")

    for required in (
        "--full",
        "ACCEPTANCE_MARKER",
        "FEATURE_DEMO_HARDWARE_HOOK",
        "FEATURE_DEMO_ACCEPTANCE_SIGNER",
        "verify_all_module_lifecycles",
        "HIGH_RISK_SEQUENCES",
        "verify_window_close",
        "require_valid_acceptance_marker",
    ):
        assert required in verifier
    assert verifier.index("require_valid_acceptance_marker") < verifier.index("systemctl disable --now robot-arm.service")


def test_verifier_uses_the_same_camera_microphone_robot_and_gimbal_paths_as_runtime():
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")

    assert "/dev/video41" in verifier
    assert "/dev/snd/pcmC5D0c" in verifier
    assert "/dev/esp32_arm" in verifier
    assert "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0" in verifier
