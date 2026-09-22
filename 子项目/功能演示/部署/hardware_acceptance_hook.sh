#!/bin/bash
set -euo pipefail

API_URL="${FEATURE_DEMO_API_URL:-http://127.0.0.1:8000}"
RESULT_FILE="${FEATURE_DEMO_RESULT_FILE:-}"
CAMERA_DEVICE="/dev/video41"
MIC_DEVICE="/dev/snd/pcmC1D0c"
ROBOT_DEVICE="/dev/esp32_arm"
GIMBAL_DEVICE="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
SPEAKER_DEVICE="/dev/snd/pcmC0D0p"
VISUAL_MODULES="object_sorting plate_recognition palm_recognition palm_tracking fruit_recognition color_recognition face_detection shape_recognition"

json_state() {
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("state", ""))'
}

wait_for_state() {
  local module_id="$1" expected="$2" state="" attempt
  for attempt in $(seq 1 120); do
    state=$(curl --fail --silent --show-error "$API_URL/api/modules/$module_id/status" 2>/dev/null | json_state || true)
    [[ "$state" == "$expected" ]] && return 0
    [[ "$state" == "failed" || "$state" == "cleanup_failed" ]] && break
    sleep 0.25
  done
  echo "Module $module_id did not reach $expected (last state: ${state:-unavailable})." >&2
  return 1
}

wait_for_device_owner() {
  local device="$1" attempt
  [[ -e "$device" ]] || { echo "Required device is missing: $device" >&2; return 1; }
  for attempt in $(seq 1 80); do
    fuser -s "$device" 2>/dev/null && return 0
    sleep 0.25
  done
  echo "Expected a live owner for $device." >&2
  return 1
}

resources_released() {
  local device
  pgrep -f 'feature_demo.workers' >/dev/null && return 1
  for device in "$CAMERA_DEVICE" "$MIC_DEVICE" "$ROBOT_DEVICE" "$GIMBAL_DEVICE" "$SPEAKER_DEVICE"; do
    [[ -e "$device" ]] || continue
    fuser -s "$device" 2>/dev/null && return 1
  done
  return 0
}

wait_for_resources_released() {
  local attempt
  for attempt in $(seq 1 80); do
    resources_released && return 0
    sleep 0.25
  done
  echo "Worker or hardware resource remained owned after stop." >&2
  return 1
}

post_command() {
  local module_id="$1" command="$2" payload="{}" response
  [[ $# -lt 3 ]] || payload="$3"
  response=$(curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d "$payload" \
    "$API_URL/api/modules/$module_id/commands/$command")
  printf '%s' "$response" | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("ok") is True else 1)'
}

verify_visual_frame() {
  local module_id="$1" frame_file status attempt
  frame_file=$(mktemp)
  for attempt in $(seq 1 80); do
    status=$(curl --silent --show-error -o "$frame_file" -w '%{http_code}' "$API_URL/api/modules/$module_id/frame")
    if [[ "$status" == "200" && $(wc -c < "$frame_file") -gt 1024 ]]; then
      rm -f "$frame_file"
      return 0
    fi
    sleep 0.25
  done
  rm -f "$frame_file"
  echo "No non-empty camera frame was produced by $module_id." >&2
  return 1
}

verify_running_module() {
  local module_id="$1"
  wait_for_state "$module_id" running || return
  if [[ " $VISUAL_MODULES " == *" $module_id "* ]]; then
    wait_for_device_owner "$CAMERA_DEVICE" || return
    verify_visual_frame "$module_id" || return
    post_command "$module_id" gimbal_left '{"amount":1}' || return
    wait_for_device_owner "$GIMBAL_DEVICE" || return
    post_command "$module_id" gimbal_right '{"amount":1}' || return
  fi
  case "$module_id" in
    ai_assistant)
      post_command "$module_id" start_listening || return
      wait_for_device_owner "$MIC_DEVICE" || return
      ;;
    voice_input_test)
      wait_for_device_owner "$MIC_DEVICE" || return
      ;;
    robot_button)
      wait_for_device_owner "$ROBOT_DEVICE" || return
      post_command "$module_id" stop_motion || return
      ;;
    voice_robot_arm)
      wait_for_device_owner "$MIC_DEVICE" || return
      wait_for_device_owner "$ROBOT_DEVICE" || return
      post_command "$module_id" stop_motion || return
      ;;
    object_sorting)
      wait_for_device_owner "$ROBOT_DEVICE" || return
      post_command "$module_id" stop_sorting || return
      ;;
    nursery_rhyme)
      wait_for_device_owner "$MIC_DEVICE" || return
      post_command "$module_id" play '{"song_id":"twinkle"}' || return
      wait_for_device_owner "$SPEAKER_DEVICE" || return
      post_command "$module_id" stop_playback || return
      ;;
  esac
  return 0
}

