from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .course import CourseCatalog, Experiment, bundled_course_path
from .runner import RunRequest, RunResult, Runner
from .workspace import WorkspaceStore


APP_STYLE = """
QWidget {
    color: #202623;
    background: #f3f5f2;
    font-size: 14px;
}
QLabel { background: transparent; }
QMainWindow { background: #e8ece8; }
#topBar { background: #17201c; border-bottom: 1px solid #303a35; }
#brand { color: #ffffff; font-size: 19px; font-weight: 700; }
#modeBadge { color: #f6c85f; background: #29332e; border-radius: 4px; padding: 4px 8px; font-size: 12px; }
#sectionTitle { color: #1c2822; font-size: 13px; font-weight: 700; }
#experimentTitle { color: #16211c; font-size: 18px; font-weight: 700; }
#description { color: #647069; font-size: 13px; }
QFrame#panel { background: #ffffff; border: 1px solid #d8ded9; border-radius: 6px; }
QTreeWidget { background: #ffffff; border: 0; outline: 0; padding: 4px; }
QTreeWidget::item { min-height: 30px; border-radius: 4px; padding: 2px 5px; }
QTreeWidget::item:selected { background: #dcece5; color: #135c41; }
QTreeWidget::item:hover:!selected { background: #f0f3f0; }
QPlainTextEdit#codeEditor {
    background: #171c1a; color: #e8eee9; border: 0;
    selection-background-color: #35664f;
    font-size: 15px; padding: 10px 8px;
}
QPlainTextEdit#outputView {
    background: #111815; color: #cfe3d7; border: 0;
    font-size: 13px; padding: 8px;
}
QPushButton {
    min-height: 34px; border: 0; border-radius: 5px; padding: 0 13px;
    background: #e7ebe7; color: #26312b; font-weight: 600;
}
QPushButton:hover { background: #dce2dd; }
QPushButton:pressed { background: #cfd7d1; }
QPushButton:disabled { color: #929a95; background: #e8ebe8; }
QPushButton#runButton { color: #ffffff; background: #16784f; }
QPushButton#runButton:hover { background: #11643f; }
QPushButton#stopButton { color: #ffffff; background: #b6453b; }
QPushButton#stopButton:hover { background: #97392f; }
QPushButton#stopButton:disabled { color: #d7ddda; background: #66716b; }
QLabel#effectStatus { background: #edf2ee; color: #27332c; border-radius: 5px; padding: 10px; }
QProgressBar { border: 0; border-radius: 3px; background: #e3e8e4; height: 8px; text-align: center; }
QProgressBar::chunk { background: #d28a2e; border-radius: 3px; }
QSplitter::handle { background: #d5dbd6; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }
"""


