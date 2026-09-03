#!/bin/bash
export DISPLAY=${DISPLAY:-:0}
export XAUTHORITY=${XAUTHORITY:-/home/ztl/.Xauthority}
USER_ID=$(id -u)
if [ -z "${XDG_RUNTIME_DIR:-}" ] || [ ! -d "${XDG_RUNTIME_DIR:-}" ] || [ ! -w "${XDG_RUNTIME_DIR:-}" ]; then
  export XDG_RUNTIME_DIR="/run/user/$USER_ID"
fi
export VOICE_DEVICE=${VOICE_DEVICE:-dsnoop:CARD=XFMDPV0018,DEV=0}
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"
if [ ! -d "$RUNTIME_DIR" ] || [ ! -w "$RUNTIME_DIR" ]; then
  RUNTIME_DIR="/tmp"
fi
AUDIO_LOG="$RUNTIME_DIR/ai_assistant_amixer.log"
amixer -c Device sset PCM 100% unmute >"$AUDIO_LOG" 2>&1 || true
export TTS_DEVICE=${TTS_DEVICE:-plughw:CARD=Device,DEV=0}
export ASR_BACKEND=${ASR_BACKEND:-paraformer}
export PARAFORMER_ASR_DIR=${PARAFORMER_ASR_DIR:-/root/sherpa_models/paraformer-large-int8}
export AI_VOICE_GAIN=${AI_VOICE_GAIN:-5.0}
export AI_TRIGGER_PEAK=${AI_TRIGGER_PEAK:-0.045}
export AI_SILENCE_PEAK=${AI_SILENCE_PEAK:-0.026}
export AI_MIN_RECORD_SEC=${AI_MIN_RECORD_SEC:-0.48}
export AI_MAX_RECORD_SEC=${AI_MAX_RECORD_SEC:-5.2}
export AI_POST_SILENCE_SEC=${AI_POST_SILENCE_SEC:-0.58}
export AI_FAST_POST_SILENCE_SEC=${AI_FAST_POST_SILENCE_SEC:-0.38}
export AI_NOISE_TRIGGER_MULT=${AI_NOISE_TRIGGER_MULT:-1.25}
export AI_NOISE_SILENCE_MULT=${AI_NOISE_SILENCE_MULT:-1.05}
export AI_MAX_DYNAMIC_TRIGGER=${AI_MAX_DYNAMIC_TRIGGER:-0.22}
export AI_MAX_DYNAMIC_SILENCE=${AI_MAX_DYNAMIC_SILENCE:-0.14}
export AI_MIN_VALID_PEAK_MARGIN=${AI_MIN_VALID_PEAK_MARGIN:-0.003}
export AI_BARGE_IN_ENABLED=${AI_BARGE_IN_ENABLED:-1}
export AI_BARGE_IN_TRIGGER_PEAK=${AI_BARGE_IN_TRIGGER_PEAK:-0.095}
export AI_SECOND_PASS_ASR=${AI_SECOND_PASS_ASR:-1}
export AI_LLM_PRELOAD=${AI_LLM_PRELOAD:-0}
export AI_LLM_MIN_AVAILABLE_MB=${AI_LLM_MIN_AVAILABLE_MB:-3600}
export AI_TTS_OUTPUT_GAIN=${AI_TTS_OUTPUT_GAIN:-1.45}
export AI_TTS_TARGET_PEAK=${AI_TTS_TARGET_PEAK:-0.72}
export AI_TTS_MAX_GAIN=${AI_TTS_MAX_GAIN:-2400}
export AI_SHERPA_TTS_SPEED=${AI_SHERPA_TTS_SPEED:-0.8}
LOCK_DIR="$RUNTIME_DIR"
exec 9>"$LOCK_DIR/ai_assistant.lock"
if ! flock -n 9; then
  pkill -u "$USER_ID" -f '/root/robot_arm/ai_assistant.py' 2>/dev/null || true
  sleep 0.8
  flock -n 9 || exit 0
fi
cd /root/robot_arm
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1
exec python3 -u /root/robot_arm/ai_assistant.py
