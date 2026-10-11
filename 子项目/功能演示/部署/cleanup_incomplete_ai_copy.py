from __future__ import annotations

import getpass
import os

import paramiko


TARGETS = (
    "/usr/local/lib/python3.10/dist-packages/ultralytics",
    "/usr/local/lib/python3.10/dist-packages/ultralytics-8.3.40.dist-info",
    "/usr/local/lib/python3.10/dist-packages/ultralytics_thop-2.1.6.dist-info",
    "/usr/local/lib/python3.10/dist-packages/torchvision",
    "/usr/local/lib/python3.10/dist-packages/torchvision-0.28.0.dist-info",
)


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.11.106", username="root", password=password, timeout=10)
    try:
        quoted = " ".join(f"'{path}'" for path in TARGETS)
        command = f'''set -eu
base=/usr/local/lib/python3.10/dist-packages
for target in {quoted}; do
  resolved=$(readlink -m "$target")
  case "$resolved" in
    "$base"/*) ;;
    *) echo "unsafe target: $resolved" >&2; exit 2 ;;
  esac
  rm -rf -- "$resolved"
done
echo CLEANED_INCOMPLETE_AI_COPY
'''
        _, stdout, stderr = client.exec_command(command, timeout=30)
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if errors:
            print(errors, end="")
        raise SystemExit(status)
    finally:
        client.close()


if __name__ == "__main__":
    main()