def choose_ui_font(families: list[str]) -> str:
    installed = set(families)
    for candidate in (
        "Noto Sans CJK SC",
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "DengXian",
        "SimHei",
    ):
        if candidate in installed:
            return candidate
    return "Sans Serif"


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._add_rule(
            r"\b(and|as|assert|break|class|continue|def|elif|else|except|False|finally|for|from|if|import|in|is|lambda|None|not|or|pass|raise|return|True|try|while|with|yield)\b",
            "#78c6a3",
            bold=True,
        )
        self._add_rule(r"\b(print|len|range|str|int|float|bool)\b", "#f1c46f")
        self._add_rule(r"#[^\n]*", "#7f9087")
        self._add_rule(r"('[^'\\]*(\\.[^'\\]*)*'|\"[^\"\\]*(\\.[^\"\\]*)*\")", "#d9a577")
        self._add_rule(r"\b[0-9]+(?:\.[0-9]+)?\b", "#88b8da")

    def _add_rule(self, pattern: str, color: str, *, bold: bool = False) -> None:
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(color))
        if bold:
            text_format.setFontWeight(QFont.Weight.DemiBold)
        self.rules.append((QRegularExpression(pattern), text_format))

    def highlightBlock(self, text: str) -> None:
        for expression, text_format in self.rules:
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("codeEditor")
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed_font.setPointSize(11)
        self.setFont(fixed_font)
        self.line_numbers = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_line_numbers)
        self._update_margin()
        self.highlighter = PythonHighlighter(self.document())
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)

    def line_number_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_line_numbers(self, rect: QRect, scroll: int) -> None:
        if scroll:
            self.line_numbers.scroll(0, scroll)
        else:
            self.line_numbers.update(0, rect.y(), self.line_numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        contents = self.contentsRect()
        self.line_numbers.setGeometry(QRect(contents.left(), contents.top(), self.line_number_width(), contents.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self.line_numbers)
        painter.fillRect(event.rect(), QColor("#202724"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        painter.setPen(QColor("#7c8a82"))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, top, self.line_numbers.width() - 7, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1


class VisualCanvas(QWidget):
    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#18211d"))
        if self.kind == "radar":
            self._paint_radar(painter)
        else:
            self._paint_camera(painter)

    def _paint_camera(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#33433b"), 1))
        for x in range(0, self.width(), 32):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 32):
            painter.drawLine(0, y, self.width(), y)
        box = QRect(self.width() // 2 - 66, self.height() // 2 - 52, 132, 104)
        painter.setPen(QPen(QColor("#61c493"), 2))
        painter.drawRect(box)
        painter.setPen(QColor("#dbe9e1"))
        painter.drawText(box.adjusted(0, 112, 0, 140), Qt.AlignmentFlag.AlignHCenter, "模拟摄像头画面")

    def _paint_radar(self, painter: QPainter) -> None:
        center_x = self.width() // 2
        center_y = self.height() // 2
        radius = max(30, min(self.width(), self.height()) // 2 - 22)
        painter.setPen(QPen(QColor("#3a5649"), 1))
        for fraction in (0.25, 0.5, 0.75, 1.0):
            r = int(radius * fraction)
            painter.drawEllipse(center_x - r, center_y - r, r * 2, r * 2)
        painter.drawLine(center_x, center_y - radius, center_x, center_y + radius)
        painter.drawLine(center_x - radius, center_y, center_x + radius, center_y)
        painter.setPen(QPen(QColor("#63d39c"), 3))
        for angle, distance in ((25, 0.72), (118, 0.48), (205, 0.62), (310, 0.37)):
            radians = math.radians(angle)
            x = center_x + int(math.sin(radians) * radius * distance)
            y = center_y - int(math.cos(radians) * radius * distance)
            painter.drawPoint(x, y)


class EffectPanel(QFrame):
    def __init__(self, name: str, title: str, *, visual: str | None = None) -> None:
        super().__init__()
        self.setObjectName(name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        if visual:
            layout.addWidget(VisualCanvas(visual), 1)
        if name == "arm":
            for joint in range(1, 7):
                row = QHBoxLayout()
                row.addWidget(QLabel(f"舵机 {joint}"))
                meter = QProgressBar()
                meter.setRange(800, 2200)
                meter.setValue(1500)
                meter.setTextVisible(False)
                row.addWidget(meter, 1)
                layout.addLayout(row)
        self.status_label = QLabel("等待运行")
        self.status_label.setObjectName("effectStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def apply_event(self, event: dict) -> None:
        self.status_label.setText(str(event.get("message") or event.get("value") or "状态已更新"))


class RunWorker(QThread):
    completed = Signal(object)

    def __init__(self, runner: Runner, request: RunRequest) -> None:
        super().__init__()
        self.runner = runner
        self.request = request

    def run(self) -> None:
        self.completed.emit(self.runner.run(self.request))


class MainWindow(QMainWindow):
    def __init__(self, catalog: CourseCatalog, workspace: WorkspaceStore) -> None:
        super().__init__()
        self.catalog = catalog
        self.workspace = workspace
        self.current_experiment: Experiment | None = None
        self.runner: Runner | None = None
        self.worker: RunWorker | None = None
        self._observing = False
        self._tree_items: dict[str, QTreeWidgetItem] = {}
        self._effect_pages: dict[str, EffectPanel] = {}
        application = QApplication.instance()
        if application is not None:
            application.setFont(QFont(choose_ui_font(QFontDatabase.families()), 10))
        self.setWindowTitle("AIBox Studio 学生编程平台")
        self.setMinimumSize(1180, 720)
        self.resize(1440, 900)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._populate_course()
        if self.catalog.experiments:
            self._load_experiment(self.catalog.experiments[0])
        self.course_tree.collapseAll()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._top_bar())
        vertical = QSplitter(Qt.Orientation.Vertical)
        horizontal = QSplitter(Qt.Orientation.Horizontal)
        horizontal.addWidget(self._course_panel())
        horizontal.addWidget(self._editor_panel())
        horizontal.addWidget(self._effects_panel())
        horizontal.setSizes([280, 750, 370])
        for index in range(3):
            horizontal.setCollapsible(index, False)
        vertical.addWidget(horizontal)
        vertical.addWidget(self._output_panel())
        vertical.setSizes([690, 210])
        root.addWidget(vertical, 1)
        self.setCentralWidget(central)

    def _top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topBar")
        bar.setFixedHeight(58)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 18, 0)
        brand = QLabel("AIBox Studio")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        mode_label = (
            "机械臂真机 · 其他设备模拟"
            if os.getenv("AIBOX_DEVICE_MODE", "simulation").lower() == "hardware"
            else "开发模拟版 · 不连接真实设备"
        )
        badge = QLabel(mode_label)
        badge.setObjectName("modeBadge")
        layout.addWidget(badge)
        layout.addStretch(1)
        self.run_button = self._button("运行", QStyle.StandardPixmap.SP_MediaPlay, "runButton")
        self.stop_button = self._button("停止", QStyle.StandardPixmap.SP_MediaStop, "stopButton")
        self.save_button = self._button("保存", QStyle.StandardPixmap.SP_DialogSaveButton)
        self.reset_button = self._button("恢复模板", QStyle.StandardPixmap.SP_BrowserReload)
        self.stop_button.setEnabled(False)
        self.run_button.clicked.connect(self._start_run)
        self.stop_button.clicked.connect(self._stop_run)
        self.save_button.clicked.connect(self._save_code)
        self.reset_button.clicked.connect(self._reset_code)
        for button in (self.run_button, self.stop_button, self.save_button, self.reset_button):
            layout.addWidget(button)
        return bar

    def _button(self, text: str, icon: QStyle.StandardPixmap, name: str = "") -> QPushButton:
        button = QPushButton(text)
        if name:
            button.setObjectName(name)
        button.setIcon(self.style().standardIcon(icon))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _panel() -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)
        return frame, layout

    def _course_panel(self) -> QWidget:
        panel, layout = self._panel()
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(380)
        title = QLabel("实验课程")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.course_tree = QTreeWidget()
        self.course_tree.setHeaderHidden(True)
        self.course_tree.itemSelectionChanged.connect(self._tree_selection_changed)
        layout.addWidget(self.course_tree, 1)
        self.experiment_title = QLabel("请选择实验")
        self.experiment_title.setObjectName("experimentTitle")
        self.experiment_title.setWordWrap(True)
        layout.addWidget(self.experiment_title)
        self.experiment_description = QLabel("")
        self.experiment_description.setObjectName("description")
        self.experiment_description.setWordWrap(True)
        layout.addWidget(self.experiment_description)
        return panel

    def _editor_panel(self) -> QWidget:
        panel, layout = self._panel()
        title_row = QHBoxLayout()
        title = QLabel("Python代码")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.editor_status = QLabel("未修改")
        self.editor_status.setObjectName("description")
        title_row.addWidget(self.editor_status)
        layout.addLayout(title_row)
        self.code_editor = CodeEditor()
        self.code_editor.textChanged.connect(lambda: self.editor_status.setText("已修改"))
        layout.addWidget(self.code_editor, 1)
        return panel

    def _effects_panel(self) -> QWidget:
        panel, layout = self._panel()
        title = QLabel("实验效果")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.effect_stack = QStackedWidget()
        definitions = (
            ("text", "程序状态", None),
            ("camera", "实时摄像头", "camera"),
            ("radar", "雷达扫描", "radar"),
            ("arm", "机械臂状态", None),
            ("voice", "语音状态", None),
            ("assistant", "本地AI回答", None),
        )
        for name, heading, visual in definitions:
            page = EffectPanel(name, heading, visual=visual)
            self._effect_pages[name] = page
            self.effect_stack.addWidget(page)
        layout.addWidget(self.effect_stack, 1)
        return panel

    def _output_panel(self) -> QWidget:
        panel, layout = self._panel()
        title = QLabel("运行结果")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.output_view = QPlainTextEdit("准备就绪")
        self.output_view.setObjectName("outputView")
        output_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        output_font.setPointSize(10)
        self.output_view.setFont(output_font)
        self.output_view.setReadOnly(True)
        layout.addWidget(self.output_view, 1)
        return panel

    def _populate_course(self) -> None:
        for part in self.catalog.parts:
            part_item = QTreeWidgetItem([part.title])
            self.course_tree.addTopLevelItem(part_item)
            for chapter in part.chapters:
                chapter_item = QTreeWidgetItem([chapter.title])
                part_item.addChild(chapter_item)
                for experiment in chapter.experiments:
                    item = QTreeWidgetItem([f"实验{experiment.number}  {experiment.title}"])
                    item.setData(0, Qt.ItemDataRole.UserRole, experiment.id)
                    chapter_item.addChild(item)
                    self._tree_items[experiment.id] = item

    def select_experiment(self, experiment_id: str) -> None:
        item = self._tree_items[experiment_id]
        self.course_tree.setCurrentItem(item)
        self._load_experiment(self.catalog.experiment(experiment_id))

    def _tree_selection_changed(self) -> None:
        items = self.course_tree.selectedItems()
        if not items:
            return
        experiment_id = items[0].data(0, Qt.ItemDataRole.UserRole)
        if experiment_id:
            self._load_experiment(self.catalog.experiment(experiment_id))

    def _load_experiment(self, experiment: Experiment) -> None:
        if self.worker and self.worker.isRunning():
            return
        if self._observing:
            self._finish_observing("已切换实验，观察任务已停止")
        self.current_experiment = experiment
        self.experiment_title.setText(f"实验{experiment.number} · {experiment.title}")
        self.experiment_description.setText(experiment.description)
        self.code_editor.blockSignals(True)
        self.code_editor.setPlainText(self.workspace.load(experiment))
        self.code_editor.blockSignals(False)
        self.editor_status.setText("已加载")
        page = self._effect_pages.get(experiment.panel, self._effect_pages["text"])
        page.status_label.setText("等待运行")
        self.effect_stack.setCurrentWidget(page)

    def _save_code(self) -> None:
        if not self.current_experiment:
            return
        self.workspace.save(self.current_experiment, self.code_editor.toPlainText())
        self.editor_status.setText("已保存")

    def _reset_code(self) -> None:
        if not self.current_experiment:
            return
        code = self.workspace.reset(self.current_experiment)
        self.code_editor.setPlainText(code)
        self.editor_status.setText("已恢复模板")

    def _start_run(self) -> None:
        experiment = self.current_experiment
        if experiment is None or (self.worker and self.worker.isRunning()):
            return
        self._save_code()
        request = RunRequest(
            code=self.code_editor.toPlainText(),
            allowed_imports=experiment.allowed_imports,
            capabilities=experiment.capabilities,
            timeout_seconds=experiment.timeout_seconds,
            output_limit_bytes=experiment.output_limit_bytes,
        )
        self.runner = Runner()
        self.worker = RunWorker(self.runner, request)
        self.worker.completed.connect(self._run_finished)
        self.worker.finished.connect(self._worker_finished)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.course_tree.setEnabled(False)
        self.output_view.setPlainText("正在运行…")
        self.effect_stack.currentWidget().status_label.setText("模拟设备运行中")
        self.worker.start()

    def _stop_run(self) -> None:
        if self.runner:
            self.runner.cancel()
            self.output_view.appendPlainText("正在停止…")
        elif self._observing:
            self._finish_observing("观察任务已停止")

    def _run_finished(self, result: RunResult) -> None:
        messages = {
            "completed": "运行完成",
            "cancelled": "程序已停止",
            "timeout": "运行时间过长，已安全停止",
            "rejected": "代码未通过安全检查",
            "failed": "程序运行失败",
        }
        lines = [messages.get(result.status, result.status)]
        if result.stdout:
            lines.extend(("", result.stdout.rstrip()))
        if result.diagnostics:
            lines.extend(f"第 {item.line} 行：{item.message}" for item in result.diagnostics)
        if result.stderr and result.status == "failed":
            lines.extend(("", self._friendly_error(result.stderr)))
        self.output_view.setPlainText("\n".join(lines))
        for event in result.events:
            self.effect_stack.currentWidget().apply_event(event)
        if not result.events:
            self.effect_stack.currentWidget().status_label.setText(messages.get(result.status, result.status))
        observe = bool(
            result.status == "completed"
            and self.current_experiment
            and self.current_experiment.run_mode == "observe"
        )
        self._observing = observe
        if observe:
            self.output_view.appendPlainText("\n观察中，点击“停止”结束。")
            self.effect_stack.currentWidget().status_label.setText("观察中")
        self.run_button.setEnabled(not observe)
        self.stop_button.setEnabled(observe)
        self.course_tree.setEnabled(True)
        self.runner = None

    def _worker_finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()

    def _finish_observing(self, message: str) -> None:
        self._observing = False
        self.output_view.appendPlainText(f"\n{message}")
        self.effect_stack.currentWidget().status_label.setText(message)
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    @staticmethod
    def _friendly_error(stderr: str) -> str:
        last_line = next((line for line in reversed(stderr.splitlines()) if line.strip()), "未知错误")
        return f"代码执行遇到问题：{last_line}"

    def closeEvent(self, event) -> None:
        self._observing = False
        if self.runner and self.runner.is_running:
            self.runner.cancel()
        if self.worker and self.worker.isRunning():
            self.worker.wait(1500)
        event.accept()


def build_window(*, course_root: str | Path, workspace_root: str | Path) -> MainWindow:
    return MainWindow(CourseCatalog.load(course_root), WorkspaceStore(workspace_root))


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("AIBox Studio")
    application.setOrganizationName("AIBox")
    course_root = Path(os.getenv("AIBOX_COURSE_ROOT", bundled_course_path()))
    default_workspace = Path.home() / "Documents" / "AIBoxStudio" / "cn.aibox.basic-ai"
    workspace_root = Path(os.getenv("AIBOX_WORKSPACE_ROOT", default_workspace))
    try:
        window = build_window(course_root=course_root, workspace_root=workspace_root)
    except Exception as error:
        QMessageBox.critical(None, "AIBox Studio", f"课程加载失败：{error}")
        return 1
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
