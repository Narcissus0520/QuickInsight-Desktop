from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QLabel, QPushButton

from quick_insight.application.importing import TabularImportService
from quick_insight.infrastructure.paths import AppPaths
from quick_insight.infrastructure.settings import AppSettings
from quick_insight.infrastructure.workspace import WorkspaceDatabase
from quick_insight.ui.dialogs import TabularImportDialog
from quick_insight.ui.main_window import MainWindow


def test_main_window_constructs_workspace_shell(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(settings=AppSettings())
    qtbot.addWidget(window)

    assert window.findChild(QLabel, "rowCountLabel") is not None
    assert window.findChild(QLabel, "queryTimeLabel") is not None
    assert window.findChild(QLabel, "approximationLabel") is not None
    assert window.findChild(QLabel, "jobsLabel") is not None
    assert window.findChild(QPushButton, "welcomeAction_import_tabular") is not None


def test_welcome_page_contains_required_chinese_actions(  # type: ignore[no-untyped-def]
    qtbot,
) -> None:
    window = MainWindow(settings=AppSettings())
    qtbot.addWidget(window)

    labels = {button.text() for button in window.findChildren(QPushButton)}
    assert {"导入表格数据", "录入文本语句", "打开最近项目", "打开示例数据"}.issubset(labels)


def test_theme_switching_updates_current_theme(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(settings=AppSettings())
    qtbot.addWidget(window)

    window.apply_theme("dark", persist=False)

    assert window.current_theme == "dark"


def test_main_window_shows_imported_dataset(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text("name,amount\nalpha,1\n", encoding="utf-8")
    paths = AppPaths.under(tmp_path / "app").ensure()
    workspace = WorkspaceDatabase(paths.cache_dir / "workspace.duckdb")
    service = TabularImportService(workspace)
    result = service.import_csv(service.preview_csv(source))
    window = MainWindow(settings=AppSettings(), paths=paths)
    qtbot.addWidget(window)

    window._show_import_result(result)

    assert window.findChild(QLabel, "rowCountLabel").text() == "行/记录：1"
    assert window.findChild(QLabel, "approximationLabel").text() == "近似：无"


def test_import_dialog_runs_confirm_in_background(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text("name,amount\nalpha,1\n", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    dialog = TabularImportDialog(service=service, initial_path=source)
    qtbot.addWidget(dialog)

    dialog._confirm()
    qtbot.waitUntil(lambda: dialog.import_result is not None, timeout=3000)

    assert dialog.import_result.handle.row_count == 1
