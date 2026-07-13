from __future__ import annotations

from quick_insight.application.importing import TabularImportService
from quick_insight.application.profiling import TabularProfiler
from quick_insight.domain.enums import ColumnSemanticType
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_tabular_profiler_builds_duckdb_backed_column_profiles(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "profile.csv"
    long_note = "这个客户反馈包含足够长的说明文本，用于触发长文本字段识别。" * 5
    source.write_text(
        "\n".join(
            [
                "id,category,amount,note,source",
                "A-001,alpha,10,short,email",
                f'A-002,beta,20,"{long_note}",email',
                "A-003,alpha,,short,web",
                "A-004,beta,30,another,web",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    import_result = service.import_preview(service.preview_file(source))

    profile = TabularProfiler(workspace).profile_table(
        import_result.handle.id,
        import_result.table_name,
    )
    profiles = {column.name: column for column in profile.column_profiles}

    assert profile.dataset_id == import_result.handle.id
    assert profile.row_count == 4
    assert profile.method == "duckdb_full_scan"
    assert profile.summary["column_count"] == 5
    assert profile.summary["semantic_type_counts"]["identifier"] == 1
    assert "candidate_identifier_columns" in profile.warnings
    assert "missing_values_present" in profile.warnings

    assert profiles["id"].semantic_type is ColumnSemanticType.IDENTIFIER
    assert "candidate_identifier" in profiles["id"].warnings
    assert profiles["category"].semantic_type is ColumnSemanticType.PRIMARY_CATEGORY
    assert profiles["category"].summary["top_values"] == (("alpha", 2), ("beta", 2))
    assert profiles["note"].semantic_type is ColumnSemanticType.LONG_TEXT
    assert profiles["source"].semantic_type is ColumnSemanticType.SOURCE_REFERENCE

    amount = profiles["amount"]
    assert amount.semantic_type is ColumnSemanticType.NUMERIC
    assert amount.null_count == 1
    assert amount.summary["min"] == 10
    assert amount.summary["max"] == 30
    assert amount.summary["mean"] == 20.0
    assert amount.summary["median"] == 20.0
