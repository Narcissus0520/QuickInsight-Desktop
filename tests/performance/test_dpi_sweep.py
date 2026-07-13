from __future__ import annotations

import json
from datetime import UTC, datetime

from quick_insight.dpi_sweep import DpiSweepSuiteResult, write_dpi_sweep_reports
from quick_insight.ui.dpi_sweep import DpiSweepSettings, run_single_scale_sweep


def test_single_scale_dpi_sweep_captures_required_pages(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = run_single_scale_sweep(
        DpiSweepSettings(
            scale_factor=1.0,
            output_dir=tmp_path / "scale-100",
        )
    )

    assert result.passed, [check.to_dict() for check in result.checks if not check.passed]
    assert {page.name for page in result.pages} == {
        "welcome",
        "preview",
        "overview",
        "recommendations",
        "chart",
        "text_labeling",
    }
    assert all(page.screenshot_path.exists() for page in result.pages)
    assert all(page.screenshot_width >= 1366 for page in result.pages)
    assert all(page.screenshot_height >= 768 for page in result.pages)
    widget_names = {widget.object_name for widget in result.widgets}
    assert {"workspaceSplitter", "bottomStatus", "textLabelingScrollArea"}.issubset(widget_names)


def test_dpi_sweep_report_writes_required_evidence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    scale_result = run_single_scale_sweep(
        DpiSweepSettings(
            scale_factor=1.0,
            output_dir=tmp_path / "scale-100",
        )
    )
    suite = DpiSweepSuiteResult(
        generated_at=datetime.now(UTC),
        output_dir=tmp_path / "reports",
        machine={"platform": "test", "python_version": "3.13"},
        scales=(scale_result.to_dict(),),
    )

    json_path, markdown_path = write_dpi_sweep_reports(suite)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert markdown_path.read_text(encoding="utf-8").startswith("# QuickInsight DPI Sweep Report")
    assert payload["schema_version"] == 1
    assert payload["passed"] is True
    assert payload["scales"][0]["scale_factor"] == 1.0
    assert len(payload["scales"][0]["pages"]) == 6
    assert payload["scales"][0]["checks"]
