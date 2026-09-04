from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_launcher_uses_dedicated_lock_and_safe_defaults() -> None:
    text = (ROOT / "启动脚本" / "palm_tracking.sh").read_text(encoding="utf-8")

    assert "palm_tracking.lock" in text
    assert "/dev/video41" in text
    assert "usb-1a86_USB_Single_Serial_5C67040336-if00" in text
    assert "PALM_TRACK_MAX_DEGREES_PER_SECOND=${PALM_TRACK_MAX_DEGREES_PER_SECOND:-80}" in text


def test_desktop_entry_has_tracking_name_and_launcher() -> None:
    text = (ROOT / "桌面入口" / "palm_tracking.desktop").read_text(encoding="utf-8")

    assert "Name[zh_CN]=手掌追踪" in text
    assert "Exec=/usr/local/bin/palm_tracking.sh" in text


def test_deployment_marks_desktop_entry_executable_for_desktop_user() -> None:
    text = (ROOT / "deploy_to_rk3588.py").read_text(encoding="utf-8")

    assert "chown ztl:ztl /home/ztl/Desktop/palm_tracking.desktop" in text
    assert "chmod 755 /home/ztl/Desktop/palm_tracking.desktop" in text
