from __future__ import annotations

from quick_insight.application.chart_preparation import (
    TabularChartPreparationOptions,
    TabularChartPreparationService,
    TextChartPreparationService,
)
from quick_insight.application.importing import TabularImportService
from quick_insight.domain.models import Category, ChartRecommendation, ChartSpec, TextRecord
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


def test_box_and_correlation_preparation_use_duckdb_aggregates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "distributions.csv"
    source.write_text(
        "\n".join(
            [
                "category,a,b,c",
                "A,1,2,9",
                "A,3,6,7",
                "A,5,10,5",
                "B,10,1,4",
                "B,14,2,3",
                "B,18,3,2",
                "C,100,50,1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    import_result = service.import_csv(service.preview_csv(source))
    preparer = TabularChartPreparationService(workspace)

    box = preparer.prepare(
        import_result.table_name,
        _recommendation("box", {"x": "category", "y": "a"}, target_points=2),
    )
    correlation = preparer.prepare(
        import_result.table_name,
        _recommendation("correlation_heatmap", {"fields": "a,b,c"}),
    )

    assert box.preparation["method"] == "box_quantiles_top_n"
    assert box.preparation["rendered_rows"] == 2
    assert box.preparation["approximate"] is True
    assert box.figure["data"][0]["type"] == "box"
    assert correlation.preparation["method"] == "pearson_correlation_matrix"
    assert correlation.preparation["rendered_rows"] == 9
    assert correlation.figure["data"][0]["type"] == "heatmap"
    assert correlation.figure["data"][0]["z"][0][0] == 1.0


def test_text_chart_preparation_uses_persisted_text_tables(tmp_path) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    workspace.save_text_corpus(
        "corpus",
        (
            TextRecord(
                id="r1",
                content="install warning sensor",
                primary_category_id="bug",
                tags=("sensor", "warning"),
                source="log",
            ),
            TextRecord(
                id="r2",
                content="install failed warning",
                primary_category_id="bug",
                tags=("install", "warning"),
                source="ticket",
            ),
            TextRecord(
                id="r3",
                content="feature request install",
                primary_category_id="feature",
                tags=("install", "ux"),
                source="ticket",
            ),
            TextRecord(
                id="r4",
                content="uncategorized warning",
                tags=("warning", "ux"),
            ),
        ),
        (
            Category(id="bug", name="Bug"),
            Category(id="feature", name="Feature"),
        ),
    )
    preparer = TextChartPreparationService(workspace)

    category = preparer.prepare("corpus", _recommendation("text_category_bar", {}))
    status = preparer.prepare("corpus", _recommendation("text_classification_status_bar", {}))
    source_category = preparer.prepare(
        "corpus",
        _recommendation("text_source_category_heatmap", {}),
    )
    keyword = preparer.prepare(
        "corpus",
        _recommendation(
            "text_keyword_bar",
            {},
            aggregation={"keywords": ("install", "warning")},
        ),
    )
    category_keyword = preparer.prepare(
        "corpus",
        _recommendation(
            "text_category_keyword_heatmap",
            {},
            aggregation={"keywords": ("install", "warning")},
        ),
    )
    tag_heatmap = preparer.prepare("corpus", _recommendation("text_tag_cooccurrence_heatmap", {}))

    assert category.preparation["method"] == "text_category_counts_top_n"
    assert sum(category.figure["data"][0]["y"]) == 4
    assert status.preparation["method"] == "text_classification_status_counts"
    assert status.figure["data"][0]["y"] == [3, 1]
    assert source_category.preparation["method"] == "text_source_category_crosstab"
    assert source_category.figure["data"][0]["type"] == "heatmap"
    assert keyword.preparation["method"] == "text_keyword_counts"
    assert set(keyword.figure["data"][0]["x"]) == {"install", "warning"}
    assert category_keyword.preparation["method"] == "text_category_keyword_counts"
    assert category_keyword.figure["data"][0]["type"] == "heatmap"
    assert tag_heatmap.preparation["method"] == "text_tag_cooccurrence_counts"
    assert tag_heatmap.figure["data"][0]["type"] == "heatmap"


def _recommendation(
    chart_type: str,
    mappings: dict[str, str],
    *,
    target_points: int = 30,
    aggregation: dict[str, object] | None = None,
) -> ChartRecommendation:
    return ChartRecommendation(
        spec=ChartSpec(
            id=f"rec_{chart_type}",
            chart_type=chart_type,
            mappings=mappings,
            aggregation=aggregation or {},
        ),
        score=90,
        reasons=("test",),
        data_budget={"target_points": target_points, "original_rows": 0},
    )
