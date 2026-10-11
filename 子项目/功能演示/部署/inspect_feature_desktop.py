from __future__ import annotations

import getpass
import os
from pathlib import Path

import paramiko


COMMAND = r'''set -u
echo PROCESSES
pgrep -af 'feature_demo|fruit_recognition|chromium|firefox|webview|cef' || true
echo LAUNCHER_ENV
launcher_pid=$(pgrep -f '^python3 -m feature_demo.launcher$' | head -n1)
if [ -n "$launcher_pid" ]; then
  tr '\0' '\n' < /proc/$launcher_pid/environ | grep -E '^(DISPLAY|WAYLAND_DISPLAY|XAUTHORITY|AIBOX_)=' || true
fi
echo SCREENSHOT_TOOLS
command -v gnome-screenshot || true
command -v scrot || true
command -v import || true
command -v grim || true
echo DISPLAYS
ls -la /tmp/.X11-unix 2>/dev/null || true
rm -f /tmp/feature-desktop.png
for display in :0 :1 :2; do
  if DISPLAY=$display xdpyinfo >/dev/null 2>&1; then
    echo ACTIVE_DISPLAY=$display
    if command -v import >/dev/null 2>&1; then
      DISPLAY=$display import -window root /tmp/feature-desktop.png 2>/dev/null && echo SCREENSHOT_OK=import
    elif command -v scrot >/dev/null 2>&1; then
      DISPLAY=$display scrot /tmp/feature-desktop.png && echo SCREENSHOT_OK=scrot
    elif command -v gnome-screenshot >/dev/null 2>&1; then
      DISPLAY=$display gnome-screenshot -f /tmp/feature-desktop.png && echo SCREENSHOT_OK=gnome
    fi
    if [ ! -s /tmp/feature-desktop.png ]; then
      DISPLAY=$display XAUTHORITY=/run/user/1000/gdm/Xauthority python3 - <<'PY' || true
try:
    from PIL import ImageGrab
    image = ImageGrab.grab()
    image.save('/tmp/feature-desktop.png')
    print('SCREENSHOT_OK=pillow')
except Exception as exc:
    print('SCREENSHOT_ERROR=' + repr(exc))
PY
    fi
    break
  fi
done
'''


def main() -> None:
    password = os.environ.get("RK3588_PASSWORD") or getpass.getpass("RK3588 password: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.11.106", username="root", password=password, timeout=10)
    try:
        _, stdout, stderr = client.exec_command(COMMAND, timeout=30)
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        errors = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if errors:
            print(errors, end="")
        if status:
            raise SystemExit(status)
        local = Path(__file__).resolve().parents[1] / "output" / "feature-desktop.png"
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.open_sftp().get("/tmp/feature-desktop.png", str(local))
            print(f"SCREENSHOT={local}")
        except OSError:
            print("SCREENSHOT=unavailable")
    finally:
        client.close()


if __name__ == "__main__":
    main()
