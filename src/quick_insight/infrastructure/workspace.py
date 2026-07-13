from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from quick_insight.domain.models import Category, TextRecord
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


@dataclass(frozen=True)
class WorkspaceCorrelationStats:
    left_column: str
    right_column: str
    row_count: int
    correlation: float | None


@dataclass(frozen=True)
class WorkspaceTrendStats:
    time_column: str
    numeric_column: str
    row_count: int
    correlation: float | None
    slope_per_day: float | None
    first_time: Any | None
    last_time: Any | None
    first_value: float | None
    last_value: float | None


@dataclass(frozen=True)
class WorkspaceGroupDifferenceStats:
    category_column: str
    numeric_column: str
    row_count: int
    category_count: int
    top_category: str
    top_mean: float
    top_count: int
    bottom_category: str
    bottom_mean: float
    bottom_count: int
    mean_difference: float
    mean_ratio: float | None


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

    def save_text_corpus(
        self,
        corpus_id: str,
        records: tuple[TextRecord, ...],
        categories: tuple[Category, ...],
    ) -> None:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            connection.execute("BEGIN TRANSACTION")
            try:
                record_ids = [
                    row[0]
                    for row in connection.execute(
                        "SELECT id FROM text_records WHERE corpus_id = ?",
                        [corpus_id],
                    ).fetchall()
                ]
                if record_ids:
                    connection.executemany(
                        "DELETE FROM text_record_tags WHERE record_id = ?",
                        [(record_id,) for record_id in record_ids],
                    )
                connection.execute("DELETE FROM text_records WHERE corpus_id = ?", [corpus_id])
                for category in categories:
                    connection.execute(
                        "DELETE FROM text_categories WHERE id = ? OR name = ?",
                        [category.id, category.name],
                    )
                    connection.execute(
                        """
                        INSERT INTO text_categories (
                            id, name, description, color, created_at, updated_at, schema_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            category.id,
                            category.name,
                            category.description,
                            category.color,
                            category.created_at,
                            category.updated_at,
                            category.schema_version,
                        ],
                    )
                for record in records:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO text_records (
                            id, corpus_id, content, primary_category_id, source, location,
                            speaker, record_time, note, custom_fields_json, created_at,
                            updated_at, schema_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            record.id,
                            corpus_id,
                            record.content,
                            record.primary_category_id,
                            record.source,
                            record.location,
                            record.speaker,
                            record.record_time,
                            record.note,
                            json.dumps(record.custom_fields, ensure_ascii=False),
                            record.created_at,
                            record.updated_at,
                            record.schema_version,
                        ],
                    )
                    if record.tags:
                        connection.executemany(
                            """
                            INSERT OR REPLACE INTO text_record_tags (record_id, tag, tag_order)
                            VALUES (?, ?, ?)
                            """,
                            [
                                (record.id, tag, tag_index)
                                for tag_index, tag in enumerate(record.tags)
                            ],
                        )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def text_record_count(self, corpus_id: str) -> int:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            row = connection.execute(
                "SELECT COUNT(*) FROM text_records WHERE corpus_id = ?",
                [corpus_id],
            ).fetchone()
        return int(row[0] or 0) if row is not None else 0

    def list_text_records(self, corpus_id: str) -> tuple[TextRecord, ...]:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            rows = connection.execute(
                """
                SELECT
                    id, content, primary_category_id, source, location, speaker,
                    record_time, note, custom_fields_json, created_at, updated_at,
                    schema_version
                FROM text_records
                WHERE corpus_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                [corpus_id],
            ).fetchall()
            tag_rows = connection.execute(
                """
                SELECT record_id, tag
                FROM text_record_tags
                WHERE record_id IN (
                    SELECT id FROM text_records WHERE corpus_id = ?
                )
                ORDER BY record_id ASC, tag_order ASC, tag ASC
                """,
                [corpus_id],
            ).fetchall()
        tags_by_record: dict[str, list[str]] = {}
        for record_id, tag in tag_rows:
            tags_by_record.setdefault(str(record_id), []).append(str(tag))
        return tuple(_text_record_from_row(row, tags_by_record) for row in rows)

    def text_record_count_filtered(
        self,
        corpus_id: str,
        *,
        search_text: str = "",
        category_id: str | None = None,
        uncategorized_only: bool = False,
    ) -> int:
        where_sql, parameters = _text_record_filter_sql(
            corpus_id,
            search_text=search_text,
            category_id=category_id,
            uncategorized_only=uncategorized_only,
        )
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            row = connection.execute(
                f"SELECT COUNT(*) FROM text_records WHERE {where_sql}",
                parameters,
            ).fetchone()
        return int(row[0] or 0) if row is not None else 0

    def fetch_text_records_page(
        self,
        corpus_id: str,
        *,
        limit: int,
        offset: int,
        search_text: str = "",
        category_id: str | None = None,
        uncategorized_only: bool = False,
    ) -> tuple[TextRecord, ...]:
        where_sql, parameters = _text_record_filter_sql(
            corpus_id,
            search_text=search_text,
            category_id=category_id,
            uncategorized_only=uncategorized_only,
        )
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            rows = connection.execute(
                f"""
                SELECT
                    id, content, primary_category_id, source, location, speaker,
                    record_time, note, custom_fields_json, created_at, updated_at,
                    schema_version
                FROM text_records
                WHERE {where_sql}
                ORDER BY created_at ASC, id ASC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
            record_ids = [str(row[0]) for row in rows]
            tag_rows = _fetch_tags_for_records(connection, record_ids)
        tags_by_record: dict[str, list[str]] = {}
        for record_id, tag in tag_rows:
            tags_by_record.setdefault(str(record_id), []).append(str(tag))
        return tuple(_text_record_from_row(row, tags_by_record) for row in rows)

    def upsert_category(self, category: Category) -> None:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            connection.execute(
                "DELETE FROM text_categories WHERE id = ? OR name = ?",
                [category.id, category.name],
            )
            connection.execute(
                """
                INSERT INTO text_categories (
                    id, name, description, color, created_at, updated_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    category.id,
                    category.name,
                    category.description,
                    category.color,
                    category.created_at,
                    category.updated_at,
                    category.schema_version,
                ],
            )

    def update_text_record(self, corpus_id: str, record: TextRecord) -> None:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            connection.execute("BEGIN TRANSACTION")
            try:
                existing = connection.execute(
                    "SELECT id FROM text_records WHERE id = ? AND corpus_id = ?",
                    [record.id, corpus_id],
                ).fetchone()
                if existing is None:
                    raise ValueError(f"Text record does not exist in corpus: {record.id}")
                connection.execute(
                    """
                    UPDATE text_records
                    SET
                        content = ?,
                        primary_category_id = ?,
                        source = ?,
                        location = ?,
                        speaker = ?,
                        record_time = ?,
                        note = ?,
                        custom_fields_json = ?,
                        updated_at = ?,
                        schema_version = ?
                    WHERE id = ? AND corpus_id = ?
                    """,
                    [
                        record.content,
                        record.primary_category_id,
                        record.source,
                        record.location,
                        record.speaker,
                        record.record_time,
                        record.note,
                        json.dumps(record.custom_fields, ensure_ascii=False),
                        record.updated_at,
                        record.schema_version,
                        record.id,
                        corpus_id,
                    ],
                )
                connection.execute("DELETE FROM text_record_tags WHERE record_id = ?", [record.id])
                if record.tags:
                    connection.executemany(
                        """
                        INSERT OR REPLACE INTO text_record_tags (record_id, tag, tag_order)
                        VALUES (?, ?, ?)
                        """,
                        [
                            (record.id, tag, tag_index)
                            for tag_index, tag in enumerate(record.tags)
                        ],
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def list_categories(self) -> tuple[Category, ...]:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            rows = connection.execute(
                """
                SELECT id, name, description, color, created_at, updated_at, schema_version
                FROM text_categories
                ORDER BY name ASC
                """
            ).fetchall()
        return tuple(_category_from_row(row) for row in rows)

    def category_usage_counts(self, corpus_id: str) -> dict[str, int]:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            rows = connection.execute(
                """
                SELECT primary_category_id, COUNT(*)
                FROM text_records
                WHERE corpus_id = ? AND primary_category_id IS NOT NULL
                GROUP BY primary_category_id
                """,
                [corpus_id],
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

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

    def correlation_stats(
        self,
        table_name: str,
        left_column: WorkspaceColumn,
        right_column: WorkspaceColumn,
    ) -> WorkspaceCorrelationStats:
        table_sql = quote_identifier(table_name)
        left_sql = quote_identifier(left_column.name)
        right_sql = quote_identifier(right_column.name)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS row_count,
                    CORR(CAST({left_sql} AS DOUBLE), CAST({right_sql} AS DOUBLE))
                FROM {table_sql}
                WHERE {left_sql} IS NOT NULL
                  AND {right_sql} IS NOT NULL
                """
            ).fetchone()
        row_count = int(row[0] or 0) if row is not None else 0
        correlation = float(row[1]) if row is not None and row[1] is not None else None
        return WorkspaceCorrelationStats(
            left_column=left_column.name,
            right_column=right_column.name,
            row_count=row_count,
            correlation=correlation,
        )

    def trend_stats(
        self,
        table_name: str,
        time_column: WorkspaceColumn,
        numeric_column: WorkspaceColumn,
    ) -> WorkspaceTrendStats:
        table_sql = quote_identifier(table_name)
        time_sql = quote_identifier(time_column.name)
        numeric_sql = quote_identifier(numeric_column.name)
        with self._connect() as connection:
            summary_row = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        CAST({time_sql} AS TIMESTAMP) AS time_value,
                        CAST({numeric_sql} AS DOUBLE) AS numeric_value
                    FROM {table_sql}
                    WHERE {time_sql} IS NOT NULL
                      AND {numeric_sql} IS NOT NULL
                )
                SELECT
                    COUNT(*) AS row_count,
                    CORR(EPOCH(time_value), numeric_value) AS correlation,
                    REGR_SLOPE(numeric_value, EPOCH(time_value)) * 86400 AS slope_per_day,
                    MIN(time_value) AS first_time,
                    MAX(time_value) AS last_time
                FROM clean
                """
            ).fetchone()
            first_row = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        CAST({time_sql} AS TIMESTAMP) AS time_value,
                        CAST({numeric_sql} AS DOUBLE) AS numeric_value
                    FROM {table_sql}
                    WHERE {time_sql} IS NOT NULL
                      AND {numeric_sql} IS NOT NULL
                )
                SELECT numeric_value
                FROM clean
                ORDER BY time_value ASC
                LIMIT 1
                """
            ).fetchone()
            last_row = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        CAST({time_sql} AS TIMESTAMP) AS time_value,
                        CAST({numeric_sql} AS DOUBLE) AS numeric_value
                    FROM {table_sql}
                    WHERE {time_sql} IS NOT NULL
                      AND {numeric_sql} IS NOT NULL
                )
                SELECT numeric_value
                FROM clean
                ORDER BY time_value DESC
                LIMIT 1
                """
            ).fetchone()
        row_count = int(summary_row[0] or 0) if summary_row is not None else 0
        correlation = (
            float(summary_row[1])
            if summary_row is not None and summary_row[1] is not None
            else None
        )
        slope_per_day = (
            float(summary_row[2])
            if summary_row is not None and summary_row[2] is not None
            else None
        )
        return WorkspaceTrendStats(
            time_column=time_column.name,
            numeric_column=numeric_column.name,
            row_count=row_count,
            correlation=correlation,
            slope_per_day=slope_per_day,
            first_time=summary_row[3] if summary_row is not None else None,
            last_time=summary_row[4] if summary_row is not None else None,
            first_value=(
                float(first_row[0]) if first_row is not None and first_row[0] is not None else None
            ),
            last_value=(
                float(last_row[0]) if last_row is not None and last_row[0] is not None else None
            ),
        )

    def group_difference_stats(
        self,
        table_name: str,
        category_column: WorkspaceColumn,
        numeric_column: WorkspaceColumn,
        *,
        min_group_count: int = 2,
    ) -> WorkspaceGroupDifferenceStats | None:
        table_sql = quote_identifier(table_name)
        category_sql = quote_identifier(category_column.name)
        numeric_sql = quote_identifier(numeric_column.name)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    CAST({category_sql} AS VARCHAR) AS category,
                    COUNT(*) AS row_count,
                    AVG(CAST({numeric_sql} AS DOUBLE)) AS mean_value
                FROM {table_sql}
                WHERE {category_sql} IS NOT NULL
                  AND {numeric_sql} IS NOT NULL
                GROUP BY category
                HAVING COUNT(*) >= ?
                ORDER BY mean_value DESC, category ASC
                """,
                [min_group_count],
            ).fetchall()
        if len(rows) < 2:
            return None
        top = rows[0]
        bottom = rows[-1]
        top_mean = float(top[2])
        bottom_mean = float(bottom[2])
        mean_difference = top_mean - bottom_mean
        mean_ratio = None if bottom_mean == 0 else top_mean / bottom_mean
        return WorkspaceGroupDifferenceStats(
            category_column=category_column.name,
            numeric_column=numeric_column.name,
            row_count=sum(int(row[1]) for row in rows),
            category_count=len(rows),
            top_category=str(top[0]),
            top_mean=top_mean,
            top_count=int(top[1]),
            bottom_category=str(bottom[0]),
            bottom_mean=bottom_mean,
            bottom_count=int(bottom[1]),
            mean_difference=mean_difference,
            mean_ratio=mean_ratio,
        )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))

    def _ensure_text_tables(self, connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS text_categories (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL UNIQUE,
                description VARCHAR NOT NULL,
                color VARCHAR NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                schema_version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS text_records (
                id VARCHAR PRIMARY KEY,
                corpus_id VARCHAR NOT NULL,
                content VARCHAR NOT NULL,
                primary_category_id VARCHAR,
                source VARCHAR,
                location VARCHAR,
                speaker VARCHAR,
                record_time TIMESTAMP,
                note VARCHAR NOT NULL,
                custom_fields_json VARCHAR NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                schema_version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS text_record_tags (
                record_id VARCHAR NOT NULL,
                tag VARCHAR NOT NULL,
                tag_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (record_id, tag)
            )
            """
        )
        with suppress(duckdb.CatalogException):
            connection.execute(
                "ALTER TABLE text_record_tags ADD COLUMN tag_order INTEGER DEFAULT 0"
            )

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


