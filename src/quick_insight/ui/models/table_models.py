from __future__ import annotations

from collections import OrderedDict
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase


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
        value = self._value_at(index.row(), index.column())
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

    def _value_at(self, row: int, column: int) -> Any:
        page_index = row // self._page_size
        page_offset = row % self._page_size
        page = self._page(page_index)
        if page_offset >= len(page):
            return None
        record = page[page_offset]
        if column >= len(record):
            return None
        return record[column]

    def _page(self, page_index: int) -> tuple[tuple[Any, ...], ...]:
        if page_index in self._cache:
            self._cache.move_to_end(page_index)
            return self._cache[page_index]
        page = self._workspace.fetch_page(
            self._table_name,
            limit=self._page_size,
            offset=page_index * self._page_size,
        )
        self._cache[page_index] = page
        while len(self._cache) > self._max_cached_pages:
            self._cache.popitem(last=False)
        return page
