from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quick_insight.application.jobs import JobContext
from quick_insight.domain.enums import DatasetKind
from quick_insight.domain.models import DatasetHandle
from quick_insight.infrastructure.csv_import import (
    CsvPreview,
    fingerprint_file,
    preview_delimited_file,
    table_name_for_fingerprint,
)
from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase


@dataclass(frozen=True)
class TabularImportResult:
    handle: DatasetHandle
    table_name: str
    columns: tuple[WorkspaceColumn, ...]


class TabularImportService:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def preview_csv(
        self,
        path: Path,
        *,
        encoding: str | None = None,
        delimiter: str | None = None,
        has_header: bool = True,
        preview_limit: int = 200,
    ) -> CsvPreview:
        return preview_delimited_file(
            path,
            encoding=encoding,
            delimiter=delimiter,
            has_header=has_header,
            preview_limit=preview_limit,
        )

    def import_csv(
        self,
        preview: CsvPreview,
        *,
        display_name: str | None = None,
        context: JobContext | None = None,
    ) -> TabularImportResult:
        if context is not None:
            context.progress(10, "正在计算源文件指纹")
        fingerprint = fingerprint_file(preview.path)
        dataset_id = fingerprint[:16]
        table_name = table_name_for_fingerprint(fingerprint)
        if context is not None:
            context.progress(35, "正在写入本地 DuckDB 工作区")
        self._workspace.import_csv(preview.path, table_name, preview.options)
        if context is not None:
            context.progress(80, "正在读取表结构")
        columns = self._workspace.columns(table_name)
        row_count = self._workspace.row_count(table_name)
        handle = DatasetHandle(
            id=dataset_id,
            kind=DatasetKind.TABULAR,
            display_name=display_name or preview.path.name,
            source_path=preview.path,
            workspace_path=self._workspace.path,
            row_count=row_count,
            column_count=len(columns),
            import_options=preview.options.to_dict(),
            fingerprint=fingerprint,
            cache_key=table_name,
        )
        return TabularImportResult(handle=handle, table_name=table_name, columns=columns)
