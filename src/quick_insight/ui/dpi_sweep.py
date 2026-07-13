from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QStackedWidget, QWidget

from quick_insight import APP_NAME, __version__
from quick_insight.infrastructure.paths import AppPaths
from quick_insight.infrastructure.settings import AppSettings
from quick_insight.ui.main_window import MainWindow

_PAGE_INDICES = {
    "welcome": 0,
    "preview": 1,
    "overview": 2,
    "recommendations": 3,
    "chart": 4,
    "text_labeling": 5,
}
_GLOBAL_VISIBLE_WIDGETS = (
    "workspaceSplitter",
    "navigationList",
    "datasetList",
    "workspaceStack",
    "rightTabs",
    "transformScrollArea",
    "bottomStatus",
    "rowCountLabel",
    "queryTimeLabel",
    "approximationLabel",
    "jobsLabel",
    "errorLabel",
)
_PAGE_VISIBLE_WIDGETS = {
    "welcome": (
        "welcomeAction_import_tabular",
        "welcomeAction_create_text_corpus",
        "welcomeAction_open_recent",
        "welcomeAction_open_sample",
    ),
    "preview": ("duckDbPreviewTable",),
    "overview": ("profileSummaryLabel", "profileFieldsList", "profileFindingsList"),
    "recommendations": ("analysisIntentSelector", "recommendationsScrollArea"),
    "chart": ("plotlyChartView", "chartExportHtmlButton", "chartResetButton"),
    "text_labeling": ("textLabelingScrollArea", "textSearchEdit"),
}


@dataclass(frozen=True)
class DpiSweepSettings:
    scale_factor: float
    output_dir: Path
    theme: str = "light"
    logical_width: int = 1366
    logical_height: int = 768
    schema_version: int = 1


@dataclass(frozen=True)
class DpiSweepCheck:
    name: str
    passed: bool
    details: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "details": self.details,
        }


@dataclass(frozen=True)
class DpiWidgetEvidence:
    object_name: str
    class_name: str
    page: str
    visible: bool
    within_window: bool
    geometry: dict[str, int]
    accessible_name: str

    def to_dict(self) -> dict[str, object]:
        return {
            "object_name": self.object_name,
            "class_name": self.class_name,
            "page": self.page,
            "visible": self.visible,
            "within_window": self.within_window,
            "geometry": self.geometry,
            "accessible_name": self.accessible_name,
        }


@dataclass(frozen=True)
class DpiPageEvidence:
    name: str
    screenshot_path: Path
    screenshot_width: int
    screenshot_height: int
    device_pixel_ratio: float
    nonblank: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "screenshot_path": str(self.screenshot_path),
            "screenshot_width": self.screenshot_width,
            "screenshot_height": self.screenshot_height,
            "device_pixel_ratio": self.device_pixel_ratio,
            "nonblank": self.nonblank,
        }


@dataclass(frozen=True)
class DpiScaleEvidence:
    scale_factor: float
    theme: str
    generated_at: datetime
    logical_window: dict[str, int]
    pages: tuple[DpiPageEvidence, ...]
    widgets: tuple[DpiWidgetEvidence, ...]
    checks: tuple[DpiSweepCheck, ...]
    schema_version: int = 1

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scale_factor": self.scale_factor,
            "theme": self.theme,
            "generated_at": self.generated_at.isoformat(),
            "app_version": __version__,
            "logical_window": self.logical_window,
            "pages": [page.to_dict() for page in self.pages],
            "widgets": [widget.to_dict() for widget in self.widgets],
            "checks": [check.to_dict() for check in self.checks],
            "passed": self.passed,
        }


def run_single_scale_sweep(settings: DpiSweepSettings) -> DpiScaleEvidence:
    _configure_qt_environment(settings.scale_factor)
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    existing_app = QApplication.instance()
    owns_app = existing_app is None
    app = (
        QApplication([APP_NAME, "--dpi-sweep", str(settings.scale_factor)])
        if existing_app is None
        else cast(QApplication, existing_app)
    )
    app.setApplicationName(APP_NAME)

    paths = AppPaths.under(settings.output_dir / "app-state").ensure()
    window = MainWindow(
        settings=AppSettings().with_theme(settings.theme),
        paths=paths,
    )
    window.resize(settings.logical_width, settings.logical_height)
    window.show()
    _process_events(app)

    try:
        pages: list[DpiPageEvidence] = []
        widgets: list[DpiWidgetEvidence] = []
        checks: list[DpiSweepCheck] = []
        stack = window.findChild(QStackedWidget, "workspaceStack")
        if stack is None:
            checks.append(DpiSweepCheck("workspace_stack_present", False, "workspaceStack missing"))
            return _scale_result(settings, window, pages, widgets, checks)

        for page_name, page_index in _PAGE_INDICES.items():
            stack.setCurrentIndex(page_index)
            _process_events(app)
            page_evidence, screenshot_check = _capture_page(
                window=window,
                page_name=page_name,
                output_dir=settings.output_dir,
            )
            pages.append(page_evidence)
            checks.append(screenshot_check)
            widgets.extend(_collect_widget_evidence(window, page_name))
            checks.extend(_visible_widget_checks(widgets, page_name))
            checks.extend(_visible_button_fit_checks(window, page_name))

        checks.append(
            DpiSweepCheck(
                "fits_minimum_logical_workspace",
                (
                    window.width() <= settings.logical_width
                    and window.height() <= settings.logical_height
                ),
                (
                    f"actual={window.width()}x{window.height()}; "
                    f"target={settings.logical_width}x{settings.logical_height}"
                ),
            )
        )
        return _scale_result(settings, window, pages, widgets, checks)
    finally:
        window.close()
        if owns_app:
            app.quit()


