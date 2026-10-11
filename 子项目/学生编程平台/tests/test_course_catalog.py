import json
from pathlib import Path

import pytest

from aibox_studio.course import CourseCatalog, CourseValidationError, bundled_course_path


def write_course(tmp_path, experiments):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "hello.py").write_text("print('你好')\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "course_id": "cn.aibox.test",
                "course_version": "1.0.0",
                "title": "测试课程",
                "experiment_count": len(experiments),
                "entry": "experiments.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "experiments.json").write_text(
        json.dumps({"parts": [{"id": "p1", "title": "第一篇", "order": 1, "chapters": [{"id": "c1", "title": "第一章", "order": 1, "experiments": experiments}]}]}, ensure_ascii=False),
        encoding="utf-8",
    )


def experiment(number=1, experiment_id="intro.01"):
    return {
        "id": experiment_id,
        "number": number,
        "title": "第一个实验",
        "description": "运行第一段代码",
        "template": "templates/hello.py",
        "allowed_imports": ["aibox"],
        "capabilities": [],
        "resources": [],
        "panel": "text",
        "run_mode": "oneshot",
        "timeout_seconds": 10,
        "output_limit_bytes": 4096,
    }


def test_catalog_loads_navigation_and_template(tmp_path):
    write_course(tmp_path, [experiment()])

    catalog = CourseCatalog.load(tmp_path)

    selected = catalog.experiment("intro.01")
    assert catalog.title == "测试课程"
    assert selected.number == 1
    assert selected.template_code == "print('你好')\n"


def test_catalog_rejects_duplicate_experiment_ids(tmp_path):
    write_course(tmp_path, [experiment(), experiment(2, "intro.01")])

    with pytest.raises(CourseValidationError, match="实验ID重复"):
        CourseCatalog.load(tmp_path)


def test_catalog_rejects_template_path_outside_course(tmp_path):
    item = experiment()
    item["template"] = "../outside.py"
    write_course(tmp_path, [item])

    with pytest.raises(CourseValidationError, match="模板路径"):
        CourseCatalog.load(tmp_path)


def test_bundled_course_contains_all_56_numbered_experiments():
    root = bundled_course_path()

    catalog = CourseCatalog.load(root)

    assert len(catalog.experiments) == 56
    assert [item.number for item in catalog.experiments] == list(range(1, 57))
    assert catalog.experiment("fun.ai-sentence.01").capabilities == ("voice.speak",)
    assert catalog.experiment("arm.move.01").capabilities == (
        "arm.adjust",
        "arm.servo",
    )

