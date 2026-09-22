#!/bin/bash
set -euo pipefail

API_URL="${FEATURE_DEMO_URL:-http://127.0.0.1:8000}"
MODULE_IDS=(ai_assistant object_sorting plate_recognition palm_recognition palm_tracking voice_input_test fruit_recognition color_recognition face_detection robot_button nursery_rhyme shape_recognition voice_robot_arm)
DEVICE_PATHS=(/dev/video41 /dev/snd/pcmC1D0c /dev/snd/pcmC0D0p /dev/esp32_arm /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0)
HIGH_RISK_SEQUENCES=("voice_robot_arm fruit_recognition" "face_detection object_sorting" "ai_assistant nursery_rhyme")
ACCEPTANCE_MARKER="${FEATURE_DEMO_ACCEPTANCE_MARKER:-/var/lib/feature-demo/full-acceptance.marker}"
DESKTOP_DIR="/home/ztl/Desktop"
STAGED_DESKTOP_ENTRY="/usr/local/share/feature-demo/功能演示.desktop"
WINDOW_CLOSE_MODULE="${FEATURE_DEMO_WINDOW_CLOSE_MODULE:-voice_input_test}"
FULL_ACCEPTANCE=false
RETIRE_LEGACY=false
ACTIVE_MODULE=""
ACCEPTANCE_RESULTS=()
MARKER_RESULTS=""

for argument in "$@"; do
  case "$argument" in
    --full) FULL_ACCEPTANCE=true ;;
    --retire-legacy) RETIRE_LEGACY=true ;;
    *) echo "Usage: $0 [--full] [--retire-legacy]" >&2; exit 2 ;;
  esac
done

cleanup_active_module() {
  [[ -n "$ACTIVE_MODULE" ]] || return 0
  curl --silent --show-error -X POST -H 'Content-Type: application/json' -d '{}' "$API_URL/api/modules/$ACTIVE_MODULE/stop" >/dev/null || true
  ACTIVE_MODULE=""
}
trap cleanup_active_module EXIT

require_full_acceptance_dependencies() {
  [[ -n "${FEATURE_DEMO_HARDWARE_HOOK:-}" && -x "$FEATURE_DEMO_HARDWARE_HOOK" ]] || { echo "--full requires executable FEATURE_DEMO_HARDWARE_HOOK for physical/manual checks." >&2; exit 2; }
  [[ -n "${FEATURE_DEMO_ACCEPTANCE_SIGNER:-}" && -x "$FEATURE_DEMO_ACCEPTANCE_SIGNER" ]] || { echo "--full requires executable FEATURE_DEMO_ACCEPTANCE_SIGNER to sign the acceptance marker." >&2; exit 2; }
}

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

check_websocket() {
  python3 <<'PY'
import importlib.util

if not (importlib.util.find_spec("websockets") or importlib.util.find_spec("wsproto")):
    raise SystemExit("Missing WebSocket backend: install websockets or wsproto before running feature-demo.")
print("WebSocket backend available")
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
  if pgrep -f 'feature_demo.workers' >/dev/null; then
    echo "Feature-demo worker process is still running." >&2
    return 1
  fi
  for device in "${DEVICE_PATHS[@]}"; do
    [[ -e "$device" ]] || continue
    if fuser -s "$device" 2>/dev/null; then
      echo "Resource is still busy: $device" >&2
      return 1
    fi
  done
}

run_hardware_hook() {
  "$FEATURE_DEMO_HARDWARE_HOOK" "$@"
}

record_acceptance_result() {
  ACCEPTANCE_RESULTS+=("$1")
}

validate_hook_result() {
  local result_file="$1" required
  shift
  [[ -s "$result_file" ]] || { echo "Hardware hook produced no result file." >&2; return 1; }
  for required in "$@"; do
    grep -Fqx "$required" "$result_file" || { echo "Hardware hook result is missing: $required" >&2; return 1; }
  done
}

run_hardware_hook_with_result() {
  local scenario="$1" result_file
  shift
  result_file=$(mktemp)
  FEATURE_DEMO_API_URL="$API_URL" FEATURE_DEMO_RESULT_FILE="$result_file" FEATURE_DEMO_SCENARIO="$scenario" run_hardware_hook "$scenario" "$@" >&2
  printf '%s\n' "$result_file"
}

