from __future__ import annotations

import threading
from typing import Any

from quick_insight.application.text_labeling import TextLabelingService, TextRecordFilter
from quick_insight.domain.models import Category, TextRecord
from quick_insight.infrastructure.csv_import import preview_delimited_file
from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase
from quick_insight.ui.models import DuckDbTableModel, TextRecordTableModel


def test_duckdb_table_model_loads_pages_in_background(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "data.csv"
    source.write_text("name,amount\nalpha,1\nbeta,2\n", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    preview = preview_delimited_file(source)
    workspace.import_csv(source, "dataset", preview.options)
    columns = workspace.columns("dataset")
    model = DuckDbTableModel(
        workspace=workspace,
        table_name="dataset",
        columns=columns,
        row_count=2,
        page_size=1,
    )

    assert model.data(model.index(1, 0)) == "加载中..."
    qtbot.waitUntil(lambda: model.cached_page_count() == 1, timeout=3000)

    assert model.data(model.index(1, 0)) == "beta"


def test_duckdb_table_model_rejects_stale_cancelled_page(qtbot) -> None:  # type: ignore[no-untyped-def]
    workspace = BlockingWorkspace()
    model = DuckDbTableModel(
        workspace=workspace,  # type: ignore[arg-type]
        table_name="old_table",
        columns=(WorkspaceColumn("name", "VARCHAR"),),
        row_count=1,
        page_size=1,
    )

    assert model.data(model.index(0, 0)) == "加载中..."
    assert workspace.started.wait(timeout=3)
    model.set_table(
        table_name="new_table",
        columns=(WorkspaceColumn("name", "VARCHAR"),),
        row_count=1,
    )
    workspace.release.set()
    qtbot.waitUntil(lambda: model.pending_page_count() == 0, timeout=3000)

    assert model.cached_page_count() == 0


def test_text_record_table_model_loads_pages_and_filters(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    category = Category(id="cat_feedback", name="反馈")
    workspace.save_text_corpus(
        "corpus",
        (
            TextRecord(id="r-1", content="第一条安装反馈", primary_category_id=category.id),
            TextRecord(id="r-2", content="第二条告警记录"),
        ),
        (category,),
    )
    service = TextLabelingService(workspace)
    model = TextRecordTableModel(
        service=service,
        corpus_id="corpus",
        categories=service.list_categories(),
        page_size=1,
    )

    assert model.rowCount() == 2
    assert model.data(model.index(1, 0)) == "加载中..."
    qtbot.waitUntil(lambda: model.cached_page_count() == 1, timeout=3000)
    assert model.data(model.index(1, 0)) == "第二条告警记录"

    model.set_filter(TextRecordFilter(search_text="安装"))

    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "加载中..."
    qtbot.waitUntil(lambda: model.cached_page_count() == 1, timeout=3000)
    assert model.data(model.index(0, 1)) == "反馈"


class BlockingWorkspace:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def fetch_page(
        self,
        _table_name: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[tuple[Any, ...], ...]:
        self.started.set()
        assert self.release.wait(timeout=3)
        return (("stale",),)
