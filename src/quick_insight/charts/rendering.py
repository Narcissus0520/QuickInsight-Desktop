from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, cast

import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

from quick_insight.domain.models import ChartRecommendation, ChartSpec, PreparedChartDataset


@dataclass(frozen=True)
class PlotlyChartDocument:
    title: str
    figure: dict[str, Any]
    config: dict[str, Any]
    chart_spec: ChartSpec
    warnings: tuple[str, ...] = ()
    data_budget: dict[str, Any] = field(default_factory=dict)
    preparation: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1


def build_preview_document(recommendation: ChartRecommendation) -> PlotlyChartDocument:
    figure = _preview_figure(recommendation.spec)
    title = f"渲染器预览：{_chart_title(recommendation.spec.chart_type)}"
    _apply_common_layout(figure, title)
    preparation = {
        "original_rows": recommendation.data_budget.get("original_rows", 0),
        "rendered_rows": _preview_rendered_rows(recommendation.spec.chart_type),
        "method": "renderer_preview_static",
        "parameters": {"chart_type": recommendation.spec.chart_type},
        "approximate": True,
    }
    return PlotlyChartDocument(
        title=title,
        figure=plotly_figure_to_dict(figure),
        config=default_plotly_config(),
        chart_spec=recommendation.spec,
        warnings=(*recommendation.warnings, "chart_data_preparation_pending"),
        data_budget=dict(recommendation.data_budget),
        preparation=preparation,
    )


def build_prepared_document(
    recommendation: ChartRecommendation,
    prepared: PreparedChartDataset,
) -> PlotlyChartDocument:
    title = _chart_title(recommendation.spec.chart_type)
    figure = _prepared_figure(recommendation.spec, prepared)
    _apply_common_layout(figure, title)
    data_budget = {
        **recommendation.data_budget,
        "original_rows": prepared.original_rows,
        "rendered_rows": prepared.rendered_rows,
        "method": prepared.method,
        "approximate": prepared.approximate,
    }
    return PlotlyChartDocument(
        title=title,
        figure=plotly_figure_to_dict(figure),
        config=default_plotly_config(),
        chart_spec=recommendation.spec,
        warnings=recommendation.warnings,
        data_budget=data_budget,
        preparation=prepared.metadata(),
    )


def plotly_figure_to_dict(figure: go.Figure) -> dict[str, Any]:
    payload = json.loads(pio.to_json(figure, validate=True, remove_uids=True))
    if not isinstance(payload, dict):
        raise TypeError("Plotly figure JSON must be an object.")
    return cast(dict[str, Any], payload)


def default_plotly_config() -> dict[str, Any]:
    return {
        "displaylogo": False,
        "responsive": True,
        "scrollZoom": True,
        "modeBarButtonsToRemove": ["sendDataToCloud"],
        "toImageButtonOptions": {
            "format": "png",
            "filename": "quick-insight-chart-preview",
            "height": 720,
            "width": 1280,
            "scale": 2,
        },
    }


def build_plotly_html(
    document: PlotlyChartDocument,
    *,
    plotly_js: str | None = None,
) -> str:
    content_security_policy = (
        "default-src 'none'; "
        "script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; "
        "img-src data: blob:; "
        "font-src data:; "
        "connect-src 'none'; "
        "worker-src blob:; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-src 'none'; "
        "object-src 'none'; "
        "manifest-src 'none';"
    )
    plotly_source = _script_safe(plotly_js if plotly_js is not None else local_plotly_js())
    figure_json = _json_for_html(document.figure)
    config_json = _json_for_html(document.config)
    metadata_json = _json_for_html(
        {
            "schema_version": document.schema_version,
            "chart_spec": {
                "id": document.chart_spec.id,
                "chart_type": document.chart_spec.chart_type,
                "mappings": document.chart_spec.mappings,
                "aggregation": document.chart_spec.aggregation,
                "style": document.chart_spec.style,
                "schema_version": document.chart_spec.schema_version,
            },
            "warnings": document.warnings,
            "data_budget": document.data_budget,
            "preparation": document.preparation,
        }
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta
    http-equiv="Content-Security-Policy"
    content="{content_security_policy}"
  >
  <title>{_html_escape(document.title)}</title>
  <style>
    html, body {{
      width: 100%;
      height: 100%;
      margin: 0;
      background: #ffffff;
      color: #18212f;
      font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
      overflow: hidden;
    }}
    #chart-root {{
      display: grid;
      grid-template-rows: 1fr auto;
      width: 100vw;
      height: 100vh;
    }}
    #chart {{
      min-width: 0;
      min-height: 0;
    }}
    #status {{
      padding: 8px 12px;
      border-top: 1px solid #d8dee8;
      color: #5d6b7a;
      font-size: 12px;
      background: #f7f8fa;
    }}
  </style>
