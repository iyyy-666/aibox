# “功能演示”单窗口整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 RK3588 上交付一个中文、单窗口、包含 13 个现有演示模块的“功能演示”软件，并保证同一时间只运行一个模块且退出后完成资源释放验证。

**Architecture:** 新建 `子项目/功能演示`，使用 FastAPI 提供统一模块 API，以 PyWebView 显示一个 HTML/CSS/JavaScript 前端。`ModuleManager` 监督独立 Worker 进程组，视觉、语音、机械臂和 AI 功能通过适配器复用现有算法；主界面只加载模块元数据，不打开业务设备。

**Tech Stack:** Python 3.10、FastAPI、Uvicorn、PyWebView、vanilla HTML/CSS/JavaScript、OpenCV、pytest、Playwright、systemd、Linux `/proc`/`fuser` 资源检查

**Spec:** `docs/superpowers/specs/2026-09-21-feature-demo-integration-design.md`

## Global Constraints

- 产品名称固定为“功能演示”，用户始终只看到一个窗口。
- ModuleRegistry 精确包含 13 个真实模块，不包含独立摄像头画面或独立云台控制。
- 八个视觉模块只提供云台上、下、左、右步进，不提供回中。
- 首页不得加载模型或占用摄像头、麦克风、机械臂、云台。
- 任意时刻 `activeModule` 只能是一个模块 ID 或 `None`。
- 停止失败时不得清空 `activeModule` 或允许启动其他模块。
- 保留现有模型、阈值、识别算法、机械臂动作和串口协议。
- 不引入 Node 或新的前端框架。
- 面向学生的界面、状态、错误、语音语言和 AI 提示全部使用中文。
- 目标分辨率为 `1366x768`、`1600x900`、`1920x1080`。

---

### Task 1: 建立子项目骨架与模块注册表

**Files:**
- Create: `子项目/功能演示/PROJECT_CONTEXT.md`
- Create: `子项目/功能演示/README.md`
- Create: `子项目/功能演示/代码/feature_demo/__init__.py`
- Create: `子项目/功能演示/代码/feature_demo/models.py`
- Create: `子项目/功能演示/代码/feature_demo/registry.py`
- Create: `子项目/功能演示/代码/tests/test_registry.py`

**Interfaces:**
- Produces: `ModuleDefinition`, `ModuleState`, `MODULES`, `get_module(module_id)`。
- `ModuleDefinition` 字段固定为 `module_id`, `name`, `description`, `category`, `worker`, `resources`, `commands`, `visual`。

- [ ] **Step 1: Write the failing registry tests**

```python
def test_registry_contains_exactly_the_confirmed_modules():
    assert [item.module_id for item in MODULES] == [
        "ai_assistant", "object_sorting", "plate_recognition",
        "palm_recognition", "palm_tracking", "voice_input_test",
        "fruit_recognition", "color_recognition", "face_detection",
        "robot_button", "nursery_rhyme", "shape_recognition",
        "voice_robot_arm",
    ]

def test_camera_and_gimbal_are_not_standalone_modules():
    ids = {item.module_id for item in MODULES}
    assert "camera_view" not in ids
    assert "gimbal_control" not in ids

def test_visual_modules_expose_only_directional_gimbal_commands():
    for item in MODULES:
        if item.visual:
            assert {"gimbal_up", "gimbal_down", "gimbal_left", "gimbal_right"} <= set(item.commands)
            assert "gimbal_center" not in item.commands
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_registry.py -v`

Expected: collection fails because `feature_demo.registry` does not exist.

- [ ] **Step 3: Implement immutable module definitions**

```python
@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    module_id: str
    name: str
    description: str
    category: str
    worker: str
    resources: tuple[str, ...]
    commands: tuple[str, ...]
    visual: bool = False

class ModuleState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    CLEANUP_FAILED = "cleanup_failed"
```