stop_module_and_release() {
  local module_id="$1" stop_rc=0 release_rc=0
  curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d '{}' \
    "$API_URL/api/modules/$module_id/stop" >/dev/null || stop_rc=$?
  wait_for_resources_released || release_rc=$?
  (( stop_rc == 0 && release_rc == 0 ))
}

run_sequence_step() (
  local module_id="$1" started=false
  cleanup_started_module() {
    local original_rc=$? cleanup_rc=0
    trap - EXIT
    if [[ "$started" == true ]]; then
      stop_module_and_release "$module_id" || cleanup_rc=$?
    fi
    (( original_rc != 0 )) && exit "$original_rc"
    exit "$cleanup_rc"
  }
  trap cleanup_started_module EXIT

  curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d '{}' \
    "$API_URL/api/modules/$module_id/start" >/dev/null || exit $?
  started=true
  verify_running_module "$module_id" || exit $?
  stop_module_and_release "$module_id" || exit $?
  started=false
  printf 'stopped=%s\nresources_released_after_stop=%s\n' "$module_id" "$module_id" >> "$RESULT_FILE"
)

run_sequence() {
  local sequence_csv="$1" module_id
  [[ -n "$RESULT_FILE" ]] || { echo "Sequence result file is required." >&2; exit 2; }
  printf 'scenario=high-risk-sequence\nsequence=%s\n' "$sequence_csv" > "$RESULT_FILE"
  for module_id in ${sequence_csv//,/ }; do
    run_sequence_step "$module_id" || return
  done
  printf 'resources_released=true\n' >> "$RESULT_FILE"
}

close_window() {
  local module_id="$1" window_id attempt
  [[ -n "$RESULT_FILE" ]] || { echo "Window-close result file is required." >&2; exit 2; }
  command -v xdotool >/dev/null || { echo "xdotool is required for real window-close acceptance." >&2; exit 2; }
  export DISPLAY="${DISPLAY:-:0}"
  export XAUTHORITY="${XAUTHORITY:-/run/user/1000/gdm/Xauthority}"
  window_id=$(xdotool search --name '功能演示' | head -n 1)
  [[ -n "$window_id" ]] || { echo "The 功能演示 window was not found." >&2; exit 1; }
  xdotool windowclose "$window_id"
  for attempt in $(seq 1 80); do
    if ! curl --silent --max-time 0.3 "$API_URL/health" >/dev/null 2>&1; then
      wait_for_resources_released
      printf 'scenario=window-close\nactive_module=%s\nwindow_closed=true\nresources_released=true\n' "$module_id" > "$RESULT_FILE"
      return 0
    fi
    sleep 0.25
  done
  echo "The application API remained alive after the real window close." >&2
  return 1
}

case "${1:-}" in
  module) verify_running_module "$2" ;;
  high-risk-sequence) run_sequence "$2" ;;
  window-close) close_window "$2" ;;
  *) echo "Usage: $0 {module MODULE|high-risk-sequence CSV|window-close MODULE}" >&2; exit 2 ;;
esac
