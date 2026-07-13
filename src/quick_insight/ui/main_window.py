from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QSignalBlocker, Qt, QThreadPool, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from quick_insight import APP_NAME_ZH
from quick_insight.application.analysis import TabularAnalysisService
from quick_insight.application.chart_preparation import TabularChartPreparationService
from quick_insight.application.errors import UserFacingError
from quick_insight.application.importing import TabularImportResult, TabularImportService
from quick_insight.application.jobs import JobContext, JobOutcome, JobProgress, JobState
from quick_insight.application.profiling import TabularProfiler
from quick_insight.application.text_corpus import TextCorpusImportResult, TextCorpusService
from quick_insight.application.text_labeling import (
    UNCATEGORIZED_FILTER,
    TextLabelingService,
    TextRecordEdit,
    TextRecordFilter,
)
from quick_insight.application.text_profiling import TextCorpusProfiler
from quick_insight.charts import (
    ChartRecommendationEngine,
    PlotlyChartDocument,
    build_preview_document,
)
from quick_insight.domain.enums import AnalysisIntent
from quick_insight.domain.models import (
    Category,
    ChartRecommendation,
    ColumnProfile,
    DatasetProfile,
    TextRecord,
)
from quick_insight.infrastructure.paths import AppPaths
from quick_insight.infrastructure.settings import AppSettings, save_settings
from quick_insight.infrastructure.workspace import WorkspaceDatabase
from quick_insight.ui.chart_view import PlotlyChartView
from quick_insight.ui.dialogs import TabularImportDialog, TextCorpusDialog
from quick_insight.ui.jobs import QtJobRunner
from quick_insight.ui.models import DuckDbTableModel, TextRecordTableModel
from quick_insight.ui.pages import WelcomePage
from quick_insight.ui.themes import build_qss


