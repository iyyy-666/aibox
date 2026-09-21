#!/bin/bash
set -euo pipefail

API_URL="${FEATURE_DEMO_URL:-http://127.0.0.1:8000}"
MODULE_IDS=(ai_assistant object_sorting plate_recognition palm_recognition palm_tracking voice_input_test fruit_recognition color_recognition face_detection robot_button nursery_rhyme shape_recognition voice_robot_arm)
DEVICE_PATHS=(/dev/video41 /dev/esp32_arm /dev/ttyS4 /dev/ttyUSB0)
VERIFY_SWITCHES=false
RETIRE_LEGACY=false

for argument in "$@"; do
  case "$argument" in
    --verify-switches) VERIFY_SWITCHES=true ;;
    --retire-legacy) RETIRE_LEGACY=true ;;
    *) echo "Usage: $0 [--verify-switches] [--retire-legacy]" >&2; exit 2 ;;
  esac
done

check_api() {
  curl --fail --silent --show-error "$API_URL/health" >/dev/null
  local modules
  modules=$(curl --fail --silent --show-error "$API_URL/api/modules")
  python3 - "$modules" "${MODULE_IDS[@]}" <<'PY'
import json
import sys

available = {item["module_id"] for item in json.loads(sys.argv[1])["modules"]}
expected = set(sys.argv[2:])
if available != expected:
    raise SystemExit(f"module registry mismatch: expected {len(expected)}, got {len(available)}")
print(f"API registry: {len(expected)} modules")
PY
}

check_resources() {
  echo "Processes:"
  ps -ef | grep -E '[f]eature_demo|[w]orkers' || true
  echo "Services:"
  systemctl is-enabled feature-demo.service 2>/dev/null || true
  systemctl is-active feature-demo.service 2>/dev/null || true
  systemctl is-enabled robot-arm.service 2>/dev/null || true
  systemctl is-active robot-arm.service 2>/dev/null || true
  echo "Device owners:"
  for device in "${DEVICE_PATHS[@]}"; do
    [[ -e "$device" ]] || continue
    fuser -v "$device" 2>/dev/null || true
  done
}

resources_are_released() {
  for device in "${DEVICE_PATHS[@]}"; do
    [[ -e "$device" ]] || continue
    if fuser -s "$device" 2>/dev/null; then
      echo "Resource is still busy: $device" >&2
      return 1
    fi
  done
}

verify_switches() {
  local index module_id
  for index in $(seq 1 20); do
    module_id="${MODULE_IDS[$(((index - 1) % ${#MODULE_IDS[@]}))]}"
    echo "Switch $index/20: $module_id"
    curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d '{}' "$API_URL/api/modules/$module_id/start" >/dev/null
    curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d '{}' "$API_URL/api/modules/$module_id/stop" >/dev/null
    resources_are_released
  done
}

check_api
check_resources
resources_are_released
if [[ "$VERIFY_SWITCHES" == true ]]; then
  verify_switches
fi
if [[ "$RETIRE_LEGACY" == true ]]; then
  systemctl disable --now robot-arm.service
  echo "Legacy robot-arm.service retired after explicit verification."
fi
echo "Verification complete. GUI service remains disabled; launch 功能演示 from the desktop entry."
