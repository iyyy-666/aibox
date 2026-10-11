import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from aibox_studio.app import build_window, choose_ui_font
from aibox_studio.course import bundled_course_path


def application():
    return QApplication.instance() or QApplication([])


def test_ui_font_prefers_an_installed_simplified_chinese_family():
    assert choose_ui_font(["Sans Serif", "Microsoft YaHei", "SimSun"]) == "Microsoft YaHei"


def test_main_window_loads_four_area_student_workspace(tmp_path):
    application()
    course_root = bundled_course_path()

    window = build_window(course_root=course_root, workspace_root=tmp_path)

    assert window.course_tree.topLevelItemCount() == 8
    assert window.code_editor.toPlainText()
    assert window.effect_stack.count() == 6
    assert window.output_view.toPlainText() == "准备就绪"
    window.close()


def test_course_tree_starts_fully_collapsed_while_first_experiment_is_loaded(tmp_path):
    application()
    window = build_window(course_root=bundled_course_path(), workspace_root=tmp_path)

    assert window.current_experiment == window.catalog.experiments[0]
    assert all(
        not window.course_tree.topLevelItem(index).isExpanded()
        for index in range(window.course_tree.topLevelItemCount())
    )
    first_part = window.course_tree.topLevelItem(0)
    assert all(not first_part.child(index).isExpanded() for index in range(first_part.childCount()))
    window.close()


def test_selecting_experiment_loads_its_template_and_effect_panel(tmp_path):
    application()
    course_root = bundled_course_path()
    window = build_window(course_root=course_root, workspace_root=tmp_path)

    window.select_experiment("fun.ai-sentence.01")

    assert "voice.speak" in window.code_editor.toPlainText()
    assert window.effect_stack.currentWidget().objectName() == "voice"
    assert "让AI说一句话" in window.experiment_title.text()
    window.close()


def test_run_button_executes_template_and_updates_output(tmp_path):
    application()
    course_root = bundled_course_path()
    window = build_window(course_root=course_root, workspace_root=tmp_path)
    window.select_experiment("arm.open.01")

    QTest.mouseClick(window.run_button, Qt.MouseButton.LeftButton)
    deadline = time.monotonic() + 3
    while not window.run_button.isEnabled() and time.monotonic() < deadline:
        application().processEvents()
        QTest.qWait(10)

    assert "运行完成" in window.output_view.toPlainText()
    assert "张开" in window.effect_stack.currentWidget().status_label.text()
    window.close()


def test_observe_experiment_stays_active_until_stop(tmp_path):
    application()
    course_root = bundled_course_path()
    window = build_window(course_root=course_root, workspace_root=tmp_path)
    window.select_experiment("lidar.show.01")

    QTest.mouseClick(window.run_button, Qt.MouseButton.LeftButton)
    deadline = time.monotonic() + 3
    while window.worker is not None and time.monotonic() < deadline:
        application().processEvents()
        QTest.qWait(10)

    assert window.run_button.isEnabled() is False
    assert window.stop_button.isEnabled() is True
    assert "观察中" in window.output_view.toPlainText()

    QTest.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)

    assert window.run_button.isEnabled() is True
    assert window.stop_button.isEnabled() is False
    assert "已停止" in window.output_view.toPlainText()
    window.close()