Populate `MODULES` in the exact tested order with Chinese names and concrete descriptions from the spec.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_registry.py -v`

Expected: all registry tests pass.

- [ ] **Step 5: Commit**

```bash
git add 子项目/功能演示
git commit -m "feat: add feature demo module registry"
```

### Task 2: 实现互斥生命周期管理器

**Files:**
- Create: `子项目/功能演示/代码/feature_demo/worker.py`
- Create: `子项目/功能演示/代码/feature_demo/resources.py`
- Create: `子项目/功能演示/代码/feature_demo/manager.py`
- Create: `子项目/功能演示/代码/tests/fakes/fake_worker.py`
- Create: `子项目/功能演示/代码/tests/test_manager.py`
- Create: `子项目/功能演示/代码/tests/test_resources.py`

**Interfaces:**
- Consumes: `ModuleDefinition`, `ModuleState`, `get_module()` from Task 1.
- Produces: `WorkerProcess.start()`, `WorkerProcess.command()`, `WorkerProcess.stop()`, `ResourceVerifier.verify()`, `ModuleManager.start_module()`, `ModuleManager.stop_module()`, `ModuleManager.snapshot()`。

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_manager_rejects_second_module_while_one_is_active(manager):
    manager.start_module("color_recognition")
    with pytest.raises(ModuleConflictError):
        manager.start_module("shape_recognition")

def test_manager_keeps_active_module_when_release_verification_fails(manager, verifier):
    manager.start_module("color_recognition")
    verifier.report = ReleaseReport(ok=False, busy_resources=("camera",))
    result = manager.stop_module("color_recognition")
    assert result.state == ModuleState.CLEANUP_FAILED
    assert manager.active_module == "color_recognition"

def test_repeated_stop_is_idempotent(manager):
    result = manager.stop_module("color_recognition")
    assert result.state == ModuleState.IDLE
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_manager.py 子项目/功能演示/代码/tests/test_resources.py -v`

Expected: imports fail because lifecycle classes do not exist.

- [ ] **Step 3: Implement process-group supervision**

`WorkerProcess` launches workers with `start_new_session=True`, reads newline-delimited JSON from stdout, writes JSON commands to stdin, sends graceful `stop`, waits for the configured timeout, then terminates only the recorded process group.

```python
process = subprocess.Popen(
    command,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=log_handle,
    text=True,
    bufsize=1,
    start_new_session=True,
    env=environment,
)
```

Implement a lock file at `/run/user/<uid>/aibox-feature-demo.lock` on RK3588 and a temporary-directory equivalent in tests. Protect all transitions with a `threading.RLock`.

- [ ] **Step 4: Implement release verification**

`ResourceVerifier` checks only resources declared by the module. It verifies recorded PIDs, `/dev/video41`, configured ALSA PCM identifiers, `/dev/esp32_arm`, and the configured gimbal serial path. Command execution is dependency-injected so tests use real temporary processes and deterministic command output.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_manager.py 子项目/功能演示/代码/tests/test_resources.py -v`

Expected: lifecycle and verifier tests pass.

- [ ] **Step 6: Commit**

```bash
git add 子项目/功能演示/代码/feature_demo 子项目/功能演示/代码/tests
git commit -m "feat: enforce single active demo lifecycle"
```

### Task 3: 建立 FastAPI 控制层和唯一桌面窗口

**Files:**
- Create: `子项目/功能演示/代码/feature_demo/api.py`
- Create: `子项目/功能演示/代码/feature_demo/app.py`
- Create: `子项目/功能演示/代码/feature_demo/launcher.py`
- Create: `子项目/功能演示/代码/tests/test_api.py`
- Create: `子项目/功能演示/启动脚本/feature_demo.sh`

**Interfaces:**
- Consumes: `MODULES`, `ModuleManager`.
- Produces: `create_app(manager)`, HTTP module API, WebSocket state channel, `launcher.main()`.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_home_listing_does_not_start_a_module(client, manager):
    response = client.get("/api/modules")
    assert response.status_code == 200
    assert len(response.json()["modules"]) == 13
    assert manager.active_module is None

def test_start_conflict_returns_409(client):
    assert client.post("/api/modules/color_recognition/start").status_code == 200
    response = client.post("/api/modules/shape_recognition/start")
    assert response.status_code == 409
    assert response.json()["detail"] == "已有功能正在运行，请先退出当前功能。"

def test_stop_waits_for_cleanup_result(client):
    client.post("/api/modules/color_recognition/start")
    response = client.post("/api/modules/color_recognition/stop")
    assert response.json()["state"] == "idle"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_api.py -v`

Expected: `create_app` is missing.

- [ ] **Step 3: Implement exact API routes**

Implement `GET /api/modules`, `GET /api/modules/active`, `POST /api/modules/{id}/start`, `POST /api/modules/{id}/stop`, `POST /api/modules/{id}/commands/{command}`, `GET /api/modules/{id}/status`, `GET /api/modules/{id}/frame`, and `WS /ws/modules/{id}`. Validate every command against the registry before forwarding it.

- [ ] **Step 4: Implement single-window launcher**

