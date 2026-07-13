from __future__ import annotations

from quick_insight.charts import build_plotly_html, build_prepared_document, build_preview_document
from quick_insight.charts.rendering import PlotlyChartDocument
from quick_insight.domain.models import ChartRecommendation, ChartSpec, PreparedChartDataset


def test_plotly_html_uses_inline_local_script_and_escapes_json() -> None:
    spec = ChartSpec(
        id="chart",
        chart_type="bar",
        mappings={"x": "category</script>", "y": "amount"},
    )
    document = PlotlyChartDocument(
        title="预览 </script>",
        figure={
            "data": [{"type": "bar", "x": ["A"], "y": [1]}],
            "layout": {"title": {"text": "unsafe </script> title"}},
        },
        config={"responsive": True},
        chart_spec=spec,
    )
    html = build_plotly_html(
        document,
        plotly_js=(
            "window.Plotly={"
            "newPlot:function(){return Promise.resolve();},"
            "Plots:{resize:function(){}},"
            "relayout:function(){}};"
        ),
    )

    assert "<script src" not in html.lower()
    assert "https://" not in html
    assert "http://" not in html
    assert "connect-src 'none'" in html
    assert "unsafe </script> title" not in html
    assert "category</script>" not in html
    assert "\\u003c/script\\u003e" in html


def test_preview_document_uses_plotly_python_and_marks_data_pending() -> None:
    recommendation = ChartRecommendation(
        spec=ChartSpec(
            id="rec_bar",
            chart_type="bar",
            mappings={"category": "region", "value": "sales"},
            aggregation={"function": "mean"},
        ),
        score=88,
        reasons=("category_numeric_comparison",),
        data_budget={"original_rows": 120, "target_points": 30, "strategy": "top_n_with_other"},
    )

    document = build_preview_document(recommendation)

    assert document.schema_version == 1
    assert document.chart_spec.chart_type == "bar"
    assert document.figure["data"]
    assert document.config["responsive"] is True
    assert document.preparation["method"] == "renderer_preview_static"
    assert document.preparation["original_rows"] == 120
    assert "chart_data_preparation_pending" in document.warnings


def test_prepared_document_records_budget_and_uses_real_rows() -> None:
    recommendation = ChartRecommendation(
        spec=ChartSpec(
            id="rec_scatter",
            chart_type="scatter",
            mappings={"x": "speed", "y": "distance"},
        ),
        score=92,
        reasons=("two_numeric_relationship",),
        data_budget={"target_points": 2, "original_rows": 4},
    )
    prepared = PreparedChartDataset(
        columns=("x", "y"),
        rows=((1.0, 2.0), (3.0, 6.0)),
        original_rows=4,
        rendered_rows=2,
        method="uniform_sample",
        parameters={"target_points": 2},
        approximate=True,
    )

    document = build_prepared_document(recommendation, prepared)

    assert document.preparation["method"] == "uniform_sample"
    assert document.data_budget["rendered_rows"] == 2
    assert document.data_budget["approximate"] is True
    assert document.figure["data"][0]["x"] == [1.0, 3.0]
    assert "chart_data_preparation_pending" not in document.warnings