</head>
<body>
  <div id="chart-root">
    <div id="chart" role="img" aria-label="{_html_escape(document.title)}"></div>
    <div id="status">正在使用本地 Plotly 渲染图表...</div>
  </div>
  <script>{plotly_source}</script>
  <script id="quick-insight-figure" type="application/json">{figure_json}</script>
  <script id="quick-insight-config" type="application/json">{config_json}</script>
  <script id="quick-insight-metadata" type="application/json">{metadata_json}</script>
  <script>
  (function () {{
    "use strict";
    const figure = JSON.parse(document.getElementById("quick-insight-figure").textContent);
    const config = JSON.parse(document.getElementById("quick-insight-config").textContent);
    const metadata = JSON.parse(document.getElementById("quick-insight-metadata").textContent);
    const chart = document.getElementById("chart");
    const status = document.getElementById("status");
    function relayoutToContainer() {{
      Plotly.Plots.resize(chart);
    }}
    window.quickInsightChart = {{
      schemaVersion: metadata.schema_version,
      metadata: metadata,
      getFigure: function () {{
        return figure;
      }},
      resetView: function () {{
        Plotly.relayout(chart, {{
          "xaxis.autorange": true,
          "yaxis.autorange": true,
          "scene.camera": null
        }});
      }}
    }};
    Plotly.newPlot(chart, figure.data || [], figure.layout || {{}}, config)
      .then(function () {{
        status.textContent = "图表已使用本地 Plotly 渲染。";
        window.addEventListener("resize", relayoutToContainer);
        relayoutToContainer();
      }})
      .catch(function (error) {{
        const message = error && error.message ? error.message : error;
        status.textContent = "图表渲染失败：" + String(message);
      }});
  }}());
  </script>
