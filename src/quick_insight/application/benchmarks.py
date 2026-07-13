from __future__ import annotations

import csv
import json
import os
import platform
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from quick_insight import __version__
from quick_insight.application.chart_preparation import TabularChartPreparationService
from quick_insight.application.importing import TabularImportService
from quick_insight.application.profiling import TabularProfiler
from quick_insight.charts import ChartRecommendationEngine
from quick_insight.infrastructure.workspace import WorkspaceDatabase

_REGIONS = ("华北", "华东", "华南", "西南", "西北", "东北")
_CHANNELS = ("线上", "门店", "代理", "项目")
_STATUSES = ("正常", "复核", "延迟", "异常")


@dataclass(frozen=True)
class BenchmarkSettings:
    row_counts: tuple[int, ...]
    output_dir: Path
    workspace_root: Path
    run_chart_preparation: bool = True
    preview_limit: int = 200
    schema_version: int = 1


@dataclass(frozen=True)
class BenchmarkOperationResult:
    name: str
    elapsed_ms: float
    peak_memory_bytes: int
    peak_memory_method: str
    query: str
    rendered_points: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "peak_memory_bytes": self.peak_memory_bytes,
            "peak_memory_method": self.peak_memory_method,
            "query": self.query,
        }
        if self.rendered_points is not None:
            payload["rendered_points"] = self.rendered_points
        return payload


@dataclass(frozen=True)
class BenchmarkCaseResult:
    name: str
    row_count: int
    column_count: int
    source_path: Path
    source_size_bytes: int
    workspace_path: Path
    operations: tuple[BenchmarkOperationResult, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "data_shape": {
                "rows": self.row_count,
                "columns": self.column_count,
                "source_size_bytes": self.source_size_bytes,
            },
            "source_path": str(self.source_path),
            "workspace_path": str(self.workspace_path),
            "operations": [operation.to_dict() for operation in self.operations],
        }


@dataclass(frozen=True)
class BenchmarkSuiteResult:
    generated_at: datetime
    machine: dict[str, object]
    cases: tuple[BenchmarkCaseResult, ...]
    output_dir: Path
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "app_version": __version__,
            "machine": self.machine,
            "cases": [case.to_dict() for case in self.cases],
        }


def run_benchmark_suite(settings: BenchmarkSettings) -> BenchmarkSuiteResult:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC)
    cases = tuple(
        _run_tabular_case(
            row_count=row_count,
            settings=settings,
        )
        for row_count in settings.row_counts
    )
    return BenchmarkSuiteResult(
        generated_at=generated_at,
        machine=_machine_details(),
        cases=cases,
        output_dir=settings.output_dir,
    )


def write_benchmark_reports(result: BenchmarkSuiteResult) -> tuple[Path, Path]:
    result.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = result.generated_at.strftime("%Y%m%dT%H%M%SZ")
    json_path = result.output_dir / f"benchmark-report-{timestamp}.json"
    markdown_path = result.output_dir / f"benchmark-report-{timestamp}.md"
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_benchmark_markdown(result), encoding="utf-8")
    return json_path, markdown_path


