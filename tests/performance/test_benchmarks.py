from __future__ import annotations

import json

from quick_insight.application.benchmarks import (
    BenchmarkSettings,
    generate_benchmark_csv,
    run_benchmark_suite,
    write_benchmark_reports,
)
from quick_insight.benchmarks import main as benchmark_main


def test_benchmark_csv_generation_is_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"

    generate_benchmark_csv(first, 12)
    generate_benchmark_csv(second, 12)

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    assert first.read_text(encoding="utf-8").splitlines()[0].startswith("record_id,event_time")
    assert len(first.read_text(encoding="utf-8").splitlines()) == 13


def test_benchmark_suite_writes_report_with_required_evidence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = run_benchmark_suite(
        BenchmarkSettings(
            row_counts=(40,),
            output_dir=tmp_path / "reports",
            workspace_root=tmp_path / "workspace",
            preview_limit=10,
        )
    )
    json_path, markdown_path = write_benchmark_reports(result)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert markdown_path.read_text(encoding="utf-8").startswith("# QuickInsight Benchmark Report")
    assert payload["schema_version"] == 1
    assert payload["machine"]["python_version"]
    case = payload["cases"][0]
    assert case["data_shape"]["rows"] == 40
    assert case["data_shape"]["columns"] == 8
    operations = {operation["name"]: operation for operation in case["operations"]}
    assert {
        "generate_csv",
        "preview_csv",
        "import_csv",
        "fetch_preview_page",
        "profile_table",
        "prepare_chart_data",
    }.issubset(operations)
    assert operations["fetch_preview_page"]["rendered_points"] == 10
    chart_operation = operations["prepare_chart_data"]
    assert chart_operation["rendered_points"] > 0
    assert chart_operation["peak_memory_method"] == "tracemalloc_python_allocations"
    assert "chart preparation" in chart_operation["query"]


def test_benchmark_cli_honors_output_arguments(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_dir = tmp_path / "custom-reports"
    workspace_dir = tmp_path / "custom-workspace"

    exit_code = benchmark_main(
        [
            "--rows",
            "8",
            "--output-dir",
            str(output_dir),
            "--workspace-dir",
            str(workspace_dir),
            "--skip-chart",
        ]
    )

    assert exit_code == 0
    assert list(output_dir.glob("benchmark-report-*.json"))
    assert list(workspace_dir.glob("tabular_8_*"))