Start Uvicorn on an available loopback port, wait for `/health`, then create one PyWebView window titled “功能演示”. Register the window-close callback to call `manager.shutdown()` before server exit.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_api.py -v`

Expected: all API tests pass.

- [ ] **Step 6: Commit**

```bash
git add 子项目/功能演示
git commit -m "feat: add feature demo API and single window launcher"
```

### Task 4: 构建统一中文前端

**Files:**
- Create: `子项目/功能演示/代码/feature_demo/web/index.html`
- Create: `子项目/功能演示/代码/feature_demo/web/styles.css`
- Create: `子项目/功能演示/代码/feature_demo/web/app.js`
- Create: `子项目/功能演示/代码/feature_demo/web/assets/` required bitmap and existing icon assets
- Create: `子项目/功能演示/代码/tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: Task 3 HTTP and WebSocket API.
- Produces: `renderHome()`, `openModule(id)`, `requestExit()`, `confirmExit()`, `sendCommand(command, payload)`.

- [ ] **Step 1: Write failing frontend contract tests**

```python
def test_shell_has_only_feature_demo_navigation(web_document):
    assert web_document.select_one('[data-nav="feature-demo"]')
    assert "系统设置" not in web_document.get_text()
    assert "帮助中心" not in web_document.get_text()
    assert "关于我们" not in web_document.get_text()

def test_exit_button_is_present_in_module_shell(web_document):
    assert web_document.select_one('[data-action="exit-module"]')

def test_home_has_no_start_request_on_load(app_javascript):
    initial_section = app_javascript.split("async function openModule", 1)[0]
    assert "/start" not in initial_section
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_frontend_contract.py -v`

Expected: web assets are missing.

- [ ] **Step 3: Implement the design system and shell**

Use CSS tokens for white/light-blue surfaces, restrained blue primary actions, green/orange/cyan module accents, 8px maximum card radius, visible focus rings, stable grid tracks, and Chinese typography. Create a compact AI education banner using an approved bitmap asset, with the module grid visible in the first viewport.

- [ ] **Step 4: Implement lifecycle UI states**

Render `starting`, `running`, `stopping`, `failed`, and `cleanup_failed`. The exit confirmation contains only “继续演示” and “退出功能”. Do not navigate home until the stop response reports `idle`.

- [ ] **Step 5: Run contract tests and verify GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_frontend_contract.py -v`

Expected: all frontend contract tests pass.

- [ ] **Step 6: Commit**

```bash
git add 子项目/功能演示/代码/feature_demo/web 子项目/功能演示/代码/tests/test_frontend_contract.py
git commit -m "feat: build unified Chinese feature demo interface"
```

### Task 5: 接入八个视觉模块与四向云台步进

**Files:**
- Create: `子项目/功能演示/代码/feature_demo/workers/base.py`
- Create: `子项目/功能演示/代码/feature_demo/workers/vision.py`
- Create: `子项目/功能演示/代码/feature_demo/adapters/vision/` per-module adapters
- Create: `子项目/功能演示/代码/feature_demo/adapters/gimbal.py`
- Create: `子项目/功能演示/代码/tests/test_vision_workers.py`
- Create: `子项目/功能演示/代码/tests/test_gimbal_adapter.py`

**Interfaces:**
- Produces: `VisionWorker.run()`, `VisionAdapter.process(frame)`, `GimbalAdapter.step(direction, amount)`.
- Worker stdout events: `ready`, `status`, `result`, `frame`, `error`, `stopped`.

- [ ] **Step 1: Write failing adapter tests**

```python
@pytest.mark.parametrize("direction", ["up", "down", "left", "right"])
def test_gimbal_accepts_only_directional_steps(direction, gimbal):
    assert gimbal.step(direction, 30).ok

def test_gimbal_rejects_center(gimbal):
    with pytest.raises(UnsupportedCommand):
        gimbal.step("center", 30)

def test_vision_worker_releases_camera_before_reporting_stopped(worker, camera):
    worker.start()
    worker.stop()
    assert camera.release_called
    assert worker.last_event["type"] == "stopped"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_vision_workers.py 子项目/功能演示/代码/tests/test_gimbal_adapter.py -v`

Expected: worker and adapters are missing.

- [ ] **Step 3: Implement common vision worker**

Open `/dev/video41` only in `start()`, run capture and inference loops with non-daemon stop events, keep a bounded latest-frame buffer, encode the latest annotated frame as JPEG, and join both loops before camera release confirmation.

- [ ] **Step 4: Port existing detection functions without changing behavior**

Adapt object sorting, plate, palm/gesture, palm tracking, fruit, color, face, and shape implementations. Preserve existing model paths, thresholds, `vision_targeting` behavior, and result semantics. Do not copy Tk layout code.

- [ ] **Step 5: Implement gimbal ownership and tracking interaction**

Open the existing ACK-based serial client only on the first step or automatic tracking start. Manual steps pause palm automatic tracking before writing. Close the serial client during Worker stop before emitting `stopped`.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_vision_workers.py 子项目/功能演示/代码/tests/test_gimbal_adapter.py -v`

