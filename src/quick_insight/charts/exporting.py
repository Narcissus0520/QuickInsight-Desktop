from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes

from quick_insight.charts.rendering import PlotlyChartDocument, build_plotly_html


class ChartExportFormat(StrEnum):
    HTML = "html"
    JSON = "json"
    SVG = "svg"
    PNG = "png"


@dataclass(frozen=True)
class ChartExportResult:
    path: Path
    format: ChartExportFormat
    warning_zh: str | None = None


def export_document_file(
    document: PlotlyChartDocument,
    destination: Path,
    export_format: ChartExportFormat,
) -> ChartExportResult:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if export_format is ChartExportFormat.HTML:
        destination.write_text(build_plotly_html(document), encoding="utf-8")
        return ChartExportResult(path=destination, format=export_format)
    if export_format is ChartExportFormat.JSON:
        destination.write_text(chart_document_json(document), encoding="utf-8")
        return ChartExportResult(path=destination, format=export_format)
    raise ValueError(f"Image export requires Plotly.toImage: {export_format.value}")


def chart_document_payload(document: PlotlyChartDocument) -> dict[str, Any]:
    return {
        "schema_version": document.schema_version,
        "title": document.title,
        "figure": document.figure,
        "config": document.config,
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


def chart_document_json(document: PlotlyChartDocument) -> str:
    return json.dumps(
        chart_document_payload(document),
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def build_to_image_script(export_format: ChartExportFormat) -> str:
    if export_format not in {ChartExportFormat.SVG, ChartExportFormat.PNG}:
        raise ValueError(f"Unsupported Plotly image format: {export_format.value}")
    return f"""
(function () {{
  "use strict";
  window.quickInsightExportResult = null;
  const chart = document.getElementById("chart");
  if (!window.Plotly || !chart) {{
    window.quickInsightExportResult = {{
      ok: false,
      error: "Plotly chart is not ready."
    }};
    return true;
  }}
  Plotly.toImage(chart, {{
    format: "{export_format.value}",
    width: 1280,
    height: 720,
    scale: {2 if export_format is ChartExportFormat.PNG else 1}
  }})
    .then(function (dataUrl) {{
      window.quickInsightExportResult = {{ ok: true, dataUrl: dataUrl }};
    }})
    .catch(function (error) {{
      const message = error && error.message ? error.message : String(error);
      window.quickInsightExportResult = {{ ok: false, error: message }};
    }});
  return true;
}}());
"""


def write_image_data_url(
    data_url: str,
    destination: Path,
    export_format: ChartExportFormat,
    *,
    document: PlotlyChartDocument,
) -> ChartExportResult:
    destination.parent.mkdir(parents=True, exist_ok=True)
    mime, encoded, is_base64 = _split_data_url(data_url)
    if export_format is ChartExportFormat.SVG:
        if mime != "image/svg+xml":
            raise ValueError(f"Expected SVG data URL, got {mime}")
        svg_bytes = base64.b64decode(encoded) if is_base64 else unquote_to_bytes(encoded)
        destination.write_text(
            svg_bytes.decode("utf-8"),
            encoding="utf-8",
        )
    elif export_format is ChartExportFormat.PNG:
        if mime != "image/png":
            raise ValueError(f"Expected PNG data URL, got {mime}")
        if not is_base64:
            raise ValueError("PNG export data URL must be base64 encoded.")
        destination.write_bytes(base64.b64decode(encoded))
    else:
        raise ValueError(f"Unsupported image export format: {export_format.value}")
    return ChartExportResult(
        path=destination,
        format=export_format,
        warning_zh=svg_vector_warning(document) if export_format is ChartExportFormat.SVG else None,
    )


def svg_vector_warning(document: PlotlyChartDocument) -> str | None:
    if any(_is_webgl_trace(trace) for trace in _figure_traces(document)):
        return "当前图表包含 WebGL trace，导出的 SVG 可能包含栅格化图像，无法保证完全矢量。"
    return None


def _figure_traces(document: PlotlyChartDocument) -> tuple[dict[str, Any], ...]:
    traces = document.figure.get("data", ())
    if not isinstance(traces, list):
        return ()
    return tuple(trace for trace in traces if isinstance(trace, dict))


def _is_webgl_trace(trace: dict[str, Any]) -> bool:
    trace_type = trace.get("type")
    return isinstance(trace_type, str) and trace_type.endswith("gl")


def _split_data_url(data_url: str) -> tuple[str, str, bool]:
    prefix, separator, encoded = data_url.partition(",")
    if separator != ",":
        raise ValueError("Image export did not return a data URL.")
    header = prefix.removeprefix("data:")
    parts = [part for part in header.split(";") if part]
    mime = parts[0] if parts else ""
    if not mime:
        raise ValueError("Image export data URL is missing a MIME type.")
    return mime, encoded, any(part.casefold() == "base64" for part in parts[1:])
