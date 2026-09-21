# Task 7 Report: Chinese Voice, Nursery, and Assistant Integration

## Scope

Implemented headless, lazy runtime integration for `voice_input_test`,
`nursery_rhyme`, `voice_robot_arm`, and `ai_assistant`. The implementation
does not start legacy Tkinter or FastAPI applications.

## Design

- `adapters/audio.py` owns only its own `aplay` Popen object. It terminates,
  waits, then kills only that tracked process if required; it never uses
  `pkill`. Registered temporary WAV files are removed when playback stops.
- `workers/voice.py` dynamically imports the deployed legacy `voice_engine`
  and `speech_context` only when a voice worker starts. The worker owns the
  ALSA PCM handle, closes it before joining its listener thread and before
  emitting `stopped`, and calls the legacy engine's `stop()` afterwards.
- Nursery playback accepts `{song_id: twinkle|two_tigers}` and the compatible
  Chinese `song` value. It preserves the deployed assets and converts to
  48 kHz, stereo, `pcm_s16le`; Two Tigers remains trimmed to 16.1 seconds.
- `workers/assistant.py` uses the legacy Qwen GGUF path and generation
  parameters, a Chinese system prompt, turn-stale cancellation, a latest-wins
  TTS queue, lazy Sherpa VITS loading, and tracked playback.
- Voice robot commands use legacy `match_command`; the original mappings are
  retained, including `复位 -> all_center()` and immediate `停止`.
- `voice.conf` sets `VOICE_LANGUAGE=zh` and preserves deployed model paths.

## TDD Evidence

Initial RED:

```text
python -m pytest tests/test_voice_workers.py -v
ModuleNotFoundError: feature_demo.adapters.audio
```

Second RED after adding the first lifecycle implementation:

```text
2 failed, 7 passed
VoiceWorker.__init__() got an unexpected keyword argument 'asset_dir'
VoiceWorker.__init__() got an unexpected keyword argument 'command_matcher'
```

Third RED for assistant speech output:

```text
1 failed, 9 passed
AssistantWorker.__init__() got an unexpected keyword argument 'tts_factory'
```

The tests cover PCM-before-stopped, owned-Popen cleanup, Chinese locale and
prompt, four runtime dispatches, robot release order, Two Tigers conversion,
legacy robot matching/center action, assistant stale turns, and lazy TTS.

## Final Verification

```text
python -m pytest tests/test_voice_workers.py -v  # 10 passed
python -m pytest tests -v                        # 71 passed, 1 existing dependency warning
python -m compileall -q feature_demo tests       # exit 0
git diff --check                                 # exit 0
```

## Remaining Risk

This Windows environment cannot open the RK3588 ALSA device, run `ffmpeg`,
or load Sherpa/llama model files. Those paths are lazy and kept at their
deployed locations, but physical-device acceptance remains required before
deployment.
