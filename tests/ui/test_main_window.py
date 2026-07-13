from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QLabel, QPushButton

from quick_insight.infrastructure.settings import AppSettings
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
