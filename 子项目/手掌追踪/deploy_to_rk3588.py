from __future__ import annotations

import os
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("RK3588_HOST", "192.168.11.109")
PASSWORD = os.environ.get("RK3588_PASSWORD")
FILES = {
    ROOT / "代码" / "hand_landmarks.py": "/root/robot_arm/hand_landmarks.py",
    ROOT / "代码" / "vision_targeting.py": "/root/robot_arm/vision_targeting.py",
    ROOT / "代码" / "palm_tracking_control.py": "/root/robot_arm/palm_tracking_control.py",
    ROOT / "代码" / "palm_tracking_serial.py": "/root/robot_arm/palm_tracking_serial.py",
    ROOT / "代码" / "palm_tracking_app.py": "/root/robot_arm/palm_tracking_app.py",
    ROOT / "启动脚本" / "palm_tracking.sh": "/usr/local/bin/palm_tracking.sh",
    ROOT / "桌面入口" / "palm_tracking.desktop": "/home/ztl/Desktop/palm_tracking.desktop",
    ROOT / "桌面入口" / "palm_tracking.svg": "/root/robot_arm/assets/icons/palm_tracking.svg",
}


def main() -> None:
    if not PASSWORD:
        raise SystemExit("set RK3588_PASSWORD before deployment")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=10)
    sftp = client.open_sftp()
    for local, remote in FILES.items():
        sftp.put(str(local), remote)
        print(f"uploaded {local.name} -> {remote}")
    sftp.close()
    command = "chmod 755 /usr/local/bin/palm_tracking.sh && chmod 755 /home/ztl/Desktop/palm_tracking.desktop && chown ztl:ztl /home/ztl/Desktop/palm_tracking.desktop && python3 -m py_compile /root/robot_arm/palm_tracking_app.py /root/robot_arm/palm_tracking_control.py /root/robot_arm/palm_tracking_serial.py && test -f /root/robot_arm/assets/icons/palm_tracking.svg"
    _, stdout, stderr = client.exec_command(command, timeout=20)
    output, errors = stdout.read().decode(), stderr.read().decode()
    client.close()
    print(output, end="")
    if errors:
        raise SystemExit(errors)


if __name__ == "__main__":
    main()
