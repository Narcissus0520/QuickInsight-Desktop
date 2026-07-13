from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QListWidget, QPushButton, QTableView

from quick_insight.application.importing import TabularImportService
from quick_insight.application.text_corpus import TextCorpusService
from quick_insight.infrastructure.paths import AppPaths
from quick_insight.infrastructure.settings import AppSettings
from quick_insight.infrastructure.workspace import WorkspaceDatabase
from quick_insight.ui.dialogs import TabularImportDialog, TextCorpusDialog
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
    source.write_text("name,amount\nalpha,1\nalpha,\nalpha,\n", encoding="utf-8")
    paths = AppPaths.under(tmp_path / "app").ensure()
    workspace = WorkspaceDatabase(paths.cache_dir / "workspace.duckdb")
    service = TabularImportService(workspace)
    result = service.import_csv(service.preview_csv(source))
    window = MainWindow(settings=AppSettings(), paths=paths)
    qtbot.addWidget(window)

    window._show_import_result(result)

    assert window.findChild(QLabel, "rowCountLabel").text() == "行/记录：3"
    assert window.findChild(QLabel, "approximationLabel").text() == "近似：无"
    qtbot.waitUntil(
        lambda: window.findChild(QLabel, "profileSummaryLabel").text().startswith("画像完成"),
        timeout=3000,
    )
    assert "缺失值 2" in window.findChild(QLabel, "profileSummaryLabel").text()
    assert window.findChild(QListWidget, "profileFieldsList").count() == 2
    assert window.findChild(QListWidget, "profileFindingsList").count() >= 1


