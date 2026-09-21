#!/bin/bash
set -euo pipefail
SOURCE_DIR=$(cd "$(dirname "$0")/.." && pwd)
STAMP=$(date +%Y%m%d_%H%M%S)
ROLLBACK_DIR="/root/feature-demo-backups/$STAMP"
APP_ROOT="/root/robot_arm"
DESKTOP_DIR="/home/ztl/Desktop"
LEGACY_DESKTOP_ENTRIES=()
export VOICE_LANGUAGE=zh

if [[ ${EUID} -ne 0 ]]; then
  echo "Please run as root." >&2
  exit 1
fi

backup_file() {
  local path="$1"
  [[ -e "$path" ]] || return 0
  mkdir -p "$ROLLBACK_DIR/files$(dirname "$path")"
  cp -a "$path" "$ROLLBACK_DIR/files$path"
}

mkdir -p "$ROLLBACK_DIR"
if [[ -d "$APP_ROOT/feature_demo" ]]; then
  tar -czf "$ROLLBACK_DIR/feature_demo-package.tar.gz" -C "$APP_ROOT" feature_demo
fi
backup_file /usr/local/bin/feature_demo.sh
backup_file /usr/local/bin/verify_feature_demo.sh
backup_file /etc/systemd/system/feature-demo.service
backup_file "$DESKTOP_DIR/功能演示.desktop"

if [[ -d "$DESKTOP_DIR" ]]; then
  while IFS= read -r entry; do
    LEGACY_DESKTOP_ENTRIES+=("$entry")
  done < <(grep -El 'robot[_ -]?arm|voice[_ -]?robot|功能演示' "$DESKTOP_DIR"/*.desktop 2>/dev/null || true)
fi
for entry in "${LEGACY_DESKTOP_ENTRIES[@]}"; do
  backup_file "$entry"
  rm -f "$entry"
done

# Only the unified package is copied. Existing models, assets, and legacy resources stay in APP_ROOT.
mkdir -p "$APP_ROOT/feature_demo"
cp -a "$SOURCE_DIR/代码/feature_demo/." "$APP_ROOT/feature_demo/"
install -Dm0755 "$SOURCE_DIR/启动脚本/feature_demo.sh" /usr/local/bin/feature_demo.sh
install -Dm0755 "$SOURCE_DIR/部署/verify_feature_demo.sh" /usr/local/bin/verify_feature_demo.sh
install -Dm0644 "$SOURCE_DIR/桌面入口/功能演示.desktop" "$DESKTOP_DIR/功能演示.desktop"
chown ztl:ztl "$DESKTOP_DIR/功能演示.desktop" 2>/dev/null || true
install -Dm0644 "$SOURCE_DIR/部署/feature-demo.service" /etc/systemd/system/feature-demo.service
systemctl daemon-reload
systemctl disable feature-demo.service >/dev/null 2>&1 || true
echo "Installed without starting the GUI service. Verify with: /usr/local/bin/verify_feature_demo.sh"
echo "After verification succeeds, retire the old robot-arm.service explicitly: /usr/local/bin/verify_feature_demo.sh --retire-legacy"
echo "Activation after verification: launch the single 功能演示 desktop entry; leave feature-demo.service disabled to avoid a second PyWebView window."
echo "Rollback: restore files from $ROLLBACK_DIR, then run systemctl daemon-reload."
