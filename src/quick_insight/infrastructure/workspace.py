from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from quick_insight.infrastructure.csv_import import CsvImportOptions
from quick_insight.infrastructure.sql import quote_identifier


@dataclass(frozen=True)
class WorkspaceColumn:
    name: str
    data_type: str


class WorkspaceDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def import_csv(self, source: Path, table_name: str, options: CsvImportOptions) -> None:
        table_sql = quote_identifier(table_name)
        with self._connect() as connection:
            connection.execute(f"DROP TABLE IF EXISTS {table_sql}")
            connection.execute(
                f"""
                CREATE TABLE {table_sql} AS
                SELECT * FROM read_csv(
                    ?,
                    delim=?,
                    header=?,
                    auto_detect=true,
                    ignore_errors=false,
                    sample_size=-1
                )
                """,
                [str(source), options.delimiter, options.has_header],
            )

    def row_count(self, table_name: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table_name)}"
            ).fetchone()
        if row is None:
            return 0
        return int(row[0])

    def columns(self, table_name: str) -> tuple[WorkspaceColumn, ...]:
        with self._connect() as connection:
            rows = connection.execute(f"DESCRIBE {quote_identifier(table_name)}").fetchall()
        return tuple(WorkspaceColumn(name=str(row[0]), data_type=str(row[1])) for row in rows)

    def fetch_page(
        self,
        table_name: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[tuple[Any, ...], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {quote_identifier(table_name)} LIMIT ? OFFSET ?",
                [limit, offset],
            ).fetchall()
        return tuple(tuple(row) for row in rows)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))