Expected: all visual lifecycle and direction tests pass.

- [ ] **Step 7: Commit**

```bash
git add 子项目/功能演示/代码/feature_demo/workers 子项目/功能演示/代码/feature_demo/adapters 子项目/功能演示/代码/tests
git commit -m "feat: integrate visual demos with directional gimbal control"
```

### Task 6: 接入机械臂相关模块并取消开机串口占用

**Files:**
- Create: `子项目/功能演示/代码/feature_demo/adapters/robot.py`
- Create: `子项目/功能演示/代码/feature_demo/workers/robot.py`
- Create: `子项目/功能演示/代码/tests/test_robot_workers.py`
- Create: `子项目/功能演示/部署/robot-arm-feature-demo.conf`

**Interfaces:**
- Produces: `RobotAdapter.connect()`, `RobotAdapter.command()`, `RobotAdapter.stop_motion()`, `RobotAdapter.disconnect()`.
- Supports modules `robot_button`, `voice_robot_arm`, and `object_sorting`.

- [ ] **Step 1: Write failing robot lifecycle tests**

```python
def test_robot_serial_is_lazy(robot_worker, serial_factory):
    assert serial_factory.open_count == 0
    robot_worker.start()
    assert serial_factory.open_count == 1

def test_robot_stop_stops_motion_before_disconnect(robot_worker, call_log):
    robot_worker.start()
    robot_worker.stop()
    assert call_log.index("stop_motion") < call_log.index("disconnect")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_robot_workers.py -v`

Expected: robot adapter is missing.

- [ ] **Step 3: Adapt existing mechanical control**

Reuse `robot.py`, `serial_driver.py`, `config.py`, `stages.json`, and `sorting_stages.json`. Preserve PWM limits and existing actions. Do not connect or move upright at import or unified app startup.

- [ ] **Step 4: Add on-demand service configuration**

Deployment disables the existing business autostart path only after the unified software passes tests. The unified app owns the API/serial lifecycle; existing API paths remain available inside the control layer for compatibility.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_robot_workers.py -v`

Expected: lazy connect and ordered shutdown tests pass.

- [ ] **Step 6: Commit**

```bash
git add 子项目/功能演示
git commit -m "feat: integrate on-demand robot arm modules"
```

### Task 7: 接入语音、儿歌和 AI 对话模块并恢复中文

**Files:**
- Create: `子项目/功能演示/代码/feature_demo/adapters/audio.py`
- Create: `子项目/功能演示/代码/feature_demo/workers/voice.py`
- Create: `子项目/功能演示/代码/feature_demo/workers/assistant.py`
- Create: `子项目/功能演示/代码/tests/test_voice_workers.py`
- Create: `子项目/功能演示/部署/voice.conf`

**Interfaces:**
- Produces: `VoiceWorker.start_listening()`, `VoiceWorker.stop_listening()`, `VoiceWorker.stop()`, `AssistantWorker.ask()`.
- Supports `voice_input_test`, `nursery_rhyme`, `voice_robot_arm`, `ai_assistant`.

- [ ] **Step 1: Write failing audio lifecycle and locale tests**

```python
def test_voice_worker_closes_pcm_before_stopped(worker, pcm):
    worker.start()
    worker.stop()
    assert pcm.closed
    assert worker.last_event["type"] == "stopped"

def test_voice_configuration_uses_chinese():
    assert deployment_environment()["VOICE_LANGUAGE"] == "zh"

def test_assistant_system_prompt_is_chinese():
    assert "中文" in assistant_system_prompt()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_voice_workers.py -v`

Expected: voice and assistant workers are missing.

- [ ] **Step 3: Adapt shared voice engine and audio playback**

Reuse `voice_engine.py`, `speech_context.py`, `audio_config.py`, and `audio_playback.py`. Load models only in the active Worker. Replace broad `pkill` cleanup with tracked playback PIDs. Join listening threads and close ALSA PCM before reporting stopped.

- [ ] **Step 4: Adapt nursery and assistant behaviors**

Keep the existing songs, model paths, queue semantics, interruption behavior, and LLM generation settings. Emit structured Chinese status/result events instead of updating Tk widgets.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_voice_workers.py -v`

