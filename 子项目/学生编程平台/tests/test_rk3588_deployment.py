from __future__ import annotations

import importlib.util
import tarfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_MODULE = PROJECT_ROOT / "tools" / "deploy_to_rk3588.py"


def load_deploy_module():
    spec = importlib.util.spec_from_file_location("deploy_to_rk3588", DEPLOY_MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_bundle_contains_runnable_app_without_development_files(tmp_path):
    deploy = load_deploy_module()

    archive = deploy.build_bundle(PROJECT_ROOT, tmp_path)

    with tarfile.open(archive, "r:gz") as bundle:
        names = set(bundle.getnames())

    assert {
        "aibox-studio/pyproject.toml",
        "aibox-studio/src/aibox/__init__.py",
        "aibox-studio/src/aibox_studio/app.py",
        "aibox-studio/src/aibox_studio/resources/basic-ai/manifest.json",
        "aibox-studio/deploy/install_aibox_studio.sh",
        "aibox-studio/deploy/verify_aibox_studio.sh",
        "aibox-studio/deploy/aibox-studio-launcher.sh",
        "aibox-studio/deploy/aibox-arm-device.service",
        "aibox-studio/deploy/AIBox学生编程平台.desktop",
        "aibox-studio/deploy/wheels/PySide6_Essentials-6.7.3-cp39-abi3-manylinux_2_31_aarch64.whl",
        "aibox-studio/deploy/wheels/shiboken6-6.7.3-cp39-abi3-manylinux_2_31_aarch64.whl",
    } <= names
    assert not any("/.venv/" in name for name in names)
    assert not any("/__pycache__/" in name for name in names)
    assert not any("/tests/" in name for name in names)
    assert not any("/output/" in name for name in names)
    assert not any("/build/" in name for name in names)
    assert not any(".egg-info/" in name for name in names)


def test_build_bundle_is_reproducible_for_unchanged_sources(tmp_path):
    deploy = load_deploy_module()

    first = deploy.build_bundle(PROJECT_ROOT, tmp_path / "first")
    second = deploy.build_bundle(PROJECT_ROOT, tmp_path / "second")

    assert first.read_bytes() == second.read_bytes()


def test_remote_install_command_uses_isolated_student_platform_paths():
    deploy = load_deploy_module()

    command = deploy.remote_install_command("/tmp/aibox-studio.tar.gz")

    assert "/opt/aibox-studio" in command
    assert "/home/ztl/Desktop" in command
    assert "/root/robot_arm" not in command
    assert "feature-demo" not in command


def test_arm_device_service_and_launcher_enable_hardware_without_autonomous_motion():
    service = (PROJECT_ROOT / "deploy" / "aibox-arm-device.service").read_text(encoding="utf-8")
    launcher = (PROJECT_ROOT / "deploy" / "aibox-studio-launcher.sh").read_text(encoding="utf-8")

    assert "User=root" in service
    assert "aibox_device.arm_service" in service
    assert "ExecStartPre" not in service
    assert "AIBOX_DEVICE_MODE=hardware" in launcher
    assert "AIBOX_ARM_SOCKET=/run/aibox-device/arm.sock" in launcher
