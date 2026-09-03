from pathlib import Path

import paramiko


HOST = "192.168.11.109"
ROOT = Path(r"G:\codexwork\人工智能实验箱\子项目\RK3588_语音识别_机械臂\latest_from_3588\extracted")
PROJECT = Path(r"G:\codexwork\人工智能实验箱\子项目")
FILES = {
    ROOT / "root" / "robot_arm" / "voice_engine.py": "/root/robot_arm/voice_engine.py",
    ROOT / "root" / "robot_arm" / "test_voice_tuning.py": "/root/robot_arm/test_voice_tuning.py",
    Path(r"G:\codexwork\人工智能实验箱\子项目\ai对话助手\代码\ai_assistant.py"): "/root/robot_arm/ai_assistant.py",
    ROOT / "usr" / "local" / "bin" / "voice_control.sh": "/usr/local/bin/voice_control.sh",
    PROJECT / "输入语音测试" / "启动脚本" / "input_voice_test.sh": "/usr/local/bin/input_voice_test.sh",
    PROJECT / "语音简单控制机械臂" / "启动脚本" / "voice_control.sh": "/usr/local/bin/voice_control.sh",
    PROJECT / "ai对话助手" / "启动脚本" / "ai_assistant.sh": "/usr/local/bin/ai_assistant.sh",
}


def main() -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password="123456", timeout=10)
    try:
        sftp = client.open_sftp()
        try:
            for source, destination in FILES.items():
                sftp.put(str(source), destination)
                print(f"uploaded {source.name} -> {destination}")
        finally:
            sftp.close()

        command = (
            "cd /root/robot_arm && python3 -m unittest -v test_voice_tuning.py "
            "&& python3 -m py_compile voice_engine.py ai_assistant.py "
            "&& grep -nE 'VOICE_MAX_RECORD_SEC|def should_review_asr|def prefer_reviewed_asr' "
            "/root/robot_arm/voice_engine.py /usr/local/bin/voice_control.sh "
            "/usr/local/bin/input_voice_test.sh /usr/local/bin/ai_assistant.sh "
            "&& (ps -eo pid,etimes,args | grep -E '[v]oice_control_app.py|[i]nput_voice_test_app.py' || true)"
        )
        _, stdout, stderr = client.exec_command(command, timeout=45)
        output = stdout.read().decode(errors="replace")
        errors = stderr.read().decode(errors="replace")
        print(output + errors, end="")
        if not output and errors:
            raise RuntimeError(errors)
    finally:
        client.close()


if __name__ == "__main__":
    main()
