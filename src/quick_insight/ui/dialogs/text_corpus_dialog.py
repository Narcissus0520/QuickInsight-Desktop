from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
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
    QTextEdit,
    QVBoxLayout,
)

from quick_insight.application.errors import UserFacingError
from quick_insight.application.jobs import JobOutcome, JobProgress, JobState
from quick_insight.application.text_corpus import (
    TextCorpusImportResult,
    TextCorpusPreview,
    TextCorpusService,
    TextImportOptions,
    TextSplitMode,
)
from quick_insight.ui.jobs import QtJobRunner
from quick_insight.ui.models import PreviewTableModel


class TextCorpusDialog(QDialog):
    def __init__(
        self,
        *,
        service: TextCorpusService,
        initial_path: Path | None = None,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setObjectName("textCorpusDialog")
        self.setWindowTitle("录入文本语句")
        self.resize(900, 640)
        self._service = service
        self._preview: TextCorpusPreview | None = None
        self.import_result: TextCorpusImportResult | None = None
        self._running_job: QtJobRunner[TextCorpusImportResult] | None = None

        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("textCorpusPathEdit")
        if initial_path is not None:
            self._path_edit.setText(str(initial_path))
        self._content_edit = QTextEdit()
        self._content_edit.setObjectName("textCorpusContentEdit")
        self._content_edit.setPlaceholderText(
            "在这里粘贴文本；也可以选择 TXT、Markdown 或 JSONL 文件。"
        )
        self._split_combo = QComboBox()
        self._split_combo.setObjectName("textSplitModeCombo")
        for label, mode in (
            ("按非空行", TextSplitMode.NON_EMPTY_LINE),
            ("按段落", TextSplitMode.PARAGRAPH),
            ("按句子", TextSplitMode.SENTENCE),
            ("自定义分隔符", TextSplitMode.CUSTOM_DELIMITER),
            ("整段作为一条", TextSplitMode.WHOLE_INPUT),
        ):
            self._split_combo.addItem(label, mode)
        self._delimiter_edit = QLineEdit()
        self._delimiter_edit.setObjectName("textDelimiterEdit")
        self._delimiter_edit.setPlaceholderText("自定义分隔符")
        self._category_edit = QLineEdit()
        self._category_edit.setObjectName("defaultCategoryEdit")
        self._category_edit.setPlaceholderText("可选，例如 产品体验")
        self._tags_edit = QLineEdit()
        self._tags_edit.setObjectName("defaultTagsEdit")
        self._tags_edit.setPlaceholderText("可选，用逗号分隔")
        self._source_edit = QLineEdit()
        self._source_edit.setObjectName("defaultSourceEdit")
        self._source_edit.setPlaceholderText("可选，例如 访谈")
        self._status_label = QLabel("粘贴文本或选择文件后预览。")
        self._status_label.setObjectName("muted")
        self._status_label.setWordWrap(True)
        self._preview_table = QTableView()
        self._preview_table.setObjectName("textCorpusPreviewTable")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        file_row = QHBoxLayout()
        browse_button = QPushButton("选择文件")
        browse_button.clicked.connect(self._browse)
        file_row.addWidget(self._path_edit, stretch=1)
        file_row.addWidget(browse_button)
        form.addRow("文件", file_row)
        form.addRow("拆分方式", self._split_combo)
        form.addRow("分隔符", self._delimiter_edit)
        form.addRow("默认分类", self._category_edit)
        form.addRow("默认标签", self._tags_edit)
        form.addRow("默认来源", self._source_edit)
        layout.addLayout(form)
        layout.addWidget(self._content_edit, stretch=1)
        preview_button = QPushButton("预览")
        preview_button.setObjectName("previewTextCorpusButton")
        preview_button.setProperty("primary", True)
        preview_button.clicked.connect(self.preview)
        layout.addWidget(preview_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._status_label)
        layout.addWidget(self._preview_table, stretch=1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认保存")
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self._confirm)
        self._buttons.rejected.connect(self._cancel_or_reject)
        layout.addWidget(self._buttons)

        if initial_path is not None:
            self.preview()

    def preview(self) -> None:
        try:
            options = self._options()
            path_text = self._path_edit.text().strip()
            if path_text:
                preview = self._service.preview_file(Path(path_text), options=options)
            else:
                preview = self._service.preview_text(
                    self._content_edit.toPlainText(),
                    options=options,
                )
        except UserFacingError as exc:
            self._show_error(exc)
            return
        self._preview = preview
        self._preview_table.setModel(
            PreviewTableModel(
                ("内容", "分类", "标签", "来源"),
                tuple(
                    (
                        record.content,
                        _category_name(record.primary_category_id, preview.categories),
                        ", ".join(record.tags),
                        record.source or "",
                    )
                    for record in preview.records
                ),
            )
        )
        warning_text = "；".join(preview.warnings)
        suffix = f" 警告：{warning_text}" if warning_text else ""
        self._status_label.setText(
            f"已预览 {len(preview.records)} 条文本记录，分类 {len(preview.categories)} 个。{suffix}"
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _browse(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择文本语料",
            "",
            "Text corpus files (*.txt *.md *.markdown *.jsonl);;All files (*.*)",
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
            "text_corpus_import",
            lambda _context: self._service.import_preview(preview),
        )
        self._running_job = job
        job.signals.progress.connect(self._on_import_progress)
        job.signals.completed.connect(self._on_import_completed)
        QThreadPool.globalInstance().start(job)

    def _cancel_or_reject(self) -> None:
        if self._running_job is None:
            self.reject()
            return
        self._running_job.cancel()
        self._status_label.setText("正在请求取消保存...")

    def _show_error(self, error: UserFacingError) -> None:
        self._status_label.setText(error.display_text())
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _on_import_progress(self, progress: JobProgress) -> None:
        if progress.state != JobState.RUNNING:
            return
        percent_text = "" if progress.percent is None else f"{progress.percent}% "
        self._status_label.setText(f"{percent_text}{progress.message_zh}")

    def _on_import_completed(self, outcome: JobOutcome[TextCorpusImportResult]) -> None:
        self._running_job = None
        self._set_import_running(False)
        if outcome.state is JobState.SUCCEEDED and outcome.value is not None:
            self.import_result = outcome.value
            self.accept()
            return
        if outcome.state is JobState.CANCELLED:
            self._status_label.setText("保存已取消。")
            return
        error = outcome.error
        if isinstance(error, UserFacingError):
            self._show_error(error)
            return
        self._show_error(
            UserFacingError(
                code="TEXT_CORPUS_UNEXPECTED_FAILURE",
                title_zh="文本语料保存失败",
                message_zh="保存文本语料时发生未预期错误。",
                next_action_zh="请复制技术详情并重试。",
                technical_detail=repr(error),
            )
        )

    def _set_import_running(self, running: bool) -> None:
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_button.setEnabled(not running)
        cancel_button.setText("取消保存" if running else "取消")
        self._path_edit.setEnabled(not running)
        self._content_edit.setEnabled(not running)
        self._split_combo.setEnabled(not running)
        self._delimiter_edit.setEnabled(not running)
        self._category_edit.setEnabled(not running)
        self._tags_edit.setEnabled(not running)
        self._source_edit.setEnabled(not running)

    def _options(self) -> TextImportOptions:
        mode = self._split_combo.currentData()
        tags = tuple(
            tag.strip()
            for tag in self._tags_edit.text().split(",")
            if tag.strip()
        )
        return TextImportOptions(
            split_mode=mode if isinstance(mode, TextSplitMode) else TextSplitMode.NON_EMPTY_LINE,
            custom_delimiter=self._delimiter_edit.text(),
            default_category=self._category_edit.text().strip(),
            default_tags=tags,
            default_source=self._source_edit.text().strip(),
        )


def _category_name(category_id: str | None, categories: tuple[object, ...]) -> str:
    for category in categories:
        if getattr(category, "id", None) == category_id:
            return str(getattr(category, "name", ""))
    return ""
