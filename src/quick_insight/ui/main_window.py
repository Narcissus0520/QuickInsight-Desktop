from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QThreadPool, Signal
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
    QTableView,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from quick_insight import APP_NAME_ZH
from quick_insight.application.analysis import TabularAnalysisService
from quick_insight.application.errors import UserFacingError
from quick_insight.application.importing import TabularImportResult, TabularImportService
from quick_insight.application.jobs import JobContext, JobOutcome, JobProgress, JobState
from quick_insight.application.profiling import TabularProfiler
from quick_insight.application.text_corpus import TextCorpusImportResult, TextCorpusService
from quick_insight.domain.models import ColumnProfile, DatasetProfile
from quick_insight.infrastructure.paths import AppPaths
from quick_insight.infrastructure.settings import AppSettings, save_settings
from quick_insight.infrastructure.workspace import WorkspaceDatabase
from quick_insight.ui.dialogs import TabularImportDialog, TextCorpusDialog
from quick_insight.ui.jobs import QtJobRunner
from quick_insight.ui.models import DuckDbTableModel
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

        self._stack = QStackedWidget()
        self._error_label = QLabel("无错误")
        self._theme_selector = QComboBox()
        self._dataset_list = QListWidget()
        self._preview_table = QTableView()
        self._preview_summary = QLabel("尚未导入数据。")
        self._profile_summary = QLabel("尚未生成数据画像。")
        self._profile_fields = QListWidget()
        self._profile_findings = QListWidget()
        self._row_count_label = QLabel("行/记录：未加载")
        self._query_time_label = QLabel("查询：--")
        self._approximation_label = QLabel("近似：无")
        self._jobs_label = QLabel("后台任务：空闲")
        self._profile_generation = 0
        self._running_profile_job: QtJobRunner[DatasetProfile] | None = None
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
        self._stack.addWidget(self._placeholder_page("推荐", "M3 将提供可解释图表推荐。"))
        self._stack.addWidget(self._placeholder_page("图表", "M4 将提供本地 Plotly 图表工作区。"))
        self._stack.addWidget(
            self._placeholder_page("文本标注", "文本语料可保存；虚拟化标注工作区将在下一步接入。")
        )

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
        self._dataset_list.addItem(handle.display_name)
        self._row_count_label.setText(f"行/记录：{handle.row_count}")
        self._query_time_label.setText("查询：文本语料已保存")
        self._approximation_label.setText("近似：无")
        self._jobs_label.setText("后台任务：空闲")
        self._error_label.setText("无错误")
        self._stack.setCurrentIndex(5)
        self.statusBar().showMessage("文本语料已保存", 5000)

    def _on_destroyed(self) -> None:
        self._is_disposed = True
        self._profile_generation += 1
        if self._running_profile_job is not None:
            self._running_profile_job.cancel()
            self._running_profile_job = None

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