def _text_record_filter_sql(
    corpus_id: str,
    *,
    search_text: str,
    category_id: str | None,
    uncategorized_only: bool,
) -> tuple[str, list[object]]:
    clauses = ["corpus_id = ?"]
    parameters: list[object] = [corpus_id]
    normalized_search = search_text.strip().casefold()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        clauses.append(
            """
            (
                LOWER(content) LIKE ?
                OR LOWER(COALESCE(source, '')) LIKE ?
                OR LOWER(COALESCE(location, '')) LIKE ?
                OR LOWER(COALESCE(speaker, '')) LIKE ?
                OR LOWER(note) LIKE ?
            )
            """
        )
        parameters.extend([pattern, pattern, pattern, pattern, pattern])
    if uncategorized_only:
        clauses.append("primary_category_id IS NULL")
    elif category_id:
        clauses.append("primary_category_id = ?")
        parameters.append(category_id)
    return " AND ".join(clauses), parameters


def _fetch_tags_for_records(
    connection: duckdb.DuckDBPyConnection,
    record_ids: list[str],
) -> tuple[tuple[Any, ...], ...]:
    if not record_ids:
        return ()
    placeholders = ", ".join("?" for _ in record_ids)
    rows = connection.execute(
        f"""
        SELECT record_id, tag
        FROM text_record_tags
        WHERE record_id IN ({placeholders})
        ORDER BY record_id ASC, tag_order ASC, tag ASC
        """,
        record_ids,
    ).fetchall()
    return tuple(tuple(row) for row in rows)


