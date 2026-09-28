import json
from pathlib import Path
import subprocess
import textwrap


WEB = Path(__file__).resolve().parents[1] / "feature_demo" / "web"


def run_radar_javascript(scenario: str) -> None:
    app_path = json.dumps(str(WEB / "app.js"))
    harness = f"""
        const assert = require("node:assert/strict");
        const elements = new Map();
        const commandControls = [];
        const windowListeners = new Map();
        const dprListeners = new Set();
        const bootNode = {{
          addEventListener() {{}},
          replaceChildren() {{}},
          removeAttribute() {{}},
          setAttribute() {{}},
          style: {{}},
          classList: {{ add() {{}}, remove() {{}}, toggle() {{}} }},
        }};

        globalThis.__FEATURE_DEMO_TEST__ = true;
        globalThis.document = {{
          addEventListener() {{}},
          querySelector(selector) {{ return elements.get(selector) || bootNode; }},
          querySelectorAll(selector) {{
            if (selector === "[data-command]") return commandControls;
            return [];
          }},
        }};
        globalThis.window = {{
          devicePixelRatio: 1,
          requestAnimationFrame(callback) {{ callback(); }},
          addEventListener(name, callback) {{ windowListeners.set(name, callback); }},
          removeEventListener(name, callback) {{
            if (windowListeners.get(name) === callback) windowListeners.delete(name);
          }},
          matchMedia() {{
            return {{
              addEventListener(name, callback) {{ if (name === "change") dprListeners.add(callback); }},
              removeEventListener(name, callback) {{ if (name === "change") dprListeners.delete(callback); }},
            }};
          }},
          setTimeout,
          clearTimeout,
          scrollTo() {{}},
        }};
        globalThis.fetch = async () => ({{ ok: true, json: async () => [] }});

        require({app_path});
        const hooks = globalThis.__featureDemoTestHooks;
        assert.ok(hooks, "app.js must expose deterministic radar test hooks");
        {textwrap.dedent(scenario)}
    """
    completed = subprocess.run(
        ["node", "-e", textwrap.dedent(harness)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_radar_module_is_rendered_by_the_existing_command_workspace():
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'moduleId === "radar_detection"' in app
    assert "建立基准" in app
    assert "开始检测" in app
    assert "停止检测" in app
    assert "雷达状态" in app
    assert "当前变化程度" in app
    assert "data-radar-canvas" in app
    assert "固定位置存在物块" in app
    assert "固定位置不存在物块" in app
    assert "雷达数据无效" in app
    assert "是否搬运" in app


def test_radar_is_not_rendered_as_a_camera_or_robot_module():
    app = (WEB / "app.js").read_text(encoding="utf-8")

    radar_block = app.split('moduleId === "radar_detection"', 1)[1].split('return `<fieldset', 1)[0]
    assert "data-camera-frame" not in radar_block
    assert "robot_button" not in radar_block


def test_radar_frontend_contract_has_scan_rendering_and_manual_confirmation_only():
    app = (WEB / "app.js").read_text(encoding="utf-8")

    assert "drawRadarScan" in app
    assert "RADAR_MAX_DISTANCE_MM = 8000" in app
    assert "Math.sin(angleRad)" in app
    assert "-Math.cos(angleRad)" in app
    assert "radar_data_valid" in app
    assert "data-radar-readiness" in app
    assert "data-radar-byte-rate" in app
    assert "data-radar-point-rate" in app
    assert "data-radar-rotation-rate" in app
    assert "data-radar-last-frame" in app
    assert "data-radar-confirm" in app
    assert "radar-workspace" in app
    assert "radar-mode" in app
    assert "sequence\"" not in app.split('moduleId === "radar_detection"', 1)[1].split("if (moduleId ===", 1)[0]


def test_radar_commands_are_gated_by_worker_readiness():
    run_radar_javascript(
        """
        const baseline = { dataset: { command: "build_baseline" }, disabled: false };
        const detection = { dataset: { command: "start_detection" }, disabled: false };
        commandControls.push(baseline, detection);

        hooks.resetRadarState();
        hooks.updateCommandControls();
        assert.equal(baseline.disabled, true);
        assert.equal(detection.disabled, true);

        hooks.renderWorkerDetails({ data_ready: true, valid_rotations: 5, required_rotations: 5 });
        assert.equal(baseline.disabled, false);
        assert.equal(detection.disabled, true);

        hooks.renderWorkerDetails({ baseline_ready: true });
        assert.equal(detection.disabled, false);
        """
    )


def test_radar_reentry_resets_manual_confirmation_and_scan_state():
    run_radar_javascript(
        """
        hooks.appState.radarConfirm = true;
        hooks.appState.radarDataReady = true;
        hooks.appState.radarBaselineReady = true;
        hooks.appState.radarScan = { points: [{ angle_deg: 90, distance_mm: 1000 }], valid: true };

        hooks.resetRadarState();

        assert.equal(hooks.appState.radarConfirm, false);
        assert.equal(hooks.appState.radarDataReady, false);
        assert.equal(hooks.appState.radarBaselineReady, false);
        assert.deepEqual(hooks.appState.radarScan.points, []);
        """
    )


def test_radar_resize_sources_redraw_and_cleanup():
    run_radar_javascript(
        """
        let draws = 0;
        let resizeCallback = null;
        let disconnected = false;
        const context = new Proxy({}, {
          get(target, property) {
            if (property === "fillRect") return () => { draws += 1; };
            if (property === "setTransform" || property === "clearRect" || property === "beginPath" ||
                property === "arc" || property === "stroke" || property === "fillText" ||
                property === "moveTo" || property === "lineTo" || property === "closePath" ||
                property === "fill") return () => {};
            return target[property];
          },
          set(target, property, value) { target[property] = value; return true; },
        });
        const canvas = {
          width: 0,
          height: 0,
          getBoundingClientRect: () => ({ width: 360, height: 360 }),
          getContext: () => context,
        };
        elements.set("[data-radar-canvas]", canvas);
        globalThis.ResizeObserver = class {
          constructor(callback) { resizeCallback = callback; }
          observe(target) { assert.equal(target, canvas); }
          disconnect() { disconnected = true; }
        };

        hooks.startRadarResizeTracking();
        resizeCallback();
        const afterObserver = draws;
        assert.ok(afterObserver > 0);
        windowListeners.get("resize")();
        assert.ok(draws > afterObserver);
        const afterWindow = draws;
        for (const callback of [...dprListeners]) callback();
        assert.ok(draws > afterWindow);

        hooks.stopRadarResizeTracking();
        assert.equal(disconnected, true);
        assert.equal(windowListeners.has("resize"), false);
        assert.equal(dprListeners.size, 0);
        """
    )


def test_radar_keeps_the_last_scan_and_worker_errors_visible():
    run_radar_javascript(
        """
        const result = { textContent: "" };
        elements.set("[data-radar-result]", result);
        elements.set("[data-activity-log]", { textContent: "", classList: { remove() {} } });
        elements.delete("[data-radar-canvas]");
        document.querySelector = selector => elements.get(selector) || null;
        hooks.appState.active = { module_id: "radar_detection", visual: false };

        hooks.appState.radarScan = {
          points: [{ angle_deg: 90, distance_mm: 1000 }],
          valid: true,
          latestAngle: 90,
          region: hooks.appState.radarScan.region,
        };
        hooks.renderWorkerDetails({ type: "error", message: "雷达读取失败" });
        hooks.renderWorkerDetails({ type: "detection", radar_data_valid: false, result: null });

        assert.equal(result.textContent, "雷达读取失败");
        assert.equal(hooks.appState.radarScan.points.length, 1);
        hooks.renderWorkerDetails({ type: "error", message: "雷达仍然离线", result: "无物块" });
        assert.equal(result.textContent, "雷达仍然离线");
        """
    )


def test_radar_desktop_layout_has_only_plot_and_control_tracks():
    styles = (WEB / "styles.css").read_text(encoding="utf-8")

    assert ".radar-workspace > .activity-panel { display: none; }" in styles
    assert "grid-template-columns: minmax(0, 1fr) 260px" in styles
    assert ".command-workspace.radar-workspace { height: calc(100dvh - 270px); min-height: 430px; grid-template-columns: minmax(0, 1fr);" in styles
    assert ".radar-control-column {" in styles
    assert "overflow: hidden" not in styles.split(".radar-control-column {", 1)[1].split("}", 1)[0]
    assert ".radar-mode .radar-details dl > div { padding: 2px 0; background: transparent; border-radius: 0; }" in styles
    assert "grid-template-rows: minmax(0, 1fr)" in styles
