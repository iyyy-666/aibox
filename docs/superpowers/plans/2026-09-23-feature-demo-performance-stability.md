# 功能演示性能与稳定性优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提升统一“功能演示”的操作流畅度、摄像头显示帧率、断连恢复能力与中文语音识别准确率，并确保货物分拣只显示单目画面。

**Architecture:** `VisionWorker` 使用一个容量为一的最新帧槽分离摄像头采集和算法处理，并由采集线程负责失败重连；HTTP 帧接口仍返回最新 JPEG，前端改为无重叠的自适应请求循环。语音 Worker 恢复旧引擎噪声校准并过滤无内容结果，部署配置切换到板端已有 Paraformer 大模型和显式中文录音参数。

**Tech Stack:** Python 3、OpenCV/V4L2、FastAPI、PyWebView、vanilla JavaScript、pytest、Bash、ALSA、Paraformer/SenseVoice。

**Spec:** `docs/superpowers/specs/2026-09-23-feature-demo-performance-stability-design.md`

## Global Constraints

- 不修改现有视觉识别算法阈值、ROI、机械臂动作、PWM 限制和串口协议。
- 首页不持有摄像头、麦克风、机械臂、云台或模型资源。
- 同一时间只运行一个模块，停止后必须通过现有资源核验。
- 货物分拣只输出左侧单目识别画面，右侧操作、结果和云台区域保持显示。
- 不下载新模型；继续使用 `/root/robot_arm` 和板端现有模型路径。
- 所有用户可见状态和错误信息使用中文。

---

### Task 1: 最新帧采集与摄像头自动重连

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/workers/vision.py`
- Modify: `子项目/功能演示/代码/feature_demo/workers/runtime.py`
- Test: `子项目/功能演示/代码/tests/test_vision_workers.py`
- Test: `子项目/功能演示/代码/tests/test_worker_entry.py`

**Interfaces:**
- `VisionWorker` 继续接收 `camera_factory: Callable[[], Camera]`，每次重连都调用该工厂创建新实例。
- 新增构造参数 `read_failure_limit: int = 3`、`reconnect_delays: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0)`。
- 采集线程只维护 `(frame_sequence, latest_frame)`，处理线程不得形成无界队列。
- 结构化事件使用 `camera_reconnecting` 和 `camera_recovered` 类型。

- [ ] **Step 1: 写出采集不堆积、失败重连和停止中断重连的测试**

```python
def test_capture_keeps_only_latest_frame_for_slow_processing():
    # 快速 FakeCamera 连续产生递增帧，慢适配器阻塞首帧。
    # 释放后下一次处理必须接近最新序号，而不是逐帧消费旧队列。

def test_camera_reopens_after_consecutive_read_failures():
    # 首个摄像头连续失败三次，第二个摄像头成功。
    # 断言首实例 release、工厂调用两次并收到 reconnect/recovered 事件。

def test_stop_during_reconnect_never_opens_another_camera():
    # 在退避等待中 stop，断言线程及时退出且工厂不再被调用。
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_vision_workers.py 子项目/功能演示/代码/tests/test_worker_entry.py -q`

Expected: 新重连和最新帧测试失败，现有资源释放测试继续通过。

- [ ] **Step 3: 实现容量一最新帧槽和可中断重连**

```python
def _capture_loop(self) -> None:
    failures = 0
    while not self._stop_event.is_set():
        camera = self._camera
        ok, frame = camera.read() if camera is not None else (False, None)
        if ok:
            failures = 0
            with self._frame_ready:
                self._frame_sequence += 1
                self._latest_frame = frame
                self._frame_ready.notify()
            continue
        failures += 1
        if failures >= self._read_failure_limit:
            self._reconnect_camera()
            failures = 0
```

处理线程等待新序号，只处理当前最新帧；`stop()` 设置停止事件、通知条件变量、连接两个线程后只释放当前摄像头一次。

- [ ] **Step 4: 运行聚焦测试并确认 GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_vision_workers.py 子项目/功能演示/代码/tests/test_worker_entry.py -q`

- [ ] **Step 5: 提交**

```bash
git add 子项目/功能演示/代码/feature_demo/workers/vision.py 子项目/功能演示/代码/feature_demo/workers/runtime.py 子项目/功能演示/代码/tests/test_vision_workers.py 子项目/功能演示/代码/tests/test_worker_entry.py
git commit -m "fix: recover feature demo camera capture"
```