class MainWindow(QMainWindow):
    theme_changed = Signal(str)

    def __init__(
        self,
        *,
        settings: AppSettings,
        settings_path: Path | None = None,
        paths: AppPaths | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle(APP_NAME_ZH)
        self.resize(1366, 768)
        self._settings = settings
        self._settings_path = settings_path
        self._paths = paths or AppPaths.default().ensure()
        self._workspace = WorkspaceDatabase(self._paths.cache_dir / "workspace.duckdb")
        self._import_service = TabularImportService(self._workspace)
        self._text_corpus_service = TextCorpusService(self._workspace)
        self._text_labeling_service = TextLabelingService(self._workspace)

        self._stack = QStackedWidget()
        self._error_label = QLabel("无错误")
        self._theme_selector = QComboBox()
        self._dataset_list = QListWidget()
        self._preview_table = QTableView()
        self._preview_summary = QLabel("尚未导入数据。")
        self._profile_summary = QLabel("尚未生成数据画像。")
        self._profile_fields = QListWidget()
        self._profile_findings = QListWidget()
        self._recommendations_summary = QLabel("尚未生成图表推荐。")
        self._intent_selector = QComboBox()
        self._recommendations_content = QWidget()
        self._recommendations_layout: QVBoxLayout | None = None
        self._chart_view = PlotlyChartView()
        self._text_label_table = QTableView()
        self._text_label_status = QLabel("尚未加载文本语料。")
        self._text_search_edit = QLineEdit()
        self._text_filter_category = QComboBox()
        self._text_record_content_edit = QTextEdit()
        self._text_record_category_combo = QComboBox()
        self._text_record_tags_edit = QLineEdit()
        self._text_record_source_edit = QLineEdit()
        self._text_record_location_edit = QLineEdit()
        self._text_record_speaker_edit = QLineEdit()
        self._text_record_note_edit = QTextEdit()
        self._text_save_button = QPushButton("保存")
        self._text_save_next_button = QPushButton("保存并下一条")
        self._text_undo_button = QPushButton("撤销上次编辑")
        self._text_bulk_apply_button = QPushButton("批量应用到选中")
        self._row_count_label = QLabel("行/记录：未加载")
        self._query_time_label = QLabel("查询：--")
        self._approximation_label = QLabel("近似：无")
        self._jobs_label = QLabel("后台任务：空闲")
        self._profile_generation = 0
        self._running_profile_job: QtJobRunner[DatasetProfile] | None = None
        self._running_chart_job: QtJobRunner[PlotlyChartDocument] | None = None
        self._chart_generation = 0
        self._current_tabular_table_name: str | None = None
        self._current_profile: DatasetProfile | None = None
        self._current_recommendations: tuple[ChartRecommendation, ...] = ()
        self._current_text_corpus_id: str | None = None
        self._text_label_model: TextRecordTableModel | None = None
        self._text_categories: tuple[Category, ...] = ()
        self._selected_text_record: TextRecord | None = None
        self._text_undo_stack: list[TextRecord] = []
        self._is_disposed = False

        self._configure_toolbar()
        self.setCentralWidget(self._build_workspace())
        self.statusBar().showMessage("准备就绪")
        self.apply_theme(settings.theme, persist=False)
        self.destroyed.connect(self._on_destroyed)

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
        hint = QLabel("已导入数据集会显示在这里。")
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
        self._dataset_list.setObjectName("datasetList")
        layout.addWidget(self._dataset_list)
        layout.addWidget(nav, stretch=1)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        welcome = WelcomePage()
        welcome.action_requested.connect(self._handle_welcome_action)
        welcome.file_dropped.connect(lambda path: self._open_tabular_import(Path(path)))
        self._stack.addWidget(welcome)
        self._stack.addWidget(self._build_preview_page())
        self._stack.addWidget(self._build_overview_page())
        self._stack.addWidget(self._build_recommendations_page())
        self._stack.addWidget(self._chart_view)
        self._stack.addWidget(self._build_text_labeling_page())

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

        for label, object_name in (
            (self._row_count_label, "rowCountLabel"),
            (self._query_time_label, "queryTimeLabel"),
            (self._approximation_label, "approximationLabel"),
            (self._jobs_label, "jobsLabel"),
        ):
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

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("数据预览")
        title.setObjectName("sectionTitle")
        self._preview_summary.setObjectName("muted")
        self._preview_summary.setWordWrap(True)
        self._preview_table.setObjectName("duckDbPreviewTable")
        self._preview_table.setSortingEnabled(False)
        self._preview_table.setAlternatingRowColors(True)
        layout.addWidget(title)
        layout.addWidget(self._preview_summary)
        layout.addWidget(self._preview_table, stretch=1)
        return page

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("数据概览")
        title.setObjectName("sectionTitle")
        self._profile_summary.setObjectName("profileSummaryLabel")
        self._profile_summary.setWordWrap(True)

        fields_title = QLabel("字段画像")
        fields_title.setObjectName("sectionTitle")
        self._profile_fields.setObjectName("profileFieldsList")

        findings_title = QLabel("质量与分析发现")
        findings_title.setObjectName("sectionTitle")
        self._profile_findings.setObjectName("profileFindingsList")

        layout.addWidget(title)
        layout.addWidget(self._profile_summary)
        layout.addWidget(fields_title)
        layout.addWidget(self._profile_fields, stretch=2)
        layout.addWidget(findings_title)
        layout.addWidget(self._profile_findings, stretch=1)
        return page

    def _build_recommendations_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("图表推荐")
        title.setObjectName("sectionTitle")
        self._recommendations_summary.setObjectName("recommendationsSummaryLabel")
        self._recommendations_summary.setWordWrap(True)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._intent_selector.setObjectName("analysisIntentSelector")
        for label, intent in _analysis_intent_options():
            self._intent_selector.addItem(label, intent.value)
        self._intent_selector.currentIndexChanged.connect(self._on_recommendation_intent_changed)
        controls.addWidget(QLabel("分析目标"))
        controls.addWidget(self._intent_selector, stretch=1)
        controls.addStretch(2)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("recommendationsScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._recommendations_content.setObjectName("recommendationsContent")
        self._recommendations_layout = QVBoxLayout(self._recommendations_content)
        self._recommendations_layout.setContentsMargins(0, 0, 0, 0)
        self._recommendations_layout.setSpacing(10)
        scroll_area.setWidget(self._recommendations_content)

        layout.addWidget(title)
        layout.addWidget(self._recommendations_summary)
        layout.addLayout(controls)
        layout.addWidget(scroll_area, stretch=1)
        self._render_recommendation_cards(())
        return page

    def _build_text_labeling_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("文本标注")
        title.setObjectName("sectionTitle")
        self._text_label_status.setObjectName("textLabelStatus")
        self._text_label_status.setWordWrap(True)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._text_search_edit.setObjectName("textSearchEdit")
        self._text_search_edit.setPlaceholderText("搜索文本、来源、地点、说话人或备注")
        self._text_search_edit.textChanged.connect(self._apply_text_label_filter)
        self._text_filter_category.setObjectName("textCategoryFilter")
        self._text_filter_category.currentIndexChanged.connect(self._apply_text_label_filter)
        controls.addWidget(QLabel("搜索"))
        controls.addWidget(self._text_search_edit, stretch=2)
        controls.addWidget(QLabel("类别"))
        controls.addWidget(self._text_filter_category, stretch=1)

        self._text_label_table.setObjectName("textLabelTable")
        self._text_label_table.setAlternatingRowColors(True)
        self._text_label_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._text_label_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._text_label_table.setSortingEnabled(False)
        self._text_label_table.horizontalHeader().setStretchLastSection(True)
        self._text_label_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        editor_title = QLabel("记录详情")
        editor_title.setObjectName("sectionTitle")
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._text_record_content_edit.setObjectName("textRecordContentEdit")
        self._text_record_content_edit.setMinimumHeight(72)
        self._text_record_category_combo.setObjectName("textRecordCategoryCombo")
        self._text_record_category_combo.setEditable(True)
        self._text_record_tags_edit.setObjectName("textRecordTagsEdit")
        self._text_record_source_edit.setObjectName("textRecordSourceEdit")
        self._text_record_location_edit.setObjectName("textRecordLocationEdit")
        self._text_record_speaker_edit.setObjectName("textRecordSpeakerEdit")
        self._text_record_note_edit.setObjectName("textRecordNoteEdit")
        self._text_record_note_edit.setMinimumHeight(56)

        form.addRow("内容", self._text_record_content_edit)
        form.addRow("主类别", self._text_record_category_combo)
        form.addRow("标签", self._text_record_tags_edit)
        form.addRow("来源", self._text_record_source_edit)
        form.addRow("位置", self._text_record_location_edit)
        form.addRow("说话人", self._text_record_speaker_edit)
        form.addRow("备注", self._text_record_note_edit)

        button_row = QHBoxLayout()
        self._text_save_button.setObjectName("textSaveButton")
        self._text_save_next_button.setObjectName("textSaveNextButton")
        self._text_undo_button.setObjectName("textUndoButton")
        self._text_bulk_apply_button.setObjectName("textBulkApplyButton")
        self._text_save_button.clicked.connect(lambda: self._save_current_text_record())
        self._text_save_next_button.clicked.connect(
            lambda: self._save_current_text_record(advance=True)
        )
        self._text_undo_button.clicked.connect(self._undo_text_label_edit)
        self._text_bulk_apply_button.clicked.connect(self._bulk_apply_text_labels)
        button_row.addWidget(self._text_save_button)
        button_row.addWidget(self._text_save_next_button)
        button_row.addWidget(self._text_undo_button)
        button_row.addStretch(1)
        button_row.addWidget(self._text_bulk_apply_button)

        editor_layout.addWidget(editor_title)
        editor_layout.addLayout(form)
        editor_layout.addLayout(button_row)

        QShortcut(QKeySequence("Ctrl+S"), page).activated.connect(
            lambda: self._save_current_text_record()
        )
        QShortcut(QKeySequence("Ctrl+Return"), page).activated.connect(
            lambda: self._save_current_text_record(advance=True)
        )
        QShortcut(QKeySequence("Alt+Backspace"), page).activated.connect(
            self._undo_text_label_edit
        )

        layout.addWidget(title)
        layout.addWidget(self._text_label_status)
        layout.addLayout(controls)
        layout.addWidget(self._text_label_table, stretch=3)
        layout.addWidget(editor, stretch=2)
        self._set_text_editor_enabled(False)
        self._refresh_text_label_categories()
        return page

    def _handle_welcome_action(self, key: str) -> None:
        if key == "import_tabular":
            self._open_tabular_import()
            return
        if key == "create_text_corpus":
            self._open_text_corpus_dialog()
            return
        messages = {
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
                technical_detail="This feature is not part of the current milestone slice.",
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

    def _open_tabular_import(self, path: Path | None = None) -> None:
        dialog = TabularImportDialog(service=self._import_service, initial_path=path, parent=self)
        if (
            dialog.exec() != TabularImportDialog.DialogCode.Accepted
            or dialog.import_result is None
        ):
            return
        self._show_import_result(dialog.import_result)

    def _open_text_corpus_dialog(self, path: Path | None = None) -> None:
        dialog = TextCorpusDialog(
            service=self._text_corpus_service,
            initial_path=path,
            parent=self,
        )
        if dialog.exec() != TextCorpusDialog.DialogCode.Accepted or dialog.import_result is None:
            return
        self._show_text_corpus_result(dialog.import_result)

    def _show_import_result(self, result: TabularImportResult) -> None:
        handle = result.handle
        self._current_tabular_table_name = result.table_name
        self._dataset_list.addItem(handle.display_name)
        self._preview_table.setModel(
            DuckDbTableModel(
                workspace=self._workspace,
                table_name=result.table_name,
                columns=result.columns,
                row_count=handle.row_count or 0,
            )
        )
        self._preview_summary.setText(
            f"{handle.display_name}：{handle.row_count} 行，{handle.column_count} 列。"
            "数据已写入本地 DuckDB 工作区，预览后台按页读取。"
        )
        self._row_count_label.setText(f"行/记录：{handle.row_count}")
        self._query_time_label.setText("查询：后台分页")
        self._approximation_label.setText("近似：无")
        self._jobs_label.setText("后台任务：空闲")
        self._stack.setCurrentIndex(1)
        self.statusBar().showMessage("导入完成", 5000)
        self._start_profile_job(result)

    def _show_text_corpus_result(self, result: TextCorpusImportResult) -> None:
        handle = result.handle
        self._current_tabular_table_name = None
        self._dataset_list.addItem(handle.display_name)
        self._row_count_label.setText(f"行/记录：{handle.row_count}")
        self._query_time_label.setText("查询：文本语料已保存")
        self._approximation_label.setText("近似：无")
        self._jobs_label.setText("后台任务：空闲")
        self._error_label.setText("无错误")
        self._load_text_label_workspace(result)
        self._stack.setCurrentIndex(2)
        self.statusBar().showMessage("文本语料已保存，正在生成画像", 5000)
        self._start_text_profile_job(result)

    def _load_text_label_workspace(self, result: TextCorpusImportResult) -> None:
        corpus_id = result.handle.cache_key or result.handle.id
        self._current_text_corpus_id = corpus_id
        self._text_undo_stack.clear()
        self._selected_text_record = None
        self._refresh_text_label_categories()
        model = TextRecordTableModel(
            service=self._text_labeling_service,
            corpus_id=corpus_id,
            categories=self._text_categories,
        )
        self._text_label_model = model
        self._text_label_table.setModel(model)
        selection_model = self._text_label_table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(
                lambda *_args: self._load_selected_text_record()
            )
        model.dataChanged.connect(lambda *_args: self._load_selected_text_record())
        self._text_label_status.setText(
            f"已加载 {result.handle.display_name}：{model.rowCount()} 条文本记录。"
        )
        self._set_text_editor_enabled(False)
        if model.rowCount() > 0:
            model.record_at(0)
            self._select_text_label_row(0)

    def _refresh_text_label_categories(self) -> None:
        self._text_categories = self._text_labeling_service.list_categories()
        usage_counts = (
            self._text_labeling_service.category_usage_counts(self._current_text_corpus_id)
            if self._current_text_corpus_id
            else {}
        )
        filter_current = self._text_filter_category.currentData()
        filter_blocker = QSignalBlocker(self._text_filter_category)
        self._text_filter_category.clear()
        self._text_filter_category.addItem("全部", "")
        self._text_filter_category.addItem("未分类", UNCATEGORIZED_FILTER)
        for category in self._text_categories:
            count = usage_counts.get(category.id, 0)
            self._text_filter_category.addItem(f"{category.name} ({count})", category.id)
        filter_index = self._text_filter_category.findData(filter_current)
        self._text_filter_category.setCurrentIndex(filter_index if filter_index >= 0 else 0)
        del filter_blocker

        detail_current = self._text_record_category_combo.currentText()
        detail_blocker = QSignalBlocker(self._text_record_category_combo)
        self._text_record_category_combo.clear()
        self._text_record_category_combo.addItem("", "")
        for category in self._text_categories:
            self._text_record_category_combo.addItem(category.name, category.id)
        self._text_record_category_combo.setEditText(detail_current)
        del detail_blocker

        if self._text_label_model is not None:
            self._text_label_model.set_categories(self._text_categories)

    def _apply_text_label_filter(self) -> None:
        if self._text_label_model is None:
            return
        self._text_label_model.set_filter(self._current_text_record_filter())
        row_count = self._text_label_model.rowCount()
        self._text_label_status.setText(f"筛选后显示 {row_count} 条文本记录。")
        if row_count:
            self._set_text_editor_enabled(False)
            self._text_label_model.record_at(0)
            self._select_text_label_row(0)
        else:
            self._selected_text_record = None
            self._clear_text_record_editor()
            self._set_text_editor_enabled(False)

    def _current_text_record_filter(self) -> TextRecordFilter:
        category_data = self._text_filter_category.currentData()
        search_text = self._text_search_edit.text()
        if category_data == UNCATEGORIZED_FILTER:
            return TextRecordFilter(search_text=search_text, uncategorized_only=True)
        if isinstance(category_data, str) and category_data:
            return TextRecordFilter(search_text=search_text, category_id=category_data)
        return TextRecordFilter(search_text=search_text)

    def _load_selected_text_record(self) -> None:
        model = self._text_label_model
        if model is None:
            return
        current_index = self._text_label_table.currentIndex()
        if current_index.isValid():
            row = current_index.row()
        else:
            selected_rows = self._selected_text_rows()
            if not selected_rows:
                return
            row = selected_rows[0]
        if row < 0:
            return
        record = model.record_at(row)
        if record is None:
            self._text_label_status.setText("正在加载所选文本记录...")
            return
        if self._selected_text_record is not None and self._selected_text_record.id == record.id:
            return
        self._selected_text_record = record
        self._fill_text_record_editor(record)
        self._set_text_editor_enabled(True)
        self._text_label_status.setText(f"正在编辑记录 {record.id}")

    def _fill_text_record_editor(self, record: TextRecord) -> None:
        self._text_record_content_edit.setPlainText(record.content)
        self._text_record_category_combo.setEditText(
            self._text_category_name(record.primary_category_id)
        )
        self._text_record_tags_edit.setText(", ".join(record.tags))
        self._text_record_source_edit.setText(record.source or "")
        self._text_record_location_edit.setText(record.location or "")
        self._text_record_speaker_edit.setText(record.speaker or "")
        self._text_record_note_edit.setPlainText(record.note)

    def _clear_text_record_editor(self) -> None:
        self._text_record_content_edit.clear()
        self._text_record_category_combo.setEditText("")
        self._text_record_tags_edit.clear()
        self._text_record_source_edit.clear()
        self._text_record_location_edit.clear()
        self._text_record_speaker_edit.clear()
        self._text_record_note_edit.clear()

    def _set_text_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self._text_record_content_edit,
            self._text_record_category_combo,
            self._text_record_tags_edit,
            self._text_record_source_edit,
            self._text_record_location_edit,
            self._text_record_speaker_edit,
            self._text_record_note_edit,
            self._text_save_button,
            self._text_save_next_button,
            self._text_bulk_apply_button,
        ):
            widget.setEnabled(enabled)
        self._text_undo_button.setEnabled(bool(self._text_undo_stack))

    def _current_text_record_edit(self, record: TextRecord) -> TextRecordEdit:
        return TextRecordEdit(
            record_id=record.id,
            content=self._text_record_content_edit.toPlainText(),
            category_name=self._text_record_category_combo.currentText(),
            tags_text=self._text_record_tags_edit.text(),
            source=self._text_record_source_edit.text(),
            location=self._text_record_location_edit.text(),
            speaker=self._text_record_speaker_edit.text(),
            note=self._text_record_note_edit.toPlainText(),
        )

    def _save_current_text_record(self, *, advance: bool = False) -> bool:
        corpus_id = self._current_text_corpus_id
        record = self._selected_text_record
        model = self._text_label_model
        if corpus_id is None or record is None or model is None:
            self._text_label_status.setText("请先选择一条文本记录。")
            return False
        current_row = self._text_label_table.currentIndex().row()
        try:
            updated = self._text_labeling_service.update_record(
                corpus_id,
                record,
                self._current_text_record_edit(record),
            )
        except UserFacingError as exc:
            self.show_user_error(exc)
            return False
        self._text_undo_stack.append(record)
        self._selected_text_record = updated
        self._refresh_text_label_after_edit()
        target_row = current_row + 1 if advance else current_row
        self._select_text_label_row(min(max(target_row, 0), model.rowCount() - 1))
        self._text_label_status.setText("文本记录已保存。")
        return True

    def _bulk_apply_text_labels(self) -> None:
        corpus_id = self._current_text_corpus_id
        model = self._text_label_model
        if corpus_id is None or model is None:
            return
        records = [model.record_at(row) for row in self._selected_text_rows()]
        loaded_records = [record for record in records if record is not None]
        if not loaded_records:
            self._text_label_status.setText("请先选择已加载的文本记录。")
            return
        category_name = self._text_record_category_combo.currentText()
        tags_text = self._text_record_tags_edit.text()
        for record in loaded_records:
            self._text_undo_stack.append(record)
            self._text_labeling_service.update_record_category_and_tags(
                corpus_id,
                record,
                category_name=category_name,
                tags_text=tags_text,
            )
        self._refresh_text_label_after_edit()
        self._text_label_status.setText(f"已批量更新 {len(loaded_records)} 条记录。")

    def _undo_text_label_edit(self) -> None:
        corpus_id = self._current_text_corpus_id
        if corpus_id is None or not self._text_undo_stack:
            self._text_label_status.setText("没有可撤销的文本编辑。")
            return
        snapshot = self._text_undo_stack.pop()
        self._text_labeling_service.restore_record(corpus_id, snapshot)
        self._refresh_text_label_after_edit()
        self._text_label_status.setText("已撤销最近一次文本编辑。")

    def _refresh_text_label_after_edit(self) -> None:
        self._refresh_text_label_categories()
        if self._text_label_model is not None:
            self._text_label_model.refresh()
        self._text_undo_button.setEnabled(bool(self._text_undo_stack))

    def _selected_text_rows(self) -> tuple[int, ...]:
        selection_model = self._text_label_table.selectionModel()
        rows = {index.row() for index in selection_model.selectedRows()}
        if not rows and self._text_label_table.currentIndex().isValid():
            rows.add(self._text_label_table.currentIndex().row())
        return tuple(sorted(rows))

    def _select_text_label_row(self, row: int) -> None:
        model = self._text_label_model
        if model is None or row < 0 or row >= model.rowCount():
            return
        index = model.index(row, 0)
        self._text_label_table.setCurrentIndex(index)
        self._text_label_table.selectRow(row)
        self._load_selected_text_record()

    def _text_category_name(self, category_id: str | None) -> str:
        if not category_id:
            return ""
        for category in self._text_categories:
            if category.id == category_id:
                return category.name
        return category_id

    def _on_recommendation_intent_changed(self, _index: int) -> None:
        if self._current_profile is not None:
            self._update_recommendations(self._current_profile)

    def _current_analysis_intent(self) -> AnalysisIntent:
        value = self._intent_selector.currentData()
        if isinstance(value, str):
            try:
                return AnalysisIntent(value)
            except ValueError:
                return AnalysisIntent.AUTO
        return AnalysisIntent.AUTO

    def _update_recommendations(self, profile: DatasetProfile) -> None:
        self._current_profile = profile
        recommendations = ChartRecommendationEngine().recommend(
            profile,
            intent=self._current_analysis_intent(),
        )
        self._current_recommendations = recommendations
        self._render_recommendation_cards(recommendations)

    def _render_recommendation_cards(
        self,
        recommendations: tuple[ChartRecommendation, ...],
    ) -> None:
        layout = self._recommendations_layout
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._current_profile is None:
            self._recommendations_summary.setText("请先导入数据并生成画像。")
            layout.addStretch(1)
            return
        self._recommendations_summary.setText(
            f"已生成 {len(recommendations)} 条推荐；"
            f"当前目标：{self._intent_selector.currentText()}。"
        )
        if not recommendations:
            empty = QLabel("当前画像没有足够字段生成图表推荐。")
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            layout.addStretch(1)
            return
        for index, recommendation in enumerate(recommendations, start=1):
            layout.addWidget(self._build_recommendation_card(index, recommendation))
        layout.addStretch(1)

    def _build_recommendation_card(
        self,
        index: int,
        recommendation: ChartRecommendation,
    ) -> QWidget:
        card = QFrame()
        card.setObjectName("recommendationCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel(f"{index}. {_chart_type_text(recommendation.spec.chart_type)}")
        title.setObjectName("recommendationTitleLabel")
        score = QLabel(f"{recommendation.score} 分")
        score.setObjectName("recommendationScoreLabel")
        title_row.addWidget(title, stretch=1)
        title_row.addWidget(score)

        fields = QLabel(f"字段：{_mapping_text(recommendation.spec.mappings)}")
        fields.setObjectName("recommendationFieldsLabel")
        fields.setWordWrap(True)
        reasons = QLabel(f"理由：{_reason_text(recommendation.reasons)}")
        reasons.setObjectName("recommendationReasonsLabel")
        reasons.setWordWrap(True)
        warnings = QLabel(f"警告：{_warning_text(recommendation.warnings)}")
        warnings.setObjectName("recommendationWarningsLabel")
        warnings.setWordWrap(True)
        aggregation = QLabel(f"聚合：{_aggregation_text(recommendation.spec.aggregation)}")
        aggregation.setObjectName("recommendationAggregationLabel")
        aggregation.setWordWrap(True)
        budget = QLabel(f"数据预算：{_data_budget_text(recommendation.data_budget)}")
        budget.setObjectName("recommendationBudgetLabel")
        budget.setWordWrap(True)
        score_breakdown = QLabel(
            f"评分：{_score_breakdown_text(recommendation.spec.aggregation)}"
        )
        score_breakdown.setObjectName("recommendationBreakdownLabel")
        score_breakdown.setWordWrap(True)

        button_row = QHBoxLayout()
        generate_button = QPushButton("生成图表")
        generate_button.setObjectName("recommendationGenerateButton")
        edit_button = QPushButton("编辑映射")
        edit_button.setObjectName("recommendationEditButton")
        generate_button.clicked.connect(
            lambda _checked=False, rec=recommendation: self._generate_recommendation_chart(rec)
        )
        edit_button.clicked.connect(
            lambda _checked=False, rec=recommendation: self._show_recommendation_future_error(
                "edit",
                rec,
            )
        )
        button_row.addStretch(1)
        button_row.addWidget(edit_button)
        button_row.addWidget(generate_button)

        card_layout.addLayout(title_row)
        card_layout.addWidget(fields)
        card_layout.addWidget(reasons)
        card_layout.addWidget(warnings)
        card_layout.addWidget(aggregation)
        card_layout.addWidget(budget)
        card_layout.addWidget(score_breakdown)
        card_layout.addLayout(button_row)
        return card

    def _generate_recommendation_chart(self, recommendation: ChartRecommendation) -> None:
        table_name = self._current_tabular_table_name
        if table_name is not None:
            self._start_chart_preparation_job(table_name, recommendation)
            return
        document = build_preview_document(recommendation)
        self._render_chart_document(document)
        self._jobs_label.setText("后台任务：本地 Plotly 渲染器预览已载入")
        self.show_user_error(
            UserFacingError(
                code="CHART_DATA_PREPARATION_PENDING",
                title_zh="已载入图表渲染器预览",
                message_zh=(
                    "当前图表页证明本地 Plotly/WebEngine 渲染路径可用，"
                    "尚未使用真实数据聚合结果。"
                ),
                next_action_zh="后续 M4 切片会接入图表数据准备、降采样、导出和编辑映射。",
                technical_detail=(
                    f"chart_type={recommendation.spec.chart_type}; "
                    f"mappings={recommendation.spec.mappings}; "
                    f"budget={recommendation.data_budget}"
                ),
            )
        )

    def _start_chart_preparation_job(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
    ) -> None:
        if self._running_chart_job is not None:
            self._running_chart_job.cancel()
        self._chart_generation += 1
        generation = self._chart_generation
        self._jobs_label.setText("后台任务：正在准备图表数据")
        job = QtJobRunner(
            "tabular_chart_preparation",
            lambda context: TabularChartPreparationService(self._workspace).prepare(
                table_name,
                recommendation,
                context=context,
            ),
        )
        self._running_chart_job = job
        job.signals.progress.connect(self._on_chart_progress)
        job.signals.completed.connect(
            lambda outcome, expected_generation=generation: self._on_chart_completed(
                expected_generation,
                outcome,
            )
        )
        QThreadPool.globalInstance().start(job)

    def _on_chart_progress(self, progress: JobProgress) -> None:
        if self._is_disposed:
            return
        if progress.state is not JobState.RUNNING:
            return
        percent_text = "" if progress.percent is None else f"{progress.percent}% "
        self._jobs_label.setText(f"后台任务：{percent_text}{progress.message_zh}")

    def _on_chart_completed(
        self,
        expected_generation: int,
        outcome: JobOutcome[PlotlyChartDocument],
    ) -> None:
        if self._is_disposed or expected_generation != self._chart_generation:
            return
        self._running_chart_job = None
        if outcome.state is JobState.CANCELLED:
            self._jobs_label.setText("后台任务：图表准备已取消")
            return
        if outcome.state is JobState.SUCCEEDED and outcome.value is not None:
            self._render_chart_document(outcome.value)
            self._jobs_label.setText("后台任务：图表数据已准备")
            self._error_label.setText("无错误")
            self.statusBar().showMessage("图表已使用真实数据准备并渲染", 5000)
            return
        self._jobs_label.setText("后台任务：图表准备失败")
        if isinstance(outcome.error, UserFacingError):
            self.show_user_error(outcome.error)
            return
        self.show_user_error(
            UserFacingError(
                code="CHART_PREPARATION_UNEXPECTED_FAILURE",
                title_zh="图表准备失败",
                message_zh="准备图表数据时发生未预期错误。",
                next_action_zh="请保留源文件并复制技术细节，稍后重试或提交问题。",
                technical_detail=repr(outcome.error),
            )
        )

    def _render_chart_document(self, document: PlotlyChartDocument) -> None:
        self._chart_view.render_document(document)
        self._stack.setCurrentIndex(4)

    def _show_recommendation_future_error(
        self,
        action: str,
        recommendation: ChartRecommendation,
    ) -> None:
        action_text = "图表生成" if action == "generate" else "映射编辑"
        self.show_user_error(
            UserFacingError(
                code=f"CHART_RECOMMENDATION_{action.upper()}_PENDING",
                title_zh=f"{action_text}尚未接入",
                message_zh=(
                    f"{_chart_type_text(recommendation.spec.chart_type)} 的{action_text}"
                    "将在后续图表工作区接入。"
                ),
                next_action_zh="当前可以先查看推荐分数、字段、理由、警告和数据预算。",
                technical_detail=(
                    f"chart_type={recommendation.spec.chart_type}; "
                    f"mappings={recommendation.spec.mappings}"
                ),
            )
        )

    def _on_destroyed(self) -> None:
        self._is_disposed = True
        self._profile_generation += 1
        if self._running_profile_job is not None:
            self._running_profile_job.cancel()
            self._running_profile_job = None
        if self._running_chart_job is not None:
            self._running_chart_job.cancel()
            self._running_chart_job = None
        if self._text_label_model is not None:
            self._text_label_model.cancel_pending_queries()
            self._text_label_model = None

    def _start_profile_job(self, result: TabularImportResult) -> None:
        if self._running_profile_job is not None:
            self._running_profile_job.cancel()
        self._profile_generation += 1
        generation = self._profile_generation
        handle = result.handle
        table_name = result.table_name
        import_options = dict(handle.import_options)
        self._profile_summary.setText("正在生成数据画像和质量检查...")
        self._profile_fields.clear()
        self._profile_findings.clear()
        self._jobs_label.setText("后台任务：正在生成画像")
        job = QtJobRunner(
            "tabular_profile",
            lambda context: self._profile_table(
                context,
                dataset_id=handle.id,
                table_name=table_name,
                import_options=import_options,
            ),
        )
        self._running_profile_job = job
        job.signals.progress.connect(self._on_profile_progress)
        job.signals.completed.connect(
            lambda outcome, expected_generation=generation: self._on_profile_completed(
                expected_generation,
                outcome,
            )
        )
        QThreadPool.globalInstance().start(job)

    def _start_text_profile_job(self, result: TextCorpusImportResult) -> None:
        if self._running_profile_job is not None:
            self._running_profile_job.cancel()
        self._profile_generation += 1
        generation = self._profile_generation
        handle = result.handle
        corpus_id = handle.cache_key or handle.id
        self._profile_summary.setText("正在生成文本语料画像和质量检查...")
        self._profile_fields.clear()
        self._profile_findings.clear()
        self._jobs_label.setText("后台任务：正在生成文本画像")
        job = QtJobRunner(
            "text_corpus_profile",
            lambda context: self._profile_text_corpus(
                context,
                dataset_id=handle.id,
                corpus_id=corpus_id,
            ),
        )
        self._running_profile_job = job
        job.signals.progress.connect(self._on_profile_progress)
        job.signals.completed.connect(
            lambda outcome, expected_generation=generation: self._on_profile_completed(
                expected_generation,
                outcome,
            )
        )
        QThreadPool.globalInstance().start(job)

    def _profile_table(
        self,
        context: JobContext,
        *,
        dataset_id: str,
        table_name: str,
        import_options: dict[str, object],
    ) -> DatasetProfile:
        context.progress(15, "正在扫描列统计和质量指标")
        profile = TabularProfiler(self._workspace).profile_table(
            dataset_id,
            table_name,
            import_options=import_options,
        )
        context.progress(70, "正在生成一键分析发现")
        analysis_findings = TabularAnalysisService(self._workspace).analyze_table(
            table_name,
            profile,
        )
        context.progress(90, "正在整理画像结果")
        return replace(profile, findings=profile.findings + analysis_findings)

    def _profile_text_corpus(
        self,
        context: JobContext,
        *,
        dataset_id: str,
        corpus_id: str,
    ) -> DatasetProfile:
        context.progress(20, "正在扫描文本记录和分类信息")
        profile = TextCorpusProfiler(self._workspace).profile_corpus(
            dataset_id,
            corpus_id,
        )
        context.progress(90, "正在整理文本画像结果")
        return profile

    def _on_profile_progress(self, progress: JobProgress) -> None:
        if self._is_disposed:
            return
        if not self._profile_widgets_available():
            return
        if progress.state is not JobState.RUNNING:
            return
        percent_text = "" if progress.percent is None else f"{progress.percent}% "
        self._jobs_label.setText(f"后台任务：{percent_text}{progress.message_zh}")

    def _on_profile_completed(
        self,
        expected_generation: int,
        outcome: JobOutcome[DatasetProfile],
    ) -> None:
        if self._is_disposed:
            return
        if expected_generation != self._profile_generation:
            return
        if not self._profile_widgets_available():
            return
        self._running_profile_job = None
        if outcome.state is JobState.CANCELLED:
            self._jobs_label.setText("后台任务：画像已取消")
            return
        if outcome.state is JobState.SUCCEEDED and outcome.value is not None:
            self._show_profile(outcome.value)
            return
        self._jobs_label.setText("后台任务：画像失败")
        error = outcome.error
        self.show_user_error(
            UserFacingError(
                code="PROFILE_UNEXPECTED_FAILURE",
                title_zh="画像失败",
                message_zh="生成数据画像时发生未预期错误。",
                next_action_zh="请保留源文件并复制技术详情，稍后重试或提交问题。",
                technical_detail=repr(error),
            )
        )

    def _profile_widgets_available(self) -> bool:
        try:
            self._profile_summary.objectName()
            self._profile_fields.objectName()
            self._profile_findings.objectName()
            self._jobs_label.objectName()
            self._stack.objectName()
        except RuntimeError:
            self._is_disposed = True
            self._profile_generation += 1
            self._running_profile_job = None
            return False
        return True

    def _show_profile(self, profile: DatasetProfile) -> None:
        if not self._profile_widgets_available():
            return
        if profile.method == "text_corpus_full_scan":
            self._show_text_profile(profile)
            return
        self._update_recommendations(profile)
        quality = profile.summary.get("quality")
        quality_summary = quality if isinstance(quality, dict) else {}
        column_count = profile.summary.get("column_count", len(profile.column_profiles))
        duplicate_rows = quality_summary.get("duplicate_row_count", 0)
        missing_values = quality_summary.get("total_missing_values", 0)
        self._profile_summary.setText(
            f"画像完成：{profile.row_count} 行，{column_count} 列；"
            f"重复行 {duplicate_rows}；缺失值 {missing_values}。"
        )
        self._profile_fields.clear()
        for column in profile.column_profiles:
            self._profile_fields.addItem(_field_profile_text(column))
        self._profile_findings.clear()
        if profile.findings:
            for finding in profile.findings:
                self._profile_findings.addItem(finding.statement)
        else:
            self._profile_findings.addItem("未发现明显质量问题。")
        self._approximation_label.setText("近似：是" if profile.approximate else "近似：无")
        self._jobs_label.setText("后台任务：空闲")
        self._stack.setCurrentIndex(2)
        self.statusBar().showMessage("数据画像完成", 5000)

    def _show_text_profile(self, profile: DatasetProfile) -> None:
        self._update_recommendations(profile)
        categorized_count = profile.summary.get("categorized_count", 0)
        uncategorized_count = profile.summary.get("uncategorized_count", 0)
        duplicate_text = profile.summary.get("exact_duplicate_record_count", 0)
        missing_source = profile.summary.get("missing_source_count", 0)
        self._profile_summary.setText(
            f"文本画像完成：{profile.row_count} 条记录；"
            f"已分类 {categorized_count}，未分类 {uncategorized_count}；"
            f"重复文本 {duplicate_text}；缺少来源 {missing_source}。"
        )
        self._profile_fields.clear()
        for column in profile.column_profiles:
            self._profile_fields.addItem(_field_profile_text(column))
        self._profile_findings.clear()
        if profile.findings:
            for finding in profile.findings:
                self._profile_findings.addItem(finding.statement)
        else:
            self._profile_findings.addItem("未发现明显文本质量问题。")
        self._approximation_label.setText("近似：是" if profile.approximate else "近似：无")
        self._jobs_label.setText("后台任务：空闲")
        self._stack.setCurrentIndex(2)
        self.statusBar().showMessage("文本画像完成", 5000)


def _field_profile_text(column: ColumnProfile) -> str:
    distinct = "未知" if column.distinct_count is None else str(column.distinct_count)
    warnings = "" if not column.warnings else f"；警告 {', '.join(column.warnings)}"
    return (
        f"{column.name} · {_semantic_type_text(column.semantic_type.value)} · "
        f"缺失 {column.null_count} · 不同值 {distinct}{warnings}"
    )


def _semantic_type_text(value: str) -> str:
    return {
        "numeric": "数值",
        "categorical": "类别",
        "datetime": "时间",
        "boolean": "布尔",
        "text": "文本",
        "long_text": "长文本",
        "identifier": "标识符",
        "geo_latitude": "纬度",
        "geo_longitude": "经度",
        "primary_category": "主类别",
        "tag_list": "标签列表",
        "source_reference": "来源",
        "unknown": "未知",
    }.get(value, value)


def _analysis_intent_options() -> tuple[tuple[str, AnalysisIntent], ...]:
    return (
        ("自动帮我分析", AnalysisIntent.AUTO),
        ("看数据随时间怎么变化", AnalysisIntent.TREND),
        ("比较不同类别", AnalysisIntent.COMPARISON),
        ("查看数据分布", AnalysisIntent.DISTRIBUTION),
        ("查看两个指标是否有关", AnalysisIntent.RELATIONSHIP),
        ("查看各类别占比", AnalysisIntent.COMPOSITION),
        ("查找异常数据", AnalysisIntent.ANOMALY),
        ("查看指标相关性", AnalysisIntent.CORRELATION),
    )


def _chart_type_text(chart_type: str) -> str:
    return {
        "line": "折线图",
        "area": "面积图",
        "bar": "柱状图",
        "box": "箱线图",
        "histogram": "直方图",
        "scatter": "散点图",
        "density_heatmap": "密度热图",
        "crosstab_heatmap": "交叉热图",
        "stacked_bar": "堆叠柱状图",
        "correlation_heatmap": "相关性热图",
        "donut": "环形图",
        "text_category_bar": "文本类别计数图",
        "text_classification_status_bar": "分类状态图",
        "text_source_category_heatmap": "来源-类别热图",
        "text_keyword_bar": "关键词排行图",
        "text_category_keyword_heatmap": "类别-关键词热图",
        "text_tag_cooccurrence_heatmap": "标签共现热图",
    }.get(chart_type, chart_type)


def _mapping_text(mappings: dict[str, str]) -> str:
    if not mappings:
        return "无字段映射"
    return "；".join(f"{_mapping_role_text(key)}={value}" for key, value in mappings.items())


def _mapping_role_text(role: str) -> str:
    return {
        "x": "横轴",
        "y": "纵轴",
        "color": "颜色",
        "category": "类别",
        "value": "数值",
        "fields": "字段",
    }.get(role, role)


def _reason_text(reasons: tuple[str, ...]) -> str:
    if not reasons:
        return "无"
    return "；".join(_reason_item_text(reason) for reason in reasons)


def _reason_item_text(reason: str) -> str:
    if reason.startswith("score="):
        return f"总分 {reason.removeprefix('score=')}"
    return {
        "datetime_numeric_trend": "时间字段与数值字段适合观察趋势",
        "line_chart_preserves_time_order": "折线图保留时间顺序",
        "non_negative_numeric_values_allow_area_context": "数值非负，适合面积上下文",
        "category_numeric_comparison": "类别字段与数值字段适合比较",
        "mean_by_category": "按类别计算均值",
        "category_numeric_distribution": "按类别查看数值分布",
        "box_plot_shows_spread": "箱线图展示离散程度",
        "single_numeric_distribution": "单个数值字段适合查看分布",
        "histogram_uses_aggregated_bins": "直方图使用分箱聚合",
        "two_numeric_relationship": "两个数值字段适合查看关系",
        "scatter_shows_pairwise_pattern": "散点图展示成对模式",
        "density_bins_preferred_for_very_large_scatter": "大数据量优先使用密度分箱",
        "two_categorical_crosstab": "两个类别字段适合交叉统计",
        "heatmap_uses_count_aggregation": "热图使用计数聚合",
        "two_categorical_composition": "两个类别字段适合查看组成",
        "stacked_bar_counts_records": "堆叠柱状图统计记录数",
        "multiple_numeric_correlation": "多个数值字段适合相关性矩阵",
        "field_limit_keeps_heatmap_readable": "字段数量已控制以保持可读",
        "small_category_composition": "少量类别适合组成图",
        "donut_allowed_for_at_most_6_categories": "类别数不超过 6，允许环形图",
        "text_category_counts": "文本主类别可做计数统计",
        "uses_persisted_primary_category": "使用已保存的主类别",
        "classified_uncategorized_status": "可比较已分类与未分类数量",
        "two_status_categories_are_readable": "状态类别数量少，易读",
        "source_category_crosstab": "来源与类别适合交叉分析",
        "heatmap_summarizes_two_text_metadata_fields": "热图汇总两个文本元数据字段",
        "keyword_ranking": "可展示字面关键字命中排行",
        "keyword_counts_are_surface_level": "关键字统计仅代表字面匹配",
        "category_keyword_differences": "可比较各类别关键字差异",
        "heatmap_compares_literal_keyword_counts": "热图比较字面关键字计数",
        "tag_co_occurrence": "可查看标签共同出现",
        "co_occurrence_is_not_causation": "共现不代表因果",
    }.get(reason, reason)


def _warning_text(warnings: tuple[str, ...]) -> str:
    if not warnings:
        return "无"
    return "；".join(_warning_item_text(warning) for warning in warnings)


def _warning_item_text(warning: str) -> str:
    field, separator, code = warning.partition(":")
    prefix = f"{field}：" if separator else ""
    key = code if separator else warning
    return prefix + {
        "missing_values": "存在缺失值",
        "too_many_categories_for_donut": "类别较多，不优先使用环形图",
        "top_n_with_other_recommended": "建议 Top N 加 Other",
        "high_cardinality_category": "类别基数较高",
        "filter_or_top_n_required": "需要过滤或 Top N",
        "very_high_cardinality_category": "类别基数很高",
        "time_series_downsampling_required": "需要时间序列降采样",
        "scatter_sampling_or_webgl_required": "散点需要采样或 WebGL",
        "raw_scatter_too_large_density_bins_preferred": "原始散点过大，优先密度分箱",
        "correlation_limited_to_first_8_numeric_fields": "相关性热图限制为前 8 个数值字段",
        "keyword_matches_are_not_semantic_topics": "关键字命中不是语义主题",
        "keyword_matches_are_surface_level": "关键字匹配仅为字面统计",
        "co_occurrence_is_not_causation": "共现不代表因果",
        "category_count_unknown": "类别数量未知",
    }.get(key, key)


def _aggregation_text(aggregation: dict[str, Any]) -> str:
    visible_items = {
        key: value for key, value in aggregation.items() if key != "score_breakdown"
    }
    if not visible_items:
        return "无需预先聚合"
    return "；".join(f"{key}={value}" for key, value in visible_items.items())


def _score_breakdown_text(aggregation: dict[str, Any]) -> str:
    breakdown = aggregation.get("score_breakdown")
    if not isinstance(breakdown, dict):
        return "无评分明细"
    parts = (
        ("字段", "field_compatibility"),
        ("意图", "intent_match"),
        ("基数", "cardinality_suitability"),
        ("质量", "data_quality_suitability"),
        ("性能", "performance_readability"),
    )
    return "；".join(f"{label} {breakdown.get(key, 0)}" for label, key in parts)


def _data_budget_text(data_budget: dict[str, Any]) -> str:
    if not data_budget:
        return "无"
    requires = "需要预处理" if data_budget.get("requires_preparation") else "可直接准备"
    approximate = "近似" if data_budget.get("approximate") else "精确"
    return (
        f"原始 {data_budget.get('original_rows', '未知')} 行；"
        f"目标点数 {data_budget.get('target_points', '未知')}；"
        f"策略 {data_budget.get('strategy', '未知')}；{requires}；{approximate}"
    )
