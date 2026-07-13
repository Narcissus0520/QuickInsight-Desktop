from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import polars as pl

from quick_insight.application.errors import UserFacingError

TabularFileFormat = Literal["excel", "parquet"]


@dataclass(frozen=True)
class DataFramePreview:
    path: Path
    file_format: TabularFileFormat
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    options: dict[str, object]
    total_preview_rows: int
    warnings: tuple[str, ...] = ()


def preview_parquet_file(path: Path, *, preview_limit: int = 200) -> DataFramePreview:
    source = _resolve_existing_file(path, "Parquet")
    try:
        frame = pl.read_parquet(source, n_rows=preview_limit)
    except Exception as exc:
        raise UserFacingError(
            code="IMPORT_PARQUET_PREVIEW_FAILED",
            title_zh="无法预览 Parquet 文件",
            message_zh="文件可能已损坏，或不是有效的 Parquet 数据。",
            next_action_zh="请确认文件可被本地工具打开后重试。",
            technical_detail=str(exc),
        ) from exc
    return _preview_from_frame(
        source,
        frame,
        file_format="parquet",
        options={"format": "parquet", "preview_limit": preview_limit},
    )


def preview_excel_file(
    path: Path,
    *,
    sheet_name: str | None = None,
    preview_limit: int = 200,
) -> DataFramePreview:
    source = _resolve_existing_file(path, "Excel")
    try:
        frame_or_sheets = pl.read_excel(
            source,
            sheet_name=sheet_name,
            engine="calamine",
            has_header=True,
        )
    except Exception as exc:
        raise UserFacingError(
            code="IMPORT_EXCEL_PREVIEW_FAILED",
            title_zh="无法预览 Excel 文件",
            message_zh="文件可能为空、受保护、损坏，或不是支持的 XLS/XLSX/XLSB 格式。",
            next_action_zh="请确认工作簿可打开，并选择包含表头的数据工作表。",
            technical_detail=str(exc),
        ) from exc
    selected_sheet, frame = sheet_name or "Sheet1", frame_or_sheets
    return _preview_from_frame(
        source,
        frame.head(preview_limit),
        file_format="excel",
        options={
            "format": "excel",
            "engine": "calamine",
            "sheet_name": selected_sheet,
            "preview_limit": preview_limit,
        },
    )


def _resolve_existing_file(path: Path, label: str) -> Path:
    source = path.expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise UserFacingError(
            code="IMPORT_SOURCE_NOT_FOUND",
            title_zh="找不到文件",
            message_zh=f"请选择一个存在的 {label} 文件。",
            next_action_zh="检查文件路径后重新选择。",
            technical_detail=str(source),
        )
    return source


def _preview_from_frame(
    path: Path,
    frame: pl.DataFrame,
    *,
    file_format: TabularFileFormat,
    options: dict[str, object],
) -> DataFramePreview:
    columns = tuple(str(column) for column in frame.columns)
    rows = tuple(
        tuple("" if value is None else str(value) for value in row)
        for row in frame.iter_rows()
    )
    warnings = ("文件没有可预览的数据行。",) if frame.height == 0 else ()
    return DataFramePreview(
        path=path,
        file_format=file_format,
        columns=columns,
        rows=rows,
        options=options,
        total_preview_rows=len(rows),
        warnings=warnings,
    )
