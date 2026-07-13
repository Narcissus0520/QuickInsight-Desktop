from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QSignalBlocker, Qt, QThreadPool, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
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
from quick_insight.application.chart_preparation import (
    TabularChartPreparationService,
    TextChartPreparationService,
)
from quick_insight.application.data_export import (
    DataExportFormat,
    DataExportResult,
    ProcessedDataExportService,
)
from quick_insight.application.errors import UserFacingError
from quick_insight.application.importing import TabularImportResult, TabularImportService
from quick_insight.application.jobs import JobContext, JobOutcome, JobProgress, JobState
from quick_insight.application.profiling import TabularProfiler
from quick_insight.application.project import (
    PROJECT_EXTENSION,
    ProjectDatasetEntry,
    ProjectManifest,
    ProjectOpenResult,
    ProjectPersistenceService,
    ProjectSaveResult,
    SourceReferenceStatus,
    validate_source_references,
)
from quick_insight.application.text_corpus import TextCorpusImportResult, TextCorpusService
from quick_insight.application.text_labeling import (
    UNCATEGORIZED_FILTER,
    TextLabelingService,
    TextRecordEdit,
    TextRecordFilter,
)
from quick_insight.application.text_profiling import TextCorpusProfiler
from quick_insight.application.transforms import TabularTransformService, TransformPreviewResult
from quick_insight.charts import (
    ChartExportFormat,
    ChartExportResult,
    ChartRecommendationEngine,
    PlotlyChartDocument,
    build_preview_document,
)
from quick_insight.domain.enums import AnalysisIntent, DatasetKind
from quick_insight.domain.models import (
    Category,
    ChartRecommendation,
    ColumnProfile,
    DatasetHandle,
    DatasetProfile,
    TextRecord,
    TransformStep,
)
from quick_insight.infrastructure.paths import AppPaths
from quick_insight.infrastructure.settings import AppSettings, save_settings
from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase
from quick_insight.ui.chart_view import PlotlyChartView
from quick_insight.ui.dialogs import SourceRelocationDialog, TabularImportDialog, TextCorpusDialog
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
        self._transform_service = TabularTransformService(self._workspace)
        self._project_service = ProjectPersistenceService(self._workspace)
        self._data_export_service = ProcessedDataExportService(self._workspace)

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
        self._transform_status = QLabel("请先导入表格数据。")
        self._transform_operation_combo = QComboBox()
        self._transform_column_combo = QComboBox()
        self._transform_extra_column_combo = QComboBox()
        self._transform_filter_operator_combo = QComboBox()
        self._transform_filter_join_combo = QComboBox()
        self._transform_value_edit = QLineEdit()
        self._transform_alias_edit = QLineEdit()
        self._transform_direction_combo = QComboBox()
        self._transform_type_combo = QComboBox()
        self._transform_aggregation_combo = QComboBox()
        self._transform_field_list = QListWidget()
        self._transform_step_list = QListWidget()
        self._transform_add_button = QPushButton("添加步骤")
        self._transform_remove_button = QPushButton("移除步骤")
        self._transform_clear_button = QPushButton("清空步骤")
        self._transform_preview_button = QPushButton("生成预览表")
        self._transform_cancel_button = QPushButton("取消预览")
        self._source_relocation_button = QPushButton("重定位源文件")
        self._export_tabular_button = QPushButton("导出表格")
        self._export_text_button = QPushButton("导出文本")
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
        self._category_manage_combo = QComboBox()
        self._category_target_combo = QComboBox()
        self._category_name_edit = QLineEdit()
        self._category_description_edit = QLineEdit()
        self._category_note_edit = QLineEdit()
        self._category_rename_button = QPushButton("重命名")
        self._category_merge_button = QPushButton("合并")
        self._category_delete_button = QPushButton("删除")
        self._row_count_label = QLabel("行/记录：未加载")
        self._query_time_label = QLabel("查询：--")
        self._approximation_label = QLabel("近似：无")
        self._jobs_label = QLabel("后台任务：空闲")
        self._profile_generation = 0
        self._running_profile_job: QtJobRunner[DatasetProfile] | None = None
        self._running_chart_job: QtJobRunner[PlotlyChartDocument] | None = None
        self._running_transform_job: QtJobRunner[TransformPreviewResult] | None = None
        self._running_project_job: QtJobRunner[ProjectSaveResult | ProjectOpenResult] | None = None
        self._running_data_export_job: QtJobRunner[DataExportResult] | None = None
        self._chart_generation = 0
        self._transform_generation = 0
        self._project_generation = 0
        self._data_export_generation = 0
        self._current_tabular_table_name: str | None = None
        self._current_tabular_columns: tuple[WorkspaceColumn, ...] = ()
        self._current_profile: DatasetProfile | None = None
        self._current_recommendations: tuple[ChartRecommendation, ...] = ()
        self._current_text_corpus_id: str | None = None
        self._project_dataset_entries: list[ProjectDatasetEntry] = []
        self._current_project_manifest: ProjectManifest | None = None
        self._current_project_path: Path | None = None
        self._source_reference_statuses: tuple[SourceReferenceStatus, ...] = ()
        self._transform_step_objects: list[TransformStep] = []
        self._text_label_model: TextRecordTableModel | None = None
        self._text_categories: tuple[Category, ...] = ()
        self._selected_text_record: TextRecord | None = None
        self._text_undo_stack: list[TextRecord] = []
        self._is_disposed = False

        self._configure_toolbar()
        self.setCentralWidget(self._build_workspace())
        self._chart_view.export_requested.connect(self._on_chart_export_requested)
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

        open_project_button = QPushButton("打开项目")
        open_project_button.setObjectName("projectOpenButton")
        open_project_button.clicked.connect(self._open_project_from_dialog)
        toolbar.addWidget(open_project_button)

        save_project_button = QPushButton("保存项目")
        save_project_button.setObjectName("projectSaveButton")
        save_project_button.clicked.connect(self._save_project)
        toolbar.addWidget(save_project_button)

        save_as_project_button = QPushButton("另存项目")
        save_as_project_button.setObjectName("projectSaveAsButton")
        save_as_project_button.clicked.connect(self._save_project_as)
        toolbar.addWidget(save_as_project_button)

        self._source_relocation_button.setObjectName("projectRelocateSourcesButton")
        self._source_relocation_button.setEnabled(False)
        self._source_relocation_button.setToolTip("打开项目后如源文件缺失或不匹配，可在这里重新定位。")
        self._source_relocation_button.clicked.connect(self._open_source_relocation_dialog)
        toolbar.addWidget(self._source_relocation_button)

        self._export_tabular_button.setObjectName("exportTabularDataButton")
        self._export_tabular_button.setEnabled(False)
        self._export_tabular_button.setToolTip("导出当前表格或转换预览结果。")
        self._export_tabular_button.clicked.connect(self._export_current_tabular_data)
        toolbar.addWidget(self._export_tabular_button)

        self._export_text_button.setObjectName("exportTextDataButton")
        self._export_text_button.setEnabled(False)
        self._export_text_button.setToolTip("导出当前文本语料及人工分类/标签。")
        self._export_text_button.clicked.connect(self._export_current_text_data)
        toolbar.addWidget(self._export_text_button)

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
        tabs.addTab(self._build_transform_panel(), "转换")
        for title_text, body in (
            ("字段", "字段映射和语义类型将在画像阶段接入。"),
            ("样式", "图表样式将在图表工作区接入。"),
        ):
            tabs.addTab(self._placeholder_page(title_text, body), title_text)

        layout.addWidget(title)
        layout.addWidget(tabs, stretch=1)
        return panel

    def _build_transform_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._transform_status.setObjectName("transformStatusLabel")
        self._transform_status.setWordWrap(True)

        self._transform_operation_combo.setObjectName("transformOperationCombo")
        for label, operation in (
            ("筛选行", "filter_rows"),
            ("选择/重命名字段", "select_columns"),
            ("排序", "sort_rows"),
            ("去重", "deduplicate_rows"),
            ("删除缺失值", "drop_missing"),
            ("填充缺失值", "fill_missing"),
            ("类型转换", "convert_type"),
            ("分组聚合", "group_aggregate"),
        ):
            self._transform_operation_combo.addItem(label, operation)
        self._transform_operation_combo.currentIndexChanged.connect(
            self._sync_transform_controls
        )

        self._transform_column_combo.setObjectName("transformColumnCombo")
        self._transform_extra_column_combo.setObjectName("transformExtraColumnCombo")

        self._transform_filter_join_combo.setObjectName("transformFilterJoinCombo")
        for label, value in (("并且", "and"), ("或者", "or")):
            self._transform_filter_join_combo.addItem(label, value)

        self._transform_filter_operator_combo.setObjectName("transformFilterOperatorCombo")
        for label, value in (
            ("等于", "=="),
            ("不等于", "!="),
            ("大于", ">"),
            ("大于等于", ">="),
            ("小于", "<"),
            ("小于等于", "<="),
            ("包含文本", "contains"),
            ("以文本开头", "starts_with"),
            ("以文本结尾", "ends_with"),
            ("属于列表", "in"),
            ("为空", "is_null"),
            ("不为空", "is_not_null"),
        ):
            self._transform_filter_operator_combo.addItem(label, value)
        self._transform_filter_operator_combo.currentIndexChanged.connect(
            self._sync_transform_controls
        )

        self._transform_value_edit.setObjectName("transformValueEdit")
        self._transform_value_edit.setPlaceholderText("筛选值、填充值或新字段名")
        self._transform_alias_edit.setObjectName("transformAliasEdit")
        self._transform_alias_edit.setPlaceholderText("输出字段名")

        self._transform_direction_combo.setObjectName("transformDirectionCombo")
        self._transform_direction_combo.addItem("升序", "asc")
        self._transform_direction_combo.addItem("降序", "desc")

        self._transform_type_combo.setObjectName("transformTypeCombo")
        for label, value in (
            ("文本", "VARCHAR"),
            ("数值", "DOUBLE"),
            ("整数", "BIGINT"),
            ("布尔", "BOOLEAN"),
            ("日期时间", "TIMESTAMP"),
            ("日期", "DATE"),
        ):
            self._transform_type_combo.addItem(label, value)

        self._transform_aggregation_combo.setObjectName("transformAggregationCombo")
        for label, value in (
            ("计数", "count"),
            ("去重计数", "count_distinct"),
            ("求和", "sum"),
            ("平均值", "mean"),
            ("中位数", "median"),
            ("最小值", "min"),
            ("最大值", "max"),
            ("标准差", "stddev"),
        ):
            self._transform_aggregation_combo.addItem(label, value)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("操作", self._transform_operation_combo)
        form.addRow("字段", self._transform_column_combo)
        form.addRow("组合", self._transform_filter_join_combo)
        form.addRow("条件", self._transform_filter_operator_combo)
        form.addRow("值", self._transform_value_edit)
        form.addRow("目标字段", self._transform_extra_column_combo)
        form.addRow("排序", self._transform_direction_combo)
        form.addRow("类型", self._transform_type_combo)
        form.addRow("聚合", self._transform_aggregation_combo)
        form.addRow("输出名", self._transform_alias_edit)

        self._transform_field_list.setObjectName("transformFieldList")
        self._transform_field_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._transform_field_list.itemChanged.connect(
            lambda _item: self._update_transform_status()
        )

        self._transform_step_list.setObjectName("transformStepList")
        self._transform_step_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )

        self._transform_add_button.setObjectName("transformAddStepButton")
        self._transform_remove_button.setObjectName("transformRemoveStepButton")
        self._transform_clear_button.setObjectName("transformClearStepsButton")
        self._transform_preview_button.setObjectName("transformPreviewButton")
        self._transform_cancel_button.setObjectName("transformCancelPreviewButton")
        self._transform_preview_button.setProperty("primary", True)
        self._transform_add_button.clicked.connect(self._add_transform_step_from_ui)
        self._transform_remove_button.clicked.connect(self._remove_selected_transform_step)
        self._transform_clear_button.clicked.connect(self._clear_transform_steps)
        self._transform_preview_button.clicked.connect(self._preview_transform_steps)
        self._transform_cancel_button.clicked.connect(self._cancel_transform_preview)

        button_row = QHBoxLayout()
        button_row.addWidget(self._transform_add_button)
        button_row.addWidget(self._transform_remove_button)
        button_row.addWidget(self._transform_clear_button)
        button_row.addStretch(1)

        preview_row = QHBoxLayout()
        preview_row.addStretch(1)
        preview_row.addWidget(self._transform_cancel_button)
        preview_row.addWidget(self._transform_preview_button)

        layout.addWidget(self._transform_status)
        layout.addLayout(form)
        layout.addWidget(QLabel("选择字段"))
        layout.addWidget(self._transform_field_list, stretch=1)
        layout.addWidget(QLabel("转换步骤"))
        layout.addWidget(self._transform_step_list, stretch=1)
        layout.addLayout(button_row)
        layout.addLayout(preview_row)
        self._sync_transform_controls()
        self._set_transform_panel_enabled(False)
        return page

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

        category_panel = QFrame()
        category_panel.setObjectName("categoryGovernancePanel")
        category_layout = QVBoxLayout(category_panel)
        category_layout.setContentsMargins(12, 10, 12, 10)
        category_layout.setSpacing(8)
        category_title = QLabel("分类管理")
        category_title.setObjectName("subsectionTitle")

        category_form = QFormLayout()
        category_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self._category_manage_combo.setObjectName("categoryManageCombo")
        self._category_manage_combo.currentIndexChanged.connect(
            self._on_category_manage_selection_changed
        )
        self._category_name_edit.setObjectName("categoryNameEdit")
        self._category_name_edit.setPlaceholderText("新的分类名称")
        self._category_description_edit.setObjectName("categoryDescriptionEdit")
        self._category_description_edit.setPlaceholderText("分类说明")
        self._category_note_edit.setObjectName("categoryAuditNoteEdit")
        self._category_note_edit.setPlaceholderText("本次操作备注（可选）")
        self._category_target_combo.setObjectName("categoryTargetCombo")
        self._category_target_combo.currentIndexChanged.connect(
            lambda _index: self._sync_category_governance_controls()
        )
        category_form.addRow("当前分类", self._category_manage_combo)
        category_form.addRow("名称", self._category_name_edit)
        category_form.addRow("说明", self._category_description_edit)
        category_form.addRow("目标/替换", self._category_target_combo)
        category_form.addRow("备注", self._category_note_edit)

        category_buttons = QHBoxLayout()
        self._category_rename_button.setObjectName("categoryRenameButton")
        self._category_merge_button.setObjectName("categoryMergeButton")
        self._category_delete_button.setObjectName("categoryDeleteButton")
        self._category_rename_button.clicked.connect(self._rename_text_category)
        self._category_merge_button.clicked.connect(self._merge_text_category)
        self._category_delete_button.clicked.connect(self._delete_text_category)
        category_buttons.addWidget(self._category_rename_button)
        category_buttons.addWidget(self._category_merge_button)
        category_buttons.addWidget(self._category_delete_button)
        category_buttons.addStretch(1)

        category_layout.addWidget(category_title)
        category_layout.addLayout(category_form)
        category_layout.addLayout(category_buttons)

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
        layout.addWidget(category_panel)
        layout.addWidget(self._text_label_table, stretch=3)
        layout.addWidget(editor, stretch=2)
        self._set_text_editor_enabled(False)
        self._refresh_text_label_categories()
        return page

    def _set_transform_panel_enabled(self, enabled: bool, message: str | None = None) -> None:
        for widget in (
            self._transform_operation_combo,
            self._transform_column_combo,
            self._transform_extra_column_combo,
            self._transform_filter_operator_combo,
            self._transform_filter_join_combo,
            self._transform_value_edit,
            self._transform_alias_edit,
            self._transform_direction_combo,
            self._transform_type_combo,
            self._transform_aggregation_combo,
            self._transform_field_list,
            self._transform_step_list,
            self._transform_add_button,
            self._transform_remove_button,
            self._transform_clear_button,
            self._transform_preview_button,
        ):
            widget.setEnabled(enabled)
        self._transform_cancel_button.setEnabled(
            enabled and self._running_transform_job is not None
        )
        if message is not None:
            self._transform_status.setText(message)
        elif enabled:
            self._sync_transform_controls()
            self._update_transform_status()
        else:
            self._transform_status.setText("请先导入表格数据。")

    def _refresh_transform_columns(self, columns: tuple[WorkspaceColumn, ...]) -> None:
        self._current_tabular_columns = columns
        for combo in (self._transform_column_combo, self._transform_extra_column_combo):
            blocker = QSignalBlocker(combo)
            combo.clear()
            for column in columns:
                combo.addItem(column.name, column.name)
            del blocker

        blocker = QSignalBlocker(self._transform_field_list)
        self._transform_field_list.clear()
        for column in columns:
            item = QListWidgetItem(column.name)
            item.setData(Qt.ItemDataRole.UserRole, column.name)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
            )
            item.setCheckState(Qt.CheckState.Checked)
            self._transform_field_list.addItem(item)
        del blocker
        self._sync_transform_controls()
        self._update_transform_status()

    def _sync_transform_controls(self) -> None:
        operation = self._current_transform_operation()
        has_table = self._current_tabular_table_name is not None
        uses_filter = operation == "filter_rows"
        self._transform_filter_join_combo.setEnabled(has_table and uses_filter)
        self._transform_filter_operator_combo.setEnabled(has_table and uses_filter)
        value_needed = operation == "fill_missing" or (
            operation == "filter_rows"
            and self._current_filter_operator() not in {"is_null", "is_not_null"}
        )
        self._transform_value_edit.setEnabled(has_table and value_needed)
        self._transform_alias_edit.setEnabled(
            has_table and operation in {"select_columns", "group_aggregate"}
        )
        self._transform_extra_column_combo.setEnabled(
            has_table and operation == "group_aggregate"
        )
        self._transform_direction_combo.setEnabled(has_table and operation == "sort_rows")
        self._transform_type_combo.setEnabled(has_table and operation == "convert_type")
        self._transform_aggregation_combo.setEnabled(
            has_table and operation == "group_aggregate"
        )
        self._transform_field_list.setEnabled(has_table and operation == "select_columns")

    def _update_transform_status(self) -> None:
        if self._current_tabular_table_name is None:
            self._transform_status.setText("请先导入表格数据。")
            return
        step_count = len(self._transform_step_objects)
        field_count = len(self._current_tabular_columns)
        self._transform_status.setText(
            f"当前表有 {field_count} 个字段；已配置 {step_count} 个转换步骤。"
        )

    def _current_transform_operation(self) -> str:
        value = self._transform_operation_combo.currentData()
        return value if isinstance(value, str) else "filter_rows"

    def _current_filter_operator(self) -> str:
        value = self._transform_filter_operator_combo.currentData()
        return value if isinstance(value, str) else "=="

    def _current_transform_column(self) -> str:
        value = self._transform_column_combo.currentData()
        if isinstance(value, str) and value:
            return value
        raise UserFacingError(
            code="TRANSFORM_UI_NO_COLUMN",
            title_zh="请选择字段",
            message_zh="添加转换步骤前需要先选择一个字段。",
            next_action_zh="请先导入表格数据，然后在字段下拉框中选择要处理的字段。",
        )

    def _current_transform_extra_column(self) -> str:
        value = self._transform_extra_column_combo.currentData()
        if isinstance(value, str) and value:
            return value
        raise UserFacingError(
            code="TRANSFORM_UI_NO_METRIC_COLUMN",
            title_zh="请选择目标字段",
            message_zh="分组聚合需要选择一个用于计算的目标字段。",
            next_action_zh="请选择数值或类别字段后再添加聚合步骤。",
        )

    def _add_transform_step_from_ui(self) -> None:
        try:
            step = self._build_transform_step_from_ui()
        except UserFacingError as exc:
            self.show_user_error(exc)
            return
        except Exception as exc:
            self.show_user_error(
                UserFacingError(
                    code="TRANSFORM_UI_STEP_INVALID",
                    title_zh="转换步骤无效",
                    message_zh="无法根据当前控件内容生成安全的转换步骤。",
                    next_action_zh="请检查字段、条件、值和输出名后重试。",
                    technical_detail=repr(exc),
                )
            )
            return

        if step.operation == "filter_rows" and self._transform_step_objects:
            join = self._transform_filter_join_combo.currentData()
            last_step = self._transform_step_objects[-1]
            if isinstance(join, str) and last_step.operation == "filter_rows":
                expression = {
                    "op": join,
                    "conditions": [
                        last_step.parameters.get("expression"),
                        step.parameters.get("expression"),
                    ],
                }
                step = TransformStep(
                    id=last_step.id,
                    operation="filter_rows",
                    parameters={"expression": expression},
                    reversible=False,
                )
                self._transform_step_objects[-1] = step
                item = self._transform_step_list.item(self._transform_step_list.count() - 1)
                if item is not None:
                    item.setText(_transform_step_text(step))
                self._update_transform_status()
                return

        self._transform_step_objects.append(step)
        self._transform_step_list.addItem(_transform_step_text(step))
        self._update_transform_status()

    def _build_transform_step_from_ui(self) -> TransformStep:
        if self._current_tabular_table_name is None:
            raise UserFacingError(
                code="TRANSFORM_UI_NO_TABLE",
                title_zh="没有可转换的表格",
                message_zh="转换面板只能处理已经导入并写入本地工作区的表格数据。",
                next_action_zh="请先导入 CSV、Excel 或 Parquet 表格。",
            )
        operation = self._current_transform_operation()
        step_id = f"ui_transform_{len(self._transform_step_objects) + 1}"
        column = self._current_transform_column()
        if operation == "filter_rows":
            operator = self._current_filter_operator()
            expression: dict[str, object] = {"column": column, "op": operator}
            if operator not in {"is_null", "is_not_null"}:
                expression["value"] = self._filter_value(column, operator)
            return TransformStep(
                id=step_id,
                operation="filter_rows",
                parameters={"expression": expression},
                reversible=False,
            )
        if operation == "select_columns":
            entries = self._selected_transform_fields()
            if not entries:
                raise UserFacingError(
                    code="TRANSFORM_UI_NO_SELECTED_COLUMNS",
                    title_zh="没有选择字段",
                    message_zh="选择/重命名步骤至少需要保留一个字段。",
                    next_action_zh="请勾选要保留的字段，可以直接编辑字段名作为输出名。",
                )
            alias_text = self._transform_alias_edit.text().strip()
            if alias_text and len(entries) == 1:
                entries = ({"source": entries[0]["source"], "alias": alias_text},)
            return TransformStep(
                id=step_id,
                operation="select_columns",
                parameters={"columns": list(entries)},
                reversible=False,
            )
        if operation == "sort_rows":
            direction = self._transform_direction_combo.currentData()
            return TransformStep(
                id=step_id,
                operation="sort_rows",
                parameters={
                    "columns": [
                        {
                            "column": column,
                            "direction": direction if isinstance(direction, str) else "asc",
                        }
                    ]
                },
                reversible=True,
            )
        if operation == "deduplicate_rows":
            return TransformStep(
                id=step_id,
                operation="deduplicate_rows",
                parameters={"columns": [column]},
                reversible=False,
            )
        if operation == "drop_missing":
            return TransformStep(
                id=step_id,
                operation="drop_missing",
                parameters={"columns": [column]},
                reversible=False,
            )
        if operation == "fill_missing":
            return TransformStep(
                id=step_id,
                operation="fill_missing",
                parameters={"values": {column: self._coerced_text_value(column)}},
                reversible=False,
            )
        if operation == "convert_type":
            target_type = self._transform_type_combo.currentData()
            return TransformStep(
                id=step_id,
                operation="convert_type",
                parameters={
                    "columns": {column: target_type if isinstance(target_type, str) else "VARCHAR"},
                    "on_error": "null",
                },
                reversible=False,
            )
        if operation == "group_aggregate":
            function = self._transform_aggregation_combo.currentData()
            if not isinstance(function, str):
                function = "count"
            aggregation: dict[str, object] = {
                "function": function,
                "alias": self._aggregation_alias(function),
            }
            if function != "count":
                aggregation["column"] = self._current_transform_extra_column()
            return TransformStep(
                id=step_id,
                operation="group_aggregate",
                parameters={"group_by": [column], "aggregations": [aggregation]},
                reversible=False,
            )
        raise UserFacingError(
            code="TRANSFORM_UI_OPERATION_UNSUPPORTED",
            title_zh="转换操作不受支持",
            message_zh=f"当前界面不支持操作：{operation}",
            next_action_zh="请选择转换面板中的已有操作。",
        )

    def _selected_transform_fields(self) -> tuple[dict[str, str], ...]:
        entries: list[dict[str, str]] = []
        for index in range(self._transform_field_list.count()):
            item = self._transform_field_list.item(index)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            source = item.data(Qt.ItemDataRole.UserRole)
            alias = item.text().strip()
            if isinstance(source, str) and alias:
                entries.append({"source": source, "alias": alias})
        return tuple(entries)

    def _filter_value(self, column: str, operator: str) -> object:
        raw_value = self._transform_value_edit.text().strip()
        if operator == "in":
            values = tuple(part.strip() for part in raw_value.split(",") if part.strip())
            if not values:
                raise UserFacingError(
                    code="TRANSFORM_UI_EMPTY_VALUE_LIST",
                    title_zh="列表值为空",
                    message_zh="属于列表条件需要至少一个值。",
                    next_action_zh="请输入一个或多个值，用英文逗号分隔。",
                )
            return tuple(
                _coerce_transform_value(column, value, self._current_tabular_columns)
                for value in values
            )
        if not raw_value:
            raise UserFacingError(
                code="TRANSFORM_UI_EMPTY_FILTER_VALUE",
                title_zh="筛选值为空",
                message_zh="当前筛选条件需要填写比较值。",
                next_action_zh="请输入筛选值，或改用为空/不为空条件。",
            )
        return _coerce_transform_value(column, raw_value, self._current_tabular_columns)

    def _coerced_text_value(self, column: str) -> object:
        value = self._transform_value_edit.text()
        return _coerce_transform_value(column, value, self._current_tabular_columns)

    def _aggregation_alias(self, function: str) -> str:
        alias = self._transform_alias_edit.text().strip()
        if alias:
            return alias
        metric = self._transform_extra_column_combo.currentText() or "rows"
        return f"{function}_{metric}".replace(" ", "_")

    def _remove_selected_transform_step(self) -> None:
        row = self._transform_step_list.currentRow()
        if row < 0 or row >= len(self._transform_step_objects):
            self._transform_status.setText("请先选择要移除的转换步骤。")
            return
        del self._transform_step_objects[row]
        self._transform_step_list.takeItem(row)
        self._update_transform_status()

    def _clear_transform_steps(self) -> None:
        self._transform_step_objects.clear()
        self._transform_step_list.clear()
        self._update_transform_status()

    def _preview_transform_steps(self) -> None:
        table_name = self._current_tabular_table_name
        if table_name is None:
            self.show_user_error(
                UserFacingError(
                    code="TRANSFORM_UI_NO_TABLE_FOR_PREVIEW",
                    title_zh="没有可预览的表格",
                    message_zh="转换预览需要一个已经导入的表格。",
                    next_action_zh="请先导入表格数据。",
                )
            )
            return
        steps = tuple(self._transform_step_objects)
        if not steps:
            self._transform_status.setText("请先添加至少一个转换步骤。")
            return
        if not self._confirm_lossy_transform_preview(steps):
            self._transform_status.setText("已取消转换预览，源数据未修改。")
            return
        if self._running_transform_job is not None:
            self._running_transform_job.cancel()
        self._transform_generation += 1
        generation = self._transform_generation
        self._jobs_label.setText("后台任务：正在生成转换预览")
        self._transform_status.setText("正在后台生成转换预览表。")
        self._transform_cancel_button.setEnabled(True)
        job = QtJobRunner(
            "tabular_transform_preview",
            lambda context: self._run_transform_preview(
                context,
                table_name=table_name,
                steps=steps,
            ),
        )
        self._running_transform_job = job
        job.signals.progress.connect(self._on_transform_progress)
        job.signals.completed.connect(
            lambda outcome, expected_generation=generation: self._on_transform_completed(
                expected_generation,
                outcome,
            )
        )
        QThreadPool.globalInstance().start(job)

    def _cancel_transform_preview(self) -> None:
        if self._running_transform_job is None:
            self._transform_status.setText("当前没有正在运行的转换预览。")
            self._transform_cancel_button.setEnabled(False)
            return
        self._running_transform_job.cancel()
        self._transform_status.setText("正在取消转换预览，源数据未修改。")
        self._jobs_label.setText("后台任务：正在取消转换预览")

    def _confirm_lossy_transform_preview(self, steps: tuple[TransformStep, ...]) -> bool:
        warnings = _lossy_transform_warnings(steps)
        if not warnings:
            return True
        message = "以下步骤可能减少行、隐藏字段或改变值；源表不会被覆盖。\n\n"
        message += "\n".join(f"- {warning}" for warning in warnings)
        message += "\n\n是否继续生成本地预览表？"
        return (
            QMessageBox.question(
                self,
                "确认转换预览",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _run_transform_preview(
        self,
        context: JobContext,
        *,
        table_name: str,
        steps: tuple[TransformStep, ...],
    ) -> TransformPreviewResult:
        context.progress(10, "正在检查转换步骤")
        result = self._transform_service.preview_transform(table_name, steps)
        context.progress(90, "正在读取转换预览结果")
        return result

    def _on_transform_progress(self, progress: JobProgress) -> None:
        if self._is_disposed or progress.state is not JobState.RUNNING:
            return
        percent_text = "" if progress.percent is None else f"{progress.percent}% "
        self._jobs_label.setText(f"后台任务：{percent_text}{progress.message_zh}")

    def _on_transform_completed(
        self,
        expected_generation: int,
        outcome: JobOutcome[TransformPreviewResult],
    ) -> None:
        if self._is_disposed or expected_generation != self._transform_generation:
            return
        self._running_transform_job = None
        self._transform_cancel_button.setEnabled(False)
        if outcome.state is JobState.CANCELLED:
            self._jobs_label.setText("后台任务：转换预览已取消")
            self._transform_status.setText("转换预览已取消，源数据未修改。")
            return
        if outcome.state is JobState.SUCCEEDED and outcome.value is not None:
            self._show_transform_preview_result(outcome.value)
            return
        self._jobs_label.setText("后台任务：转换预览失败")
        self._transform_status.setText("转换预览失败，源数据未修改。")
        if isinstance(outcome.error, UserFacingError):
            self.show_user_error(outcome.error)
            return
        self.show_user_error(
            UserFacingError(
                code="TRANSFORM_PREVIEW_UNEXPECTED_FAILURE",
                title_zh="转换预览失败",
                message_zh="生成转换预览时发生未预期错误，源数据没有被修改。",
                next_action_zh="请检查转换步骤，复制技术详情后稍后重试或提交问题。",
                technical_detail=repr(outcome.error),
            )
        )

    def _show_transform_preview_result(self, result: TransformPreviewResult) -> None:
        display_name = f"转换预览 {len(result.steps)} 步"
        handle = DatasetHandle(
            id=result.table_name,
            kind=DatasetKind.TABULAR,
            display_name=display_name,
            source_path=None,
            workspace_path=self._workspace.path,
            row_count=result.row_count,
            column_count=len(result.columns),
            import_options={
                "source_table": result.source_table,
                "transform_step_count": len(result.steps),
                "transform_steps": [_transform_step_payload(step) for step in result.steps],
            },
            fingerprint=None,
            cache_key=result.table_name,
        )
        self._add_project_dataset_entry(
            ProjectDatasetEntry.from_handle(
                handle,
                table_name=result.table_name,
                transform_steps=result.steps,
            )
        )
        self._current_tabular_table_name = result.table_name
        self._current_tabular_columns = result.columns
        self._current_text_corpus_id = None
        self._sync_data_export_buttons()
        self._dataset_list.addItem(display_name)
        self._preview_table.setModel(
            DuckDbTableModel(
                workspace=self._workspace,
                table_name=result.table_name,
                columns=result.columns,
                row_count=result.row_count,
            )
        )
        self._preview_summary.setText(
            f"{display_name}：{result.row_count} 行，{len(result.columns)} 列。"
            "源表未修改，转换结果写入本地预览表。"
        )
        self._row_count_label.setText(f"行/记录：{result.row_count}")
        self._query_time_label.setText("查询：转换预览分页")
        self._approximation_label.setText("近似：无")
        self._jobs_label.setText("后台任务：转换预览已完成")
        self._error_label.setText("无错误")
        self._refresh_transform_columns(result.columns)
        self._transform_step_objects.clear()
        self._transform_step_list.clear()
        self._transform_status.setText(
            f"已生成预览表 {result.table_name}，源表 {result.source_table} 未修改。"
        )
        self._stack.setCurrentIndex(1)
        self.statusBar().showMessage("转换预览完成", 5000)
        self._start_tabular_profile_job(
            dataset_id=result.table_name,
            table_name=result.table_name,
            import_options={
                "transform_step_count": len(result.steps),
                "transform_steps": [_transform_step_payload(step) for step in result.steps],
            },
        )

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

    def _open_project_from_dialog(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "打开项目",
            str(Path.home() / "Documents"),
            "QuickInsight 项目 (*.qiproject)",
        )
        if not selected:
            return
        self._open_project_from_path(Path(selected))

    def _save_project(self) -> None:
        if self._current_project_path is None:
            self._save_project_as()
            return
        self._save_project_to_path(self._current_project_path)

    def _save_project_as(self) -> None:
        default_dir = Path.home() / "Documents"
        if not default_dir.exists():
            default_dir = self._paths.config_dir
        default_name = (
            self._current_project_manifest.display_name
            if self._current_project_manifest is not None
            else "quick-insight-project"
        )
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "保存项目",
            str(default_dir / f"{default_name}{PROJECT_EXTENSION}"),
            "QuickInsight 项目 (*.qiproject)",
        )
        if not selected:
            return
        self._save_project_to_path(Path(selected))

    def _save_project_to_path(self, path: Path) -> None:
        try:
            manifest = self._build_project_manifest(path)
        except UserFacingError as exc:
            self.show_user_error(exc)
            return
        if self._running_project_job is not None:
            self._running_project_job.cancel()
        self._project_generation += 1
        generation = self._project_generation
        self._jobs_label.setText("后台任务：正在保存项目")
        job: QtJobRunner[ProjectSaveResult | ProjectOpenResult] = QtJobRunner(
            "project_save",
            lambda context: self._save_project_job(context, path=path, manifest=manifest),
        )
        self._running_project_job = job
        job.signals.progress.connect(self._on_project_progress)
        job.signals.completed.connect(
            lambda outcome, expected_generation=generation: self._on_project_completed(
                expected_generation,
                outcome,
            )
        )
        QThreadPool.globalInstance().start(job)

    def _open_project_from_path(self, path: Path) -> None:
        if self._running_project_job is not None:
            self._running_project_job.cancel()
        self._cancel_background_work()
        self._project_generation += 1
        generation = self._project_generation
        self._jobs_label.setText("后台任务：正在打开项目")
        workspace_path = self._paths.cache_dir / "workspace.duckdb"
        job: QtJobRunner[ProjectSaveResult | ProjectOpenResult] = QtJobRunner(
            "project_open",
            lambda context: self._open_project_job(
                context,
                project_path=path,
                workspace_path=workspace_path,
            ),
        )
        self._running_project_job = job
        job.signals.progress.connect(self._on_project_progress)
        job.signals.completed.connect(
            lambda outcome, expected_generation=generation: self._on_project_completed(
                expected_generation,
                outcome,
            )
        )
        QThreadPool.globalInstance().start(job)

    def _build_project_manifest(self, path: Path) -> ProjectManifest:
        if not self._project_dataset_entries:
            raise UserFacingError(
                code="PROJECT_SAVE_NO_DATASETS",
                title_zh="没有可保存的数据",
                message_zh="当前项目还没有导入表格或文本语料。",
                next_action_zh="请先导入数据，再保存项目。",
            )
        display_name = (
            self._current_project_manifest.display_name
            if self._current_project_manifest is not None
            else (path.stem or "未命名项目")
        )
        datasets = self._project_entries_for_current_workspace()
        if self._current_project_manifest is None:
            return ProjectManifest.create(
                display_name,
                datasets,
            )
        return replace(
            self._current_project_manifest,
            display_name=display_name,
            datasets=datasets,
        )

    def _save_project_job(
        self,
        context: JobContext,
        *,
        path: Path,
        manifest: ProjectManifest,
    ) -> ProjectSaveResult:
        context.progress(10, "正在整理项目清单")
        result = self._project_service.save_project(path, manifest)
        context.progress(90, "正在完成项目保存")
        return result

    def _open_project_job(
        self,
        context: JobContext,
        *,
        project_path: Path,
        workspace_path: Path,
    ) -> ProjectOpenResult:
        context.progress(10, "正在读取项目包")
        result = self._project_service.open_project(project_path, workspace_path)
        context.progress(90, "正在校验源文件引用")
        return result

    def _on_project_progress(self, progress: JobProgress) -> None:
        if self._is_disposed or progress.state is not JobState.RUNNING:
            return
        percent_text = "" if progress.percent is None else f"{progress.percent}% "
        self._jobs_label.setText(f"后台任务：{percent_text}{progress.message_zh}")

    def _on_project_completed(
        self,
        expected_generation: int,
        outcome: JobOutcome[ProjectSaveResult | ProjectOpenResult],
    ) -> None:
        if self._is_disposed or expected_generation != self._project_generation:
            return
        self._running_project_job = None
        if outcome.state is JobState.CANCELLED:
            self._jobs_label.setText("后台任务：项目操作已取消")
            return
        if outcome.state is not JobState.SUCCEEDED or outcome.value is None:
            self._jobs_label.setText("后台任务：项目操作失败")
            if isinstance(outcome.error, UserFacingError):
                self.show_user_error(outcome.error)
            else:
                self.show_user_error(
                    UserFacingError(
                        code="PROJECT_OPERATION_UNEXPECTED_FAILURE",
                        title_zh="项目操作失败",
                        message_zh="保存或打开项目时发生未预期错误。",
                        next_action_zh="请复制技术详情后稍后重试或提交问题。",
                        technical_detail=repr(outcome.error),
                    )
                )
            return
        if isinstance(outcome.value, ProjectSaveResult):
            self._on_project_saved(outcome.value)
            return
        self._on_project_opened(outcome.value)

    def _on_project_saved(self, result: ProjectSaveResult) -> None:
        self._current_project_path = result.path
        self._current_project_manifest = result.manifest
        self._project_dataset_entries = list(result.manifest.datasets)
        self._set_source_reference_statuses(validate_source_references(result.manifest))
        self._jobs_label.setText("后台任务：项目已保存")
        if _has_relocatable_source_issues(self._source_reference_statuses):
            self._error_label.setText(
                f"项目已保存，但仍有源文件需要处理：{result.path}"
            )
        else:
            self._error_label.setText(f"项目已保存：{result.path}")
        self.statusBar().showMessage("项目保存完成", 5000)

    def _on_project_opened(self, result: ProjectOpenResult) -> None:
        self._set_workspace(result.workspace)
        self._current_project_path = result.path
        self._current_project_manifest = result.manifest
        self._project_dataset_entries = list(result.manifest.datasets)
        self._restore_project_dataset_list()
        self._restore_first_project_dataset()
        self._set_source_reference_statuses(result.source_statuses)
        self._jobs_label.setText("后台任务：项目已打开")
        self._error_label.setText(_project_source_status_text(result.source_statuses))
        self.statusBar().showMessage("项目打开完成", 5000)

    def _set_source_reference_statuses(
        self,
        statuses: tuple[SourceReferenceStatus, ...],
    ) -> None:
        self._source_reference_statuses = statuses
        has_issues = _has_relocatable_source_issues(statuses)
        self._source_relocation_button.setEnabled(
            has_issues and self._current_project_manifest is not None
        )
        if has_issues:
            self._source_relocation_button.setToolTip(
                "有源文件缺失或不匹配。点击后选择移动后的原始文件并校验。"
            )
        else:
            self._source_relocation_button.setToolTip("当前项目没有需要重定位的源文件。")

    def _sync_data_export_buttons(self) -> None:
        self._export_tabular_button.setEnabled(self._current_tabular_table_name is not None)
        self._export_text_button.setEnabled(self._current_text_corpus_id is not None)

    def _open_source_relocation_dialog(self) -> None:
        if self._current_project_manifest is None:
            self.show_user_error(
                UserFacingError(
                    code="PROJECT_RELOCATION_NO_PROJECT",
                    title_zh="没有可重定位的项目",
                    message_zh="请先打开或保存一个项目。",
                    next_action_zh="打开 .qiproject 项目后再处理源文件位置。",
                )
            )
            return
        statuses = validate_source_references(self._current_project_manifest)
        self._set_source_reference_statuses(statuses)
        if not _has_relocatable_source_issues(statuses):
            self._error_label.setText("当前项目没有缺失或不匹配的源文件。")
            return
        dialog = SourceRelocationDialog(
            manifest=self._current_project_manifest,
            statuses=statuses,
            parent=self,
        )
        if dialog.exec() != SourceRelocationDialog.DialogCode.Accepted:
            return
        if dialog.result_manifest is None:
            return
        self._apply_source_relocation_result(
            dialog.result_manifest,
            dialog.result_statuses,
        )

    def _apply_source_relocation_result(
        self,
        manifest: ProjectManifest,
        statuses: tuple[SourceReferenceStatus, ...],
    ) -> None:
        self._current_project_manifest = manifest
        self._project_dataset_entries = list(manifest.datasets)
        self._restore_project_dataset_list()
        self._set_source_reference_statuses(statuses)
        if _has_relocatable_source_issues(statuses):
            self._error_label.setText(
                "已应用部分源文件重定位，但仍有源文件需要处理。请继续重定位或重新导入。"
            )
        else:
            self._error_label.setText(
                "源文件重定位完成并通过校验。请保存项目以写入 .qiproject 文件。"
            )
        self.statusBar().showMessage("源文件重定位已应用到当前项目", 5000)

    def _set_workspace(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace
        self._import_service = TabularImportService(self._workspace)
        self._text_corpus_service = TextCorpusService(self._workspace)
        self._text_labeling_service = TextLabelingService(self._workspace)
        self._transform_service = TabularTransformService(self._workspace)
        self._project_service = ProjectPersistenceService(self._workspace)

    def _cancel_background_work(self) -> None:
        self._profile_generation += 1
        self._chart_generation += 1
        self._transform_generation += 1
        self._data_export_generation += 1
        if self._running_profile_job is not None:
            self._running_profile_job.cancel()
            self._running_profile_job = None
        if self._running_chart_job is not None:
            self._running_chart_job.cancel()
            self._running_chart_job = None
        if self._running_transform_job is not None:
            self._running_transform_job.cancel()
            self._running_transform_job = None
        if self._running_data_export_job is not None:
            self._running_data_export_job.cancel()
            self._running_data_export_job = None
        if self._text_label_model is not None:
            self._text_label_model.cancel_pending_queries()
            self._text_label_model = None

    def _restore_project_dataset_list(self) -> None:
        self._dataset_list.clear()
        for entry in self._project_dataset_entries:
            self._dataset_list.addItem(entry.handle.display_name)

    def _restore_first_project_dataset(self) -> None:
        self._clear_workspace_views()
        for entry in self._project_dataset_entries:
            if entry.handle.kind is DatasetKind.TABULAR and entry.table_name:
                self._display_tabular_project_entry(entry)
                return
            if entry.handle.kind is DatasetKind.TEXT_CORPUS:
                self._display_text_project_entry(entry)
                return
        self._stack.setCurrentIndex(0)
        self._row_count_label.setText("行/记录：未加载")
        self._query_time_label.setText("查询：--")
        self._approximation_label.setText("近似：无")

    def _clear_workspace_views(self) -> None:
        self._current_tabular_table_name = None
        self._current_tabular_columns = ()
        self._current_profile = None
        self._current_recommendations = ()
        self._current_text_corpus_id = None
        self._sync_data_export_buttons()
        self._preview_table.setModel(None)
        self._preview_summary.setText("尚未导入数据。")
        self._profile_summary.setText("尚未生成数据画像。")
        self._profile_fields.clear()
        self._profile_findings.clear()
        self._render_recommendation_cards(())
        self._refresh_transform_columns(())
        self._clear_transform_steps()
        self._set_transform_panel_enabled(False)
        self._text_label_table.setModel(None)
        self._text_label_status.setText("尚未加载文本语料。")
        self._set_text_editor_enabled(False)

    def _display_tabular_project_entry(self, entry: ProjectDatasetEntry) -> None:
        table_name = entry.table_name
        if table_name is None:
            return
        try:
            columns = self._workspace.columns(table_name)
            row_count = self._workspace.row_count(table_name)
        except Exception as exc:
            self.show_user_error(
                UserFacingError(
                    code="PROJECT_RESTORE_TABLE_FAILED",
                    title_zh="无法恢复表格预览",
                    message_zh=f"项目中的表格 {entry.handle.display_name} 无法读取。",
                    next_action_zh="请重新打开项目，或从源文件重新导入。",
                    technical_detail=repr(exc),
                )
            )
            return
        self._current_tabular_table_name = table_name
        self._current_tabular_columns = columns
        self._current_text_corpus_id = None
        self._sync_data_export_buttons()
        self._refresh_transform_columns(columns)
        self._clear_transform_steps()
        self._set_transform_panel_enabled(True)
        self._preview_table.setModel(
            DuckDbTableModel(
                workspace=self._workspace,
                table_name=table_name,
                columns=columns,
                row_count=row_count,
            )
        )
        self._preview_summary.setText(
            f"{entry.handle.display_name}：{row_count} 行，{len(columns)} 列。"
            "项目已从 .qiproject 恢复，预览后台按页读取。"
        )
        self._row_count_label.setText(f"行/记录：{row_count}")
        self._query_time_label.setText("查询：项目恢复分页")
        self._approximation_label.setText("近似：无")
        self._stack.setCurrentIndex(1)
        self._start_tabular_profile_job(
            dataset_id=entry.handle.id,
            table_name=table_name,
            import_options=dict(entry.handle.import_options),
        )

    def _display_text_project_entry(self, entry: ProjectDatasetEntry) -> None:
        corpus_id = entry.handle.cache_key or entry.handle.id
        records = self._workspace.list_text_records(corpus_id)
        categories = self._workspace.list_categories()
        result = TextCorpusImportResult(
            handle=entry.handle,
            records=records,
            categories=categories,
        )
        self._current_tabular_table_name = None
        self._current_tabular_columns = ()
        self._sync_data_export_buttons()
        self._refresh_transform_columns(())
        self._clear_transform_steps()
        self._set_transform_panel_enabled(False, "文本语料暂不使用表格转换面板。")
        self._row_count_label.setText(f"行/记录：{len(records)}")
        self._query_time_label.setText("查询：项目文本语料已恢复")
        self._approximation_label.setText("近似：无")
        self._load_text_label_workspace(result)
        self._stack.setCurrentIndex(5)
        self._start_text_profile_job(result)

    def _add_project_dataset_entry(self, entry: ProjectDatasetEntry) -> None:
        key = _project_dataset_key(entry)
        self._project_dataset_entries = [
            existing
            for existing in self._project_dataset_entries
            if _project_dataset_key(existing) != key
        ]
        self._project_dataset_entries.append(entry)
        if self._current_project_manifest is not None:
            self._current_project_manifest = replace(
                self._current_project_manifest,
                datasets=tuple(self._project_dataset_entries),
            )

    def _project_entries_for_current_workspace(self) -> tuple[ProjectDatasetEntry, ...]:
        return tuple(
            replace(
                entry,
                handle=replace(entry.handle, workspace_path=self._workspace.path),
            )
            for entry in self._project_dataset_entries
        )

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
        self._add_project_dataset_entry(
            ProjectDatasetEntry.from_handle(handle, table_name=result.table_name)
        )
        self._current_tabular_table_name = result.table_name
        self._current_tabular_columns = result.columns
        self._current_text_corpus_id = None
        self._sync_data_export_buttons()
        self._refresh_transform_columns(result.columns)
        self._clear_transform_steps()
        self._set_transform_panel_enabled(True)
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
        self._add_project_dataset_entry(ProjectDatasetEntry.from_handle(handle))
        self._current_tabular_table_name = None
        self._current_tabular_columns = ()
        self._sync_data_export_buttons()
        self._refresh_transform_columns(())
        self._clear_transform_steps()
        self._set_transform_panel_enabled(False, "文本语料暂不使用表格转换面板。")
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
        self._sync_data_export_buttons()
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
        self._refresh_category_governance_controls(usage_counts)

    def _refresh_category_governance_controls(self, usage_counts: dict[str, int]) -> None:
        selected_category_id = self._category_manage_combo.currentData()
        selected_target_id = self._category_target_combo.currentData()

        manage_blocker = QSignalBlocker(self._category_manage_combo)
        self._category_manage_combo.clear()
        for category in self._text_categories:
            count = usage_counts.get(category.id, 0)
            self._category_manage_combo.addItem(f"{category.name} ({count})", category.id)
        manage_index = self._category_manage_combo.findData(selected_category_id)
        self._category_manage_combo.setCurrentIndex(manage_index if manage_index >= 0 else 0)
        del manage_blocker

        target_blocker = QSignalBlocker(self._category_target_combo)
        self._category_target_combo.clear()
        self._category_target_combo.addItem("删除后设为未分类", "")
        for category in self._text_categories:
            count = usage_counts.get(category.id, 0)
            self._category_target_combo.addItem(f"{category.name} ({count})", category.id)
        target_index = self._category_target_combo.findData(selected_target_id)
        self._category_target_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        del target_blocker

        self._on_category_manage_selection_changed(self._category_manage_combo.currentIndex())

    def _on_category_manage_selection_changed(self, _index: int) -> None:
        category = self._selected_category_for_management()
        if category is None:
            self._category_name_edit.clear()
            self._category_description_edit.clear()
        else:
            self._category_name_edit.setText(category.name)
            self._category_description_edit.setText(category.description)
        self._sync_category_governance_controls()

    def _sync_category_governance_controls(self) -> None:
        has_corpus = self._current_text_corpus_id is not None
        category = self._selected_category_for_management()
        has_category = has_corpus and category is not None
        target_id = self._selected_category_target_id()
        can_merge = False
        can_delete = False
        if has_category and category is not None:
            can_merge = bool(target_id) and target_id != category.id
            can_delete = target_id != category.id
        for widget in (
            self._category_manage_combo,
            self._category_name_edit,
            self._category_description_edit,
            self._category_note_edit,
            self._category_target_combo,
        ):
            widget.setEnabled(has_category)
        self._category_rename_button.setEnabled(has_category)
        self._category_merge_button.setEnabled(can_merge)
        self._category_delete_button.setEnabled(can_delete)

    def _rename_text_category(self) -> None:
        corpus_id = self._current_text_corpus_id
        category = self._selected_category_for_management()
        if corpus_id is None or category is None:
            self._text_label_status.setText("请先加载文本语料并选择分类。")
            return
        try:
            result = self._text_labeling_service.rename_category(
                corpus_id,
                category.id,
                new_name=self._category_name_edit.text(),
                new_description=self._category_description_edit.text(),
                note=self._category_note_edit.text(),
            )
        except UserFacingError as exc:
            self.show_user_error(exc)
            return
        self._apply_category_operation_result(
            result.audit.target_category_id,
            f"分类已重命名，影响 {result.audit.affected_record_count} 条记录。",
        )

    def _merge_text_category(self) -> None:
        corpus_id = self._current_text_corpus_id
        source = self._selected_category_for_management()
        target_id = self._selected_category_target_id()
        target = self._category_by_id(target_id)
        if corpus_id is None or source is None or target is None:
            self._text_label_status.setText("请选择要合并的来源分类和目标分类。")
            return
        affected_count = self._category_usage_count(source.id)
        if not self._confirm_category_operation(
            "合并分类",
            f"将“{source.name}”合并到“{target.name}”，影响 {affected_count} 条记录。",
        ):
            return
        try:
            result = self._text_labeling_service.merge_categories(
                corpus_id,
                source_category_id=source.id,
                target_category_id=target.id,
                note=self._category_note_edit.text(),
            )
        except UserFacingError as exc:
            self.show_user_error(exc)
            return
        self._apply_category_operation_result(
            result.audit.target_category_id,
            f"分类已合并，更新 {result.audit.affected_record_count} 条记录。",
        )

    def _delete_text_category(self) -> None:
        corpus_id = self._current_text_corpus_id
        category = self._selected_category_for_management()
        replacement_id = self._selected_category_target_id()
        replacement = self._category_by_id(replacement_id)
        if corpus_id is None or category is None:
            self._text_label_status.setText("请选择要删除的分类。")
            return
        affected_count = self._category_usage_count(category.id)
        replacement_text = (
            f"替换为“{replacement.name}”" if replacement is not None else "设为未分类"
        )
        if not self._confirm_category_operation(
            "删除分类",
            f"将删除“{category.name}”，并把 {affected_count} 条记录{replacement_text}。",
        ):
            return
        try:
            result = self._text_labeling_service.delete_category(
                corpus_id,
                category_id=category.id,
                replacement_category_id=replacement.id if replacement is not None else None,
                note=self._category_note_edit.text(),
            )
        except UserFacingError as exc:
            self.show_user_error(exc)
            return
        self._apply_category_operation_result(
            result.audit.target_category_id,
            f"分类已删除，更新 {result.audit.affected_record_count} 条记录。",
        )

    def _apply_category_operation_result(
        self,
        preferred_category_id: str | None,
        message: str,
    ) -> None:
        current_row = self._text_label_table.currentIndex().row()
        self._category_note_edit.clear()
        self._refresh_text_label_categories()
        if preferred_category_id:
            index = self._category_manage_combo.findData(preferred_category_id)
            if index >= 0:
                self._category_manage_combo.setCurrentIndex(index)
        if self._text_label_model is not None:
            self._text_label_model.refresh()
            self._selected_text_record = None
            row_count = self._text_label_model.rowCount()
            if row_count:
                self._select_text_label_row(min(max(current_row, 0), row_count - 1))
            else:
                self._clear_text_record_editor()
                self._set_text_editor_enabled(False)
        self._text_label_status.setText(message)

    def _confirm_category_operation(self, title: str, message: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            f"{message}\n\n该操作会写入审计记录，原始文本内容不会被记录到审计日志。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _selected_category_for_management(self) -> Category | None:
        data = self._category_manage_combo.currentData()
        return self._category_by_id(data if isinstance(data, str) else None)

    def _selected_category_target_id(self) -> str | None:
        data = self._category_target_combo.currentData()
        if isinstance(data, str) and data:
            return data
        return None

    def _category_by_id(self, category_id: str | None) -> Category | None:
        if not category_id:
            return None
        for category in self._text_categories:
            if category.id == category_id:
                return category
        return None

    def _category_usage_count(self, category_id: str) -> int:
        corpus_id = self._current_text_corpus_id
        if corpus_id is None:
            return 0
        return self._text_labeling_service.category_usage_counts(corpus_id).get(category_id, 0)

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
        corpus_id = self._current_text_corpus_id
        if corpus_id is not None:
            self._start_text_chart_preparation_job(corpus_id, recommendation)
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

    def _start_text_chart_preparation_job(
        self,
        corpus_id: str,
        recommendation: ChartRecommendation,
    ) -> None:
        if self._running_chart_job is not None:
            self._running_chart_job.cancel()
        self._chart_generation += 1
        generation = self._chart_generation
        self._jobs_label.setText("后台任务：正在准备文本图表数据")
        job = QtJobRunner(
            "text_chart_preparation",
            lambda context: TextChartPreparationService(self._workspace).prepare(
                corpus_id,
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

    def _export_current_tabular_data(self) -> None:
        if self._current_tabular_table_name is None:
            self.show_user_error(
                UserFacingError(
                    code="DATA_EXPORT_NO_TABLE",
                    title_zh="没有可导出的表格",
                    message_zh="当前没有已导入或转换后的表格数据。",
                    next_action_zh="请先导入表格，或生成转换预览表后再导出。",
                )
            )
            return
        selection = self._choose_data_export_path(
            title="导出处理后表格",
            stem=self._current_tabular_table_name,
            default_format=DataExportFormat.CSV,
            formats=(DataExportFormat.CSV, DataExportFormat.PARQUET),
        )
        if selection is None:
            return
        destination, export_format = selection
        self._export_tabular_data_to_path(destination, export_format)

    def _export_current_text_data(self) -> None:
        if self._current_text_corpus_id is None:
            self.show_user_error(
                UserFacingError(
                    code="DATA_EXPORT_NO_TEXT_CORPUS",
                    title_zh="没有可导出的文本语料",
                    message_zh="当前没有已录入或导入的文本语料。",
                    next_action_zh="请先录入文本语句，或打开包含文本语料的项目。",
                )
            )
            return
        selection = self._choose_data_export_path(
            title="导出文本语料",
            stem="text-corpus",
            default_format=DataExportFormat.JSONL,
            formats=(DataExportFormat.JSONL, DataExportFormat.CSV),
        )
        if selection is None:
            return
        destination, export_format = selection
        self._export_text_data_to_path(destination, export_format)

    def _choose_data_export_path(
        self,
        *,
        title: str,
        stem: str,
        default_format: DataExportFormat,
        formats: tuple[DataExportFormat, ...],
    ) -> tuple[Path, DataExportFormat] | None:
        default_dir = Path.home() / "Documents"
        if not default_dir.exists():
            default_dir = self._paths.config_dir
        suggested = default_dir / (_safe_export_stem(stem) + f".{default_format.value}")
        filters = ";;".join(_data_export_filter(export_format) for export_format in formats)
        selected, selected_filter = QFileDialog.getSaveFileName(
            self,
            title,
            str(suggested),
            filters,
        )
        if not selected:
            return None
        export_format = _data_export_format_for_selection(
            Path(selected),
            selected_filter,
            default_format,
            formats,
        )
        destination = _ensure_data_export_suffix(Path(selected), export_format)
        return destination, export_format

    def _export_tabular_data_to_path(
        self,
        destination: Path,
        export_format: DataExportFormat,
    ) -> None:
        table_name = self._current_tabular_table_name
        if table_name is None:
            self._export_current_tabular_data()
            return
        self._start_data_export_job(
            name="tabular_data_export",
            message_zh=f"正在导出 {export_format.value.upper()} 表格",
            work=lambda context: self._data_export_service.export_tabular(
                table_name,
                destination,
                export_format,
                context=context,
            ),
        )

    def _export_text_data_to_path(
        self,
        destination: Path,
        export_format: DataExportFormat,
    ) -> None:
        corpus_id = self._current_text_corpus_id
        if corpus_id is None:
            self._export_current_text_data()
            return
        self._start_data_export_job(
            name="text_data_export",
            message_zh=f"正在导出 {export_format.value.upper()} 文本",
            work=lambda context: self._data_export_service.export_text_corpus(
                corpus_id,
                destination,
                export_format,
                context=context,
            ),
        )

    def _start_data_export_job(
        self,
        *,
        name: str,
        message_zh: str,
        work: Callable[[JobContext], DataExportResult],
    ) -> None:
        if self._running_data_export_job is not None:
            self._running_data_export_job.cancel()
        self._data_export_generation += 1
        generation = self._data_export_generation
        self._jobs_label.setText(f"后台任务：{message_zh}")
        job: QtJobRunner[DataExportResult] = QtJobRunner(name, work)
        self._running_data_export_job = job
        job.signals.progress.connect(self._on_data_export_progress)
        job.signals.completed.connect(
            lambda outcome, expected_generation=generation: self._on_data_export_completed(
                expected_generation,
                outcome,
            )
        )
        QThreadPool.globalInstance().start(job)

    def _on_data_export_progress(self, progress: JobProgress) -> None:
        if self._is_disposed or progress.state is not JobState.RUNNING:
            return
        percent_text = "" if progress.percent is None else f"{progress.percent}% "
        self._jobs_label.setText(f"后台任务：{percent_text}{progress.message_zh}")

    def _on_data_export_completed(
        self,
        expected_generation: int,
        outcome: JobOutcome[DataExportResult],
    ) -> None:
        if self._is_disposed or expected_generation != self._data_export_generation:
            return
        self._running_data_export_job = None
        if outcome.state is JobState.CANCELLED:
            self._jobs_label.setText("后台任务：数据导出已取消")
            return
        if outcome.state is JobState.SUCCEEDED and outcome.value is not None:
            result = outcome.value
            self._jobs_label.setText("后台任务：数据导出完成")
            self._error_label.setText(
                f"数据已导出：{result.path}（{result.row_count} 行，{result.bytes_written} 字节）"
            )
            self.statusBar().showMessage("数据导出完成", 5000)
            return
        self._jobs_label.setText("后台任务：数据导出失败")
        if isinstance(outcome.error, UserFacingError):
            self.show_user_error(outcome.error)
            return
        self.show_user_error(
            UserFacingError(
                code="DATA_EXPORT_UNEXPECTED_FAILURE",
                title_zh="数据导出失败",
                message_zh="导出处理后数据时发生未预期错误。",
                next_action_zh="请确认目标文件夹可写，换一个文件名后重试。",
                technical_detail=repr(outcome.error),
            )
        )

    def _on_chart_export_requested(self, export_format_value: str) -> None:
        try:
            export_format = ChartExportFormat(export_format_value)
        except ValueError:
            self.show_user_error(
                UserFacingError(
                    code="CHART_EXPORT_FORMAT_UNKNOWN",
                    title_zh="导出格式未知",
                    message_zh=f"不支持的图表导出格式：{export_format_value}",
                    next_action_zh="请使用 HTML、SVG、PNG 或 JSON 导出按钮。",
                )
            )
            return
        document = self._chart_view.current_document
        if document is None:
            self.show_user_error(
                UserFacingError(
                    code="CHART_EXPORT_NO_DOCUMENT",
                    title_zh="没有可导出的图表",
                    message_zh="请先从推荐卡片生成一个图表。",
                    next_action_zh="生成图表后再使用导出按钮。",
                )
            )
            return
        destination = self._choose_chart_export_path(export_format, document)
        if destination is None:
            return
        self._jobs_label.setText(f"后台任务：正在导出 {export_format.value.upper()} 图表")
        self._chart_view.export_document(
            export_format,
            destination,
            self._on_chart_export_completed,
        )

    def _choose_chart_export_path(
        self,
        export_format: ChartExportFormat,
        document: PlotlyChartDocument,
    ) -> Path | None:
        default_dir = Path.home() / "Documents"
        if not default_dir.exists():
            default_dir = self._paths.config_dir
        suggested = default_dir / (_safe_export_stem(document.title) + f".{export_format.value}")
        filters = {
            ChartExportFormat.HTML: "HTML 文件 (*.html)",
            ChartExportFormat.SVG: "SVG 文件 (*.svg)",
            ChartExportFormat.PNG: "PNG 文件 (*.png)",
            ChartExportFormat.JSON: "JSON 文件 (*.json)",
        }
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "导出图表",
            str(suggested),
            filters[export_format],
        )
        if not selected:
            return None
        destination = Path(selected)
        if destination.suffix.lower() != f".{export_format.value}":
            destination = destination.with_suffix(f".{export_format.value}")
        return destination

    def _on_chart_export_completed(self, result: ChartExportResult | Exception) -> None:
        if isinstance(result, Exception):
            self._jobs_label.setText("后台任务：图表导出失败")
            self.show_user_error(
                UserFacingError(
                    code="CHART_EXPORT_FAILED",
                    title_zh="图表导出失败",
                    message_zh="导出图表时发生错误。",
                    next_action_zh="请确认目标文件夹可写，稍后重试或复制技术细节提交问题。",
                    technical_detail=repr(result),
                )
            )
            return
        self._jobs_label.setText("后台任务：图表导出完成")
        if result.warning_zh:
            self.show_user_error(
                UserFacingError(
                    code="CHART_EXPORT_COMPLETED_WITH_WARNING",
                    title_zh="图表已导出，但有提示",
                    message_zh=result.warning_zh,
                    next_action_zh=(
                        f"文件已保存到 {result.path}，"
                        "如需完全矢量图可改用非 WebGL 图表。"
                    ),
                    technical_detail=f"format={result.format.value}; path={result.path}",
                )
            )
            return
        self._error_label.setText(f"图表已导出：{result.path}")
        self.statusBar().showMessage("图表导出完成", 5000)

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
        self._cancel_background_work()
        self._project_generation += 1
        if self._running_project_job is not None:
            self._running_project_job.cancel()
            self._running_project_job = None

    def _start_profile_job(self, result: TabularImportResult) -> None:
        self._start_tabular_profile_job(
            dataset_id=result.handle.id,
            table_name=result.table_name,
            import_options=dict(result.handle.import_options),
        )

    def _start_tabular_profile_job(
        self,
        *,
        dataset_id: str,
        table_name: str,
        import_options: dict[str, object],
    ) -> None:
        if self._running_profile_job is not None:
            self._running_profile_job.cancel()
        self._profile_generation += 1
        generation = self._profile_generation
        self._profile_summary.setText("正在生成数据画像和质量检查...")
        self._profile_fields.clear()
        self._profile_findings.clear()
        self._jobs_label.setText("后台任务：正在生成画像")
        job = QtJobRunner(
            "tabular_profile",
            lambda context: self._profile_table(
                context,
                dataset_id=dataset_id,
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


def _project_dataset_key(entry: ProjectDatasetEntry) -> str:
    if entry.table_name:
        return f"table:{entry.table_name}"
    return f"dataset:{entry.handle.id}"


def _project_source_status_text(statuses: tuple[SourceReferenceStatus, ...]) -> str:
    if not statuses:
        return "项目已打开：没有外部源文件引用。"
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status.status] = counts.get(status.status, 0) + 1
    if counts.get("missing") or counts.get("mismatch"):
        details = "；".join(
            f"{status.display_name}：{status.message_zh}"
            for status in statuses
            if status.status in {"missing", "mismatch"}
        )
        return f"项目已打开，但有源文件需要处理：{details}"
    if counts.get("metadata_changed"):
        return "项目已打开：部分源文件内容采样匹配但元数据变化，建议确认后重新保存。"
    return "项目已打开：源文件引用校验通过。"


def _has_relocatable_source_issues(statuses: tuple[SourceReferenceStatus, ...]) -> bool:
    return any(status.status in {"missing", "mismatch"} for status in statuses)


def _coerce_transform_value(
    column_name: str,
    value: str,
    columns: tuple[WorkspaceColumn, ...],
) -> object:
    data_type = ""
    for column in columns:
        if column.name == column_name:
            data_type = column.data_type.upper()
            break
    if _is_integer_workspace_type(data_type):
        try:
            return int(value)
        except ValueError:
            return value
    if _is_numeric_workspace_type(data_type):
        try:
            return float(value)
        except ValueError:
            return value
    if "BOOL" in data_type:
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "y", "是"}:
            return True
        if normalized in {"false", "0", "no", "n", "否"}:
            return False
    return value


def _is_integer_workspace_type(data_type: str) -> bool:
    return any(token in data_type for token in ("BIGINT", "INTEGER", "SMALLINT", "TINYINT"))


def _is_numeric_workspace_type(data_type: str) -> bool:
    return any(
        token in data_type
        for token in ("DECIMAL", "DOUBLE", "FLOAT", "REAL", "HUGEINT", "UBIGINT")
    ) or _is_integer_workspace_type(data_type)


def _transform_step_text(step: TransformStep) -> str:
    parameters = step.parameters
    if step.operation == "filter_rows":
        return f"筛选行：{_filter_expression_text(parameters.get('expression'))}"
    if step.operation == "select_columns":
        columns = parameters.get("columns")
        if isinstance(columns, list | tuple):
            return f"选择/重命名字段：保留 {len(columns)} 个字段"
        return "选择/重命名字段"
    if step.operation == "sort_rows":
        return f"排序：{parameters.get('columns')}"
    if step.operation == "deduplicate_rows":
        return f"去重：{parameters.get('columns')}"
    if step.operation == "drop_missing":
        return f"删除缺失值：{parameters.get('columns')}"
    if step.operation == "fill_missing":
        values = parameters.get("values")
        return f"填充缺失值：{', '.join(values) if isinstance(values, dict) else values}"
    if step.operation == "convert_type":
        return f"类型转换：{parameters.get('columns')}"
    if step.operation == "group_aggregate":
        return (
            f"分组聚合：按 {parameters.get('group_by')}，"
            f"计算 {parameters.get('aggregations')}"
        )
    return step.operation


def _filter_expression_text(expression: object) -> str:
    if not isinstance(expression, dict):
        return "条件无效"
    op = str(expression.get("op", ""))
    if op in {"and", "or"}:
        joiner = " 并且 " if op == "and" else " 或者 "
        conditions = expression.get("conditions")
        if isinstance(conditions, list | tuple):
            return "(" + joiner.join(_filter_expression_text(item) for item in conditions) + ")"
    if op == "not":
        return "非 " + _filter_expression_text(expression.get("condition"))
    column = expression.get("column")
    if op in {"is_null", "is_not_null"}:
        return f"{column} {_filter_operator_text(op)}"
    return f"{column} {_filter_operator_text(op)} {expression.get('value')}"


def _filter_operator_text(operator: str) -> str:
    return {
        "==": "=",
        "eq": "=",
        "!=": "!=",
        "ne": "!=",
        ">": ">",
        ">=": ">=",
        "<": "<",
        "<=": "<=",
        "contains": "包含",
        "starts_with": "开头为",
        "ends_with": "结尾为",
        "in": "属于",
        "is_null": "为空",
        "is_not_null": "不为空",
    }.get(operator, operator)


def _lossy_transform_warnings(steps: tuple[TransformStep, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    for step in steps:
        if step.operation == "filter_rows":
            warnings.append("筛选行可能减少可见记录。")
        elif step.operation == "select_columns":
            warnings.append("选择/重命名字段可能隐藏字段或改变字段名。")
        elif step.operation == "deduplicate_rows":
            warnings.append("去重会只保留每组第一条记录。")
        elif step.operation == "drop_missing":
            warnings.append("删除缺失值会移除含空值的记录。")
        elif step.operation == "fill_missing":
            warnings.append("填充缺失值会改变预览结果中的空值。")
        elif step.operation == "convert_type":
            warnings.append("类型转换失败的值会在预览中变为空值。")
        elif step.operation == "group_aggregate":
            warnings.append("分组聚合会把明细行汇总为聚合结果。")
    return tuple(warnings)


def _transform_step_payload(step: TransformStep) -> dict[str, object]:
    return {
        "id": step.id,
        "operation": step.operation,
        "parameters": step.parameters,
        "reversible": step.reversible,
        "schema_version": step.schema_version,
    }


def _field_profile_text(column: ColumnProfile) -> str:
    distinct = "未知" if column.distinct_count is None else str(column.distinct_count)
    warnings = "" if not column.warnings else f"；警告 {', '.join(column.warnings)}"
    return (
        f"{column.name} · {_semantic_type_text(column.semantic_type.value)} · "
        f"缺失 {column.null_count} · 不同值 {distinct}{warnings}"
    )


def _data_export_filter(export_format: DataExportFormat) -> str:
    return {
        DataExportFormat.CSV: "CSV 文件 (*.csv)",
        DataExportFormat.PARQUET: "Parquet 文件 (*.parquet)",
        DataExportFormat.JSONL: "JSONL 文件 (*.jsonl)",
    }[export_format]


def _data_export_format_for_selection(
    path: Path,
    selected_filter: str,
    default_format: DataExportFormat,
    formats: tuple[DataExportFormat, ...],
) -> DataExportFormat:
    suffix = path.suffix.lower().lstrip(".")
    for export_format in formats:
        if suffix == export_format.value:
            return export_format
    for export_format in formats:
        if export_format.value in selected_filter.casefold():
            return export_format
    return default_format


def _ensure_data_export_suffix(path: Path, export_format: DataExportFormat) -> Path:
    if path.suffix.lower() == f".{export_format.value}":
        return path
    return path.with_suffix(f".{export_format.value}")


def _safe_export_stem(title: str) -> str:
    cleaned = "".join(
        character
        if character.isalnum() or character in {" ", "-", "_"}
        else "_"
        for character in title
    ).strip()
    cleaned = "_".join(part for part in cleaned.split() if part)
    return cleaned[:80] or "quick-insight-chart"


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
