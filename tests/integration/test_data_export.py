from __future__ import annotations

import csv
import json

import polars as pl
import pytest

from quick_insight.application.data_export import DataExportFormat, ProcessedDataExportService
from quick_insight.application.errors import UserFacingError
from quick_insight.application.importing import TabularImportService
from quick_insight.application.text_corpus import TextCorpusService, TextImportOptions
from quick_insight.application.transforms import TabularTransformService
from quick_insight.domain.models import TransformStep
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_export_processed_tabular_csv_and_parquet_without_overwrite(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text(
        "\n".join(
            [
                "region,amount,status",
                "North,10,open",
                "South,20,closed",
                "East,5,open",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    import_service = TabularImportService(workspace)
    imported = import_service.import_csv(import_service.preview_csv(source))
    transformed = TabularTransformService(workspace).preview_transform(
        imported.table_name,
        (
            TransformStep(
                id="filter_open",
                operation="filter_rows",
                parameters={"expression": {"column": "status", "op": "==", "value": "open"}},
                reversible=False,
            ),
            TransformStep(
                id="select_columns",
                operation="select_columns",
                parameters={
                    "columns": [
                        {"source": "region", "alias": "region"},
                        {"source": "amount", "alias": "amount"},
                    ]
                },
                reversible=False,
            ),
        ),
        destination_table="sales_open_export",
    )
    exporter = ProcessedDataExportService(workspace)
    csv_path = tmp_path / "processed.csv"
    parquet_path = tmp_path / "processed.parquet"

    csv_result = exporter.export_tabular(transformed.table_name, csv_path, DataExportFormat.CSV)
    parquet_result = exporter.export_tabular(
        transformed.table_name,
        parquet_path,
        DataExportFormat.PARQUET,
    )

    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert csv_result.row_count == 2
    assert csv_result.bytes_written > 0
    assert rows == [
        {"region": "North", "amount": "10"},
        {"region": "East", "amount": "5"},
    ]
    assert parquet_result.row_count == 2
    assert pl.read_parquet(parquet_path).to_dicts() == [
        {"region": "North", "amount": 10},
        {"region": "East", "amount": 5},
    ]
    with pytest.raises(UserFacingError) as exc_info:
        exporter.export_tabular(transformed.table_name, csv_path, DataExportFormat.CSV)
    assert exc_info.value.code == "DATA_EXPORT_DESTINATION_EXISTS"


def test_export_text_corpus_jsonl_and_csv(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TextCorpusService(workspace)
    imported = service.import_preview(
        service.preview_text(
            "第一条反馈\n第二条反馈",
            display_name="文本导出测试",
            options=TextImportOptions(
                default_category="体验",
                default_tags=("安装", "新手"),
                default_source="访谈",
            ),
        )
    )
    exporter = ProcessedDataExportService(workspace)
    jsonl_path = tmp_path / "records.jsonl"
    csv_path = tmp_path / "records.csv"

    jsonl_result = exporter.export_text_corpus(
        imported.handle.cache_key or "",
        jsonl_path,
        DataExportFormat.JSONL,
    )
    csv_result = exporter.export_text_corpus(
        imported.handle.cache_key or "",
        csv_path,
        DataExportFormat.CSV,
    )

    payloads = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert jsonl_result.row_count == 2
    assert jsonl_result.bytes_written > 0
    payload_by_content = {payload["content"]: payload for payload in payloads}
    assert set(payload_by_content) == {"第一条反馈", "第二条反馈"}
    assert payload_by_content["第一条反馈"]["primary_category"] == "体验"
    assert payload_by_content["第一条反馈"]["tags"] == ["安装", "新手"]
    assert payload_by_content["第一条反馈"]["source"] == "访谈"

    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert csv_result.row_count == 2
    row_by_content = {row["content"]: row for row in rows}
    assert set(row_by_content) == {"第一条反馈", "第二条反馈"}
    assert row_by_content["第一条反馈"]["primary_category"] == "体验"
    assert row_by_content["第一条反馈"]["tags"] == "安装, 新手"
    assert row_by_content["第一条反馈"]["source"] == "访谈"
