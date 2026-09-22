#!/bin/bash
set -euo pipefail
SOURCE_DIR=$(cd "$(dirname "$0")/.." && pwd)
STAMP=$(date +%Y%m%d_%H%M%S)
ROLLBACK_DIR="/root/feature-demo-backups/$STAMP"
APP_ROOT="/root/robot_arm"
DESKTOP_DIR="/home/ztl/Desktop"
STAGED_DESKTOP_ENTRY="/usr/local/share/feature-demo/功能演示.desktop"
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

archive_directory() {
  local source="$1"
  local name="$2"
  local archive="$ROLLBACK_DIR/$name.tar.gz"
  [[ -e "$source" ]] || { echo "Missing rollback source: $source" >&2; exit 1; }
  tar -czf "$archive" "$source"
  tar -tzf "$archive" >/dev/null
}

mkdir -p "$ROLLBACK_DIR"
[[ -d "$APP_ROOT" ]] || { echo "Missing existing robot arm root: $APP_ROOT" >&2; exit 1; }
archive_directory "$APP_ROOT" "robot_arm"
archive_directory "$DESKTOP_DIR" "desktop"
archive_directory "/usr/local/bin" "launchers"
archive_directory "/etc/systemd/system" "systemd"
backup_file /usr/local/bin/feature_demo.sh
backup_file /usr/local/bin/verify_feature_demo.sh
backup_file /usr/local/bin/feature_demo_hardware_acceptance.sh
backup_file /usr/local/bin/feature_demo_acceptance_signer.sh
backup_file /etc/systemd/system/feature-demo.service
backup_file /etc/default/feature-demo
backup_file /var/lib/feature-demo/full-acceptance.marker

# Only the unified package is copied. Existing models, assets, and legacy resources stay in APP_ROOT.
mkdir -p "$APP_ROOT/feature_demo"
cp -a "$SOURCE_DIR/代码/feature_demo/." "$APP_ROOT/feature_demo/"
install -Dm0755 "$SOURCE_DIR/启动脚本/feature_demo.sh" /usr/local/bin/feature_demo.sh
install -Dm0755 "$SOURCE_DIR/部署/verify_feature_demo.sh" /usr/local/bin/verify_feature_demo.sh
install -Dm0755 "$SOURCE_DIR/部署/hardware_acceptance_hook.sh" /usr/local/bin/feature_demo_hardware_acceptance.sh
install -Dm0755 "$SOURCE_DIR/部署/acceptance_signer.sh" /usr/local/bin/feature_demo_acceptance_signer.sh
install -Dm0644 "$SOURCE_DIR/桌面入口/功能演示.desktop" "$STAGED_DESKTOP_ENTRY"
install -Dm0644 "$SOURCE_DIR/部署/feature-demo.service" /etc/systemd/system/feature-demo.service
install -Dm0644 "$SOURCE_DIR/部署/voice.conf" /etc/default/feature-demo
install -d -m0700 /var/lib/feature-demo
rm -f /var/lib/feature-demo/full-acceptance.marker
if [[ ! -s /var/lib/feature-demo/acceptance.key ]]; then
  umask 077
  openssl rand -out /var/lib/feature-demo/acceptance.key 32
fi
chmod 0600 /var/lib/feature-demo/acceptance.key
systemctl daemon-reload
systemctl disable feature-demo.service >/dev/null 2>&1 || true
echo "Installed without starting the GUI service. Verify with: /usr/local/bin/verify_feature_demo.sh"
echo "Full hardware acceptance: FEATURE_DEMO_HARDWARE_HOOK=/usr/local/bin/feature_demo_hardware_acceptance.sh FEATURE_DEMO_ACCEPTANCE_SIGNER=/usr/local/bin/feature_demo_acceptance_signer.sh /usr/local/bin/verify_feature_demo.sh --full"
echo "After verification succeeds, retire the old robot-arm.service explicitly: /usr/local/bin/verify_feature_demo.sh --retire-legacy"
echo "New application launch for hardware acceptance: /usr/local/bin/feature_demo.sh"
echo "The existing desktop entries remain unchanged until --retire-legacy validates full acceptance."
echo "Rollback: restore files from $ROLLBACK_DIR, then run systemctl daemon-reload."
