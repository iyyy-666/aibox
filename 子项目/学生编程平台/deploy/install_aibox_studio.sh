#!/bin/bash
set -euo pipefail

SOURCE_DIR=$(cd "$(dirname "$0")/.." && pwd)
APP_ROOT=${AIBOX_APP_ROOT:-/opt/aibox-studio}
DESKTOP_DIR=${AIBOX_DESKTOP_DIR:-/home/ztl/Desktop}
BACKUP_ROOT=${AIBOX_BACKUP_ROOT:-/opt/aibox-studio-backups}
WORKSPACE_ROOT=${AIBOX_WORKSPACE_ROOT:-/home/ztl/Documents/AIBoxStudio}
STAMP=$(date +%Y%m%d_%H%M%S)
STAGE="${APP_ROOT}.new.$$"
BACKUP="${BACKUP_ROOT}/${STAMP}"

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 root 运行安装脚本。" >&2
  exit 1
fi

case "$(uname -m)" in
  aarch64|arm64) ;;
  *) echo "仅支持 ARM64 RK3588。" >&2; exit 1 ;;
esac

grep -q 'libxcb-cursor.so.0' <<<"$(ldconfig -p)" || {
  echo "缺少桌面运行库 libxcb-cursor0，请先安装后再运行本安装器。" >&2
  exit 1
}

python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("需要 Python 3.9 或更高版本")
print(sys.version)
PY

cleanup() {
  rm -rf "$STAGE"
}
trap cleanup EXIT

mkdir -p "$STAGE" "$BACKUP_ROOT" "$DESKTOP_DIR" "$WORKSPACE_ROOT"
cp -a "$SOURCE_DIR/src" "$STAGE/src"
cp -a "$SOURCE_DIR/pyproject.toml" "$STAGE/pyproject.toml"
[[ ! -f "$SOURCE_DIR/README.md" ]] || cp -a "$SOURCE_DIR/README.md" "$STAGE/README.md"
python3 -m pip install \
  --no-index \
  --no-deps \
  --target "$STAGE/vendor" \
  "$SOURCE_DIR/deploy/wheels/shiboken6-6.7.3-cp39-abi3-manylinux_2_31_aarch64.whl" \
  "$SOURCE_DIR/deploy/wheels/PySide6_Essentials-6.7.3-cp39-abi3-manylinux_2_31_aarch64.whl"

PYTHONPATH="$STAGE/src:$STAGE/vendor" python3 - <<'PY'
import PySide6
from aibox_studio.course import CourseCatalog, bundled_course_path
catalog = CourseCatalog.load(bundled_course_path())
if len(catalog.experiments) != 56:
    raise SystemExit(f"课程数量错误：{len(catalog.experiments)}")
print(f"PySide6 {PySide6.__version__}")
print("课程检查：56 个实验")
PY

mkdir -p "$BACKUP"
[[ ! -e "$APP_ROOT" ]] || mv "$APP_ROOT" "$BACKUP/application"
[[ ! -e /usr/local/bin/aibox-studio ]] || cp -a /usr/local/bin/aibox-studio "$BACKUP/aibox-studio-launcher"
[[ ! -e /usr/local/bin/verify_aibox_studio.sh ]] || cp -a /usr/local/bin/verify_aibox_studio.sh "$BACKUP/verify_aibox_studio.sh"
[[ ! -e "$DESKTOP_DIR/AIBox学生编程平台.desktop" ]] || cp -a "$DESKTOP_DIR/AIBox学生编程平台.desktop" "$BACKUP/desktop-entry"
[[ ! -e /etc/systemd/system/aibox-arm-device.service ]] || cp -a /etc/systemd/system/aibox-arm-device.service "$BACKUP/aibox-arm-device.service"
mv "$STAGE" "$APP_ROOT"

install -m0755 "$SOURCE_DIR/deploy/aibox-studio-launcher.sh" /usr/local/bin/aibox-studio
install -m0755 "$SOURCE_DIR/deploy/verify_aibox_studio.sh" /usr/local/bin/verify_aibox_studio.sh
install -m0755 "$SOURCE_DIR/deploy/AIBox学生编程平台.desktop" "$DESKTOP_DIR/AIBox学生编程平台.desktop"
install -m0644 "$SOURCE_DIR/deploy/aibox-arm-device.service" /etc/systemd/system/aibox-arm-device.service
chown -R ztl:ztl "$WORKSPACE_ROOT" "$DESKTOP_DIR/AIBox学生编程平台.desktop" 2>/dev/null || true
runuser -u ztl -- env \
  XDG_RUNTIME_DIR=/run/user/1000 \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
  gio set "$DESKTOP_DIR/AIBox学生编程平台.desktop" metadata::trusted true 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now aibox-arm-device.service

echo "AIBox Studio 已安装到 $APP_ROOT"
echo "学生文件目录：$WORKSPACE_ROOT（安装不会覆盖）"
echo "旧版本备份：$BACKUP"
