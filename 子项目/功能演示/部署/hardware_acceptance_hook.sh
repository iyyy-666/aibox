#!/bin/bash
set -euo pipefail

API_URL="${FEATURE_DEMO_API_URL:-http://127.0.0.1:8000}"
RESULT_FILE="${FEATURE_DEMO_RESULT_FILE:-}"
STABLE_CAMERA_DEVICE="/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0"
LEGACY_CAMERA_DEVICE="/dev/video41"
METADATA_CAMERA_DEVICE="/dev/video43"

validate_camera_device() {
  local device="$1" canonical
  canonical=$(readlink -f -- "$device" 2>/dev/null || printf '%s' "$device")
  if [[ "$device" == "$METADATA_CAMERA_DEVICE" || "$canonical" == "$METADATA_CAMERA_DEVICE" ]]; then
    echo "Camera device is metadata-only and cannot capture: $device" >&2
    return 2
  fi
}

if [[ -n "${AIBOX_CAMERA_DEVICE:-}" ]]; then
  CAMERA_DEVICE="$AIBOX_CAMERA_DEVICE"
elif [[ -e "$STABLE_CAMERA_DEVICE" ]]; then
  CAMERA_DEVICE="$STABLE_CAMERA_DEVICE"
elif [[ -e "$LEGACY_CAMERA_DEVICE" ]]; then
  CAMERA_DEVICE="$LEGACY_CAMERA_DEVICE"
else
  CAMERA_DEVICE="$STABLE_CAMERA_DEVICE"
fi
validate_camera_device "$CAMERA_DEVICE"
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
  post_command_json "$@" >/dev/null
}

