from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from quick_insight.application.errors import UserFacingError
from quick_insight.application.importing import (
    TabularImportResult,
    TabularImportService,
    TabularPreview,
)
from quick_insight.application.jobs import JobOutcome, JobProgress, JobState
from quick_insight.infrastructure.csv_import import DELIMITER_BY_NAME, CsvPreview
from quick_insight.ui.jobs import QtJobRunner
from quick_insight.ui.models import PreviewTableModel


class TabularImportDialog(QDialog):
    def __init__(
        self,
        *,
        service: TabularImportService,
        initial_path: Path | None = None,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setObjectName("tabularImportDialog")
        self.setWindowTitle("导入表格数据")
        self.resize(900, 620)
        self._service = service
        self._preview: TabularPreview | None = None
        self.import_result: TabularImportResult | None = None
        self._running_job: QtJobRunner[TabularImportResult] | None = None

        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("importPathEdit")
        if initial_path is not None:
            self._path_edit.setText(str(initial_path))
        self._encoding_combo = QComboBox()
        self._encoding_combo.setObjectName("encodingCombo")
        self._encoding_combo.addItem("自动检测", None)
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "shift_jis"):
            self._encoding_combo.addItem(encoding, encoding)
        self._delimiter_combo = QComboBox()
        self._delimiter_combo.setObjectName("delimiterCombo")
        self._delimiter_combo.addItem("自动检测", None)
        self._delimiter_combo.addItem("逗号 ,", DELIMITER_BY_NAME["comma"])
        self._delimiter_combo.addItem("制表符 Tab", DELIMITER_BY_NAME["tab"])
        self._delimiter_combo.addItem("分号 ;", DELIMITER_BY_NAME["semicolon"])
        self._delimiter_combo.addItem("竖线 |", DELIMITER_BY_NAME["pipe"])
        self._header_check = QCheckBox("第一行是表头")
        self._header_check.setObjectName("hasHeaderCheck")
        self._header_check.setChecked(True)
        self._status_label = QLabel("请选择 CSV 或 TSV 文件并预览。")
        self._status_label.setObjectName("muted")
        self._status_label.setWordWrap(True)
        self._preview_table = QTableView()
        self._preview_table.setObjectName("csvPreviewTable")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        file_row = QHBoxLayout()
        browse_button = QPushButton("选择文件")
        browse_button.clicked.connect(self._browse)
        file_row.addWidget(self._path_edit, stretch=1)
        file_row.addWidget(browse_button)
        form.addRow("文件", file_row)
        form.addRow("编码", self._encoding_combo)
        form.addRow("分隔符", self._delimiter_combo)
        form.addRow("", self._header_check)
        layout.addLayout(form)
        preview_button = QPushButton("预览")
        preview_button.setObjectName("previewImportButton")
        preview_button.setProperty("primary", True)
        preview_button.clicked.connect(self.preview)
        layout.addWidget(preview_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._status_label)
        layout.addWidget(self._preview_table, stretch=1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认导入")
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self._confirm)
        self._buttons.rejected.connect(self._cancel_or_reject)
        layout.addWidget(self._buttons)

        if initial_path is not None:
            self.preview()

    def preview(self) -> None:
        path_text = self._path_edit.text().strip()
        if not path_text:
            self._show_error(
                UserFacingError(
                    code="IMPORT_NO_FILE",
                    title_zh="未选择文件",
                    message_zh="请先选择一个 CSV 或 TSV 文件。",
                    next_action_zh="点击“选择文件”后再预览。",
                )
            )
            return
        try:
            path = Path(path_text)
            preview: TabularPreview
            if path.suffix.lower() in {".csv", ".tsv", ".txt"}:
                preview = self._service.preview_csv(
                    path,
                    encoding=self._encoding_combo.currentData(),
                    delimiter=self._delimiter_combo.currentData(),
                    has_header=self._header_check.isChecked(),
                )
            else:
                preview = self._service.preview_file(path)
        except UserFacingError as exc:
            self._show_error(exc)
            return
        self._preview = preview
        self._preview_table.setModel(PreviewTableModel(preview.columns, preview.rows))
        self._status_label.setText(_preview_status(preview))
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _browse(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择表格数据",
            "",
            "Tabular files (*.csv *.tsv *.xlsx *.xls *.xlsb *.parquet);;All files (*.*)",
        )
        if path:
            self._path_edit.setText(path)
            self.preview()

    def _confirm(self) -> None:
        if self._preview is None:
            self.preview()
        if self._preview is None:
            return
        preview = self._preview
        self._set_import_running(True)
        job = QtJobRunner(
            "tabular_import",
            lambda context: self._service.import_preview(preview, context=context),
        )
        self._running_job = job
        job.signals.progress.connect(self._on_import_progress)
        job.signals.completed.connect(self._on_import_completed)
        QThreadPool.globalInstance().start(job)

    def _show_error(self, error: UserFacingError) -> None:
        self._status_label.setText(error.display_text())
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _cancel_or_reject(self) -> None:
        if self._running_job is None:
            self.reject()
            return
        self._running_job.cancel()
        self._status_label.setText("正在请求取消导入...")

    def _on_import_progress(self, progress: JobProgress) -> None:
        if progress.state != JobState.RUNNING:
            return
        percent_text = "" if progress.percent is None else f"{progress.percent}% "
        self._status_label.setText(f"{percent_text}{progress.message_zh}")

    def _on_import_completed(self, outcome: JobOutcome[TabularImportResult]) -> None:
        self._running_job = None
        self._set_import_running(False)
        if outcome.state is JobState.SUCCEEDED and outcome.value is not None:
            self.import_result = outcome.value
            self.accept()
            return
        if outcome.state is JobState.CANCELLED:
            self._status_label.setText("导入已取消。")
            return
        error = outcome.error
        if isinstance(error, UserFacingError):
            self._show_error(error)
            return
        self._show_error(
            UserFacingError(
                code="IMPORT_UNEXPECTED_FAILURE",
                title_zh="导入失败",
                message_zh="导入过程中发生未预期错误。",
                next_action_zh="请复制技术详情并检查文件格式后重试。",
                technical_detail=repr(error),
            )
        )

    def _set_import_running(self, running: bool) -> None:
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_button.setEnabled(not running)
        cancel_button.setText("取消导入" if running else "取消")
        self._path_edit.setEnabled(not running)
        self._encoding_combo.setEnabled(not running)
        self._delimiter_combo.setEnabled(not running)
        self._header_check.setEnabled(not running)


def _preview_status(preview: TabularPreview) -> str:
    warning_text = "；".join(preview.warnings)
    suffix = f" 警告：{warning_text}" if warning_text else ""
    if isinstance(preview, CsvPreview):
        return (
            f"已预览 {preview.total_preview_rows} 行，编码 {preview.options.encoding}，"
            f"分隔符 {preview.options.delimiter!r}。{suffix}"
        )
    format_name = "Excel" if preview.file_format == "excel" else "Parquet"
    sheet_text = ""
    if preview.file_format == "excel":
        sheet_text = f"，工作表 {preview.options.get('sheet_name')}"
    return f"已预览 {format_name} 文件 {preview.total_preview_rows} 行{sheet_text}。{suffix}"
