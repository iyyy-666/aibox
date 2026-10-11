from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap


WEB = Path(__file__).resolve().parents[1] / "feature_demo" / "web"


def run_plate_javascript(scenario: str) -> None:
    app_path = json.dumps(str(WEB / "app.js"))
    harness = f"""
        const assert = require("node:assert/strict");
        const resultClasses = new Set(["result-empty"]);
        const result = {{
          textContent: "",
          classList: {{
            add(...names) {{ names.forEach(name => resultClasses.add(name)); }},
            remove(...names) {{ names.forEach(name => resultClasses.delete(name)); }},
            contains(name) {{ return resultClasses.has(name); }},
          }},
        }};
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
          querySelector(selector) {{
            if (selector === "[data-result-content]") return result;
            if (selector === "[data-radar-canvas]") return null;
            return bootNode;
          }},
          querySelectorAll() {{ return []; }},
        }};
        globalThis.window = {{
          devicePixelRatio: 1,
          requestAnimationFrame(callback) {{ callback(); }},
          addEventListener() {{}},
          removeEventListener() {{}},
          matchMedia() {{ return {{ addEventListener() {{}}, removeEventListener() {{}} }}; }},
          setTimeout() {{ return 1; }},
          clearTimeout() {{}},
          scrollTo() {{}},
        }};
        globalThis.fetch = async () => ({{ ok: true, json: async () => [] }});

        require({app_path});
        const hooks = globalThis.__featureDemoTestHooks;
        hooks.appState.active = {{ module_id: "plate_recognition", visual: true }};
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


def test_plate_result_shows_a_clear_empty_state_instead_of_json_array():
    run_plate_javascript(
        """
        hooks.renderWorkerDetails({ result: [] });
        assert.equal(result.textContent, "暂未识别到车牌");
        assert.equal(result.classList.contains("result-empty"), true);
        """
    )


def test_plate_result_uses_chinese_labels_instead_of_raw_json():
    run_plate_javascript(
        """
        hooks.renderWorkerDetails({
          result: [{
            plate: "粤B12345",
            color: "Blue Plate",
            vehicle_type: "Fuel Vehicle",
            confidence: 0.93,
            source: "HyperLPR3",
            box: [220, 190, 290, 210],
          }],
        });
        assert.equal(
          result.textContent,
          "车牌号码：粤B12345\\n车牌颜色：蓝色\\n车辆类型：燃油车\\n置信度：93%",
        );
        assert.equal(result.textContent.includes("box"), false);
        assert.equal(result.textContent.includes("{"), false);
        assert.equal(result.classList.contains("result-empty"), false);
        """
    )


def test_plate_result_ignores_null_entries_and_bounds_invalid_confidence():
    run_plate_javascript(
        """
        hooks.renderWorkerDetails({
          result: [null, { plate: "粤B12345", color: "Blue Plate", confidence: -2 }],
        });
        assert.equal(
          result.textContent,
          "车牌号码：粤B12345\\n车牌颜色：蓝色\\n车辆类型：未知\\n置信度：--",
        );
        """
    )


def test_plate_result_does_not_coerce_invalid_fields_into_garbled_text():
    run_plate_javascript(
        """
        hooks.renderWorkerDetails({
          result: [{ plate: { raw: "粤B12345" }, color: false, vehicle_type: null, confidence: null }],
        });
        assert.equal(
          result.textContent,
          "车牌号码：未读取\\n车牌颜色：未知\\n车辆类型：未知\\n置信度：--",
        );
        assert.equal(result.textContent.includes("[object Object]"), false);
        """
    )


def test_plate_result_container_preserves_formatted_line_breaks():
    styles = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "[data-result-content] { white-space: pre-wrap;" in styles