def generate_benchmark_csv(path: Path, row_count: int) -> None:
    if row_count <= 0:
        raise ValueError("row_count must be positive.")
    path.parent.mkdir(parents=True, exist_ok=True)
    start_time = datetime(2026, 1, 1)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "record_id",
                "event_time",
                "region",
                "channel",
                "revenue",
                "temperature",
                "defect_count",
                "status",
            ]
        )
        for index in range(row_count):
            writer.writerow(
                [
                    index + 1,
                    (start_time + timedelta(minutes=index)).isoformat(),
                    _REGIONS[index % len(_REGIONS)],
                    _CHANNELS[(index // 3) % len(_CHANNELS)],
                    round(50 + ((index * 17) % 10_000) / 10, 2),
                    round(18 + ((index * 13) % 450) / 10, 2),
                    (index * 19) % 11,
                    _STATUSES[(index // 11) % len(_STATUSES)],
                ]
            )


def _run_tabular_case(row_count: int, settings: BenchmarkSettings) -> BenchmarkCaseResult:
    case_name = f"tabular_{row_count}"
    case_dir = settings.workspace_root / f"{case_name}_{uuid4().hex[:8]}"
    case_dir.mkdir(parents=True, exist_ok=True)
    source_path = case_dir / "source.csv"
    workspace_path = case_dir / "workspace.duckdb"
    workspace = WorkspaceDatabase(workspace_path)
    import_service = TabularImportService(
        workspace,
        normalized_cache_dir=case_dir / "normalized",
    )
    operations: list[BenchmarkOperationResult] = []

    _, operation = _measure_operation(
        "generate_csv",
        "deterministic csv writer",
        lambda: generate_benchmark_csv(source_path, row_count),
    )
    operations.append(operation)

    preview, operation = _measure_operation(
        "preview_csv",
        f"preview_delimited_file(limit={settings.preview_limit})",
        lambda: import_service.preview_csv(source_path, preview_limit=settings.preview_limit),
    )
    operations.append(operation)

    imported, operation = _measure_operation(
        "import_csv",
        "DuckDB CSV import plus normalized Parquet cache",
        lambda: import_service.import_preview(preview, display_name=case_name),
    )
    operations.append(operation)

    page_rows, operation = _measure_operation(
        "fetch_preview_page",
        f"SELECT * FROM {imported.table_name} LIMIT {settings.preview_limit} OFFSET 0",
        lambda: workspace.fetch_page(
            imported.table_name,
            limit=settings.preview_limit,
            offset=0,
        ),
    )
    operations.append(replace(operation, rendered_points=len(page_rows)))

    profile, operation = _measure_operation(
        "profile_table",
        "DuckDB full-scan profile_table",
        lambda: TabularProfiler(workspace).profile_table(
            imported.handle.id,
            imported.table_name,
            import_options=imported.handle.import_options,
        ),
    )
    operations.append(operation)

    if settings.run_chart_preparation:
        recommendations = ChartRecommendationEngine().recommend(profile)
        if recommendations:
            recommendation = recommendations[0]
            document, operation = _measure_operation(
                "prepare_chart_data",
                f"{recommendation.spec.chart_type} chart preparation",
                lambda: TabularChartPreparationService(workspace).prepare(
                    imported.table_name,
                    recommendation,
                ),
            )
            rendered_points = document.preparation.get("rendered_rows")
            operations.append(
                replace(
                    operation,
                    rendered_points=rendered_points if isinstance(rendered_points, int) else None,
                    query=(
                        f"{operation.query}; method={document.preparation.get('method', '')}"
                    ),
                )
            )

    return BenchmarkCaseResult(
        name=case_name,
        row_count=row_count,
        column_count=len(imported.columns),
        source_path=source_path,
        source_size_bytes=source_path.stat().st_size,
        workspace_path=workspace_path,
        operations=tuple(operations),
    )


def _measure_operation[T](
    name: str,
    query: str,
    work: Callable[[], T],
) -> tuple[T, BenchmarkOperationResult]:
    tracemalloc.start()
    started = time.perf_counter()
    try:
        value = work()
        elapsed_ms = (time.perf_counter() - started) * 1000
        _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return value, BenchmarkOperationResult(
        name=name,
        elapsed_ms=elapsed_ms,
        peak_memory_bytes=peak_bytes,
        peak_memory_method="tracemalloc_python_allocations",
        query=query,
    )


def _machine_details() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count() or 0,
    }


def _benchmark_markdown(result: BenchmarkSuiteResult) -> str:
    lines = [
        "# QuickInsight Benchmark Report",
        "",
        f"Generated: {result.generated_at.isoformat()}",
        f"App version: {__version__}",
        "",
        "## Machine",
        "",
    ]
    for key, value in result.machine.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Cases", ""])
    for case in result.cases:
        lines.append(
            f"### {case.name}: {case.row_count} rows x {case.column_count} columns"
        )
        lines.append(f"- Source size: {case.source_size_bytes} bytes")
        lines.append(f"- Workspace: `{case.workspace_path}`")
        lines.append("")
        lines.append("| Operation | Elapsed ms | Peak memory bytes | Rendered points | Query |")
        lines.append("| --- | ---: | ---: | ---: | --- |")
        for operation in case.operations:
            rendered_points = (
                str(operation.rendered_points)
                if operation.rendered_points is not None
                else ""
            )
            lines.append(
                "| "
                f"{operation.name} | "
                f"{operation.elapsed_ms:.3f} | "
                f"{operation.peak_memory_bytes} | "
                f"{rendered_points} | "
                f"{operation.query} |"
            )
        lines.append("")
    return "\n".join(lines)