Expected: all voice lifecycle and locale tests pass.

- [ ] **Step 6: Commit**

```bash
git add 子项目/功能演示
git commit -m "feat: integrate Chinese voice and assistant demos"
```

### Task 8: 完成桌面入口、部署、全量自动化和浏览器验收

**Files:**
- Create: `子项目/功能演示/桌面入口/功能演示.desktop`
- Create: `子项目/功能演示/部署/install_feature_demo.sh`
- Create: `子项目/功能演示/部署/feature-demo.service`
- Create: `子项目/功能演示/部署/verify_feature_demo.sh`
- Create: `子项目/功能演示/代码/tests/test_deployment.py`
- Create: `子项目/功能演示/代码/tests/test_switching.py`
- Modify: `INDEX.md`

**Interfaces:**
- Consumes: complete unified application.
- Produces: reproducible installation and device verification commands.

- [ ] **Step 1: Write failing deployment and switching tests**

```python
def test_desktop_has_single_chinese_entry(desktop_entry):
    assert "Name=功能演示" in desktop_entry
    assert "Exec=/usr/local/bin/feature_demo.sh" in desktop_entry

def test_twenty_sequential_switches_release_every_module(manager):
    sequence = ["color_recognition", "voice_input_test", "robot_button"] * 7
    for module_id in sequence[:20]:
        manager.start_module(module_id)
        result = manager.stop_module(module_id)
        assert result.state == ModuleState.IDLE
        assert manager.active_module is None
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_deployment.py 子项目/功能演示/代码/tests/test_switching.py -v`

Expected: deployment files are missing.

- [ ] **Step 3: Implement idempotent installation**

The installer backs up current `/root/robot_arm`, desktop entries, launch scripts, and service configuration to a timestamped directory before copying new files. It installs the unique desktop entry, does not delete models, and prints the rollback directory.

- [ ] **Step 4: Run the full local suite**

Run: `python -m pytest 子项目/功能演示/代码/tests -v`

Expected: all tests pass with no warnings attributable to the new project.

- [ ] **Step 5: Run browser validation at all target resolutions**

Start the FastAPI app with test workers, then use Playwright to capture `1366x768`, `1600x900`, and `1920x1080`. Verify no horizontal overflow, all 13 cards are reachable, exit remains visible, startup/error/cleanup states render, visual pages show a nonblank frame, and there is no center-gimbal control.

- [ ] **Step 6: Deploy to RK3588 and run hardware verification**

Deploy to `192.168.11.106` only after creating the timestamped backup. Run all 13 modules individually, the three high-risk switch sequences from the spec, main-window close during activity, and 20 sequential switches. After each stop, use `ps`, `fuser`, and service status to verify no Worker, camera, microphone, `/dev/esp32_arm`, or gimbal serial owner remains.

- [ ] **Step 7: Commit**

```bash
git add 子项目/功能演示 INDEX.md
git commit -m "feat: package and verify unified feature demo"
```

### Task 9: Final regression and delivery audit

**Files:**
- Modify only files required by failures discovered during this audit.

**Interfaces:**
- Consumes: Tasks 1-8.
- Produces: final evidence bundle and rollback reference.

- [ ] **Step 1: Run existing affected project tests**

Run the existing tests for shared voice, robot, palm tracking, palm recognition, fruit, and shape modules in addition to the unified project suite. Record every command and result.

- [ ] **Step 2: Run static and syntax checks**

Run: `python -m compileall -q 子项目/功能演示/代码`

Run: `git diff --check`

Expected: both commands exit zero.

- [ ] **Step 3: Re-run device resource verification from a clean boot**

After reboot, verify that the unified homepage does not hold `/dev/video41`, the microphone, `/dev/esp32_arm`, or the gimbal serial device. Then repeat one visual, one voice, and one robot module lifecycle.

- [ ] **Step 4: Compare implementation against every spec acceptance item**

Produce a checklist covering the 13 modules, single window, zero-resource homepage, mutual exclusion, verified cleanup, directional-only gimbal controls, Chinese UI/voice, three resolutions, and no algorithm regression.

- [ ] **Step 5: Commit audit fixes if any**

```bash
git status --short 子项目/功能演示 INDEX.md
git add 子项目/功能演示 INDEX.md
git commit -m "fix: close feature demo acceptance gaps"
```
