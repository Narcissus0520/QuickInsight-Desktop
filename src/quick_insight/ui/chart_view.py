from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from quick_insight.charts.rendering import PlotlyChartDocument, build_plotly_html


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plotlyChartView")
        self._last_html = ""
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

        header = QFrame()
        header.setObjectName("chartHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addWidget(self._title_label, stretch=1)
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

    def render_document(self, document: PlotlyChartDocument) -> None:
        self._title_label.setText(document.title)
        self._status_label.setText("正在载入本地 Plotly 图表...")
        self._warning_label.setText(_warning_text(document))
        self._last_html = build_plotly_html(document)
        if os.environ.get("QT_QPA_PLATFORM", "").casefold() == "offscreen":
            self._status_label.setText("本地 Plotly HTML 已生成；offscreen 测试未加载 WebEngine。")
            self.chart_loaded.emit(True)
            return
        self._web_view.setHtml(self._last_html, QUrl("qrc:/quick-insight/charts/"))

    def reset_view(self) -> None:
        self._web_view.page().runJavaScript(
            "window.quickInsightChart && window.quickInsightChart.resetView();"
        )

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
