from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from quick_insight.infrastructure.csv_import import CsvImportOptions
from quick_insight.infrastructure.sql import quote_identifier


@dataclass(frozen=True)
class WorkspaceColumn:
    name: str
    data_type: str


@dataclass(frozen=True)
class WorkspaceColumnStats:
    name: str
    data_type: str
    row_count: int
    null_count: int
    distinct_count: int
    min_value: Any | None = None
    max_value: Any | None = None
    mean_value: float | None = None
    median_value: float | None = None
    stddev_value: float | None = None
    avg_text_length: float | None = None
    max_text_length: int | None = None
    top_values: tuple[tuple[str, int], ...] = ()


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

    def import_parquet(self, source: Path, table_name: str) -> None:
        table_sql = quote_identifier(table_name)
        with self._connect() as connection:
            connection.execute(f"DROP TABLE IF EXISTS {table_sql}")
            connection.execute(
                f"CREATE TABLE {table_sql} AS SELECT * FROM read_parquet(?)",
                [str(source)],
            )

    def import_polars_dataframe(self, frame: pl.DataFrame, table_name: str) -> None:
        table_sql = quote_identifier(table_name)
        with self._connect() as connection:
            connection.register("_quick_insight_import_frame", frame.to_arrow())
            connection.execute(f"DROP TABLE IF EXISTS {table_sql}")
            connection.execute(
                f"CREATE TABLE {table_sql} AS SELECT * FROM _quick_insight_import_frame"
            )
            connection.unregister("_quick_insight_import_frame")

    def export_table_to_parquet(self, table_name: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                f"COPY {quote_identifier(table_name)} TO ? (FORMAT PARQUET)",
                [str(destination)],
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

    def column_stats(self, table_name: str, column: WorkspaceColumn) -> WorkspaceColumnStats:
        table_sql = quote_identifier(table_name)
        column_sql = quote_identifier(column.name)
        with self._connect() as connection:
            base_row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS row_count,
                    SUM(CASE WHEN {column_sql} IS NULL THEN 1 ELSE 0 END) AS null_count,
                    COUNT(DISTINCT {column_sql}) AS distinct_count
                FROM {table_sql}
                """
            ).fetchone()
            text_row = connection.execute(
                f"""
                SELECT
                    AVG(LENGTH(CAST({column_sql} AS VARCHAR))) AS avg_text_length,
                    MAX(LENGTH(CAST({column_sql} AS VARCHAR))) AS max_text_length
                FROM {table_sql}
                WHERE {column_sql} IS NOT NULL
                """
            ).fetchone()
            top_rows = connection.execute(
                f"""
                SELECT CAST({column_sql} AS VARCHAR) AS value, COUNT(*) AS count
                FROM {table_sql}
                WHERE {column_sql} IS NOT NULL
                GROUP BY value
                ORDER BY count DESC, value ASC
                LIMIT 10
                """
            ).fetchall()
            numeric_row = self._numeric_stats(connection, table_sql, column_sql, column.data_type)
        row_count = int(base_row[0]) if base_row is not None else 0
        null_count = int(base_row[1] or 0) if base_row is not None else 0
        distinct_count = int(base_row[2] or 0) if base_row is not None else 0
        avg_text_length = (
            float(text_row[0]) if text_row is not None and text_row[0] is not None else None
        )
        max_text_length = (
            int(text_row[1]) if text_row is not None and text_row[1] is not None else None
        )
        return WorkspaceColumnStats(
            name=column.name,
            data_type=column.data_type,
            row_count=row_count,
            null_count=null_count,
            distinct_count=distinct_count,
            min_value=numeric_row[0] if numeric_row is not None else None,
            max_value=numeric_row[1] if numeric_row is not None else None,
            mean_value=(
                float(numeric_row[2])
                if numeric_row is not None and numeric_row[2] is not None
                else None
            ),
            median_value=(
                float(numeric_row[3])
                if numeric_row is not None and numeric_row[3] is not None
                else None
            ),
            stddev_value=(
                float(numeric_row[4])
                if numeric_row is not None and numeric_row[4] is not None
                else None
            ),
            avg_text_length=avg_text_length,
            max_text_length=max_text_length,
            top_values=tuple((str(row[0]), int(row[1])) for row in top_rows),
        )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))

    def _numeric_stats(
        self,
        connection: duckdb.DuckDBPyConnection,
        table_sql: str,
        column_sql: str,
        data_type: str,
    ) -> tuple[Any, ...] | None:
        if not _is_numeric_type(data_type):
            return None
        return connection.execute(
            f"""
            SELECT
                MIN({column_sql}),
                MAX({column_sql}),
                AVG({column_sql}),
                MEDIAN({column_sql}),
                STDDEV_SAMP({column_sql})
            FROM {table_sql}
            WHERE {column_sql} IS NOT NULL
            """
        ).fetchone()


def _is_numeric_type(data_type: str) -> bool:
    normalized = data_type.upper()
    return any(
        token in normalized
        for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "REAL")
    )
