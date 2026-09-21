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


def test_service_and_verifier_are_deployable():
    assert "ExecStart=/usr/local/bin/feature_demo.sh" in (DEPLOY / "feature-demo.service").read_text(encoding="utf-8")
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")
    assert "fuser" in verifier
    assert "MODULE_IDS" in verifier
    assert "20" in verifier
    assert "--retire-legacy" in verifier
    assert "systemctl disable --now robot-arm.service" in verifier
