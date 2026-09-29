from __future__ import annotations

import os
import posixpath
from pathlib import Path

import paramiko


HOST = os.environ.get("RK3588_HOST", "192.168.11.106")
USERNAME = os.environ.get("RK3588_USER", "root")
PASSWORD = os.environ.get("RK3588_PASSWORD")
REMOTE_ROOT = "/root/robot_arm/feature_demo"
REMOTE_ROBOT = "/root/robot_arm/robot.py"
REMOTE_CONFIG = "/root/robot_arm/config.py"
REMOTE_SERIAL_DRIVER = "/root/robot_arm/serial_driver.py"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROBOT_SOURCE = (
    PROJECT_ROOT.parent
    / "RK3588_语音识别_机械臂"
    / "latest_from_3588"
    / "extracted"
    / "root"
    / "robot_arm"
    / "robot.py"
)
ROBOT_CONFIG_SOURCE = ROBOT_SOURCE.with_name("config.py")
SERIAL_DRIVER_SOURCE = ROBOT_SOURCE.with_name("serial_driver.py")

FILES = (
    Path("代码/feature_demo/adapters/robot.py"),
    Path("代码/feature_demo/worker.py"),
    Path("代码/feature_demo/manager.py"),
    Path("代码/feature_demo/radar/__init__.py"),
    Path("代码/feature_demo/radar/protocol.py"),
    Path("代码/feature_demo/radar/detection.py"),
    Path("代码/feature_demo/radar/device.py"),
    Path("代码/feature_demo/workers/radar.py"),
    Path("代码/feature_demo/workers/runtime.py"),
    Path("代码/feature_demo/registry.py"),
    Path("代码/feature_demo/resources.py"),
    Path("代码/feature_demo/web/index.html"),
    Path("代码/feature_demo/web/app.js"),
    Path("代码/feature_demo/web/styles.css"),
)


def main() -> None:
    if not PASSWORD:
        raise SystemExit("set RK3588_PASSWORD before deployment")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USERNAME, password=PASSWORD, timeout=10)
    try:
        _, stdout, stderr = client.exec_command(
            "stamp=$(date +%Y%m%d-%H%M%S); "
            f"backup={REMOTE_ROOT}.backup-$stamp; "
            f"cp -a {REMOTE_ROOT} $backup && "
            f"cp -a {REMOTE_ROBOT} {REMOTE_ROBOT}.backup-$stamp && "
            f"cp -a {REMOTE_CONFIG} {REMOTE_CONFIG}.backup-$stamp && "
            f"cp -a {REMOTE_SERIAL_DRIVER} {REMOTE_SERIAL_DRIVER}.backup-$stamp && "
            f"echo BACKUP=$backup ROBOT_BACKUP={REMOTE_ROBOT}.backup-$stamp",
            timeout=20,
        )
        output = stdout.read().decode(errors="replace")
        errors = stderr.read().decode(errors="replace")
        if errors or "BACKUP=" not in output:
            raise SystemExit(errors or output or "remote backup failed")
        sftp = client.open_sftp()
        try:
            sftp.mkdir(f"{REMOTE_ROOT}/radar")
        except OSError:
            pass
        for relative in FILES:
            local = PROJECT_ROOT / relative
            remote = posixpath.join(REMOTE_ROOT, relative.as_posix().removeprefix("代码/feature_demo/"))
            if relative.parts[-2] == "workers":
                remote = posixpath.join(REMOTE_ROOT, "workers", relative.name)
            elif relative.parts[-2] == "adapters":
                remote = posixpath.join(REMOTE_ROOT, "adapters", relative.name)
            elif relative.parts[-2] == "web":
                remote = posixpath.join(REMOTE_ROOT, "web", relative.name)
            elif relative.parts[-2] == "feature_demo":
                remote = posixpath.join(REMOTE_ROOT, relative.name)
            sftp.put(str(local), remote)
            print(f"uploaded {relative.as_posix()} -> {remote}")
        sftp.put(str(ROBOT_SOURCE), REMOTE_ROBOT)
        print(f"uploaded {ROBOT_SOURCE} -> {REMOTE_ROBOT}")
        sftp.put(str(ROBOT_CONFIG_SOURCE), REMOTE_CONFIG)
        print(f"uploaded {ROBOT_CONFIG_SOURCE} -> {REMOTE_CONFIG}")
        sftp.put(str(SERIAL_DRIVER_SOURCE), REMOTE_SERIAL_DRIVER)
        print(f"uploaded {SERIAL_DRIVER_SOURCE} -> {REMOTE_SERIAL_DRIVER}")
        sftp.close()
        command = (
            f"cd {REMOTE_ROOT} && "
            "python3 -m py_compile adapters/robot.py worker.py manager.py "
            "radar/__init__.py radar/protocol.py radar/detection.py radar/device.py "
            "workers/radar.py workers/runtime.py registry.py resources.py && "
            f"python3 -m py_compile {REMOTE_ROBOT} {REMOTE_CONFIG} {REMOTE_SERIAL_DRIVER} && "
            "echo RADAR_DEPLOY_COMPILE_OK"
        )
        _, stdout, stderr = client.exec_command(command, timeout=30)
        output = stdout.read().decode(errors="replace")
        errors = stderr.read().decode(errors="replace")
        print(output, end="")
        if errors or "RADAR_DEPLOY_COMPILE_OK" not in output:
            raise SystemExit(errors or output or "remote compile failed")
    finally:
        client.close()


if __name__ == "__main__":
    main()
