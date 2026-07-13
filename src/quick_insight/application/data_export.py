from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from quick_insight.application.errors import UserFacingError
from quick_insight.application.jobs import JobContext
from quick_insight.domain.enums import DatasetKind
from quick_insight.infrastructure.workspace import WorkspaceDatabase


class DataExportFormat(StrEnum):
    CSV = "csv"
    PARQUET = "parquet"
    JSONL = "jsonl"


@dataclass(frozen=True)
class DataExportResult:
    path: Path
    format: DataExportFormat
    dataset_kind: DatasetKind
    row_count: int
    bytes_written: int


class ProcessedDataExportService:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def export_tabular(
        self,
        table_name: str,
        destination: Path,
        export_format: DataExportFormat,
        *,
        context: JobContext | None = None,
    ) -> DataExportResult:
        if export_format not in {DataExportFormat.CSV, DataExportFormat.PARQUET}:
            raise UserFacingError(
                code="DATA_EXPORT_TABULAR_FORMAT_UNSUPPORTED",
                title_zh="表格导出格式不支持",
                message_zh="处理后表格当前支持 CSV 和 Parquet 导出。",
                next_action_zh="请选择 CSV 或 Parquet 格式后重试。",
                technical_detail=f"format={export_format.value}",
            )
        if not table_name:
            raise UserFacingError(
                code="DATA_EXPORT_NO_TABLE",
                title_zh="没有可导出的表格",
                message_zh="当前没有已导入或转换后的表格数据。",
                next_action_zh="请先导入表格，或生成转换预览表后再导出。",
            )
        destination = _prepare_destination(destination)
        temp_path = _temporary_export_path(destination)
        try:
            _progress(context, 10, "正在检查表格数据")
            row_count = self._workspace.row_count(table_name)
            _progress(context, 35, "正在写出表格文件")
            if export_format is DataExportFormat.CSV:
                self._workspace.export_table_to_csv(table_name, temp_path)
            else:
                self._workspace.export_table_to_parquet(table_name, temp_path)
            _progress(context, 90, "正在完成表格导出")
            _move_completed_export(temp_path, destination)
            return DataExportResult(
                path=destination,
                format=export_format,
                dataset_kind=DatasetKind.TABULAR,
                row_count=row_count,
                bytes_written=destination.stat().st_size,
            )
        except UserFacingError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            raise UserFacingError(
                code="DATA_EXPORT_TABULAR_FAILED",
                title_zh="表格导出失败",
                message_zh="写出处理后表格文件时发生错误。",
                next_action_zh="请确认目标文件夹可写，或换一个文件名后重试。",
                technical_detail=repr(exc),
            ) from exc

    def export_text_corpus(
        self,
        corpus_id: str,
        destination: Path,
        export_format: DataExportFormat,
        *,
        context: JobContext | None = None,
    ) -> DataExportResult:
        if export_format not in {DataExportFormat.CSV, DataExportFormat.JSONL}:
            raise UserFacingError(
                code="DATA_EXPORT_TEXT_FORMAT_UNSUPPORTED",
                title_zh="文本导出格式不支持",
                message_zh="文本语料当前支持 CSV 和 JSONL 导出。",
                next_action_zh="请选择 CSV 或 JSONL 格式后重试。",
                technical_detail=f"format={export_format.value}",
            )
        if not corpus_id:
            raise UserFacingError(
                code="DATA_EXPORT_NO_TEXT_CORPUS",
                title_zh="没有可导出的文本语料",
                message_zh="当前没有已录入或导入的文本语料。",
                next_action_zh="请先录入文本语句，或打开包含文本语料的项目。",
            )
        destination = _prepare_destination(destination)
        temp_path = _temporary_export_path(destination)
        try:
            _progress(context, 10, "正在检查文本语料")
            row_count = self._workspace.text_record_count(corpus_id)
            if row_count <= 0:
                raise UserFacingError(
                    code="DATA_EXPORT_TEXT_EMPTY",
                    title_zh="文本语料为空",
                    message_zh="当前文本语料没有可导出的记录。",
                    next_action_zh="请先录入或导入文本记录后再导出。",
                    technical_detail=f"corpus_id={corpus_id}",
                )
            _progress(context, 35, "正在写出文本数据")
            if export_format is DataExportFormat.CSV:
                self._workspace.export_text_corpus_to_csv(corpus_id, temp_path)
            else:
                self._workspace.export_text_corpus_to_jsonl(corpus_id, temp_path)
            _progress(context, 90, "正在完成文本导出")
            _move_completed_export(temp_path, destination)
            return DataExportResult(
                path=destination,
                format=export_format,
                dataset_kind=DatasetKind.TEXT_CORPUS,
                row_count=row_count,
                bytes_written=destination.stat().st_size,
            )
        except UserFacingError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            raise UserFacingError(
                code="DATA_EXPORT_TEXT_FAILED",
                title_zh="文本导出失败",
                message_zh="写出文本语料文件时发生错误。",
                next_action_zh="请确认目标文件夹可写，或换一个文件名后重试。",
                technical_detail=repr(exc),
            ) from exc


def _prepare_destination(destination: Path) -> Path:
    resolved = destination.expanduser().resolve()
    if resolved.exists():
        raise UserFacingError(
            code="DATA_EXPORT_DESTINATION_EXISTS",
            title_zh="目标文件已存在",
            message_zh="为避免覆盖原始数据或已有结果，导出不会默认覆盖文件。",
            next_action_zh="请选择一个新文件名后重试。",
            technical_detail=str(resolved),
        )
    if resolved.parent.exists() and not resolved.parent.is_dir():
        raise UserFacingError(
            code="DATA_EXPORT_PARENT_NOT_DIRECTORY",
            title_zh="导出位置无效",
            message_zh="目标文件所在位置不是文件夹。",
            next_action_zh="请选择一个有效的文件夹后重试。",
            technical_detail=str(resolved.parent),
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _temporary_export_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")


def _move_completed_export(temp_path: Path, destination: Path) -> None:
    if destination.exists():
        raise UserFacingError(
            code="DATA_EXPORT_DESTINATION_EXISTS",
            title_zh="目标文件已存在",
            message_zh="导出过程中发现目标文件已经存在，已停止写入。",
            next_action_zh="请换一个新文件名后重试。",
            technical_detail=str(destination),
        )
    temp_path.rename(destination)


def _progress(context: JobContext | None, percent: int, message_zh: str) -> None:
    if context is not None:
        context.progress(percent, message_zh)