### Task 2: 帧序号、自适应刷新与状态重连

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/api.py`
- Modify: `子项目/功能演示/代码/feature_demo/web/app.js`
- Modify: `子项目/功能演示/代码/feature_demo/web/index.html`
- Test: `子项目/功能演示/代码/tests/test_api.py`
- Test: `子项目/功能演示/代码/tests/test_frontend_contract.py`

**Interfaces:**
- `GET /api/modules/{module_id}/frame` 的成功响应增加 `X-Frame-Sequence`，值来自 Worker snapshot 的 `frame_sequence`；状态事件不得推进该序号。
- `startFrameUpdates()` 任意时刻最多持有一个 fetch；活动页面间隔 80 ms，隐藏页面间隔 500 ms。
- `stopFrameUpdates()` 中止当前请求、清除 timeout 并释放对象 URL。
- WebSocket 非主动关闭时按 250/500/1000/2000 ms 退避重连；退出模块后不得重连。

- [ ] **Step 1: 写 API 帧序号及前端无重叠循环测试**

```python
def test_frame_response_exposes_monotonic_sequence(client, manager):
    # 注入带 JPEG 和 event_sequence 的 worker snapshot。
    assert response.headers["x-frame-sequence"] == "7"

def test_frame_updates_use_abortable_single_request_loop(app_javascript):
    assert "setInterval(refresh, 250)" not in app_javascript
    assert "AbortController" in app_javascript
    assert "setTimeout" in app_javascript
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_api.py 子项目/功能演示/代码/tests/test_frontend_contract.py -q`

- [ ] **Step 3: 实现帧响应标识、80 ms 单请求循环和 WebSocket 重连**

```javascript
async function refreshFrame(moduleId, generation) {
  const controller = new AbortController();
  appState.frameRequest = controller;
  try {
    const response = await fetch(`/api/modules/${moduleId}/frame`, {
      cache: "no-store",
      signal: controller.signal,
    });
    // 只在序号变化时替换 object URL。
  } finally {
    if (generation === appState.frameGeneration) {
      appState.frameTimer = window.setTimeout(
        () => refreshFrame(moduleId, generation),
        document.hidden ? 500 : 80,
      );
    }
  }
}
```

连接中断时保留最近画面并更新重连提示；新帧到达后清除提示。

- [ ] **Step 4: 运行聚焦测试和 JavaScript 语法检查**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_api.py 子项目/功能演示/代码/tests/test_frontend_contract.py -q`

Run: `node --check 子项目/功能演示/代码/feature_demo/web/app.js`

- [ ] **Step 5: 提交**

```bash
git add 子项目/功能演示/代码/feature_demo/api.py 子项目/功能演示/代码/feature_demo/web/app.js 子项目/功能演示/代码/feature_demo/web/index.html 子项目/功能演示/代码/tests/test_api.py 子项目/功能演示/代码/tests/test_frontend_contract.py
git commit -m "perf: raise feature demo frame refresh rate"
```

### Task 3: 货物分拣单目输出契约

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/adapters/vision.py`
- Test: `子项目/功能演示/代码/tests/test_legacy_vision_adapters.py`
- Test: `子项目/功能演示/代码/tests/test_frontend_contract.py`

**Interfaces:**
- `LegacyVisionAdapter.process()` 的 `sorting` 分支只对 `split_stereo(frame)[0]` 检测、标注和返回。
- 前端 `visual-workspace` 的 `vision-side` 对 `object_sorting` 保持可见。

- [ ] **Step 1: 使用可区分左右目的合成帧写失败测试**

```python
def test_sorting_returns_only_annotated_left_eye():
    left = np.full((4, 6, 3), 11, dtype=np.uint8)
    right = np.full((4, 6, 3), 222, dtype=np.uint8)
    stereo = np.concatenate((left, right), axis=1)
    annotated, _ = adapter.process(stereo)
    assert annotated.shape == left.shape
    assert np.all(annotated == 11)
```

前端契约同时断言 `object_sorting` 不隐藏 `.vision-side`。

- [ ] **Step 2: 运行测试并确认 RED 或锁定已有行为**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_legacy_vision_adapters.py 子项目/功能演示/代码/tests/test_frontend_contract.py -q`

若后端测试立即通过，记录其为防回归契约；仅补最小显式实现或注释，不改原分拣阈值。

- [ ] **Step 3: 完成最小实现并运行 GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_legacy_vision_adapters.py 子项目/功能演示/代码/tests/test_frontend_contract.py -q`

- [ ] **Step 4: 提交**

```bash
git add 子项目/功能演示/代码/feature_demo/adapters/vision.py 子项目/功能演示/代码/tests/test_legacy_vision_adapters.py 子项目/功能演示/代码/tests/test_frontend_contract.py
git commit -m "test: lock sorting preview to one camera eye"
```

### Task 4: 语音噪声校准、无效结果过滤与中文模型配置

**Files:**
- Modify: `子项目/功能演示/代码/feature_demo/workers/voice.py`
- Modify: `子项目/功能演示/部署/voice.conf`
- Test: `子项目/功能演示/代码/tests/test_voice_workers.py`
- Test: `子项目/功能演示/代码/tests/test_deployment.py`

**Interfaces:**
- `VoiceWorker.start_listening()` 在监听线程前调用可选的 `engine._calibrate_noise(pcm)`。
- 校准前设置 `engine.running = True`，停止时仍设置为 `False`。
- `_is_meaningful_transcript(text: str) -> bool` 至少要求一个中文字符、字母或数字；纯标点和空白不发送 `speech` 事件。
- `voice.conf` 使用 `VOICE_BACKEND=paraformer`，并显式设置项目已有的中文录音参数。

- [ ] **Step 1: 写校准顺序、标点过滤、命令不误触发及部署配置测试**

```python
def test_voice_calibrates_before_listener_thread_reads_pcm():
    assert calls.index("calibrate") < calls.index("record")

