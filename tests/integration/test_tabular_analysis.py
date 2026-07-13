from __future__ import annotations

from quick_insight.application.analysis import TabularAnalysisService
from quick_insight.application.importing import TabularImportService
from quick_insight.application.profiling import TabularProfiler
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_tabular_analysis_generates_trend_correlation_and_group_findings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "analysis.csv"
    source.write_text(
        "\n".join(
            [
                "date,category,revenue,cost",
                "2026-01-01,A,10,11",
                "2026-01-02,A,20,21",
                "2026-01-03,B,30,31",
                "2026-01-04,B,40,41",
                "2026-01-05,C,50,51",
                "2026-01-06,C,60,61",
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

    findings = TabularAnalysisService(workspace).analyze_table(
        import_result.table_name,
        profile,
    )
    methods = {finding.method for finding in findings}

    assert "duckdb_time_numeric_correlation_regr_slope" in methods
    assert "duckdb_pearson_correlation" in methods
    assert "duckdb_group_mean_difference" in methods
    correlation = next(
        finding for finding in findings if finding.method == "duckdb_pearson_correlation"
    )
    assert correlation.fields == ("revenue", "cost")
    assert correlation.evidence["pearson_correlation"] == 1.0
    assert "correlation_not_causation" in correlation.warnings
    trend = next(
        finding
        for finding in findings
        if finding.method == "duckdb_time_numeric_correlation_regr_slope"
    )
    assert trend.evidence["row_count"] == 6
    assert trend.evidence["time_column"] == "date"
    assert trend.evidence["pearson_correlation"] == 1.0
    group_difference = next(
        finding for finding in findings if finding.method == "duckdb_group_mean_difference"
    )
    assert group_difference.evidence["category_column"] == "category"
    assert group_difference.evidence["top_category"] == "C"
    assert group_difference.evidence["bottom_category"] == "A"