def _text_record_from_row(row: tuple[Any, ...], tags_by_record: dict[str, list[str]]) -> TextRecord:
    record_id = str(row[0])
    custom_fields = json.loads(str(row[8] or "{}"))
    if not isinstance(custom_fields, dict):
        custom_fields = {}
    return TextRecord(
        id=record_id,
        content=str(row[1]),
        primary_category_id=str(row[2]) if row[2] is not None else None,
        source=str(row[3]) if row[3] is not None else None,
        location=str(row[4]) if row[4] is not None else None,
        speaker=str(row[5]) if row[5] is not None else None,
        record_time=_datetime_or_none(row[6]),
        note=str(row[7] or ""),
        custom_fields=custom_fields,
        created_at=_datetime_or_none(row[9]) or datetime.min,
        updated_at=_datetime_or_none(row[10]) or datetime.min,
        schema_version=int(row[11]),
        tags=tuple(tags_by_record.get(record_id, ())),
    )


def _category_from_row(row: tuple[Any, ...]) -> Category:
    return Category(
        id=str(row[0]),
        name=str(row[1]),
        description=str(row[2]),
        color=str(row[3]),
        created_at=_datetime_or_none(row[4]) or datetime.min,
        updated_at=_datetime_or_none(row[5]) or datetime.min,
        schema_version=int(row[6]),
    )


def _datetime_or_none(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None