</body>
</html>
"""


@lru_cache(maxsize=1)
def local_plotly_js() -> str:
    source = get_plotlyjs()
    if not isinstance(source, str) or "Plotly" not in source:
        raise RuntimeError("Local Plotly.js asset could not be loaded from the plotly package.")
    return source


def _preview_figure(spec: ChartSpec) -> go.Figure:
    chart_type = spec.chart_type
    mappings = spec.mappings
    x_title = mappings.get("x") or mappings.get("category") or "类别"
    y_title = mappings.get("y") or mappings.get("value") or "数值"

    if chart_type in {"line", "area"}:
        x_values = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
        y_values = [12, 18, 15, 24, 30]
        scatter = go.Scatter(
            x=x_values,
            y=y_values,
            mode="lines+markers",
            fill="tozeroy" if chart_type == "area" else None,
            name=y_title,
        )
        figure = go.Figure(data=[scatter])
        figure.update_xaxes(title_text=x_title)
        figure.update_yaxes(title_text=y_title)
        return figure

    if chart_type in {
        "bar",
        "text_category_bar",
        "text_classification_status_bar",
        "text_keyword_bar",
    }:
        figure = go.Figure(
            data=[
                go.Bar(
                    x=["A", "B", "C", "Other"],
                    y=[34, 27, 18, 9],
                    marker_color=["#2563eb", "#0f766e", "#9333ea", "#64748b"],
                    name=y_title,
                )
            ]
        )
        figure.update_xaxes(title_text=x_title)
        figure.update_yaxes(title_text="记录数" if chart_type.startswith("text_") else y_title)
        return figure

    if chart_type == "stacked_bar":
        figure = go.Figure(
            data=[
                go.Bar(x=["A", "B", "C"], y=[12, 18, 9], name="组 1"),
                go.Bar(x=["A", "B", "C"], y=[8, 11, 7], name="组 2"),
            ]
        )
        figure.update_layout(barmode="stack")
        figure.update_xaxes(title_text=x_title)
        figure.update_yaxes(title_text="记录数")
        return figure

    if chart_type == "box":
        figure = go.Figure(
            data=[
                go.Box(y=[8, 10, 12, 14, 17, 21], name="A"),
                go.Box(y=[6, 7, 10, 13, 19, 24], name="B"),
            ]
        )
        figure.update_yaxes(title_text=y_title)
        return figure

    if chart_type == "histogram":
        figure = go.Figure(data=[go.Histogram(x=[4, 5, 5, 6, 7, 7, 8, 10, 12], nbinsx=6)])
        figure.update_xaxes(title_text=y_title)
        figure.update_yaxes(title_text="频数")
        return figure

    if chart_type == "scatter":
        figure = go.Figure(
            data=[
                go.Scatter(
                    x=[1, 2, 3, 4, 5, 6],
                    y=[1.2, 2.1, 2.8, 4.4, 4.9, 6.2],
                    mode="markers",
                    marker={"size": 10, "color": "#2563eb"},
                )
            ]
        )
        figure.update_xaxes(title_text=x_title)
        figure.update_yaxes(title_text=y_title)
        return figure

    if chart_type in {
        "density_heatmap",
        "crosstab_heatmap",
        "correlation_heatmap",
        "text_source_category_heatmap",
        "text_category_keyword_heatmap",
        "text_tag_cooccurrence_heatmap",
    }:
        figure = go.Figure(
            data=[
                go.Heatmap(
                    z=[[1, 4, 2], [3, 2, 5], [2, 5, 4]],
                    x=["A", "B", "C"],
                    y=["组 1", "组 2", "组 3"],
                    colorscale="Blues",
                    colorbar={"title": "计数"},
                )
            ]
        )
        figure.update_xaxes(title_text=x_title)
        figure.update_yaxes(title_text=y_title)
        return figure

    if chart_type == "donut":
        return go.Figure(
            data=[
                go.Pie(
                    labels=["A", "B", "C"],
                    values=[45, 35, 20],
                    hole=0.45,
                    textinfo="label+percent",
                )
            ]
        )

    return go.Figure(data=[go.Bar(x=["A", "B", "C"], y=[3, 5, 4])])


def _prepared_figure(spec: ChartSpec, prepared: PreparedChartDataset) -> go.Figure:
    chart_type = spec.chart_type
    mappings = spec.mappings
    if chart_type in {"line", "area"}:
        x_values = _column_values(prepared, "x")
        y_values = _column_values(prepared, "y")
        figure = go.Figure(
            data=[
                go.Scatter(
                    x=x_values,
                    y=y_values,
                    mode="lines+markers",
                    fill="tozeroy" if chart_type == "area" else None,
                    name=mappings.get("y", "value"),
                    customdata=_optional_column_values(prepared, "source_count"),
                    hovertemplate="%{x}<br>%{y}<extra></extra>",
                )
            ]
        )
        figure.update_xaxes(title_text=mappings.get("x", "x"))
        figure.update_yaxes(title_text=mappings.get("y", "y"))
        return figure

    if chart_type in {
        "bar",
        "text_category_bar",
        "text_classification_status_bar",
        "text_keyword_bar",
    }:
        x_column = "category" if "category" in prepared.columns else "x"
        y_column = "value" if "value" in prepared.columns else "source_count"
        x_values = _column_values(prepared, x_column)
        y_values = _column_values(prepared, y_column)
        figure = go.Figure(
            data=[
                go.Bar(
                    x=x_values,
                    y=y_values,
                    customdata=_optional_column_values(prepared, "source_count"),
                    hovertemplate="%{x}<br>%{y}<br>rows=%{customdata}<extra></extra>",
                    marker_color="#2563eb",
                )
            ]
        )
        figure.update_xaxes(title_text=mappings.get("x", mappings.get("category", "category")))
        figure.update_yaxes(title_text=mappings.get("y", mappings.get("value", "value")))
        return figure

    if chart_type == "box":
        return _box_quantile_figure(prepared, mappings)

    if chart_type == "donut":
        return go.Figure(
            data=[
                go.Pie(
                    labels=_column_values(prepared, "category"),
                    values=_column_values(prepared, "source_count"),
                    hole=0.45,
                    textinfo="label+percent",
                )
            ]
        )

    if chart_type == "histogram":
        labels = [
            f"{_compact_number(row[0])} - {_compact_number(row[1])}"
            for row in prepared.rows
        ]
        figure = go.Figure(
            data=[
                go.Bar(
                    x=labels,
                    y=_column_values(prepared, "source_count"),
                    marker_color="#0f766e",
                )
            ]
        )
        figure.update_xaxes(title_text=mappings.get("x", "value"))
        figure.update_yaxes(title_text="count")
        return figure

    if chart_type == "scatter":
        scatter_class = go.Scattergl if prepared.rendered_rows > 10_000 else go.Scatter
        figure = go.Figure(
            data=[
                scatter_class(
                    x=_column_values(prepared, "x"),
                    y=_column_values(prepared, "y"),
                    mode="markers",
                    marker={"size": 6, "color": "#2563eb", "opacity": 0.72},
                )
            ]
        )
        figure.update_xaxes(title_text=mappings.get("x", "x"))
        figure.update_yaxes(title_text=mappings.get("y", "y"))
        return figure

    if chart_type in {
        "density_heatmap",
        "crosstab_heatmap",
        "text_source_category_heatmap",
        "text_category_keyword_heatmap",
        "text_tag_cooccurrence_heatmap",
    }:
        return _xyz_heatmap(prepared, mappings)

    if chart_type == "correlation_heatmap":
        return _xyz_heatmap(
            prepared,
            mappings,
            value_column="value",
            colorbar_title="correlation",
            colorscale="RdBu",
            zmin=-1.0,
            zmax=1.0,
            missing_value=None,
        )

    if chart_type == "stacked_bar":
        return _stacked_bar(prepared, mappings)

    return _preview_figure(spec)


def _apply_common_layout(figure: go.Figure, title: str) -> None:
    figure.update_layout(
        title=title,
        template="plotly_white",
        font={
            "family": "Microsoft YaHei UI, Microsoft YaHei, Segoe UI, sans-serif",
            "size": 13,
        },
        margin={"l": 48, "r": 24, "t": 64, "b": 48},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
    )


def _column_values(prepared: PreparedChartDataset, column: str) -> list[Any]:
    index = prepared.columns.index(column)
    return [_plotly_value(row[index]) for row in prepared.rows]


def _optional_column_values(prepared: PreparedChartDataset, column: str) -> list[Any] | None:
    if column not in prepared.columns:
        return None
    return _column_values(prepared, column)


def _box_quantile_figure(
    prepared: PreparedChartDataset,
    mappings: dict[str, str],
) -> go.Figure:
    figure = go.Figure()
    category_index = prepared.columns.index("category")
    lower_index = prepared.columns.index("lower_fence")
    q1_index = prepared.columns.index("q1")
    median_index = prepared.columns.index("median")
    q3_index = prepared.columns.index("q3")
    upper_index = prepared.columns.index("upper_fence")
    count_index = prepared.columns.index("source_count")
    for row in prepared.rows:
        figure.add_trace(
            go.Box(
                name=str(row[category_index]),
                q1=[_plotly_value(row[q1_index])],
                median=[_plotly_value(row[median_index])],
                q3=[_plotly_value(row[q3_index])],
                lowerfence=[_plotly_value(row[lower_index])],
                upperfence=[_plotly_value(row[upper_index])],
                boxpoints=False,
                customdata=[[row[count_index]]],
                hovertemplate=(
                    "%{fullData.name}<br>"
                    "Q1=%{q1}<br>Median=%{median}<br>Q3=%{q3}<br>"
                    "rows=%{customdata[0]}<extra></extra>"
                ),
            )
        )
    figure.update_xaxes(title_text=mappings.get("x", "category"))
    figure.update_yaxes(title_text=mappings.get("y", "value"))
    return figure


def _xyz_heatmap(
    prepared: PreparedChartDataset,
    mappings: dict[str, str],
    *,
    value_column: str = "source_count",
    colorbar_title: str = "count",
    colorscale: str = "Blues",
    zmin: float | None = None,
    zmax: float | None = None,
    missing_value: float | None = 0.0,
) -> go.Figure:
    x_values = _ordered_unique(_column_values(prepared, "x"))
    y_values = _ordered_unique(_column_values(prepared, "y"))
    counts: dict[tuple[Any, Any], float | None] = {}
    x_index = prepared.columns.index("x")
    y_index = prepared.columns.index("y")
    value_index = prepared.columns.index(value_column)
    for row in prepared.rows:
        raw_value = row[value_index]
        counts[(_plotly_value(row[x_index]), _plotly_value(row[y_index]))] = (
            None if raw_value is None else float(raw_value)
        )
    z_values = [
        [counts.get((x_value, y_value), missing_value) for x_value in x_values]
        for y_value in y_values
    ]
    heatmap_kwargs: dict[str, Any] = {}
    if zmin is not None:
        heatmap_kwargs["zmin"] = zmin
    if zmax is not None:
        heatmap_kwargs["zmax"] = zmax
    figure = go.Figure(
        data=[
            go.Heatmap(
                x=x_values,
                y=y_values,
                z=z_values,
                colorscale=colorscale,
                colorbar={"title": colorbar_title},
                **heatmap_kwargs,
            )
        ]
    )
    figure.update_xaxes(title_text=mappings.get("x", "x"))
    figure.update_yaxes(title_text=mappings.get("y", "y"))
    return figure


def _stacked_bar(prepared: PreparedChartDataset, mappings: dict[str, str]) -> go.Figure:
    x_values = _ordered_unique(_column_values(prepared, "x"))
    color_values = _ordered_unique(_column_values(prepared, "y"))
    x_index = prepared.columns.index("x")
    color_index = prepared.columns.index("y")
    count_index = prepared.columns.index("source_count")
    counts: dict[tuple[Any, Any], float] = {}
    for row in prepared.rows:
        counts[(_plotly_value(row[x_index]), _plotly_value(row[color_index]))] = float(
            row[count_index] or 0
        )
    figure = go.Figure()
    for color_value in color_values:
        figure.add_bar(
            x=x_values,
            y=[counts.get((x_value, color_value), 0.0) for x_value in x_values],
            name=str(color_value),
        )
    figure.update_layout(barmode="stack")
    figure.update_xaxes(title_text=mappings.get("x", "x"))
    figure.update_yaxes(title_text="count")
    return figure


def _ordered_unique(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _plotly_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _compact_number(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def _preview_rendered_rows(chart_type: str) -> int:
    if chart_type in {"density_heatmap", "crosstab_heatmap", "correlation_heatmap"}:
        return 9
    if chart_type == "donut":
        return 3
    return 6


def _chart_title(chart_type: str) -> str:
    return {
        "line": "折线图",
        "area": "面积图",
        "bar": "柱状图",
        "box": "箱线图",
        "histogram": "直方图",
        "scatter": "散点图",
        "density_heatmap": "密度热图",
        "crosstab_heatmap": "交叉热图",
        "stacked_bar": "堆叠柱状图",
        "correlation_heatmap": "相关性热图",
        "donut": "环形图",
        "text_category_bar": "文本类别计数图",
        "text_classification_status_bar": "分类状态图",
        "text_source_category_heatmap": "来源-类别热图",
        "text_keyword_bar": "关键词排行图",
        "text_category_keyword_heatmap": "类别-关键词热图",
        "text_tag_cooccurrence_heatmap": "标签共现热图",
    }.get(chart_type, chart_type)


def _json_for_html(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _script_safe(source: str) -> str:
    return source.replace("</script", "<\\/script")


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