post_command_json() {
  local module_id="$1" command="$2" payload="{}" response
  [[ $# -lt 3 ]] || payload="$3"
  response=$(curl --fail --silent --show-error -X POST -H 'Content-Type: application/json' -d "$payload" \
    "$API_URL/api/modules/$module_id/commands/$command")
  printf '%s' "$response" | python3 -c 'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if data.get("ok") is True else 1)' || return
  printf '%s\n' "$response"
}

current_event_sequence() {
  local module_id="$1"
  curl --fail --silent --show-error "$API_URL/api/modules/$module_id/status" \
    | python3 -c 'import json,sys; print(int((json.load(sys.stdin).get("details") or {}).get("event_sequence", 0)))'
}

json_field() {
  local field="$1"
  python3 -c 'import json,sys; value=json.load(sys.stdin).get(sys.argv[1], ""); print(value)' "$field"
}

match_behavior_event() {
  local behavior="$1" expected="$2" after_sequence="$3"
  python3 -c '
import json, sys

behavior, expected, after = sys.argv[1], sys.argv[2], int(sys.argv[3])
details = json.load(sys.stdin).get("details") or {}
for event in details.get("recent_events") or []:
    sequence = event.get("_sequence")
    if not isinstance(sequence, int) or sequence <= after:
        continue
    ok = False
    if behavior == "assistant_reply":
        ok = event.get("type") == "assistant_reply" and event.get("ok") is True and str(event.get("turn")) == expected and bool(str(event.get("text", "")).strip())
    elif behavior == "speech_result":
        normalized = str(event.get("normalized", "")).strip()
        ok = event.get("type") == "speech" and bool(normalized) and (not expected or expected in normalized)
    elif behavior == "playback_started":
        ok = event.get("type") == "playing" and event.get("ok") is True and str(event.get("token")) == expected
    elif behavior == "robot_action":
        ok = event.get("type") in {"result", "robot_action"} and event.get("ok") is True and (not expected or event.get("command") == expected)
        if event.get("type") == "robot_action":
            ok = ok and bool(str(event.get("recognized", "")).strip())
    elif behavior == "sorting_result":
        ok = event.get("type") == "sorting_result" and event.get("ok") is True and (event.get("color"), event.get("side")) in {("red", "left"), ("blue", "right")}
    elif behavior == "tracking_motion":
        action = event.get("tracking_action") or {}
        ok = event.get("type") == "frame" and event.get("tracking") is True and action.get("state") == "moved"
    elif behavior == "recognition_result":
        result = event.get("result")
        if expected == "plate_text":
            ok = event.get("type") == "frame" and isinstance(result, list) and any(
                isinstance(item, dict) and bool(str(item.get("plate", "")).strip())
                for item in result
            )
        else:
            ok = event.get("type") == "frame" and bool(result) and result != "未检测到手掌"
    if ok:
        print(sequence)
        raise SystemExit(0)
raise SystemExit(1)
' "$behavior" "$expected" "$after_sequence"
}

wait_for_behavior_event() {
  local module_id="$1" behavior="$2" expected="$3" after_sequence="$4" attempt status correlation
  for attempt in $(seq 1 120); do
    status=$(curl --fail --silent --show-error "$API_URL/api/modules/$module_id/status" 2>/dev/null) || { sleep 0.25; continue; }
    correlation=$(printf '%s' "$status" | match_behavior_event "$behavior" "$expected" "$after_sequence" || true)
    if [[ -n "$correlation" ]]; then
      printf '%s\n' "$correlation"
      return 0
    fi
    sleep 0.25
  done
  echo "No correlated $behavior evidence was observed for $module_id." >&2
  return 1
}

require_operator_confirmation() {
  local module_id="$1" prompt="$2" answer
  [[ -r /dev/tty ]] || { echo "Operator confirmation requires an interactive terminal for $module_id." >&2; return 1; }
  printf '%s [yes/no]: ' "$prompt" >/dev/tty
  IFS= read -r answer </dev/tty
  [[ "$answer" == "yes" ]] || { echo "Operator did not confirm physical behavior for $module_id." >&2; return 1; }
  EVIDENCE_OPERATOR="confirmed"
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
  local module_id="$1" baseline response expected correlation
  EVIDENCE_BEHAVIOR=""
  EVIDENCE_SOURCE="event"
  EVIDENCE_CORRELATION=""
  EVIDENCE_OPERATOR=""
  wait_for_state "$module_id" running || return
  if [[ " $VISUAL_MODULES " == *" $module_id "* ]]; then
    wait_for_device_owner "$CAMERA_DEVICE" || return
    verify_visual_frame "$module_id" || return
    post_command "$module_id" gimbal_left '{"amount":1}' || return
    post_command "$module_id" gimbal_right '{"amount":1}' || return
  fi
  case "$module_id" in
    ai_assistant)
      baseline=$(current_event_sequence "$module_id") || return
      response=$(post_command_json "$module_id" ask '{"text":"请用一句话回答：一加一等于几？"}') || return
      expected=$(printf '%s' "$response" | json_field turn) || return
      EVIDENCE_BEHAVIOR="assistant_reply"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "$expected" "$baseline") || return
      ;;
    voice_input_test)
      wait_for_device_owner "$MIC_DEVICE" || return
      baseline=$(current_event_sequence "$module_id") || return
      printf '请对麦克风说一句中文测试短语。\n' >/dev/tty 2>/dev/null || true
      EVIDENCE_BEHAVIOR="speech_result"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "" "$baseline") || return
      ;;
    robot_button)
      wait_for_device_owner "$ROBOT_DEVICE" || return
      baseline=$(current_event_sequence "$module_id") || return
      post_command "$module_id" joint_step '{"servo_id":5,"delta":20,"time_ms":200}' || return
      EVIDENCE_BEHAVIOR="robot_action"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "joint_step" "$baseline") || return
      require_operator_confirmation "$module_id" "Confirm that the robot gripper moved" || return
      post_command "$module_id" stop_motion || return
      ;;
    voice_robot_arm)
      wait_for_device_owner "$MIC_DEVICE" || return
      wait_for_device_owner "$ROBOT_DEVICE" || return
      baseline=$(current_event_sequence "$module_id") || return
      printf '请说“复位”，并观察机械臂动作。\n' >/dev/tty 2>/dev/null || true
      EVIDENCE_BEHAVIOR="robot_action"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "" "$baseline") || return
      require_operator_confirmation "$module_id" "Confirm that the recognized voice command moved the robot" || return
      post_command "$module_id" stop_motion || return
      ;;
    object_sorting)
      wait_for_device_owner "$ROBOT_DEVICE" || return
      post_command "$module_id" prepare || return
      baseline=$(current_event_sequence "$module_id") || return
      post_command "$module_id" start_sorting || return
      printf '请放入红色或蓝色物块，等待机械臂完成分拣。\n' >/dev/tty 2>/dev/null || true
      EVIDENCE_BEHAVIOR="sorting_result"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "" "$baseline") || return
      require_operator_confirmation "$module_id" "Confirm that the object was physically sorted to the reported side" || return
      post_command "$module_id" stop_sorting || return
      ;;
    palm_tracking)
      baseline=$(current_event_sequence "$module_id") || return
      post_command "$module_id" start_tracking || return
      EVIDENCE_BEHAVIOR="tracking_motion"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "" "$baseline") || return
      require_operator_confirmation "$module_id" "Confirm that the gimbal physically followed the hand" || return
      post_command "$module_id" stop_tracking || return
      ;;
    nursery_rhyme)
      wait_for_device_owner "$MIC_DEVICE" || return
      baseline=$(current_event_sequence "$module_id") || return
      response=$(post_command_json "$module_id" play '{"song_id":"twinkle"}') || return
      expected=$(printf '%s' "$response" | json_field token) || return
      EVIDENCE_BEHAVIOR="playback_started"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "$expected" "$baseline") || return
      wait_for_device_owner "$SPEAKER_DEVICE" || return
      require_operator_confirmation "$module_id" "Confirm that the nursery rhyme is audible" || return
      post_command "$module_id" stop_playback || return
      ;;
    plate_recognition)
      baseline=$(current_event_sequence "$module_id") || return
      EVIDENCE_BEHAVIOR="recognition_result"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "plate_text" "$baseline") || return
      ;;
    palm_recognition|fruit_recognition|color_recognition|face_detection|shape_recognition)
      baseline=$(current_event_sequence "$module_id") || return
      EVIDENCE_BEHAVIOR="recognition_result"
      EVIDENCE_CORRELATION=$(wait_for_behavior_event "$module_id" "$EVIDENCE_BEHAVIOR" "" "$baseline") || return
      ;;
  esac
  [[ -n "$EVIDENCE_BEHAVIOR" && -n "$EVIDENCE_CORRELATION" ]] || {
    echo "No primary behavior evidence was configured for $module_id." >&2
    return 1
  }
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
  verify_running_module "$module_id" || {
    echo "Module $module_id was not active and verified before window close." >&2
    return 1
  }
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

run_module_check() {
  local module_id="$1"
  [[ -n "$RESULT_FILE" ]] || { echo "Module result file is required." >&2; exit 2; }
  verify_running_module "$module_id"
  printf 'scenario=module\nmodule=%s\nevidence_behavior=%s\nevidence_source=%s\nevidence_correlation=%s\n' \
    "$module_id" "$EVIDENCE_BEHAVIOR" "$EVIDENCE_SOURCE" "$EVIDENCE_CORRELATION" > "$RESULT_FILE"
  [[ -z "$EVIDENCE_OPERATOR" ]] || printf 'operator_evidence=%s\n' "$EVIDENCE_OPERATOR" >> "$RESULT_FILE"
}

case "${1:-}" in
  module) run_module_check "$2" ;;
  high-risk-sequence) run_sequence "$2" ;;
  window-close) close_window "$2" ;;
  *) echo "Usage: $0 {module MODULE|high-risk-sequence CSV|window-close MODULE}" >&2; exit 2 ;;
esac
