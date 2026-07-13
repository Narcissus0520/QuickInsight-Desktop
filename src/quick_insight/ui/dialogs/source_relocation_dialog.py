from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from quick_insight.application.errors import UserFacingError
from quick_insight.application.project import (
    ProjectManifest,
    SourceReferenceStatus,
    relocate_source_reference,
    validate_source_references,
)

RELOCATABLE_SOURCE_STATUSES = frozenset({"missing", "mismatch"})


class SourceRelocationDialog(QDialog):
    def __init__(
        self,
        *,
        manifest: ProjectManifest,
        statuses: tuple[SourceReferenceStatus, ...],
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.setObjectName("sourceRelocationDialog")
        self.setWindowTitle("重定位源文件")
        self.resize(760, 480)

        self._manifest = manifest
        self._statuses = statuses
        self._relocated_any = False
        self._result_manifest: ProjectManifest | None = None
        self._result_statuses: tuple[SourceReferenceStatus, ...] = statuses

        self._issue_list = QListWidget()
        self._issue_list.setObjectName("sourceRelocationIssueList")
        self._issue_list.currentItemChanged.connect(self._on_issue_selection_changed)

        self._detail_label = QLabel("请选择一个需要处理的源文件。")
        self._detail_label.setObjectName("sourceRelocationDetailLabel")
        self._detail_label.setWordWrap(True)

        self._path_edit = QLineEdit()
        self._path_edit.setObjectName("sourceRelocationPathEdit")
        self._path_edit.setPlaceholderText("选择移动后的原始源文件")
        browse_button = QPushButton("选择文件")
        browse_button.setObjectName("sourceRelocationBrowseButton")
        browse_button.clicked.connect(self._browse)

        self._relocate_button = QPushButton("验证并重定位")
        self._relocate_button.setObjectName("sourceRelocationApplyButton")
        self._relocate_button.setProperty("primary", True)
        self._relocate_button.clicked.connect(self._relocate_current)

        self._status_label = QLabel("只会接受大小和内容采样与项目记录匹配的文件。")
        self._status_label.setObjectName("sourceRelocationStatusLabel")
        self._status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "项目中的外部源文件缺失或与记录不一致。请选择原始文件的新位置，"
            "应用会校验大小和内容采样，校验失败不会更新项目。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self._issue_list, stretch=1)
        layout.addWidget(self._detail_label)

        form = QFormLayout()
        path_row = QHBoxLayout()
        path_row.addWidget(self._path_edit, stretch=1)
        path_row.addWidget(browse_button)
        form.addRow("新位置", path_row)
        layout.addLayout(form)
        layout.addWidget(self._relocate_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._status_label)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.setObjectName("sourceRelocationButtons")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("完成")
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("关闭")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self._accept_result)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._refresh_issues()

    @property
    def result_manifest(self) -> ProjectManifest | None:
        return self._result_manifest

    @property
    def result_statuses(self) -> tuple[SourceReferenceStatus, ...]:
        return self._result_statuses

    def _browse(self) -> None:
        status = self._current_status()
        start_dir = ""
        if status is not None and status.source_path is not None:
            start_dir = str(status.source_path.parent)
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择移动后的源文件",
            start_dir,
            "All files (*.*)",
        )
        if path:
            self._path_edit.setText(path)

    def _relocate_current(self) -> None:
        status = self._current_status()
        if status is None:
            self._show_error(
                UserFacingError(
                    code="PROJECT_RELOCATION_NO_SELECTION",
                    title_zh="未选择数据集",
                    message_zh="请先选择一个需要重定位的数据集。",
                    next_action_zh="在列表中选择源文件缺失或不匹配的数据集。",
                )
            )
            return
        path_text = self._path_edit.text().strip()
        if not path_text:
            self._show_error(
                UserFacingError(
                    code="PROJECT_RELOCATION_NO_FILE",
                    title_zh="未选择源文件",
                    message_zh="请先选择移动后的原始源文件。",
                    next_action_zh="点击“选择文件”，或手动输入文件路径。",
                )
            )
            return
        try:
            relocation = relocate_source_reference(
                self._manifest,
                dataset_id=status.dataset_id,
                new_source_path=Path(path_text),
            )
        except UserFacingError as exc:
            self._show_error(exc)
            return
        self._manifest = relocation.manifest
        self._relocated_any = True
        self._status_label.setText(
            f"{relocation.status.display_name} 已重定位并通过源文件校验。"
        )
        self._refresh_issues()

    def _accept_result(self) -> None:
        self._result_manifest = self._manifest
        self._result_statuses = validate_source_references(self._manifest)
        self.accept()

    def _refresh_issues(self) -> None:
        self._statuses = validate_source_references(self._manifest)
        self._issue_list.clear()
        for status in self._statuses:
            if status.status not in RELOCATABLE_SOURCE_STATUSES:
                continue
            item = QListWidgetItem(
                f"{status.display_name} - {_source_status_label(status)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, status.dataset_id)
            if status.source_path is not None:
                item.setToolTip(str(status.source_path))
            self._issue_list.addItem(item)
        has_issues = self._issue_list.count() > 0
        self._relocate_button.setEnabled(has_issues)
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(self._relocated_any)
        if has_issues:
            self._issue_list.setCurrentRow(0)
        else:
            self._detail_label.setText("所有需要处理的源文件都已通过校验。")
            self._path_edit.clear()
            self._relocate_button.setEnabled(False)
            if self._relocated_any:
                self._status_label.setText("源文件重定位完成。点击“完成”应用到当前项目。")

    def _on_issue_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        self._sync_detail(current)

    def _sync_detail(self, item: QListWidgetItem | None = None) -> None:
        status = self._status_for_item(item) if item is not None else self._current_status()
        if status is None:
            self._detail_label.setText("请选择一个需要处理的源文件。")
            return
        source_text = "无" if status.source_path is None else str(status.source_path)
        expected_text = _source_evidence_text(status)
        self._detail_label.setText(
            f"{status.display_name}：{status.message_zh}\n"
            f"项目记录路径：{source_text}\n"
            f"项目记录证据：{expected_text}"
        )

    def _current_status(self) -> SourceReferenceStatus | None:
        if self._issue_list.count() == 0:
            return None
        item = self._issue_list.currentItem()
        return self._status_for_item(item)

    def _status_for_item(self, item: QListWidgetItem | None) -> SourceReferenceStatus | None:
        if item is None:
            return None
        dataset_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(dataset_id, str):
            return None
        for status in self._statuses:
            if status.dataset_id == dataset_id:
                return status
        return None

    def _show_error(self, error: UserFacingError) -> None:
        self._status_label.setText(error.display_text())


def _source_status_label(status: SourceReferenceStatus) -> str:
    if status.status == "missing":
        return "源文件缺失"
    if status.status == "mismatch":
        return "源文件不匹配"
    return status.message_zh


def _source_evidence_text(status: SourceReferenceStatus) -> str:
    expected = status.expected
    if expected is None:
        return "缺少校验证据"
    return (
        f"大小 {expected.size} 字节；"
        f"内容采样 {expected.sample_sha256[:12]}...；"
        f"修改时间 {expected.modified_ns}"
    )
