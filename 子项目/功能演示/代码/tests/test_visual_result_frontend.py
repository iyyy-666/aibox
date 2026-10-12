from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap


WEB = Path(__file__).resolve().parents[1] / "feature_demo" / "web"


def run_visual_result_javascript(module_id: str, result_payload: str, expected: str) -> None:
    app_path = json.dumps(str(WEB / "app.js"))
    harness = f"""
        const assert = require("node:assert/strict");
        const classes = new Set(["result-empty"]);
        const resultNode = {{
          textContent: "",
          classList: {{
            add(...names) {{ names.forEach(name => classes.add(name)); }},
            remove(...names) {{ names.forEach(name => classes.delete(name)); }},
          }},
        }};
        const node = {{
          textContent: "", style: {{}}, hidden: false,
          querySelector() {{ return node; }},
          addEventListener() {{}}, replaceChildren() {{}},
          classList: {{ add() {{}}, remove() {{}}, toggle() {{}} }},
        }};
        globalThis.__FEATURE_DEMO_TEST__ = true;
        globalThis.document = {{
          hidden: false,
          addEventListener() {{}},
          querySelector(selector) {{
            if (selector === "[data-result-content]") return resultNode;
            if (selector === "[data-radar-canvas]") return null;
            return node;
          }},
          querySelectorAll() {{ return []; }},
        }};
        globalThis.window = {{
          devicePixelRatio: 1, requestAnimationFrame(callback) {{ callback(); }},
          addEventListener() {{}}, removeEventListener() {{}},
          matchMedia() {{ return {{ addEventListener() {{}}, removeEventListener() {{}} }}; }},
          setTimeout() {{ return 1; }}, clearTimeout() {{}}, scrollTo() {{}},
        }};
        require({app_path});
        const hooks = globalThis.__featureDemoTestHooks;
        hooks.appState.active = {{ module_id: {json.dumps(module_id)}, visual: true }};
        hooks.renderWorkerDetails({{ result: {result_payload} }});
        assert.equal(resultNode.textContent, {json.dumps(expected)});
        assert.equal(resultNode.textContent.includes("{{"), false);
        assert.equal(resultNode.textContent.includes("box"), false);
    """
    completed = subprocess.run(
        ["node", "-e", textwrap.dedent(harness)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_fruit_result_is_concise_chinese():
    run_visual_result_javascript(
        "fruit_recognition",
        '[{"name_en":"banana","name_cn":"Banana","confidence":0.95,"box":[1,2,3,4]}]',
        "香蕉（置信度 95%）",
    )


def test_color_and_shape_results_are_concise_chinese():
    run_visual_result_javascript(
        "color_recognition",
        '[{"name":"Blue","center":[100,120],"area":4200}]',
        "蓝色",
    )
    run_visual_result_javascript(
        "shape_recognition",
        '[{"name":"Circle","confidence":0.88,"vertices":12,"box":[1,2,3,4]}]',
        "圆形（置信度 88%）",
    )


def test_shape_result_uses_specialized_chinese_names():
    run_visual_result_javascript(
        "shape_recognition",
        '[{"name":"Rectangle"},{"name":"Parallelogram"},{"name":"Pentagon"}]',
        "长方形\n斜平行四边形\n正五边形",
    )


def test_sorting_and_face_results_hide_internal_fields():
    run_visual_result_javascript(
        "object_sorting",
        '["Red",[120,80,90,60],5400]',
        "检测到红色货物",
    )
    run_visual_result_javascript(
        "face_detection",
        '[[10,20,80,90,0.93],[120,30,70,85,0.89]]',
        "检测到 2 张人脸",
    )


def test_empty_visual_result_uses_module_specific_chinese_message():
    run_visual_result_javascript("fruit_recognition", "[]", "暂未识别到水果")


def test_visual_result_normalizes_case_and_hides_unknown_english_labels():
    run_visual_result_javascript(
        "color_recognition",
        '[{"name":"blue"}]',
        "蓝色",
    )
    run_visual_result_javascript(
        "shape_recognition",
        '[{"name":"Trapezoid","confidence":0.75}]',
        "检测到形状（置信度 75%）",
    )
