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
    quantile_25: float | None = None
    quantile_75: float | None = None
    mean_value: float | None = None
    median_value: float | None = None
    stddev_value: float | None = None
    outlier_count: int | None = None
    avg_text_length: float | None = None
    max_text_length: int | None = None
    non_empty_count: int = 0
    numeric_like_count: int = 0
    datetime_like_count: int = 0
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

    def duplicate_row_count(
        self,
        table_name: str,
        columns: tuple[WorkspaceColumn, ...],
    ) -> int:
        if not columns:
            return 0
        table_sql = quote_identifier(table_name)
        column_sql = ", ".join(quote_identifier(column.name) for column in columns)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COALESCE(SUM(duplicate_count - 1), 0)
                FROM (
                    SELECT COUNT(*) AS duplicate_count
                    FROM {table_sql}
                    GROUP BY {column_sql}
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()
        if row is None:
            return 0
        return int(row[0] or 0)

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
            shape_row = connection.execute(
                f"""
                SELECT
                    SUM(
                        CASE
                            WHEN TRIM(CAST({column_sql} AS VARCHAR)) <> ''
                            THEN 1 ELSE 0
                        END
                    ) AS non_empty_count,
                    SUM(
                        CASE
                            WHEN TRIM(CAST({column_sql} AS VARCHAR)) <> ''
                             AND TRY_CAST(CAST({column_sql} AS VARCHAR) AS DOUBLE) IS NOT NULL
                            THEN 1 ELSE 0
                        END
                    ) AS numeric_like_count,
                    SUM(
                        CASE
                            WHEN TRIM(CAST({column_sql} AS VARCHAR)) <> ''
                             AND TRY_CAST(CAST({column_sql} AS VARCHAR) AS TIMESTAMP) IS NOT NULL
                            THEN 1 ELSE 0
                        END
                    ) AS datetime_like_count
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
            datetime_row = self._datetime_stats(
                connection,
                table_sql,
                column_sql,
                column.data_type,
            )
        row_count = int(base_row[0]) if base_row is not None else 0
        null_count = int(base_row[1] or 0) if base_row is not None else 0
        distinct_count = int(base_row[2] or 0) if base_row is not None else 0
        avg_text_length = (
            float(text_row[0]) if text_row is not None and text_row[0] is not None else None
        )
        max_text_length = (
            int(text_row[1]) if text_row is not None and text_row[1] is not None else None
        )
        non_empty_count = int(shape_row[0] or 0) if shape_row is not None else 0
        numeric_like_count = int(shape_row[1] or 0) if shape_row is not None else 0
        datetime_like_count = int(shape_row[2] or 0) if shape_row is not None else 0
        min_value = numeric_row[0] if numeric_row is not None else None
        max_value = numeric_row[1] if numeric_row is not None else None
        if datetime_row is not None:
            min_value = datetime_row[0]
            max_value = datetime_row[1]
        return WorkspaceColumnStats(
            name=column.name,
            data_type=column.data_type,
            row_count=row_count,
            null_count=null_count,
            distinct_count=distinct_count,
            min_value=min_value,
            max_value=max_value,
            quantile_25=(
                float(numeric_row[2])
                if numeric_row is not None and numeric_row[2] is not None
                else None
            ),
            quantile_75=(
                float(numeric_row[3])
                if numeric_row is not None and numeric_row[3] is not None
                else None
            ),
            mean_value=(
                float(numeric_row[4])
                if numeric_row is not None and numeric_row[4] is not None
                else None
            ),
            median_value=(
                float(numeric_row[5])
                if numeric_row is not None and numeric_row[5] is not None
                else None
            ),
            stddev_value=(
                float(numeric_row[6])
                if numeric_row is not None and numeric_row[6] is not None
                else None
            ),
            outlier_count=(
                int(numeric_row[7])
                if numeric_row is not None and numeric_row[7] is not None
                else None
            ),
            avg_text_length=avg_text_length,
            max_text_length=max_text_length,
            non_empty_count=non_empty_count,
            numeric_like_count=numeric_like_count,
            datetime_like_count=datetime_like_count,
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
            WITH clean AS (
                SELECT {column_sql} AS value
                FROM {table_sql}
                WHERE {column_sql} IS NOT NULL
            ),
            stats AS (
                SELECT
                    QUANTILE_CONT(value, 0.25) AS q1,
                    QUANTILE_CONT(value, 0.75) AS q3
                FROM clean
            )
            SELECT
                MIN(value),
                MAX(value),
                q1,
                q3,
                AVG(value),
                MEDIAN(value),
                STDDEV_SAMP(value),
                SUM(
                    CASE
                        WHEN q1 IS NULL OR q3 IS NULL THEN 0
                        WHEN value < q1 - (1.5 * (q3 - q1))
                          OR value > q3 + (1.5 * (q3 - q1))
                        THEN 1 ELSE 0
                    END
                )
            FROM clean, stats
            GROUP BY q1, q3
            """
        ).fetchone()

    def _datetime_stats(
        self,
        connection: duckdb.DuckDBPyConnection,
        table_sql: str,
        column_sql: str,
        data_type: str,
    ) -> tuple[Any, ...] | None:
        if not _is_datetime_type(data_type):
            return None
        return connection.execute(
            f"""
            SELECT MIN({column_sql}), MAX({column_sql})
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


def _is_datetime_type(data_type: str) -> bool:
    normalized = data_type.upper()
    return "DATE" in normalized or "TIME" in normalized
