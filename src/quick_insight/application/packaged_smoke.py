from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from quick_insight.application.chart_preparation import TabularChartPreparationService
from quick_insight.application.importing import TabularImportService
from quick_insight.application.profiling import TabularProfiler
from quick_insight.charts.recommendation import ChartRecommendationEngine
from quick_insight.charts.rendering import build_plotly_html
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def run_packaged_workflow_smoke(result_path: Path) -> int:
    try:
        payload = _run_workflow_smoke()
    except Exception as exc:
        payload = {
            "schema_version": 1,
            "passed": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    _write_result(result_path, payload)
    return 0 if payload["passed"] is True else 1


def _run_workflow_smoke() -> dict[str, object]:
    with TemporaryDirectory(prefix="quick-insight-package-smoke-") as temporary_dir:
        root = Path(temporary_dir)
        source = root / "workflow-smoke.csv"
        source.write_text(
            "category,value\n"
            "north,12\n"
            "north,16\n"
            "south,7\n"
            "south,9\n"
            "east,20\n"
            "east,22\n",
            encoding="utf-8",
        )
        workspace = WorkspaceDatabase(root / "workflow.duckdb")
        importing = TabularImportService(workspace, normalized_cache_dir=root / "normalized")
        imported = importing.import_csv(importing.preview_csv(source))
        profile = TabularProfiler(workspace).profile_table(
            imported.handle.id,
            imported.table_name,
            import_options=imported.handle.import_options,
        )
        recommendations = ChartRecommendationEngine().recommend(profile)
        recommendation = next(
            (item for item in recommendations if item.spec.chart_type == "bar"),
            None,
        )
        if recommendation is None:
            raise RuntimeError("The workflow smoke did not receive a bar-chart recommendation.")
        document = TabularChartPreparationService(workspace).prepare(
            imported.table_name,
            recommendation,
        )
        html = build_plotly_html(document)
        if "quickInsightChart" not in html or "connect-src 'none'" not in html:
            raise RuntimeError("The workflow smoke generated an invalid offline chart document.")
        return {
            "schema_version": 1,
            "passed": True,
            "source_rows": imported.handle.row_count,
            "chart_type": document.chart_spec.chart_type,
            "rendered_rows": document.data_budget.get("rendered_rows"),
            "html_bytes": len(html.encode("utf-8")),
        }


def _write_result(result_path: Path, payload: dict[str, object]) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = result_path.with_suffix(result_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(result_path)