run_module_lifecycle() {
  local module_id="$1"
  echo "Lifecycle: $module_id"
  curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d '{}' "$API_URL/api/modules/$module_id/start" >/dev/null
  ACTIVE_MODULE="$module_id"
  run_hardware_hook module "$module_id"
  curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d '{}' "$API_URL/api/modules/$module_id/stop" >/dev/null
  ACTIVE_MODULE=""
  resources_are_released
  record_acceptance_result "module:$module_id=passed"
}

verify_all_module_lifecycles() {
  local module_id
  for module_id in "${MODULE_IDS[@]}"; do
    run_module_lifecycle "$module_id"
  done
}

run_high_risk_sequence() {
  local sequence="$1" result_file sequence_id module_id
  sequence_id=${sequence// /,}
  result_file=$(run_hardware_hook_with_result high-risk-sequence "$sequence_id")
  validate_hook_result "$result_file" "scenario=high-risk-sequence" "sequence=$sequence_id" "resources_released=true"
  for module_id in $sequence; do
    validate_hook_result "$result_file" "stopped=$module_id" "resources_released_after_stop=$module_id"
  done
  rm -f "$result_file"
  resources_are_released
  record_acceptance_result "sequence:$sequence_id=passed"
}

verify_high_risk_sequences() {
  local sequence
  for sequence in "${HIGH_RISK_SEQUENCES[@]}"; do
    echo "High-risk sequence: $sequence"
    run_high_risk_sequence "$sequence"
  done
}

verify_window_close() {
  local result_file
  echo "Window-close scenario: $WINDOW_CLOSE_MODULE"
  curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d '{}' "$API_URL/api/modules/$WINDOW_CLOSE_MODULE/start" >/dev/null
  ACTIVE_MODULE="$WINDOW_CLOSE_MODULE"
  result_file=$(run_hardware_hook_with_result window-close "$WINDOW_CLOSE_MODULE")
  validate_hook_result "$result_file" "scenario=window-close" "active_module=$WINDOW_CLOSE_MODULE" "window_closed=true" "resources_released=true"
  rm -f "$result_file"
  ACTIVE_MODULE=""
  resources_are_released
  record_acceptance_result "window-close:$WINDOW_CLOSE_MODULE=passed"
}

verify_twenty_switches() {
  local index module_id
  for index in $(seq 1 20); do
    module_id="${MODULE_IDS[$(((index - 1) % ${#MODULE_IDS[@]}))]}"
    echo "Switch $index/20: $module_id"
    run_module_lifecycle "$module_id"
    record_acceptance_result "switch:$index=passed"
  done
}

write_acceptance_marker() {
  local timestamp script_hash machine_id board_hostname results_hash payload signature marker_dir
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  script_hash=$(sha256sum "$0" | awk '{print $1}')
  machine_id=$(cat /etc/machine-id)
  board_hostname=$(hostname)
  results_hash=$(printf '%s\n' "${ACCEPTANCE_RESULTS[@]}" | sha256sum | awk '{print $1}')
  payload="full-acceptance|$timestamp|$machine_id|$board_hostname|$script_hash|$results_hash"
  signature=$("$FEATURE_DEMO_ACCEPTANCE_SIGNER" "$payload")
  [[ -n "$signature" ]] || { echo "Acceptance signer returned an empty signature." >&2; exit 1; }
  marker_dir=$(dirname "$ACCEPTANCE_MARKER")
  install -d -m 0700 "$marker_dir"
  umask 077
  printf '%s\n%s\n' "$payload" "$signature" > "$ACCEPTANCE_MARKER.tmp"
  printf '%s\n' "${ACCEPTANCE_RESULTS[@]}" >> "$ACCEPTANCE_MARKER.tmp"
  mv "$ACCEPTANCE_MARKER.tmp" "$ACCEPTANCE_MARKER"
  echo "Signed full-acceptance marker written: $ACCEPTANCE_MARKER"
}

require_valid_acceptance_marker() {
  local payload signature expected_signature script_hash machine_id board_hostname results_hash actual_results_hash
  [[ -f "$ACCEPTANCE_MARKER" ]] || { echo "Refusing to retire legacy service: no full-acceptance marker." >&2; exit 1; }
  [[ -n "${FEATURE_DEMO_ACCEPTANCE_SIGNER:-}" && -x "$FEATURE_DEMO_ACCEPTANCE_SIGNER" ]] || { echo "Refusing to retire legacy service: FEATURE_DEMO_ACCEPTANCE_SIGNER is required to verify the marker." >&2; exit 1; }
  payload=$(sed -n '1p' "$ACCEPTANCE_MARKER")
  signature=$(sed -n '2p' "$ACCEPTANCE_MARKER")
  MARKER_RESULTS=$(sed -n '3,$p' "$ACCEPTANCE_MARKER")
  script_hash=$(sha256sum "$0" | awk '{print $1}')
  machine_id=$(cat /etc/machine-id)
  board_hostname=$(hostname)
  IFS='|' read -r _ timestamp marker_machine_id marker_hostname marker_script_hash results_hash <<< "$payload"
  [[ "$payload" == full-acceptance\|* && "$marker_machine_id" == "$machine_id" && "$marker_hostname" == "$board_hostname" && "$marker_script_hash" == "$script_hash" ]] || { echo "Refusing to retire legacy service: marker is stale, malformed, or belongs to another board." >&2; exit 1; }
  actual_results_hash=$(printf '%s\n' "$MARKER_RESULTS" | sha256sum | awk '{print $1}')
  [[ "$results_hash" == "$actual_results_hash" ]] || { echo "Refusing to retire legacy service: marker acceptance results are invalid." >&2; exit 1; }
  expected_signature=$("$FEATURE_DEMO_ACCEPTANCE_SIGNER" "$payload")
  [[ -n "$signature" && "$signature" == "$expected_signature" ]] || { echo "Refusing to retire legacy service: marker signature is invalid." >&2; exit 1; }
  local module_id sequence required_result
  for module_id in "${MODULE_IDS[@]}"; do
    required_result="module:$module_id=passed"
    printf '%s\n' "$MARKER_RESULTS" | grep -Fqx "$required_result" || { echo "Refusing to retire legacy service: missing $required_result." >&2; exit 1; }
  done
  for sequence in "${HIGH_RISK_SEQUENCES[@]}"; do
    required_result="sequence:${sequence// /,}=passed"
    printf '%s\n' "$MARKER_RESULTS" | grep -Fqx "$required_result" || { echo "Refusing to retire legacy service: missing $required_result." >&2; exit 1; }
  done
  required_result="window-close:$WINDOW_CLOSE_MODULE=passed"
  printf '%s\n' "$MARKER_RESULTS" | grep -Fqx "$required_result" || { echo "Refusing to retire legacy service: missing $required_result." >&2; exit 1; }
  required_result="switch:20=passed"
  printf '%s\n' "$MARKER_RESULTS" | grep -Fqx "$required_result" || { echo "Refusing to retire legacy service: missing $required_result." >&2; exit 1; }
}

retire_legacy_desktop_entries() {
  local stamp backup_dir entry
  [[ -f "$STAGED_DESKTOP_ENTRY" ]] || { echo "Refusing to retire legacy entries: staged desktop entry is missing." >&2; exit 1; }
  stamp=$(date +%Y%m%d_%H%M%S)
  backup_dir="/root/feature-demo-backups/retire-$stamp/desktop"
  mkdir -p "$backup_dir"
  for entry in "$DESKTOP_DIR"/*.desktop; do
    [[ -f "$entry" ]] || continue
    if grep -Eql 'robot[_ -]?arm|voice[_ -]?robot|功能演示' "$entry"; then
      cp -a "$entry" "$backup_dir/"
      rm -f "$entry"
    fi
  done
  install -Dm0644 "$STAGED_DESKTOP_ENTRY" "$DESKTOP_DIR/功能演示.desktop"
  chown ztl:ztl "$DESKTOP_DIR/功能演示.desktop" 2>/dev/null || true
}

check_api
check_websocket
check_resources
resources_are_released
if [[ "$FULL_ACCEPTANCE" == true ]]; then
  require_full_acceptance_dependencies
  verify_all_module_lifecycles
  verify_high_risk_sequences
  verify_twenty_switches
  verify_window_close
  write_acceptance_marker
fi
if [[ "$RETIRE_LEGACY" == true ]]; then
  require_valid_acceptance_marker
  retire_legacy_desktop_entries
  systemctl disable --now robot-arm.service
  echo "Legacy robot-arm.service retired after explicit verification."
fi
echo "Verification complete. HTTP checks alone are not hardware acceptance; run --full before legacy retirement."
