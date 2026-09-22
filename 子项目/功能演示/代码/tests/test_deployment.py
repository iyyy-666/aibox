from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "部署"


def run_hook_bash(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
    if not Path(bash).is_file():
        pytest.skip("Bash is required for deployment behavior tests")
    hook = (DEPLOY / "hardware_acceptance_hook.sh").as_posix()
    python = Path(sys.executable).as_posix()
    script = (
        f'python3() {{ "{python}" "$@"; }}\n'
        f'source <(sed \'/^case "${{1:-}}" in/,$d\' "{hook}")\n{body}'
    )
    return subprocess.run(
        [bash, "-c", script],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
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
    assert "ExecStart=/usr/local/bin/feature_demo.sh" in (DEPLOY / "feature-demo.service").read_text(encoding="utf-8")
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


def test_verifier_uses_the_same_camera_microphone_robot_and_gimbal_paths_as_runtime():
    verifier = (DEPLOY / "verify_feature_demo.sh").read_text(encoding="utf-8")

    assert "/dev/video41" in verifier
    assert "/dev/snd/pcmC1D0c" in verifier
    assert "/dev/esp32_arm" in verifier
    assert "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0" in verifier


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
sleep() {{ :; }}
verify_running_module nursery_rhyme''',
    )

    assert result.returncode == 0, result.stderr
    assert Path(trace).read_text(encoding="utf-8").splitlines() == [
        "owner=/dev/test-mic",
        "command=play",
        "owner=/dev/test-speaker",
        "command=stop_playback",
    ]
