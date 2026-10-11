#!/bin/bash
set -euo pipefail

APP_ROOT=${AIBOX_APP_ROOT:-/opt/aibox-studio}
DESKTOP_DIR=${AIBOX_DESKTOP_DIR:-/home/ztl/Desktop}

[[ -x /usr/local/bin/aibox-studio ]] || { echo "启动器不存在" >&2; exit 1; }
[[ -f "$DESKTOP_DIR/AIBox学生编程平台.desktop" ]] || { echo "桌面入口不存在" >&2; exit 1; }
[[ -d "$APP_ROOT/src/aibox_studio/resources/basic-ai" ]] || { echo "课程资源不存在" >&2; exit 1; }
systemctl is-active --quiet aibox-arm-device.service || { echo "机械臂设备服务未运行" >&2; exit 1; }
[[ -S /run/aibox-device/arm.sock ]] || { echo "机械臂设备 Socket 不存在" >&2; exit 1; }

PYTHONPATH="$APP_ROOT/src:$APP_ROOT/vendor" AIBOX_DEVICE_MODE=simulation QT_QPA_PLATFORM=offscreen python3 - <<'PY'
from PySide6.QtWidgets import QApplication
from aibox_studio.app import build_window
from aibox_studio.course import CourseCatalog, bundled_course_path
from aibox_studio.runner import RunRequest, Runner
from pathlib import Path
import tempfile

catalog = CourseCatalog.load(bundled_course_path())
assert len(catalog.experiments) == 56, len(catalog.experiments)
application = QApplication.instance() or QApplication([])
with tempfile.TemporaryDirectory(prefix="aibox-verify-") as workspace:
    window = build_window(course_root=bundled_course_path(), workspace_root=Path(workspace))
    assert window.catalog.experiments[0].number == 1
    window.close()
result = Runner().run(
    RunRequest(
        code="from aibox import Arm\narm = Arm()\narm.reset()\n",
        allowed_imports=("aibox",),
        capabilities=("arm.reset",),
        timeout_seconds=10,
        output_limit_bytes=4096,
    )
)
assert result.status == "completed", result
assert any(event.get("type") == "robot.state" for event in result.events), result.events
print("界面与课程检查通过：56 个实验")
print("学生代码执行检查通过：Arm.reset()")
PY

echo "功能演示服务状态（只读）："
systemctl is-active feature-demo.service 2>/dev/null || true
systemctl is-active robot-arm.service 2>/dev/null || true
echo "AIBox Studio 验证通过"
