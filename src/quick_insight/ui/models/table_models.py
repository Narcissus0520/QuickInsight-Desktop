from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QThreadPool,
)

from quick_insight.application.jobs import JobContext, JobOutcome, JobState
from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase
from quick_insight.ui.jobs import QtJobRunner


@dataclass(frozen=True)
class PageResult:
    generation: int
    page_index: int
    rows: tuple[tuple[Any, ...], ...]


class PreviewTableModel(QAbstractTableModel):
    def __init__(self, columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> None:
        super().__init__()
        self._columns = columns
        self._rows = rows

    def rowCount(self, _parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return len(self._rows)

    def columnCount(self, _parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return len(self._columns)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._rows[index.row()][index.column()]

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | int | None:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section]
        return section + 1


class DuckDbTableModel(QAbstractTableModel):
    def __init__(
        self,
        *,
        workspace: WorkspaceDatabase,
        table_name: str,
        columns: tuple[WorkspaceColumn, ...],
        row_count: int,
        page_size: int = 200,
        max_cached_pages: int = 5,
    ) -> None:
        super().__init__()
        self._workspace = workspace
        self._table_name = table_name
        self._columns = columns
        self._row_count = row_count
        self._page_size = page_size
        self._max_cached_pages = max_cached_pages
        self._cache: OrderedDict[int, tuple[tuple[Any, ...], ...]] = OrderedDict()
        self._pending_pages: dict[int, QtJobRunner[PageResult]] = {}
        self._failed_pages: set[int] = set()
        self._generation = 0

    def rowCount(self, _parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return self._row_count

    def columnCount(self, _parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return len(self._columns)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = index.row()
        column = index.column()
        page_index = row // self._page_size
        if page_index in self._failed_pages:
            return "加载失败"
        if page_index not in self._cache:
            self._request_page(page_index)
            return "加载中..."
        value = self._value_at(row, column)
        return "" if value is None else str(value)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | int | None:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section].name
        return section + 1

    def set_table(
        self,
        *,
        table_name: str,
        columns: tuple[WorkspaceColumn, ...],
        row_count: int,
    ) -> None:
        self.beginResetModel()
        self.cancel_pending_queries()
        self._generation += 1
        self._table_name = table_name
        self._columns = columns
        self._row_count = row_count
        self._cache.clear()
        self._failed_pages.clear()
        self.endResetModel()

    def cancel_pending_queries(self) -> None:
        for runner in self._pending_pages.values():
            runner.cancel()
        self._pending_pages.clear()

    def cached_page_count(self) -> int:
        return len(self._cache)

    def pending_page_count(self) -> int:
        return len(self._pending_pages)

    def _value_at(self, row: int, column: int) -> Any:
        page_index = row // self._page_size
        page_offset = row % self._page_size
        page = self._cache.get(page_index)
        if page is None:
            return None
        if page_offset >= len(page):
            return None
        record = page[page_offset]
        if column >= len(record):
            return None
        return record[column]

    def _request_page(self, page_index: int) -> None:
        if page_index in self._pending_pages:
            return
        self._failed_pages.discard(page_index)
        generation = self._generation
        table_name = self._table_name
        runner = QtJobRunner(
            f"fetch_page_{page_index}",
            lambda context: self._fetch_page(
                context,
                table_name=table_name,
                generation=generation,
                page_index=page_index,
            ),
        )
        self._pending_pages[page_index] = runner
        runner.signals.completed.connect(
            lambda outcome, requested_page=page_index, requested_generation=generation: (
                self._on_page_loaded(requested_page, requested_generation, outcome)
            )
        )
        QThreadPool.globalInstance().start(runner)

    def _fetch_page(
        self,
        context: JobContext,
        *,
        table_name: str,
        generation: int,
        page_index: int,
    ) -> PageResult:
        context.cancellation.raise_if_cancelled()
        rows = self._workspace.fetch_page(
            table_name,
            limit=self._page_size,
            offset=page_index * self._page_size,
        )
        context.cancellation.raise_if_cancelled()
        return PageResult(generation=generation, page_index=page_index, rows=rows)

    def _on_page_loaded(
        self,
        requested_page: int,
        requested_generation: int,
        outcome: JobOutcome[PageResult],
    ) -> None:
        self._pending_pages.pop(requested_page, None)
        page_result = outcome.value
        if page_result is None:
            if requested_generation == self._generation and outcome.state is JobState.FAILED:
                self._failed_pages.add(requested_page)
            return
        if outcome.state is not JobState.SUCCEEDED:
            if page_result.generation == self._generation:
                self._failed_pages.add(page_result.page_index)
            return
        if page_result.generation != self._generation:
            return
        self._cache[page_result.page_index] = page_result.rows
        self._cache.move_to_end(page_result.page_index)
        while len(self._cache) > self._max_cached_pages:
            self._cache.popitem(last=False)
        first_row = page_result.page_index * self._page_size
        last_row = min(first_row + len(page_result.rows), self._row_count) - 1
        if last_row >= first_row and self._columns:
            self.dataChanged.emit(
                self.index(first_row, 0),
                self.index(last_row, len(self._columns) - 1),
                [Qt.ItemDataRole.DisplayRole],
            )
