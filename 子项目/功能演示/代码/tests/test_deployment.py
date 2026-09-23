import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "部署"
CAPTURE_CAPABILITY_STUB = '''
udevadm() { printf 'ID_V4L_CAPABILITIES=:capture:\n'; }
v4l2-ctl() { return 1; }
'''


def run_hook_bash(
    tmp_path: Path,
    body: str,
    *,
    environment: dict[str, str] | None = None,
    prelude: str = CAPTURE_CAPABILITY_STUB,
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
    if not Path(bash).is_file():
        pytest.skip("Bash is required for deployment behavior tests")
    hook = (DEPLOY / "hardware_acceptance_hook.sh").as_posix()
    python = Path(sys.executable).as_posix()
    script = (
        f'python3() {{ "{python}" "$@"; }}\n'
        f"{prelude}\n"
        f'source <(sed \'/^case "${{1:-}}" in/,$d\' "{hook}")\n{body}'
    )
    return subprocess.run(
        [bash, "-c", script],
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env={**os.environ, **(environment or {})},
    )


def run_verifier_bash(
    tmp_path: Path,
    body: str,
    *,
    environment: dict[str, str] | None = None,
    prelude: str = CAPTURE_CAPABILITY_STUB,
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
    if not Path(bash).is_file():
        pytest.skip("Bash is required for deployment behavior tests")
    verifier = (DEPLOY / "verify_feature_demo.sh").as_posix()
    python = Path(sys.executable).as_posix()
    script = (
        f'python3() {{ "{python}" "$@"; }}\n'
        f"{prelude}\n"
        f'source <(sed \'/^check_api$/,$d\' "{verifier}")\n'
        f'ACTIVE_MODULE=""\n{body}'
    )
    return subprocess.run(
        [bash, "-c", script],
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env={**os.environ, **(environment or {})},
    )


def test_desktop_has_single_chinese_entry():
    entry = (ROOT / "桌面入口" / "功能演示.desktop").read_text(encoding="utf-8")
    assert "Name=功能演示" in entry
    assert "Exec=/usr/local/bin/feature_demo.sh" in entry


def test_launcher_enters_robot_arm_root_before_importing_unified_package():
    launcher = (ROOT / "启动脚本" / "feature_demo.sh").read_text(encoding="utf-8")

    assert 'APP_ROOT="/root/robot_arm"' in launcher
    assert 'cd "$APP_ROOT"' in launcher
    assert 'PYTHONPATH="$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"' in launcher


def test_installer_backs_up_targeted_files_and_keeps_existing_robot_arm_resources():
    script = (DEPLOY / "install_feature_demo.sh").read_text(encoding="utf-8")

    assert "tar -czf" in script
    assert "/root/robot_arm" in script
    assert 'cp -a "$SOURCE_DIR/代码/feature_demo/." "$APP_ROOT/feature_demo/"' in script
    assert "backup_file" in script
    assert "robot-arm.service" in script
    assert "VOICE_LANGUAGE=zh" in script
    assert "ROLLBACK_DIR" in script
    assert "systemctl enable --now feature-demo.service" not in script
    assert "systemctl disable --now robot-arm.service" not in script
    assert "New application launch for hardware acceptance" in script


def test_installer_stages_new_desktop_entry_without_replacing_legacy_entries():
    script = (DEPLOY / "install_feature_demo.sh").read_text(encoding="utf-8")

    assert "STAGED_DESKTOP_ENTRY" in script
    assert 'install -Dm0644 "$SOURCE_DIR/桌面入口/功能演示.desktop" "$STAGED_DESKTOP_ENTRY"' in script
    assert 'rm -f "$entry"' not in script
    assert '"$DESKTOP_DIR/功能演示.desktop"' not in script
    assert "/usr/local/bin/feature_demo.sh" in script


def test_installer_archives_the_entire_robot_arm_before_copying_unified_package():
    script = (DEPLOY / "install_feature_demo.sh").read_text(encoding="utf-8")

    archive = 'archive_directory "$APP_ROOT" "robot_arm"'
    copy = 'cp -a "$SOURCE_DIR/代码/feature_demo/." "$APP_ROOT/feature_demo/"'
    assert archive in script
    assert script.index(archive) < script.index(copy)


def test_installer_verifies_complete_rollback_archives_before_any_deployment_write():
    script = (DEPLOY / "install_feature_demo.sh").read_text(encoding="utf-8")

    copy = 'cp -a "$SOURCE_DIR/代码/feature_demo/." "$APP_ROOT/feature_demo/"'
    for archive in (
        'archive_directory "$APP_ROOT" "robot_arm"',
        'archive_directory "$DESKTOP_DIR" "desktop"',
        'archive_directory "/usr/local/bin" "launchers"',
        'archive_directory "/etc/systemd/system" "systemd"',
    ):
        assert archive in script
        assert script.index(archive) < script.index(copy)
    assert 'local source="$1"\n  local name="$2"\n  local archive="$ROLLBACK_DIR/$name.tar.gz"' in script
    assert 'tar -tzf "$archive" >/dev/null' in script


def test_service_and_verifier_are_deployable():
    service = (DEPLOY / "feature-demo.service").read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/bin/feature_demo.sh" in service
    assert "Environment=DISPLAY=:0" in service
    assert "Environment=XAUTHORITY=/run/user/1000/gdm/Xauthority" in service
    assert "Environment=XDG_RUNTIME_DIR=/run/user/1000" in service
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")
    assert "fuser" in verifier
    assert "MODULE_IDS" in verifier
    assert "20" in verifier
    assert "--retire-legacy" in verifier
    assert "systemctl disable --now robot-arm.service" in verifier
    assert "check_websocket" in verifier
    assert 'find_spec("websockets")' in verifier
    assert 'find_spec("wsproto")' in verifier


def test_full_acceptance_is_required_before_the_legacy_service_can_be_retired():
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")

    for required in (
        "--full",
        "ACCEPTANCE_MARKER",
        "FEATURE_DEMO_HARDWARE_HOOK",
        "FEATURE_DEMO_ACCEPTANCE_SIGNER",
        "verify_all_module_lifecycles",
        "HIGH_RISK_SEQUENCES",
        "verify_window_close",
        "require_valid_acceptance_marker",
        "retire_legacy_desktop_entries",
    ):
        assert required in verifier
    assert verifier.index("require_valid_acceptance_marker") < verifier.index("systemctl disable --now robot-arm.service")


def test_acceptance_marker_binds_this_board_and_records_full_acceptance_results():
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")

    for required in (
        "machine-id",
        "hostname",
        "ACCEPTANCE_RESULTS",
        "results_hash",
        "record_acceptance_result",
        "required_result",
    ):
        assert required in verifier


def test_high_risk_and_window_close_hooks_require_verifiable_scenario_results():
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")

    for required in (
        "run_high_risk_sequence",
        "validate_hook_result",
        "high-risk-sequence",
        "WINDOW_CLOSE_MODULE",
        "window-close",
        "window_closed=true",
        "resources_released=true",
    ):
        assert required in verifier


def test_full_acceptance_runs_api_dependent_switches_before_window_close():
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")
    full_block = verifier.split('if [[ "$FULL_ACCEPTANCE" == true ]]; then', 1)[1]

    assert full_block.index("verify_twenty_switches") < full_block.index("verify_window_close")
    assert full_block.index("verify_window_close") < full_block.index("write_acceptance_marker")


def test_verifier_and_hardware_hook_use_the_same_stable_camera_default(tmp_path):
    expected = "/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0"
    verifier = run_verifier_bash(tmp_path, "printf '%s' \"${DEVICE_PATHS[0]}\"")
    hook = run_hook_bash(tmp_path, "printf '%s' \"$CAMERA_DEVICE\"")

    assert verifier.returncode == 0, verifier.stderr
    assert hook.returncode == 0, hook.stderr
    assert verifier.stdout == expected
    assert hook.stdout == expected


def test_verifier_and_hardware_hook_use_the_same_camera_override(tmp_path):
    expected = "/dev/custom-capture"
    environment = {"AIBOX_CAMERA_DEVICE": expected}
    verifier = run_verifier_bash(
        tmp_path,
        "printf '%s' \"${DEVICE_PATHS[0]}\"",
        environment=environment,
    )
    hook = run_hook_bash(
        tmp_path,
        "printf '%s' \"$CAMERA_DEVICE\"",
        environment=environment,
    )

    assert verifier.returncode == 0, verifier.stderr
    assert hook.returncode == 0, hook.stderr
    assert verifier.stdout == expected
    assert hook.stdout == expected


@pytest.mark.parametrize("runner", [run_verifier_bash, run_hook_bash])
def test_deployment_scripts_accept_capture_capable_video43_override(tmp_path, runner):
    selected = "/dev/video43"
    result = runner(
        tmp_path,
        "printf '%s' \"$CAMERA_DEVICE\"",
        environment={"AIBOX_CAMERA_DEVICE": selected},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == selected


@pytest.mark.parametrize("runner", [run_verifier_bash, run_hook_bash])
def test_deployment_scripts_reject_metadata_capability_at_any_number(tmp_path, runner):
    selected = "/dev/video77"
    result = runner(
        tmp_path,
        "printf unreachable",
        environment={"AIBOX_CAMERA_DEVICE": selected},
        prelude="udevadm() { printf 'ID_V4L_CAPABILITIES=:metadata:\\n'; }\n"
        "v4l2-ctl() { return 1; }",
    )

    assert result.returncode != 0
    assert selected in result.stderr


@pytest.mark.parametrize("runner", [run_verifier_bash, run_hook_bash])
def test_deployment_scripts_use_v4l2_device_caps_not_driver_caps(tmp_path, runner):
    selected = "/dev/video88"
    result = runner(
        tmp_path,
        "printf unreachable",
        environment={"AIBOX_CAMERA_DEVICE": selected},
        prelude="udevadm() { return 1; }\n"
        "v4l2-ctl() { printf 'Capabilities     : 0x1\\n\\tVideo Capture\\n"
        "Device Caps      : 0x2\\n\\tMetadata Capture\\n'; }",
    )

    assert result.returncode != 0
    assert selected in result.stderr


def test_voice_config_preserves_caller_camera_override(tmp_path):
    bash = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
    if not Path(bash).is_file():
        pytest.skip("Bash is required for deployment behavior tests")
    config = (DEPLOY / "voice.conf").as_posix()
    selected = "/dev/video77"
    result = subprocess.run(
        [
            bash,
            "-c",
            f'AIBOX_CAMERA_DEVICE="{selected}"; export AIBOX_CAMERA_DEVICE; '
            f'source "{config}"; printf "%s" "$AIBOX_CAMERA_DEVICE"',
        ],
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == selected


@pytest.mark.parametrize("runner", [run_verifier_bash, run_hook_bash])
def test_deployment_scripts_fall_back_from_metadata_stable_link_to_legacy_capture(
    tmp_path, runner
):
    stable = tmp_path / "stable-camera"
    legacy = tmp_path / "legacy-camera"
    stable.touch()
    legacy.touch()
    prelude = f'''udevadm() {{
  if [[ "$*" == *"{legacy.as_posix()}"* ]]; then
    printf 'ID_V4L_CAPABILITIES=:capture:\n'
  else
    printf 'ID_V4L_CAPABILITIES=:metadata:\n'
  fi
}}
v4l2-ctl() {{ return 1; }}'''
    result = runner(
        tmp_path,
        f'''unset AIBOX_CAMERA_DEVICE
STABLE_CAMERA_DEVICE="{stable.as_posix()}"
LEGACY_CAMERA_DEVICE="{legacy.as_posix()}"
resolve_camera_device''',
        prelude=prelude,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == legacy.as_posix()


def test_verifier_uses_the_three_specified_high_risk_sequences():
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")

    assert '"voice_robot_arm fruit_recognition"' in verifier
    assert '"face_detection object_sorting"' in verifier
    assert '"ai_assistant nursery_rhyme"' in verifier


def test_installer_deploys_real_hardware_hook_and_board_local_signer():
    installer = (DEPLOY / "install_feature_demo.sh").read_text(encoding="utf-8")
    hook = (DEPLOY / "hardware_acceptance_hook.sh").read_text(encoding="utf-8")
    signer = (DEPLOY / "acceptance_signer.sh").read_text(encoding="utf-8")

    assert "hardware_acceptance_hook.sh" in installer
    assert "acceptance_signer.sh" in installer
    assert "openssl rand" in installer
    assert "chmod 0600" in installer
    assert "xdotool search --name '\u529f能演示'" in hook
    assert "/api/modules/$module_id/status" in hook
    assert "/api/modules/$module_id/frame" in hook
    assert "fuser -s" in hook
    assert "resources_released_after_stop=" in hook
    release_wait = hook.split("wait_for_resources_released()", 1)[1].split("}", 1)[0]
    assert "seq 1 80" in release_wait
    assert 'nursery_rhyme)' in hook
    assert 'play \'{"song_id":"twinkle"}\'' in hook
    assert "hmac.new" in signer
    assert "FEATURE_DEMO_ACCEPTANCE_KEY" in signer


def test_hardware_hook_preserves_explicit_json_payload(tmp_path):
    trace = (tmp_path / "curl-args.txt").as_posix()
    result = run_hook_bash(
        tmp_path,
        f'''curl() {{ printf '%s\\n' "$@" > "{trace}"; printf '{{"ok":true}}'; }}
post_command demo move '{{"amount":1}}' ''',
    )

    assert result.returncode == 0, result.stderr
    assert Path(trace).read_text(encoding="utf-8").splitlines().count('{"amount":1}') == 1


def test_hardware_hook_rejects_unsuccessful_command_response(tmp_path):
    result = run_hook_bash(
        tmp_path,
        '''curl() { printf '{"ok":false,"message":"hardware rejected"}'; }
post_command demo move '{"amount":1}' ''',
    )

    assert result.returncode != 0


def test_hardware_hook_reports_success_when_no_resources_are_owned(tmp_path):
    result = run_hook_bash(
        tmp_path,
        '''pgrep() { return 1; }
fuser() { return 1; }
CAMERA_DEVICE=/dev/null
MIC_DEVICE=/dev/null
ROBOT_DEVICE=/dev/null
GIMBAL_DEVICE=/dev/null
resources_released''',
    )

    assert result.returncode == 0, result.stderr


def test_high_risk_sequence_stops_started_module_when_check_fails(tmp_path):
    trace = (tmp_path / "sequence.txt").as_posix()
    result_file = (tmp_path / "result.txt").as_posix()
    result = run_hook_bash(
        tmp_path,
        f'''TRACE="{trace}"
RESULT_FILE="{result_file}"
curl() {{ printf '%s\\n' "$*" >> "$TRACE"; return 0; }}
verify_running_module() {{ return 1; }}
wait_for_resources_released() {{ printf 'released\\n' >> "$TRACE"; return 0; }}
set +e
(set -e; run_sequence broken)
rc=$?
grep -q '/api/modules/broken/stop' "$TRACE" || exit 90
test "$rc" -ne 0''',
    )

    assert result.returncode == 0, result.stderr


def test_nursery_rhyme_verification_waits_for_speaker_owner(tmp_path):
    trace = (tmp_path / "nursery.txt").as_posix()
    result = run_hook_bash(
        tmp_path,
        f'''TRACE="{trace}"
MIC_DEVICE=/dev/test-mic
SPEAKER_DEVICE=/dev/test-speaker
wait_for_state() {{ return 0; }}
wait_for_device_owner() {{ printf 'owner=%s\n' "$1" >> "$TRACE"; }}
post_command() {{ printf 'command=%s\n' "$2" >> "$TRACE"; }}
post_command_json() {{ printf 'command=%s\n' "$2" >> "$TRACE"; printf '{{"ok":true,"token":9}}'; }}
current_event_sequence() {{ printf '10\n'; }}
wait_for_behavior_event() {{ printf 'evidence=%s\n' "$2" >> "$TRACE"; printf '11\n'; }}
require_operator_confirmation() {{ printf 'operator=%s\n' "$1" >> "$TRACE"; EVIDENCE_OPERATOR=confirmed; }}
sleep() {{ :; }}
verify_running_module nursery_rhyme''',
    )

    assert result.returncode == 0, result.stderr
    assert Path(trace).read_text(encoding="utf-8").splitlines() == [
        "owner=/dev/test-mic",
        "command=play",
        "evidence=playback_started",
        "owner=/dev/test-speaker",
        "operator=nursery_rhyme",
        "command=stop_playback",
    ]


@pytest.mark.parametrize(
    ("module_id", "failed_step"),
    [
        ("fruit_recognition", "frame"),
        ("face_detection", "gimbal"),
        ("nursery_rhyme", "speaker"),
    ],
)
def test_sequence_propagates_verification_failure_and_cleans_up(
    tmp_path, module_id, failed_step
):
    trace = (tmp_path / f"{failed_step}.txt").as_posix()
    result_file = (tmp_path / f"{failed_step}-result.txt").as_posix()
    result = run_hook_bash(
        tmp_path,
        f'''TRACE="{trace}"
RESULT_FILE="{result_file}"
FAILED_STEP="{failed_step}"
curl() {{ printf '%s\n' "$*" >> "$TRACE"; return 0; }}
wait_for_state() {{ return 0; }}
verify_visual_frame() {{ [[ "$FAILED_STEP" != frame ]]; }}
wait_for_device_owner() {{
  [[ "$FAILED_STEP" != speaker || "$1" != "$SPEAKER_DEVICE" ]]
}}
post_command() {{
  printf 'command=%s\n' "$2" >> "$TRACE"
  [[ "$FAILED_STEP" != gimbal || "$2" != gimbal_left ]]
}}
wait_for_resources_released() {{ printf 'released\n' >> "$TRACE"; return 0; }}
set +e
run_sequence "{module_id}"
rc=$?
grep -q '/api/modules/{module_id}/stop' "$TRACE" || exit 90
test "$rc" -ne 0''',
    )

    assert result.returncode == 0, result.stderr


def test_voice_configuration_is_installed_and_loaded_for_service_and_direct_launch():
    installer = (DEPLOY / "install_feature_demo.sh").read_text(encoding="utf-8")
    service = (DEPLOY / "feature-demo.service").read_text(encoding="utf-8")
    launcher = (ROOT / "启动脚本" / "feature_demo.sh").read_text(encoding="utf-8")

    assert 'install -Dm0644 "$SOURCE_DIR/部署/voice.conf" /etc/default/feature-demo' in installer
    assert "EnvironmentFile=-/etc/default/feature-demo" in service
    assert '. /etc/default/feature-demo' in launcher


def test_regular_hardware_hook_inherits_configured_api_url(tmp_path):
    trace = tmp_path / "hook-url.txt"
    hook = tmp_path / "hook.sh"
    hook.write_text(
        f'#!/bin/sh\nprintf "%s\\n%s" "$FEATURE_DEMO_API_URL" "$AIBOX_CAMERA_DEVICE" > "{trace.as_posix()}"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    result = run_verifier_bash(
        tmp_path,
        f'''FEATURE_DEMO_HARDWARE_HOOK="{hook.as_posix()}"
API_URL=http://127.0.0.1:19090
run_hardware_hook module demo''',
    )

    assert result.returncode == 0, result.stderr
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "http://127.0.0.1:19090",
        "/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0",
    ]


def test_visual_gimbal_check_trusts_ack_without_persistent_device_owner(tmp_path):
    trace = (tmp_path / "owners.txt").as_posix()
    result = run_hook_bash(
        tmp_path,
        f'''TRACE="{trace}"
wait_for_state() {{ return 0; }}
wait_for_device_owner() {{ printf '%s\n' "$1" >> "$TRACE"; [[ "$1" != "$GIMBAL_DEVICE" ]]; }}
verify_visual_frame() {{ return 0; }}
post_command() {{ return 0; }}
current_event_sequence() {{ printf '10\n'; }}
wait_for_behavior_event() {{ printf '11\n'; }}
verify_running_module face_detection''',
    )

    assert result.returncode == 0, result.stderr
    assert Path(trace).read_text(encoding="utf-8").splitlines() == [
        "/dev/v4l/by-id/usb-DECXIN_DECXIN_Camera_01.00.00-video-index0"
    ]


def test_window_close_rejects_a_start_response_that_is_not_running(tmp_path):
    trace = (tmp_path / "window-hook.txt").as_posix()
    result_file = (tmp_path / "window-result.txt").as_posix()
    result = run_verifier_bash(
        tmp_path,
        f'''TRACE="{trace}"
curl() {{ printf '{{"state":"failed"}}'; }}
run_hardware_hook_with_result() {{
  printf 'called\n' > "$TRACE"
  printf 'scenario=window-close\nactive_module=%s\nwindow_closed=true\nresources_released=true\n' "$WINDOW_CLOSE_MODULE" > "{result_file}"
  printf '%s\n' "{result_file}"
}}
resources_are_released() {{ return 0; }}
    set +e
    verify_window_close
    rc=$?
    test "$rc" -ne 0 && test ! -s "$TRACE"''',
    )

    assert result.returncode == 0, result.stderr


def test_module_lifecycle_rejects_missing_primary_behavior_evidence(tmp_path):
    result_file = (tmp_path / "module-result.txt").as_posix()
    result = run_verifier_bash(
        tmp_path,
        f'''curl() {{ printf '{{"state":"running"}}'; }}
run_hardware_hook() {{ return 0; }}
run_hardware_hook_with_result() {{
  printf 'scenario=module\nmodule=demo\n' > "{result_file}"
  printf '%s\n' "{result_file}"
}}
resources_are_released() {{ return 0; }}
set +e
run_module_lifecycle demo
rc=$?
set -e
test "$rc" -ne 0''',
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("behavior", "expected", "event"),
    [
        ("assistant_reply", "7", {"_sequence": 11, "type": "assistant_reply", "ok": True, "turn": 7, "text": "验收回答"}),
        ("speech_result", "test", {"_sequence": 12, "type": "speech", "normalized": "test phrase"}),
        ("playback_started", "9", {"_sequence": 13, "type": "playing", "ok": True, "token": 9, "song": "小星星"}),
        ("robot_action", "joint_step", {"_sequence": 14, "type": "result", "ok": True, "command": "joint_step"}),
        ("sorting_result", "", {"_sequence": 15, "type": "sorting_result", "ok": True, "color": "red", "side": "left"}),
        ("tracking_motion", "", {"_sequence": 16, "type": "frame", "tracking": True, "tracking_action": {"state": "moved"}}),
        ("recognition_result", "", {"_sequence": 17, "type": "frame", "result": [{"label": "apple"}]}),
    ],
)
def test_hardware_hook_accepts_fresh_matching_behavior_event(
    tmp_path, behavior, expected, event
):
    import json

    payload = json.dumps({"details": {"recent_events": [event]}}, ensure_ascii=False)
    result = run_hook_bash(
        tmp_path,
        f'''printf '%s' '{payload}' | match_behavior_event '{behavior}' '{expected}' 10''',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(event["_sequence"])


@pytest.mark.parametrize(
    ("behavior", "expected", "event"),
    [
        ("assistant_reply", "7", {"_sequence": 10, "type": "assistant_reply", "ok": True, "turn": 7, "text": "stale"}),
        ("speech_result", "测试", {"_sequence": 11, "type": "speech", "normalized": "别的内容"}),
        ("playback_started", "9", {"_sequence": 11, "type": "playing", "ok": True, "token": 8}),
        ("robot_action", "joint_step", {"_sequence": 11, "type": "result", "ok": False, "command": "joint_step"}),
        ("sorting_result", "", {"_sequence": 11, "type": "sorting_result", "ok": True, "color": "red", "side": "right"}),
        ("tracking_motion", "", {"_sequence": 11, "type": "frame", "tracking": True}),
        ("recognition_result", "", {"_sequence": 11, "type": "frame", "result": []}),
    ],
)
def test_hardware_hook_rejects_stale_or_nonmatching_behavior_event(
    tmp_path, behavior, expected, event
):
    import json

    payload = json.dumps({"details": {"recent_events": [event]}}, ensure_ascii=False)
    result = run_hook_bash(
        tmp_path,
        f'''set +e
printf '%s' '{payload}' | match_behavior_event '{behavior}' '{expected}' 10
rc=$?
test "$rc" -ne 0''',
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("plate", "expected_success"),
    [("", False), ("ABC123", True)],
)
def test_plate_evidence_requires_nonempty_recognized_plate_text(
    tmp_path, plate, expected_success
):
    import json

    event = {
        "_sequence": 11,
        "type": "frame",
        "result": [{"plate": plate, "color": "blue"}],
    }
    payload = json.dumps({"details": {"recent_events": [event]}})
    expectation = "eq 0" if expected_success else "ne 0"
    result = run_hook_bash(
        tmp_path,
        f'''set +e
printf '%s' '{payload}' | match_behavior_event recognition_result plate_text 10
rc=$?
test "$rc" -{expectation}''',
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("module_id", "behavior", "source", "operator_required"),
    [
        ("ai_assistant", "assistant_reply", "event", False),
        ("object_sorting", "sorting_result", "event", True),
        ("plate_recognition", "recognition_result", "event", False),
        ("palm_recognition", "recognition_result", "event", False),
        ("palm_tracking", "tracking_motion", "event", True),
        ("voice_input_test", "speech_result", "event", False),
        ("fruit_recognition", "recognition_result", "event", False),
        ("color_recognition", "recognition_result", "event", False),
        ("face_detection", "recognition_result", "event", False),
        ("robot_button", "robot_action", "event", True),
        ("nursery_rhyme", "playback_started", "event", True),
        ("shape_recognition", "recognition_result", "event", False),
        ("voice_robot_arm", "robot_action", "event", True),
    ],
)
def test_verifier_accepts_module_specific_correlated_evidence(
    tmp_path, module_id, behavior, source, operator_required
):
    result_file = tmp_path / "module-result.txt"
    operator_line = "operator_evidence=confirmed\n" if operator_required else ""
    result_file.write_text(
        f"scenario=module\nmodule={module_id}\n"
        f"evidence_behavior={behavior}\nevidence_source={source}\n"
        f"evidence_correlation=17\n{operator_line}",
        encoding="utf-8",
    )
    result = run_verifier_bash(
        tmp_path,
        f'''validate_module_evidence "{result_file.as_posix()}" "{module_id}"''',
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "invalid_body",
    [
        "evidence=demo:primary_behavior\n",
        "evidence_behavior=recognition_result\nevidence_source=event\nevidence_correlation=\n",
        "evidence_behavior=assistant_reply\nevidence_source=label\nevidence_correlation=17\n",
        "evidence_behavior=robot_action\nevidence_source=event\nevidence_correlation=17\n",
    ],
)
def test_verifier_rejects_label_only_or_invalid_module_evidence(
    tmp_path, invalid_body
):
    result_file = tmp_path / "invalid-result.txt"
    result_file.write_text(
        "scenario=module\nmodule=ai_assistant\n" + invalid_body,
        encoding="utf-8",
    )
    result = run_verifier_bash(
        tmp_path,
        f'''set +e
validate_module_evidence "{result_file.as_posix()}" ai_assistant
rc=$?
test "$rc" -ne 0''',
    )

    assert result.returncode == 0, result.stderr


def test_acceptance_marker_rejects_changed_deployed_application_hash(tmp_path):
    app_root = tmp_path / "feature_demo"
    app_root.mkdir()
    app_file = app_root / "app.py"
    app_file.write_text("before\n", encoding="utf-8")
    hook = tmp_path / "hook.sh"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    signer = tmp_path / "signer.sh"
    signer.write_text("#!/bin/sh\nprintf signature\n", encoding="utf-8")
    signer.chmod(0o755)
    marker = tmp_path / "acceptance.marker"
    verifier = (DEPLOY / "verify_feature_demo.sh").as_posix()
    result = run_verifier_bash(
        tmp_path,
        f'''FEATURE_DEMO_VERIFIER_PATH="{verifier}"
FEATURE_DEMO_APP_ROOT="{app_root.as_posix()}"
FEATURE_DEMO_HARDWARE_HOOK="{hook.as_posix()}"
FEATURE_DEMO_ACCEPTANCE_SIGNER="{signer.as_posix()}"
ACCEPTANCE_MARKER="{marker.as_posix()}"
APP_PACKAGE_ROOT="{app_root.as_posix()}"
VERIFIER_PATH="{verifier}"
cat() {{ printf 'test-machine-id\n'; }}
install() {{ mkdir -p "${{@: -1}}"; }}
MODULE_IDS=()
HIGH_RISK_SEQUENCES=()
WINDOW_CLOSE_MODULE=demo
ACCEPTANCE_RESULTS=("window-close:demo=passed" "switch:20=passed")
write_acceptance_marker
printf 'after\n' >> "{app_file.as_posix()}"
set +e
    (require_valid_acceptance_marker)
rc=$?
test "$rc" -ne 0''',
    )

    assert result.returncode == 0, result.stderr
