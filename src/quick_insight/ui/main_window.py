from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from quick_insight import APP_NAME_ZH
from quick_insight.application.errors import UserFacingError
from quick_insight.infrastructure.settings import AppSettings, save_settings
from quick_insight.ui.pages import WelcomePage
from quick_insight.ui.themes import build_qss


class MainWindow(QMainWindow):
    theme_changed = Signal(str)

    def __init__(self, *, settings: AppSettings, settings_path: Path | None = None) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle(APP_NAME_ZH)
        self.resize(1366, 768)
        self._settings = settings
        self._settings_path = settings_path

        self._stack = QStackedWidget()
        self._error_label = QLabel("无错误")
        self._theme_selector = QComboBox()

        self._configure_toolbar()
        self.setCentralWidget(self._build_workspace())
        self.statusBar().showMessage("准备就绪")
        self.apply_theme(settings.theme, persist=False)

    @property
    def current_theme(self) -> str:
        return self._settings.theme

    def apply_theme(self, theme: str, *, persist: bool = True) -> None:
        self._settings = self._settings.with_theme(theme)
        app = QApplication.instance()
        if app is not None:
            cast(QApplication, app).setStyleSheet(build_qss(self._settings.theme))
        self.setProperty("theme", self._settings.theme)
        self._sync_theme_selector()
        self.theme_changed.emit(self._settings.theme)
        if persist and self._settings_path is not None:
            save_settings(self._settings_path, self._settings)

    def show_user_error(self, error: UserFacingError) -> None:
        self._error_label.setText(error.display_text())
        self.statusBar().showMessage(error.title_zh, 5000)

    def _configure_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addWidget(QLabel("主题"))
        self._theme_selector.setObjectName("themeSelector")
        self._theme_selector.addItem("浅色", "light")
        self._theme_selector.addItem("深色", "dark")
        self._theme_selector.currentIndexChanged.connect(self._on_theme_selected)
        toolbar.addWidget(self._theme_selector)

        help_button = QPushButton("设置")
        help_button.setObjectName("settingsButton")
        help_button.clicked.connect(
            lambda: self._show_future_error("settings", "设置将在后续里程碑完善")
        )
        toolbar.addWidget(help_button)

    def _build_workspace(self) -> QWidget:
        root = QWidget()
        root.setObjectName("workspaceShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("workspaceSplitter")
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 820, 286])

        root_layout.addWidget(splitter, stretch=1)
        root_layout.addWidget(self._build_bottom_status())
        return root

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("数据与导航")
        title.setObjectName("sectionTitle")
        hint = QLabel("数据集、字段、分类将在后续里程碑接入。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        nav = QListWidget()
        nav.setObjectName("navigationList")
        for label in ("欢迎", "预览", "概览", "推荐", "图表", "文本标注"):
            item = QListWidgetItem(label)
            nav.addItem(item)
        nav.setCurrentRow(0)
        nav.currentRowChanged.connect(self._stack.setCurrentIndex)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(nav, stretch=1)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        welcome = WelcomePage()
        welcome.action_requested.connect(self._handle_welcome_action)
        self._stack.addWidget(welcome)
        self._stack.addWidget(self._placeholder_page("预览", "M1 将提供虚拟化表格预览。"))
        self._stack.addWidget(self._placeholder_page("概览", "M2 将提供结构化数据画像和质量检查。"))
        self._stack.addWidget(self._placeholder_page("推荐", "M3 将提供可解释图表推荐。"))
        self._stack.addWidget(self._placeholder_page("图表", "M4 将提供本地 Plotly 图表工作区。"))
        self._stack.addWidget(self._placeholder_page("文本标注", "M2 将提供虚拟化文本标注工作区。"))

        layout.addWidget(self._stack)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(260)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("上下文面板")
        title.setObjectName("sectionTitle")
        tabs = QTabWidget()
        tabs.setObjectName("rightTabs")
        for title_text, body in (
            ("筛选", "M1/M5 将接入安全过滤表达式。"),
            ("字段", "字段映射和语义类型将在画像阶段接入。"),
            ("聚合", "分组聚合将在变换阶段接入。"),
            ("样式", "图表样式将在图表工作区接入。"),
        ):
            tabs.addTab(self._placeholder_page(title_text, body), title_text)

        layout.addWidget(title)
        layout.addWidget(tabs, stretch=1)
        return panel

    def _build_bottom_status(self) -> QWidget:
        status = QFrame()
        status.setObjectName("bottomStatus")
        layout = QHBoxLayout(status)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(16)

        for object_name, text in (
            ("rowCountLabel", "行/记录：未加载"),
            ("queryTimeLabel", "查询：--"),
            ("approximationLabel", "近似：无"),
            ("jobsLabel", "后台任务：空闲"),
        ):
            label = QLabel(text)
            label.setObjectName(object_name)
            layout.addWidget(label)
        layout.addStretch(1)
        self._error_label.setObjectName("errorLabel")
        self._error_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._error_label)
        return status

    def _placeholder_page(self, title: str, body: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        body_label = QLabel(body)
        body_label.setObjectName("muted")
        body_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(body_label)
        layout.addStretch(1)
        return page

    def _handle_welcome_action(self, key: str) -> None:
        messages = {
            "import_tabular": "表格导入将在 M1 接入，目前仅提供启动外壳。",
            "create_text_corpus": "文本语句录入将在 M2 接入，目前仅提供启动外壳。",
            "open_recent": "项目持久化将在 M5 接入，目前没有最近项目。",
            "open_sample": "示例导入将在 M1/M2 接入；样例文件已放在 samples 目录。",
        }
        self._show_future_error(key, messages.get(key, "该功能尚未接入。"))

    def _show_future_error(self, code: str, message: str) -> None:
        self.show_user_error(
            UserFacingError(
                code=f"M0_SHELL_{code.upper()}",
                title_zh="功能尚未启用",
                message_zh=message,
                next_action_zh="继续完成当前里程碑后再进入对应功能。",
                technical_detail=(
                    "M0 foundation shell only; no data import or chart pipeline is active."
                ),
            )
        )

    def _on_theme_selected(self, index: int) -> None:
        theme = self._theme_selector.itemData(index)
        if isinstance(theme, str):
            self.apply_theme(theme)

    def _sync_theme_selector(self) -> None:
        index = self._theme_selector.findData(self._settings.theme)
        if index >= 0 and index != self._theme_selector.currentIndex():
            was_blocked = self._theme_selector.blockSignals(True)
            self._theme_selector.setCurrentIndex(index)
            self._theme_selector.blockSignals(was_blocked)
