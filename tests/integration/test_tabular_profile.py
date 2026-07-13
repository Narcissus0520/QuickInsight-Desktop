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


def test_tabular_profiler_reports_quality_findings_and_parse_failures(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "quality.csv"
    source.write_text(
        "\n".join(
            [
                "id,category,amount,status,mixed,created_at",
                "A-001,alpha,10,active,100,2026-01-01",
                "A-002,beta,11,active,101,2026-01-02",
                "A-003,alpha,,active,N/A,2026-01-03",
                "A-004,beta,12,active,102,2026-01-04",
                "A-005,gamma,13,active,103,2026-01-05",
                "A-006,gamma,14,active,note,2026-01-06",
                "A-007,delta,15,active,105,2026-01-07",
                "A-008,delta,16,active,106,2026-01-08",
                "A-009,epsilon,100,active,107,2026-01-09",
                "A-009,epsilon,100,active,107,2026-01-09",
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
        import_options=import_result.handle.import_options,
    )
    profiles = {column.name: column for column in profile.column_profiles}
    quality = profile.summary["quality"]
    parse_failures = profile.summary["parse_failures"]
    time_ranges = profile.summary["time_ranges"]

    assert quality["duplicate_row_count"] == 1
    assert quality["total_missing_values"] == 1
    assert quality["columns_with_missing_values"] == {"amount": 1}
    assert quality["constant_columns"] == ("status",)
    assert quality["mixed_type_columns"] == ("mixed",)
    assert quality["numeric_outlier_columns"] == {"amount": 2}
    assert parse_failures["reported"] is True
    assert parse_failures["count"] == 0
    assert parse_failures["method"] == "import_options"
    assert str(time_ranges["created_at"]["min"]) == "2026-01-01"
    assert str(time_ranges["created_at"]["max"]) == "2026-01-09"

    assert "duplicate_rows_present" in profile.warnings
    assert "constant_columns_present" in profile.warnings
    assert "mixed_type_values_present" in profile.warnings
    assert "numeric_outlier_candidates_present" in profile.warnings
    assert profiles["amount"].summary["outlier_count"] == 2
    assert profiles["mixed"].summary["numeric_like_count"] == 8
    assert {finding.method for finding in profile.findings} >= {
        "duckdb_group_by_all_columns",
        "duckdb_column_null_counts",
        "distinct_count_equals_one",
        "duckdb_try_cast_numeric_datetime_counts",
        "iqr_1_5_full_scan",
    }
