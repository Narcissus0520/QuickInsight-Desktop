from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from quick_insight.charts.exporting import (
    ChartExportFormat,
    ChartExportResult,
    build_to_image_script,
    export_document_file,
    write_image_data_url,
)
from quick_insight.charts.rendering import PlotlyChartDocument, build_plotly_html

ExportCallback = Callable[[ChartExportResult | Exception], None]


class OfflineChartRequestInterceptor(QWebEngineUrlRequestInterceptor):
    blocked = Signal(str)

    _allowed_schemes = frozenset({"about", "blob", "data", "file", "qrc"})

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl()
        scheme = url.scheme().lower()
        if scheme in self._allowed_schemes:
            return
        info.block(True)
        self.blocked.emit(url.toString())


class OfflineChartWebView(QWebEngineView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("offlineChartWebView")
        self._profile = QWebEngineProfile(self)
        self._interceptor = OfflineChartRequestInterceptor(self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)
        self.setPage(QWebEnginePage(self._profile, self._profile))


class PlotlyChartView(QWidget):
    chart_loaded = Signal(bool)
    export_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plotlyChartView")
        self._last_html = ""
        self._document: PlotlyChartDocument | None = None
        self._pending_export: tuple[ChartExportFormat, Path, ExportCallback, int] | None = None
        self._title_label = QLabel("尚未生成图表")
        self._title_label.setObjectName("chartTitleLabel")
        self._status_label = QLabel("从推荐卡片点击生成后，将在这里载入本地 Plotly 图表。")
        self._status_label.setObjectName("chartStatusLabel")
        self._status_label.setWordWrap(True)
        self._warning_label = QLabel("图表数据准备、导出和编辑将在 M4 后续切片接入。")
        self._warning_label.setObjectName("chartWarningLabel")
        self._warning_label.setWordWrap(True)
        self._web_view = OfflineChartWebView(self)
        self._reset_button = QPushButton("重置视图")
        self._reset_button.setObjectName("chartResetButton")
        self._reset_button.clicked.connect(self.reset_view)
        self._export_html_button = QPushButton("导出 HTML")
        self._export_html_button.setObjectName("chartExportHtmlButton")
        self._export_svg_button = QPushButton("导出 SVG")
        self._export_svg_button.setObjectName("chartExportSvgButton")
        self._export_png_button = QPushButton("导出 PNG")
        self._export_png_button.setObjectName("chartExportPngButton")
        self._export_json_button = QPushButton("导出 JSON")
        self._export_json_button.setObjectName("chartExportJsonButton")
        for export_format, button in (
            (ChartExportFormat.HTML, self._export_html_button),
            (ChartExportFormat.SVG, self._export_svg_button),
            (ChartExportFormat.PNG, self._export_png_button),
            (ChartExportFormat.JSON, self._export_json_button),
        ):
            button.clicked.connect(
                lambda _checked=False, fmt=export_format: self.export_requested.emit(fmt.value)
            )

        header = QFrame()
        header.setObjectName("chartHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addWidget(self._title_label, stretch=1)
        header_layout.addWidget(self._export_html_button)
        header_layout.addWidget(self._export_svg_button)
        header_layout.addWidget(self._export_png_button)
        header_layout.addWidget(self._export_json_button)
        header_layout.addWidget(self._reset_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(header)
        layout.addWidget(self._status_label)
        layout.addWidget(self._warning_label)
        layout.addWidget(self._web_view, stretch=1)

        self._web_view.loadFinished.connect(self._on_load_finished)

    @property
    def last_html(self) -> str:
        return self._last_html

    @property
    def current_document(self) -> PlotlyChartDocument | None:
        return self._document

    def render_document(self, document: PlotlyChartDocument) -> None:
        self._document = document
        self._title_label.setText(document.title)
        self._status_label.setText("正在载入本地 Plotly 图表...")
        self._warning_label.setText(_warning_text(document))
        self._last_html = build_plotly_html(document)
        if os.environ.get("QT_QPA_PLATFORM", "").casefold() == "offscreen":
            self._status_label.setText("本地 Plotly HTML 已生成；offscreen 测试未加载 WebEngine。")
            self.chart_loaded.emit(True)
            return
        self._web_view.setHtml(self._last_html, QUrl("qrc:/quick-insight/charts/"))

    def export_document(
        self,
        export_format: ChartExportFormat,
        destination: Path,
        callback: ExportCallback,
    ) -> None:
        document = self._document
        if document is None:
            callback(RuntimeError("No chart document has been rendered."))
            return
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if export_format in {ChartExportFormat.HTML, ChartExportFormat.JSON}:
                callback(export_document_file(document, destination, export_format))
                return
            if os.environ.get("QT_QPA_PLATFORM", "").casefold() == "offscreen":
                callback(
                    RuntimeError(
                        "SVG/PNG export requires a loaded QWebEngineView; offscreen tests "
                        "only validate HTML/JSON export."
                    )
                )
                return
            self._pending_export = (export_format, destination, callback, 0)
            self._web_view.page().runJavaScript(build_to_image_script(export_format))
            QTimer.singleShot(50, self._poll_image_export)
        except Exception as exc:
            callback(exc)

    def reset_view(self) -> None:
        self._web_view.page().runJavaScript(
            "window.quickInsightChart && window.quickInsightChart.resetView();"
        )

    def _poll_image_export(self) -> None:
        self._web_view.page().runJavaScript(
            "window.quickInsightExportResult",
            self._on_image_export_result,
        )

    def _on_image_export_result(self, result: object) -> None:
        pending = self._pending_export
        document = self._document
        if pending is None or document is None:
            return
        export_format, destination, callback, attempts = pending
        if not isinstance(result, dict):
            if attempts >= 200:
                self._pending_export = None
                callback(RuntimeError("Timed out while waiting for Plotly.toImage export."))
                return
            self._pending_export = (export_format, destination, callback, attempts + 1)
            QTimer.singleShot(50, self._poll_image_export)
            return
        self._pending_export = None
        if not result.get("ok"):
            callback(RuntimeError(str(result.get("error", "Plotly.toImage export failed."))))
            return
        data_url = result.get("dataUrl")
        if not isinstance(data_url, str):
            callback(RuntimeError("Plotly.toImage did not return image data."))
            return
        try:
            callback(write_image_data_url(data_url, destination, export_format, document=document))
        except Exception as exc:
            callback(exc)

    def _on_load_finished(self, ok: bool) -> None:
        self._status_label.setText(
            "本地 Plotly 图表已载入。" if ok else "图表载入失败，请查看技术细节。"
        )
        self.chart_loaded.emit(ok)


def _warning_text(document: PlotlyChartDocument) -> str:
    if "chart_data_preparation_pending" not in document.warnings:
        return "图表已根据准备好的本地数据渲染。"
    rendered_rows = document.preparation.get("rendered_rows", "未知")
    return (
        "当前显示的是渲染器预览：真实图表数据准备、降采样和导出仍在 M4 后续切片接入；"
        f"本预览渲染 {rendered_rows} 个示例点。"
    )