@pytest.mark.parametrize("text", ["", "。", "，！", "... "])
def test_voice_ignores_punctuation_only_transcripts(text):
    worker._handle_text(text, text)
    assert events == []
    assert robot_calls == []
```

配置测试断言 Paraformer、增益、触发/静音阈值、录音时长、尾静音、预录音和动态阈值均被写入。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_voice_workers.py 子项目/功能演示/代码/tests/test_deployment.py -q`

- [ ] **Step 3: 实现校准与结果过滤，写入现有中文调优参数**

```python
def _is_meaningful_transcript(text: str) -> bool:
    return any(character.isalnum() for character in (text or ""))

calibrate = getattr(self._engine, "_calibrate_noise", None)
if callable(calibrate):
    self._engine.running = True
    self._emit({"type": "calibrating", "message": "正在校准环境噪声。"})
    calibrate(self._pcm)
```

配置值以当前旧引擎已经验证的中文默认值为起点：增益 `3.0`、触发 `0.038`、静音 `0.022`、最短 `0.46s`、最长 `3.20s`、普通尾静音 `0.58s`、快速尾静音 `0.38s`、预录音 `35` 帧。

- [ ] **Step 4: 运行聚焦测试并确认 GREEN**

Run: `python -m pytest 子项目/功能演示/代码/tests/test_voice_workers.py 子项目/功能演示/代码/tests/test_deployment.py -q`

- [ ] **Step 5: 提交**

```bash
git add 子项目/功能演示/代码/feature_demo/workers/voice.py 子项目/功能演示/部署/voice.conf 子项目/功能演示/代码/tests/test_voice_workers.py 子项目/功能演示/代码/tests/test_deployment.py
git commit -m "fix: calibrate Chinese voice recognition"
```

### Task 5: 全量验证、增量部署与 RK3588 实测

**Files:**
- Modify: `.superpowers/sdd/2026-09-21-feature-demo-integration-implementation/task-9-report.md`

**Interfaces:**
- 板端部署前备份所有修改目标到 `/root/feature-demo-backups/performance-stability-<timestamp>`。
- 部署后本地与板端 SHA-256 必须一致。
- 帧率以五秒内 `frame_sequence` 增量和前端帧请求序号共同记录。

- [ ] **Step 1: 运行统一和旧模块测试**

Run: `python -m pytest 子项目/功能演示/代码/tests -q`

Run: `python -m pytest 子项目/共享模块与资源/代码/tests 子项目/语音简单控制机械臂/代码/tests 子项目/手掌追踪/测试 子项目/手掌识别/代码/tests 子项目/水果识别/代码/tests 子项目/形状识别/代码/tests -q`

- [ ] **Step 2: 运行静态检查**

Run: `python -m compileall -q 子项目/功能演示/代码`

Run: `node --check 子项目/功能演示/代码/feature_demo/web/app.js`

Run: Git Bash `bash -n` on launcher, installer, verifier, hardware hook, and signer.

Run: `git diff --check`

- [ ] **Step 3: 创建板端备份并增量部署变更文件**

停止当前统一窗口前确认无活动模块；复制生产文件和 `/etc/default/feature-demo` 的旧版本到时间戳备份目录，再安装新文件。不得运行 apt、dpkg 修复或重启开发板。

- [ ] **Step 4: 验证摄像头与前端**

在颜色识别中记录五秒后端 `frame_sequence` 增量；连续注入或模拟读帧失败，确认释放、重开、恢复事件和停止中断。使用浏览器/窗口画面确认显示达到 10 至 15 FPS 且无请求堆积。

- [ ] **Step 5: 验证分拣和语音**

确认货物分拣 JPEG 尺寸为单目 `640x480`，右侧操作区仍存在。现场依次说普通中文短语、儿歌名称和机械臂命令，记录原始/规范化文本；纯噪声和标点不得触发动作。

- [ ] **Step 6: 验证 13 个模块生命周期和最终桌面状态**

逐个启动、停止 13 个模块，确认每次停止后摄像头、麦克风、扬声器、机械臂和云台无所有者。桌面保持唯一“功能演示”入口，旧服务保持 disabled/inactive。

- [ ] **Step 7: 更新验收报告并提交**

```bash
git add .superpowers/sdd/2026-09-21-feature-demo-integration-implementation/task-9-report.md
git commit -m "docs: record feature demo performance verification"
```