def test_main_window_shows_one_click_analysis_findings(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "analysis.csv"
    source.write_text(
        "\n".join(
            [
                "date,category,revenue,cost",
                "2026-01-01,A,10,11",
                "2026-01-02,A,20,21",
                "2026-01-03,B,30,31",
                "2026-01-04,B,40,41",
                "2026-01-05,C,50,51",
                "2026-01-06,C,60,61",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    paths = AppPaths.under(tmp_path / "app").ensure()
    workspace = WorkspaceDatabase(paths.cache_dir / "workspace.duckdb")
    service = TabularImportService(workspace)
    result = service.import_csv(service.preview_csv(source))
    window = MainWindow(settings=AppSettings(), paths=paths)
    qtbot.addWidget(window)

    window._show_import_result(result)

    findings = window.findChild(QListWidget, "profileFindingsList")
    qtbot.waitUntil(lambda: findings.count() >= 3, timeout=3000)
    finding_text = "\n".join(findings.item(index).text() for index in range(findings.count()))
    assert "呈较强正相关" in finding_text
    assert "呈明显上升趋势" in finding_text


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


def test_text_corpus_dialog_saves_pasted_records(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TextCorpusService(workspace)
    dialog = TextCorpusDialog(service=service)
    qtbot.addWidget(dialog)

    dialog._content_edit.setPlainText("第一条\n第二条")
    dialog._category_edit.setText("体验")
    dialog._tags_edit.setText("安装,新手")
    dialog._source_edit.setText("访谈")
    dialog.preview()
    dialog._confirm()
    qtbot.waitUntil(lambda: dialog.import_result is not None, timeout=3000)

    assert dialog.import_result.handle.row_count == 2
    stored = workspace.list_text_records(dialog.import_result.handle.cache_key or "")
    assert stored[0].tags == ("安装", "新手")


def test_main_window_shows_text_corpus_result(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = AppPaths.under(tmp_path / "app").ensure()
    workspace = WorkspaceDatabase(paths.cache_dir / "workspace.duckdb")
    service = TextCorpusService(workspace)
    result = service.import_preview(
        service.preview_text(
            "第一条\n第二条",
            display_name="文本语料",
        )
    )
    window = MainWindow(settings=AppSettings(), paths=paths)
    qtbot.addWidget(window)

    window._show_text_corpus_result(result)

    assert window.findChild(QLabel, "rowCountLabel").text() == "行/记录：2"
    assert window.findChild(QLabel, "queryTimeLabel").text() == "查询：文本语料已保存"
    qtbot.waitUntil(
        lambda: window.findChild(QLabel, "profileSummaryLabel")
        .text()
        .startswith("文本画像完成"),
        timeout=3000,
    )
    assert "未分类 2" in window.findChild(QLabel, "profileSummaryLabel").text()
    assert window.findChild(QListWidget, "profileFieldsList").count() == 4
    assert window.findChild(QListWidget, "profileFindingsList").count() >= 1
    qtbot.waitUntil(
        lambda: window._text_label_model is not None
        and window._text_label_model.pending_page_count() == 0,
        timeout=3000,
    )


def test_text_labeling_workspace_edits_record_and_filters(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = AppPaths.under(tmp_path / "app").ensure()
    workspace = WorkspaceDatabase(paths.cache_dir / "workspace.duckdb")
    service = TextCorpusService(workspace)
    result = service.import_preview(
        service.preview_text(
            "第一条安装反馈\n第二条告警记录",
            display_name="文本语料",
        )
    )
    window = MainWindow(settings=AppSettings(), paths=paths)
    qtbot.addWidget(window)

    window._show_text_corpus_result(result)
    table = window.findChild(QTableView, "textLabelTable")
    model = table.model()
    model.data(model.index(0, 0))
    qtbot.waitUntil(lambda: model.cached_page_count() == 1, timeout=3000)
    table.selectRow(0)
    qtbot.waitUntil(
        lambda: window.findChild(QLineEdit, "textRecordTagsEdit").isEnabled(),
        timeout=3000,
    )
    qtbot.waitUntil(
        lambda: window._text_record_content_edit.toPlainText()
        in {"第一条安装反馈", "第二条告警记录"},
        timeout=3000,
    )
    edited_content = window._text_record_content_edit.toPlainText()

    window.findChild(QComboBox, "textRecordCategoryCombo").setEditText("体验")
    window.findChild(QLineEdit, "textRecordTagsEdit").setText("安装,新手")
    window.findChild(QPushButton, "textSaveNextButton").click()
    qtbot.waitUntil(lambda: table.currentIndex().row() == 1, timeout=3000)

    stored = {
        record.content: record
        for record in workspace.list_text_records(result.handle.cache_key or "")
    }
    categories = {category.id: category.name for category in workspace.list_categories()}
    assert categories[stored[edited_content].primary_category_id or ""] == "体验"
    assert stored[edited_content].tags == ("安装", "新手")

    window.findChild(QLineEdit, "textSearchEdit").setText("告警")
    qtbot.waitUntil(lambda: table.model().rowCount() == 1, timeout=3000)
    filtered_model = table.model()
    filtered_model.data(filtered_model.index(0, 0))
    qtbot.waitUntil(lambda: filtered_model.cached_page_count() == 1, timeout=3000)
    assert "告警" in filtered_model.data(filtered_model.index(0, 0))
    qtbot.waitUntil(lambda: window._running_profile_job is None, timeout=3000)
    qtbot.waitUntil(lambda: filtered_model.pending_page_count() == 0, timeout=3000)


def test_import_dialog_shows_bad_csv_encoding_error(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "bad.csv"
    source.write_bytes(b"\xff\xff\x00\xfe")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    dialog = TabularImportDialog(service=service, initial_path=source)
    qtbot.addWidget(dialog)

    assert "无法识别文件编码" in dialog._status_label.text()
    assert dialog.import_result is None


def test_import_dialog_shows_bad_parquet_error(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "bad.parquet"
    source.write_text("not parquet", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    dialog = TabularImportDialog(service=service, initial_path=source)
    qtbot.addWidget(dialog)

    assert "无法预览 Parquet 文件" in dialog._status_label.text()
    assert dialog.import_result is None


def test_import_dialog_shows_bad_excel_error(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "bad.xlsx"
    source.write_text("not excel", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    dialog = TabularImportDialog(service=service, initial_path=source)
    qtbot.addWidget(dialog)

    assert "无法预览 Excel 文件" in dialog._status_label.text()
    assert dialog.import_result is None


def test_import_dialog_shows_missing_source_on_confirm(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text("name,amount\nalpha,1\n", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    dialog = TabularImportDialog(service=service, initial_path=source)
    qtbot.addWidget(dialog)
    source.unlink()

    dialog._confirm()
    qtbot.waitUntil(lambda: "找不到文件" in dialog._status_label.text(), timeout=3000)

    assert dialog.import_result is None