def write_scale_evidence(result: DpiScaleEvidence, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _scale_result(
    settings: DpiSweepSettings,
    window: MainWindow,
    pages: list[DpiPageEvidence],
    widgets: list[DpiWidgetEvidence],
    checks: list[DpiSweepCheck],
) -> DpiScaleEvidence:
    return DpiScaleEvidence(
        scale_factor=settings.scale_factor,
        theme=settings.theme,
        generated_at=datetime.now(UTC),
        logical_window={"width": window.width(), "height": window.height()},
        pages=tuple(pages),
        widgets=tuple(widgets),
        checks=tuple(checks),
    )


def _configure_qt_environment(scale_factor: float) -> None:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_SCALE_FACTOR"] = _scale_text(scale_factor)


def _process_events(app: QApplication) -> None:
    for _index in range(5):
        app.processEvents()


def _capture_page(
    *,
    window: MainWindow,
    page_name: str,
    output_dir: Path,
) -> tuple[DpiPageEvidence, DpiSweepCheck]:
    pixmap = window.grab()
    screenshot_path = output_dir / f"{page_name}.png"
    saved = pixmap.save(str(screenshot_path), "PNG")
    nonblank = saved and _pixmap_is_nonblank(pixmap)
    evidence = DpiPageEvidence(
        name=page_name,
        screenshot_path=screenshot_path,
        screenshot_width=pixmap.width(),
        screenshot_height=pixmap.height(),
        device_pixel_ratio=pixmap.devicePixelRatio(),
        nonblank=nonblank,
    )
    return evidence, DpiSweepCheck(
        name=f"{page_name}_screenshot_nonblank",
        passed=nonblank,
        details=(
            f"{screenshot_path.name}; {pixmap.width()}x{pixmap.height()}; "
            f"dpr={pixmap.devicePixelRatio():.2f}"
        ),
    )


def _pixmap_is_nonblank(pixmap: QPixmap) -> bool:
    if pixmap.isNull():
        return False
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    colors: set[int] = set()
    width = max(1, image.width())
    height = max(1, image.height())
    for x_index in range(8):
        x = min(width - 1, round(x_index * (width - 1) / 7))
        for y_index in range(8):
            y = min(height - 1, round(y_index * (height - 1) / 7))
            colors.add(image.pixel(x, y))
            if len(colors) > 1:
                return True
    return False


def _collect_widget_evidence(window: MainWindow, page_name: str) -> tuple[DpiWidgetEvidence, ...]:
    object_names = (*_GLOBAL_VISIBLE_WIDGETS, *_PAGE_VISIBLE_WIDGETS[page_name])
    return tuple(
        _widget_evidence(window, object_name, page_name)
        for object_name in object_names
        if window.findChild(QWidget, object_name) is not None
    )


def _widget_evidence(
    window: MainWindow,
    object_name: str,
    page_name: str,
) -> DpiWidgetEvidence:
    widget = window.findChild(QWidget, object_name)
    if widget is None:
        return DpiWidgetEvidence(
            object_name=object_name,
            class_name="missing",
            page=page_name,
            visible=False,
            within_window=False,
            geometry={"x": 0, "y": 0, "width": 0, "height": 0},
            accessible_name="",
        )
    rect = _widget_rect_in_window(window, widget)
    return DpiWidgetEvidence(
        object_name=object_name,
        class_name=widget.metaObject().className(),
        page=page_name,
        visible=widget.isVisible() and rect.width() > 0 and rect.height() > 0,
        within_window=_rect_within_window(window, rect),
        geometry={
            "x": rect.x(),
            "y": rect.y(),
            "width": rect.width(),
            "height": rect.height(),
        },
        accessible_name=widget.accessibleName(),
    )


def _visible_widget_checks(
    widgets: list[DpiWidgetEvidence],
    page_name: str,
) -> tuple[DpiSweepCheck, ...]:
    relevant = [widget for widget in widgets if widget.page == page_name]
    return tuple(
        DpiSweepCheck(
            f"{page_name}_{widget.object_name}_visible_within_window",
            widget.visible and widget.within_window,
            (
                f"visible={widget.visible}; within_window={widget.within_window}; "
                f"geometry={widget.geometry}"
            ),
        )
        for widget in relevant
    )


def _visible_button_fit_checks(window: MainWindow, page_name: str) -> tuple[DpiSweepCheck, ...]:
    checks: list[DpiSweepCheck] = []
    for button in window.findChildren(QPushButton):
        if not button.isVisible() or not button.text():
            continue
        text_width = button.fontMetrics().horizontalAdvance(button.text())
        available = max(0, button.width() - 24)
        passed = text_width <= available
        checks.append(
            DpiSweepCheck(
                f"{page_name}_{button.objectName()}_text_fits",
                passed,
                f"text_width={text_width}; available={available}; text={button.text()}",
            )
        )
    return tuple(checks)


def _widget_rect_in_window(window: QWidget, widget: QWidget) -> QRect:
    top_left = widget.mapTo(window, QPoint(0, 0))
    return QRect(top_left, widget.size())


def _rect_within_window(window: QWidget, rect: QRect) -> bool:
    window_rect = QRect(QPoint(0, 0), window.size())
    return window_rect.contains(rect.topLeft()) and window_rect.contains(rect.bottomRight())


def _scale_text(scale_factor: float) -> str:
    return f"{scale_factor:.2f}".rstrip("0").rstrip(".")
