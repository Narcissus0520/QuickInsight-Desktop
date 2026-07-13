from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from quick_insight.application.jobs import JobContext
from quick_insight.domain.enums import DatasetKind
from quick_insight.domain.models import DatasetHandle
from quick_insight.infrastructure.csv_import import (
    CsvPreview,
    fingerprint_file,
    preview_delimited_file,
    table_name_for_fingerprint,
)
from quick_insight.infrastructure.tabular_files import (
    DataFramePreview,
    preview_excel_file,
    preview_parquet_file,
)
from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase

TabularPreview = CsvPreview | DataFramePreview


@dataclass(frozen=True)
class TabularImportResult:
    handle: DatasetHandle
    table_name: str
    columns: tuple[WorkspaceColumn, ...]


class TabularImportService:
    def __init__(
        self,
        workspace: WorkspaceDatabase,
        normalized_cache_dir: Path | None = None,
    ) -> None:
        self._workspace = workspace
        self._normalized_cache_dir = normalized_cache_dir or workspace.path.parent / "normalized"

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

    def preview_file(self, path: Path, *, preview_limit: int = 200) -> TabularPreview:
        suffix = path.suffix.lower()
        if suffix in {".csv", ".tsv", ".txt"}:
            return self.preview_csv(path, preview_limit=preview_limit)
        if suffix == ".parquet":
            return preview_parquet_file(path, preview_limit=preview_limit)
        if suffix in {".xlsx", ".xls", ".xlsb"}:
            return preview_excel_file(path, preview_limit=preview_limit)
        return self.preview_csv(path, preview_limit=preview_limit)

    def import_preview(
        self,
        preview: TabularPreview,
        *,
        display_name: str | None = None,
        context: JobContext | None = None,
    ) -> TabularImportResult:
        if isinstance(preview, CsvPreview):
            return self.import_csv(preview, display_name=display_name, context=context)
        if preview.file_format == "parquet":
            return self._import_parquet(preview, display_name=display_name, context=context)
        return self._import_excel(preview, display_name=display_name, context=context)

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
        table_name = table_name_for_fingerprint(fingerprint)
        if context is not None:
            context.progress(35, "正在写入本地 DuckDB 工作区")
        self._workspace.import_csv(preview.path, table_name, preview.options)
        if context is not None:
            context.progress(80, "正在读取表结构")
        return self._result_from_table(preview, display_name, fingerprint, table_name)

    def is_source_current(self, handle: DatasetHandle) -> bool:
        if handle.source_path is None or handle.fingerprint is None:
            return False
        if not handle.source_path.exists():
            return False
        return fingerprint_file(handle.source_path) == handle.fingerprint

    def normalized_cache_path(self, fingerprint: str) -> Path:
        return self._normalized_cache_dir / f"{fingerprint[:16]}.parquet"

    def _import_parquet(
        self,
        preview: DataFramePreview,
        *,
        display_name: str | None,
        context: JobContext | None,
    ) -> TabularImportResult:
        if context is not None:
            context.progress(10, "正在计算源文件指纹")
        fingerprint = fingerprint_file(preview.path)
        table_name = table_name_for_fingerprint(fingerprint)
        if context is not None:
            context.progress(35, "正在写入本地 DuckDB 工作区")
        self._workspace.import_parquet(preview.path, table_name)
        return self._result_from_table(preview, display_name, fingerprint, table_name)

    def _import_excel(
        self,
        preview: DataFramePreview,
        *,
        display_name: str | None,
        context: JobContext | None,
    ) -> TabularImportResult:
        if context is not None:
            context.progress(10, "正在计算源文件指纹")
        fingerprint = fingerprint_file(preview.path)
        table_name = table_name_for_fingerprint(fingerprint)
        if context is not None:
            context.progress(35, "正在读取 Excel 工作表")
        frame = pl.read_excel(
            preview.path,
            sheet_name=str(preview.options.get("sheet_name") or "Sheet1"),
            engine="calamine",
            has_header=True,
        )
        if context is not None:
            context.progress(70, "正在写入本地 DuckDB 工作区")
        self._workspace.import_polars_dataframe(frame, table_name)
        return self._result_from_table(preview, display_name, fingerprint, table_name)

    def _result_from_table(
        self,
        preview: TabularPreview,
        display_name: str | None,
        fingerprint: str,
        table_name: str,
    ) -> TabularImportResult:
        columns = self._workspace.columns(table_name)
        row_count = self._workspace.row_count(table_name)
        normalized_cache = self._write_normalized_cache(table_name, fingerprint)
        import_options = {
            **_preview_options(preview),
            "normalized_cache_path": str(normalized_cache),
        }
        handle = DatasetHandle(
            id=fingerprint[:16],
            kind=DatasetKind.TABULAR,
            display_name=display_name or preview.path.name,
            source_path=preview.path,
            workspace_path=self._workspace.path,
            row_count=row_count,
            column_count=len(columns),
            import_options=import_options,
            fingerprint=fingerprint,
            cache_key=str(normalized_cache),
        )
        return TabularImportResult(handle=handle, table_name=table_name, columns=columns)

    def _write_normalized_cache(self, table_name: str, fingerprint: str) -> Path:
        destination = self.normalized_cache_path(fingerprint)
        self._workspace.export_table_to_parquet(table_name, destination)
        return destination


def _preview_options(preview: TabularPreview) -> dict[str, object]:
    if isinstance(preview, CsvPreview):
        return preview.options.to_dict()
    return preview.options
