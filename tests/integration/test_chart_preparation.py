from __future__ import annotations

from quick_insight.application.chart_preparation import (
    TabularChartPreparationOptions,
    TabularChartPreparationService,
)
from quick_insight.application.importing import TabularImportService
from quick_insight.domain.models import ChartRecommendation, ChartSpec
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_bar_chart_preparation_uses_top_n_with_other(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text(
        "\n".join(
            [
                "category,amount",
                "A,10",
                "A,20",
                "A,30",
                "B,40",
                "B,50",
                "C,60",
                "D,70",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    import_result = TabularImportService(workspace).import_csv(
        TabularImportService(workspace).preview_csv(source)
    )
    recommendation = _recommendation(
        "bar",
        {"x": "category", "y": "amount"},
        target_points=2,
    )

    document = TabularChartPreparationService(workspace).prepare(
        import_result.table_name,
        recommendation,
    )

    assert document.preparation["method"] == "top_n_with_other"
    assert document.preparation["original_rows"] == 7
    assert document.preparation["rendered_rows"] == 3
    assert document.preparation["approximate"] is False
    assert document.figure["data"][0]["x"] == ["A", "B", "Other"]


def test_time_series_preparation_downsamples_to_budget(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "series.csv"
    lines = ["date,value"]
    for index in range(50):
        lines.append(f"2026-01-{(index % 28) + 1:02d},{index}")
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    import_result = service.import_csv(service.preview_csv(source))
    recommendation = _recommendation(
        "line",
        {"x": "date", "y": "value"},
        target_points=10,
    )

    document = TabularChartPreparationService(workspace).prepare(
        import_result.table_name,
        recommendation,
    )

    assert document.preparation["method"] == "time_window_mean"
    assert document.preparation["original_rows"] == 50
    assert document.preparation["rendered_rows"] <= 10
    assert len(document.figure["data"][0]["x"]) <= 10
    assert document.preparation["approximate"] is True


def test_scatter_preparation_uses_uniform_sample(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "points.csv"
    source.write_text(
        "x,y\n" + "\n".join(f"{index},{index * 2}" for index in range(25)) + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    import_result = service.import_csv(service.preview_csv(source))
    recommendation = _recommendation("scatter", {"x": "x", "y": "y"}, target_points=5)

    document = TabularChartPreparationService(workspace).prepare(
        import_result.table_name,
        recommendation,
    )

    assert document.preparation["method"] == "uniform_sample"
    assert document.preparation["rendered_rows"] <= 5
    assert document.preparation["approximate"] is True
    assert len(document.figure["data"][0]["x"]) <= 5


def test_density_and_histogram_preparation_bin_in_duckdb(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "binned.csv"
    source.write_text(
        "x,y\n" + "\n".join(f"{index},{index % 7}" for index in range(40)) + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    import_result = service.import_csv(service.preview_csv(source))
    preparer = TabularChartPreparationService(
        workspace,
        TabularChartPreparationOptions(
            histogram_bins=5,
            density_x_bins=4,
            density_y_bins=3,
        ),
    )

    histogram = preparer.prepare(
        import_result.table_name,
        _recommendation("histogram", {"x": "x"}),
    )
    density = preparer.prepare(
        import_result.table_name,
        _recommendation("density_heatmap", {"x": "x", "y": "y"}),
    )

    assert histogram.preparation["method"] == "histogram_bins"
    assert histogram.preparation["rendered_rows"] <= 5
    assert density.preparation["method"] == "density_2d_bins"
    assert density.preparation["rendered_rows"] <= 12
    assert density.figure["data"][0]["type"] == "heatmap"


def _recommendation(
    chart_type: str,
    mappings: dict[str, str],
    *,
    target_points: int = 30,
) -> ChartRecommendation:
    return ChartRecommendation(
        spec=ChartSpec(id=f"rec_{chart_type}", chart_type=chart_type, mappings=mappings),
        score=90,
        reasons=("test",),
        data_budget={"target_points": target_points, "original_rows": 0},
    )
