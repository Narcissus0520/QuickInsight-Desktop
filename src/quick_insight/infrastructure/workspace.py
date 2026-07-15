from __future__ import annotations

import csv
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from quick_insight.domain.models import (
    Category,
    CategoryAuditRecord,
    PreparedChartDataset,
    TextRecord,
    TransformStep,
)
from quick_insight.infrastructure.csv_import import CsvImportOptions
from quick_insight.infrastructure.sql import quote_identifier
from quick_insight.infrastructure.transform_sql import compile_transform_query


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

    def export_table_to_csv(self, table_name: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                f"COPY {quote_identifier(table_name)} TO ? (FORMAT CSV, HEADER TRUE)",
                [str(destination)],
            )

    def materialize_transform(
        self,
        source_table: str,
        destination_table: str,
        steps: tuple[TransformStep, ...],
    ) -> None:
        if source_table == destination_table:
            raise ValueError("Transform destination must not overwrite the source table.")
        source_columns = self.columns(source_table)
        compiled = compile_transform_query(source_table, source_columns, steps)
        destination_sql = quote_identifier(destination_table)
        with self._connect() as connection:
            connection.execute(f"DROP TABLE IF EXISTS {destination_sql}")
            connection.execute(
                f"CREATE TABLE {destination_sql} AS {compiled.sql}",
                list(compiled.parameters),
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

    def list_category_audit(
        self,
        corpus_id: str,
        *,
        limit: int = 100,
    ) -> tuple[CategoryAuditRecord, ...]:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            rows = connection.execute(
                """
                SELECT
                    id, corpus_id, action, source_category_id, source_category_name,
                    target_category_id, target_category_name, affected_record_count,
                    note, created_at, schema_version
                FROM text_category_audit
                WHERE corpus_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                [corpus_id, limit],
            ).fetchall()
        return tuple(_category_audit_from_row(row) for row in rows)

    def rename_category(
        self,
        corpus_id: str,
        category_id: str,
        *,
        new_name: str,
        new_description: str,
        audit_id: str,
        note: str,
        changed_at: datetime,
    ) -> CategoryAuditRecord:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            connection.execute("BEGIN TRANSACTION")
            try:
                category = _fetch_category_by_id(connection, category_id)
                if category is None:
                    raise ValueError(f"Category does not exist: {category_id}")
                duplicate = connection.execute(
                    """
                    SELECT id
                    FROM text_categories
                    WHERE LOWER(name) = LOWER(?) AND id <> ?
                    """,
                    [new_name, category_id],
                ).fetchone()
                if duplicate is not None:
                    raise ValueError(f"Category name already exists: {new_name}")
                outside_count = _text_category_usage_outside_corpus_count(
                    connection,
                    corpus_id,
                    category_id,
                )
                if outside_count:
                    raise ValueError(
                        "Category is used by another text corpus "
                        f"({outside_count} records)."
                    )
                affected_count = _text_category_usage_count(
                    connection,
                    corpus_id,
                    category_id,
                )
                connection.execute(
                    """
                    UPDATE text_categories
                    SET name = ?, description = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    [new_name, new_description, changed_at, category_id],
                )
                audit = CategoryAuditRecord(
                    id=audit_id,
                    corpus_id=corpus_id,
                    action="rename",
                    source_category_id=category.id,
                    source_category_name=category.name,
                    target_category_id=category.id,
                    target_category_name=new_name,
                    affected_record_count=affected_count,
                    note=note,
                    created_at=changed_at,
                )
                _insert_category_audit(connection, audit)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return audit

    def merge_categories(
        self,
        corpus_id: str,
        source_category_id: str,
        target_category_id: str,
        *,
        audit_id: str,
        note: str,
        changed_at: datetime,
    ) -> CategoryAuditRecord:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            connection.execute("BEGIN TRANSACTION")
            try:
                if source_category_id == target_category_id:
                    raise ValueError("Source and target category must be different.")
                source = _fetch_category_by_id(connection, source_category_id)
                target = _fetch_category_by_id(connection, target_category_id)
                if source is None:
                    raise ValueError(f"Source category does not exist: {source_category_id}")
                if target is None:
                    raise ValueError(f"Target category does not exist: {target_category_id}")
                outside_count = _text_category_usage_outside_corpus_count(
                    connection,
                    corpus_id,
                    source_category_id,
                )
                if outside_count:
                    raise ValueError(
                        "Source category is used by another text corpus "
                        f"({outside_count} records)."
                    )
                affected_count = _text_category_usage_count(
                    connection,
                    corpus_id,
                    source_category_id,
                )
                connection.execute(
                    """
                    UPDATE text_records
                    SET primary_category_id = ?, updated_at = ?
                    WHERE corpus_id = ? AND primary_category_id = ?
                    """,
                    [target_category_id, changed_at, corpus_id, source_category_id],
                )
                connection.execute(
                    "DELETE FROM text_categories WHERE id = ?",
                    [source_category_id],
                )
                audit = CategoryAuditRecord(
                    id=audit_id,
                    corpus_id=corpus_id,
                    action="merge",
                    source_category_id=source.id,
                    source_category_name=source.name,
                    target_category_id=target.id,
                    target_category_name=target.name,
                    affected_record_count=affected_count,
                    note=note,
                    created_at=changed_at,
                )
                _insert_category_audit(connection, audit)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return audit

    def delete_category(
        self,
        corpus_id: str,
        category_id: str,
        *,
        replacement_category_id: str | None,
        audit_id: str,
        note: str,
        changed_at: datetime,
    ) -> CategoryAuditRecord:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            connection.execute("BEGIN TRANSACTION")
            try:
                category = _fetch_category_by_id(connection, category_id)
                if category is None:
                    raise ValueError(f"Category does not exist: {category_id}")
                if replacement_category_id == category_id:
                    raise ValueError("Replacement category must be different.")
                replacement = (
                    _fetch_category_by_id(connection, replacement_category_id)
                    if replacement_category_id is not None
                    else None
                )
                if replacement_category_id is not None and replacement is None:
                    raise ValueError(
                        f"Replacement category does not exist: {replacement_category_id}"
                    )
                outside_count = _text_category_usage_outside_corpus_count(
                    connection,
                    corpus_id,
                    category_id,
                )
                if outside_count:
                    raise ValueError(
                        "Category is used by another text corpus "
                        f"({outside_count} records)."
                    )
                affected_count = _text_category_usage_count(
                    connection,
                    corpus_id,
                    category_id,
                )
                connection.execute(
                    """
                    UPDATE text_records
                    SET primary_category_id = ?, updated_at = ?
                    WHERE corpus_id = ? AND primary_category_id = ?
                    """,
                    [replacement_category_id, changed_at, corpus_id, category_id],
                )
                connection.execute(
                    "DELETE FROM text_categories WHERE id = ?",
                    [category_id],
                )
                audit = CategoryAuditRecord(
                    id=audit_id,
                    corpus_id=corpus_id,
                    action="delete_to_category"
                    if replacement_category_id is not None
                    else "delete_to_uncategorized",
                    source_category_id=category.id,
                    source_category_name=category.name,
                    target_category_id=replacement.id if replacement is not None else None,
                    target_category_name=replacement.name if replacement is not None else None,
                    affected_record_count=affected_count,
                    note=note,
                    created_at=changed_at,
                )
                _insert_category_audit(connection, audit)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return audit

    def export_text_corpus_to_csv(self, corpus_id: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            cursor = connection.execute(
                """
                SELECT
                    r.id,
                    r.content,
                    COALESCE(c.name, '') AS primary_category,
                    COALESCE(tags.tags, '') AS tags,
                    COALESCE(r.source, '') AS source,
                    COALESCE(r.location, '') AS location,
                    COALESCE(r.speaker, '') AS speaker,
                    r.record_time,
                    r.note,
                    r.custom_fields_json,
                    r.created_at,
                    r.updated_at,
                    r.schema_version
                FROM text_records AS r
                LEFT JOIN text_categories AS c ON r.primary_category_id = c.id
                LEFT JOIN (
                    SELECT
                        record_id,
                        STRING_AGG(tag, ', ' ORDER BY tag_order ASC, tag ASC) AS tags
                    FROM text_record_tags
                    GROUP BY record_id
                ) AS tags ON r.id = tags.record_id
                WHERE r.corpus_id = ?
                ORDER BY r.created_at ASC, r.id ASC
                """,
                [corpus_id],
            )
            with destination.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    [
                        "id",
                        "content",
                        "primary_category",
                        "tags",
                        "source",
                        "location",
                        "speaker",
                        "record_time",
                        "note",
                        "custom_fields_json",
                        "created_at",
                        "updated_at",
                        "schema_version",
                    ]
                )
                while True:
                    rows = cursor.fetchmany(1000)
                    if not rows:
                        break
                    writer.writerows(rows)

    def export_text_corpus_to_jsonl(self, corpus_id: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            cursor = connection.execute(
                """
                SELECT
                    r.id,
                    r.content,
                    COALESCE(c.name, '') AS primary_category,
                    tags.tags,
                    r.source,
                    r.location,
                    r.speaker,
                    r.record_time,
                    r.note,
                    r.custom_fields_json,
                    r.created_at,
                    r.updated_at,
                    r.schema_version
                FROM text_records AS r
                LEFT JOIN text_categories AS c ON r.primary_category_id = c.id
                LEFT JOIN (
                    SELECT
                        record_id,
                        LIST(tag ORDER BY tag_order ASC, tag ASC) AS tags
                    FROM text_record_tags
                    GROUP BY record_id
                ) AS tags ON r.id = tags.record_id
                WHERE r.corpus_id = ?
                ORDER BY r.created_at ASC, r.id ASC
                """,
                [corpus_id],
            )
            with destination.open("w", encoding="utf-8", newline="\n") as stream:
                while True:
                    rows = cursor.fetchmany(1000)
                    if not rows:
                        break
                    for row in rows:
                        stream.write(
                            json.dumps(
                                _text_export_json_payload(row),
                                ensure_ascii=False,
                                default=str,
                            )
                            + "\n"
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
                GROUP BY CAST({column_sql} AS VARCHAR)
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

    def chart_time_series(
        self,
        table_name: str,
        time_column: WorkspaceColumn,
        numeric_column: WorkspaceColumn,
        *,
        target_points: int,
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        time_sql = quote_identifier(time_column.name)
        numeric_sql = quote_identifier(numeric_column.name)
        with self._connect() as connection:
            count_row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_sql}
                WHERE {time_sql} IS NOT NULL
                  AND {numeric_sql} IS NOT NULL
                """
            ).fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            if original_rows <= max(target_points, 1):
                rows = connection.execute(
                    f"""
                    SELECT
                        CAST({time_sql} AS TIMESTAMP) AS x_value,
                        CAST({numeric_sql} AS DOUBLE) AS y_value,
                        1 AS source_count
                    FROM {table_sql}
                    WHERE {time_sql} IS NOT NULL
                      AND {numeric_sql} IS NOT NULL
                    ORDER BY x_value ASC
                    """,
                ).fetchall()
                return PreparedChartDataset(
                    columns=("x", "y", "source_count"),
                    rows=tuple(tuple(row) for row in rows),
                    original_rows=original_rows,
                    rendered_rows=len(rows),
                    method="raw_time_series",
                    parameters={
                        "time_column": time_column.name,
                        "numeric_column": numeric_column.name,
                        "target_points": target_points,
                    },
                    approximate=False,
                )
            rows = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        CAST({time_sql} AS TIMESTAMP) AS x_value,
                        CAST({numeric_sql} AS DOUBLE) AS y_value
                    FROM {table_sql}
                    WHERE {time_sql} IS NOT NULL
                      AND {numeric_sql} IS NOT NULL
                ),
                numbered AS (
                    SELECT
                        x_value,
                        y_value,
                        ROW_NUMBER() OVER (ORDER BY x_value ASC) AS row_number,
                        COUNT(*) OVER () AS total_rows
                    FROM clean
                ),
                bucketed AS (
                    SELECT
                        CAST(FLOOR(((row_number - 1) * ?) / total_rows) AS BIGINT) AS bucket,
                        x_value,
                        y_value
                    FROM numbered
                )
                SELECT
                    MIN(x_value) AS x_value,
                    AVG(y_value) AS y_value,
                    COUNT(*) AS source_count
                FROM bucketed
                GROUP BY bucket
                ORDER BY bucket ASC
                """,
                [target_points],
            ).fetchall()
        return PreparedChartDataset(
            columns=("x", "y", "source_count"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="time_window_mean",
            parameters={
                "time_column": time_column.name,
                "numeric_column": numeric_column.name,
                "target_points": target_points,
            },
            approximate=True,
        )

    def chart_category_numeric_top_n(
        self,
        table_name: str,
        category_column: WorkspaceColumn,
        numeric_column: WorkspaceColumn,
        *,
        limit: int,
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        category_sql = quote_identifier(category_column.name)
        numeric_sql = quote_identifier(numeric_column.name)
        rows, original_rows = self._category_numeric_rows(
            table_sql,
            category_sql,
            numeric_sql,
            limit=limit,
        )
        return PreparedChartDataset(
            columns=("category", "value", "source_count"),
            rows=rows,
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="top_n_with_other",
            parameters={
                "category_column": category_column.name,
                "numeric_column": numeric_column.name,
                "limit": limit,
                "aggregation": "weighted_mean",
                "other_label": "Other",
            },
            approximate=False,
        )

    def chart_category_count_top_n(
        self,
        table_name: str,
        category_column: WorkspaceColumn,
        *,
        limit: int,
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        category_sql = quote_identifier(category_column.name)
        with self._connect() as connection:
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM {table_sql} WHERE {category_sql} IS NOT NULL"
            ).fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            rows = connection.execute(
                f"""
                WITH grouped AS (
                    SELECT
                        CAST({category_sql} AS VARCHAR) AS category,
                        COUNT(*) AS source_count
                    FROM {table_sql}
                    WHERE {category_sql} IS NOT NULL
                    GROUP BY category
                ),
                ranked AS (
                    SELECT
                        category,
                        source_count,
                        ROW_NUMBER() OVER (ORDER BY source_count DESC, category ASC) AS rank
                    FROM grouped
                ),
                aggregated AS (
                    SELECT
                        CASE WHEN rank <= ? THEN category ELSE 'Other' END AS category,
                        SUM(source_count) AS source_count
                    FROM ranked
                    GROUP BY 1
                )
                SELECT category, source_count
                FROM aggregated
                ORDER BY
                    CASE WHEN category = 'Other' THEN 1 ELSE 0 END ASC,
                    source_count DESC,
                    category ASC
                """,
                [limit],
            ).fetchall()
        return PreparedChartDataset(
            columns=("category", "source_count"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="top_n_with_other",
            parameters={
                "category_column": category_column.name,
                "limit": limit,
                "aggregation": "count",
                "other_label": "Other",
            },
            approximate=False,
        )

    def chart_histogram_bins(
        self,
        table_name: str,
        numeric_column: WorkspaceColumn,
        *,
        bins: int,
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        numeric_sql = quote_identifier(numeric_column.name)
        with self._connect() as connection:
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM {table_sql} WHERE {numeric_sql} IS NOT NULL"
            ).fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            rows = connection.execute(
                f"""
                WITH clean AS (
                    SELECT CAST({numeric_sql} AS DOUBLE) AS value
                    FROM {table_sql}
                    WHERE {numeric_sql} IS NOT NULL
                ),
                stats AS (
                    SELECT MIN(value) AS min_value, MAX(value) AS max_value
                    FROM clean
                ),
                binned AS (
                    SELECT
                        CASE
                            WHEN stats.max_value = stats.min_value THEN 0
                            ELSE LEAST(
                                ? - 1,
                                GREATEST(
                                    0,
                                    CAST(
                                        FLOOR(
                                            ((value - stats.min_value)
                                             / (stats.max_value - stats.min_value)) * ?
                                        ) AS BIGINT
                                    )
                                )
                            )
                        END AS bin_index,
                        stats.min_value,
                        stats.max_value
                    FROM clean, stats
                )
                SELECT
                    min_value + ((max_value - min_value) * bin_index / ?) AS bin_start,
                    min_value + ((max_value - min_value) * (bin_index + 1) / ?) AS bin_end,
                    COUNT(*) AS source_count
                FROM binned
                GROUP BY bin_index, min_value, max_value
                ORDER BY bin_index ASC
                """,
                [bins, bins, bins, bins],
            ).fetchall()
        return PreparedChartDataset(
            columns=("bin_start", "bin_end", "source_count"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="histogram_bins",
            parameters={"numeric_column": numeric_column.name, "bins": bins},
            approximate=False,
        )

    def chart_scatter_sample(
        self,
        table_name: str,
        x_column: WorkspaceColumn,
        y_column: WorkspaceColumn,
        *,
        target_points: int,
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        x_sql = quote_identifier(x_column.name)
        y_sql = quote_identifier(y_column.name)
        with self._connect() as connection:
            count_row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_sql}
                WHERE {x_sql} IS NOT NULL
                  AND {y_sql} IS NOT NULL
                """
            ).fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            if original_rows <= max(target_points, 1):
                rows = connection.execute(
                    f"""
                    SELECT
                        CAST({x_sql} AS DOUBLE) AS x_value,
                        CAST({y_sql} AS DOUBLE) AS y_value
                    FROM {table_sql}
                    WHERE {x_sql} IS NOT NULL
                      AND {y_sql} IS NOT NULL
                    ORDER BY x_value ASC, y_value ASC
                    """
                ).fetchall()
                return PreparedChartDataset(
                    columns=("x", "y"),
                    rows=tuple(tuple(row) for row in rows),
                    original_rows=original_rows,
                    rendered_rows=len(rows),
                    method="raw_scatter",
                    parameters={
                        "x_column": x_column.name,
                        "y_column": y_column.name,
                        "target_points": target_points,
                    },
                    approximate=False,
                )
            rows = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        CAST({x_sql} AS DOUBLE) AS x_value,
                        CAST({y_sql} AS DOUBLE) AS y_value
                    FROM {table_sql}
                    WHERE {x_sql} IS NOT NULL
                      AND {y_sql} IS NOT NULL
                ),
                numbered AS (
                    SELECT
                        x_value,
                        y_value,
                        ROW_NUMBER() OVER (ORDER BY x_value ASC, y_value ASC) AS row_number,
                        COUNT(*) OVER () AS total_rows
                    FROM clean
                )
                SELECT x_value, y_value
                FROM numbered
                WHERE ((row_number - 1) % CAST(CEIL(total_rows::DOUBLE / ?) AS BIGINT)) = 0
                ORDER BY row_number ASC
                LIMIT ?
                """,
                [target_points, target_points],
            ).fetchall()
        return PreparedChartDataset(
            columns=("x", "y"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="uniform_sample",
            parameters={
                "x_column": x_column.name,
                "y_column": y_column.name,
                "target_points": target_points,
            },
            approximate=True,
        )

    def chart_density_bins(
        self,
        table_name: str,
        x_column: WorkspaceColumn,
        y_column: WorkspaceColumn,
        *,
        x_bins: int,
        y_bins: int,
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        x_sql = quote_identifier(x_column.name)
        y_sql = quote_identifier(y_column.name)
        with self._connect() as connection:
            count_row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_sql}
                WHERE {x_sql} IS NOT NULL
                  AND {y_sql} IS NOT NULL
                """
            ).fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            rows = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        CAST({x_sql} AS DOUBLE) AS x_value,
                        CAST({y_sql} AS DOUBLE) AS y_value
                    FROM {table_sql}
                    WHERE {x_sql} IS NOT NULL
                      AND {y_sql} IS NOT NULL
                ),
                stats AS (
                    SELECT
                        MIN(x_value) AS min_x,
                        MAX(x_value) AS max_x,
                        MIN(y_value) AS min_y,
                        MAX(y_value) AS max_y
                    FROM clean
                ),
                binned AS (
                    SELECT
                        CASE
                            WHEN stats.max_x = stats.min_x THEN 0
                            ELSE LEAST(
                                ? - 1,
                                GREATEST(
                                    0,
                                    CAST(
                                        FLOOR(
                                            ((x_value - stats.min_x)
                                             / (stats.max_x - stats.min_x)) * ?
                                        ) AS BIGINT
                                    )
                                )
                            )
                        END AS x_bin,
                        CASE
                            WHEN stats.max_y = stats.min_y THEN 0
                            ELSE LEAST(
                                ? - 1,
                                GREATEST(
                                    0,
                                    CAST(
                                        FLOOR(
                                            ((y_value - stats.min_y)
                                             / (stats.max_y - stats.min_y)) * ?
                                        ) AS BIGINT
                                    )
                                )
                            )
                        END AS y_bin,
                        stats.min_x,
                        stats.max_x,
                        stats.min_y,
                        stats.max_y
                    FROM clean, stats
                )
                SELECT
                    min_x + ((max_x - min_x) * (x_bin + 0.5) / ?) AS x_center,
                    min_y + ((max_y - min_y) * (y_bin + 0.5) / ?) AS y_center,
                    COUNT(*) AS source_count
                FROM binned
                GROUP BY x_bin, y_bin, min_x, max_x, min_y, max_y
                ORDER BY y_bin ASC, x_bin ASC
                """,
                [x_bins, x_bins, y_bins, y_bins, x_bins, y_bins],
            ).fetchall()
        return PreparedChartDataset(
            columns=("x", "y", "source_count"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="density_2d_bins",
            parameters={
                "x_column": x_column.name,
                "y_column": y_column.name,
                "x_bins": x_bins,
                "y_bins": y_bins,
            },
            approximate=True,
        )

    def chart_categorical_heatmap_top_n(
        self,
        table_name: str,
        x_column: WorkspaceColumn,
        y_column: WorkspaceColumn,
        *,
        x_limit: int,
        y_limit: int,
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        x_sql = quote_identifier(x_column.name)
        y_sql = quote_identifier(y_column.name)
        with self._connect() as connection:
            count_row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_sql}
                WHERE {x_sql} IS NOT NULL
                  AND {y_sql} IS NOT NULL
                """
            ).fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            rows = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        CAST({x_sql} AS VARCHAR) AS x_value,
                        CAST({y_sql} AS VARCHAR) AS y_value
                    FROM {table_sql}
                    WHERE {x_sql} IS NOT NULL
                      AND {y_sql} IS NOT NULL
                ),
                x_ranked AS (
                    SELECT
                        x_value,
                        ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, x_value ASC) AS x_rank
                    FROM clean
                    GROUP BY x_value
                ),
                y_ranked AS (
                    SELECT
                        y_value,
                        ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, y_value ASC) AS y_rank
                    FROM clean
                    GROUP BY y_value
                )
                SELECT
                    CASE WHEN x_rank <= ? THEN clean.x_value ELSE 'Other' END AS x_value,
                    CASE WHEN y_rank <= ? THEN clean.y_value ELSE 'Other' END AS y_value,
                    COUNT(*) AS source_count
                FROM clean
                JOIN x_ranked ON clean.x_value = x_ranked.x_value
                JOIN y_ranked ON clean.y_value = y_ranked.y_value
                GROUP BY 1, 2
                ORDER BY source_count DESC, x_value ASC, y_value ASC
                """,
                [x_limit, y_limit],
            ).fetchall()
        return PreparedChartDataset(
            columns=("x", "y", "source_count"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="categorical_top_n_crosstab",
            parameters={
                "x_column": x_column.name,
                "y_column": y_column.name,
                "x_limit": x_limit,
                "y_limit": y_limit,
                "other_label": "Other",
            },
            approximate=False,
        )

    def chart_box_quantiles_top_n(
        self,
        table_name: str,
        category_column: WorkspaceColumn,
        numeric_column: WorkspaceColumn,
        *,
        limit: int,
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        category_sql = quote_identifier(category_column.name)
        numeric_sql = quote_identifier(numeric_column.name)
        with self._connect() as connection:
            count_row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_sql}
                WHERE {category_sql} IS NOT NULL
                  AND {numeric_sql} IS NOT NULL
                """
            ).fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            rows = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        CAST({category_sql} AS VARCHAR) AS category,
                        CAST({numeric_sql} AS DOUBLE) AS value
                    FROM {table_sql}
                    WHERE {category_sql} IS NOT NULL
                      AND {numeric_sql} IS NOT NULL
                ),
                ranked_categories AS (
                    SELECT
                        category,
                        COUNT(*) AS source_count,
                        ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, category ASC) AS rank
                    FROM clean
                    GROUP BY category
                ),
                selected AS (
                    SELECT clean.category, clean.value
                    FROM clean
                    JOIN ranked_categories USING (category)
                    WHERE rank <= ?
                )
                SELECT
                    category,
                    MIN(value) AS lower_fence,
                    QUANTILE_CONT(value, 0.25) AS q1,
                    MEDIAN(value) AS median,
                    QUANTILE_CONT(value, 0.75) AS q3,
                    MAX(value) AS upper_fence,
                    COUNT(*) AS source_count
                FROM selected
                GROUP BY category
                ORDER BY source_count DESC, category ASC
                """,
                [limit],
            ).fetchall()
        rendered_source_rows = sum(int(row[6] or 0) for row in rows)
        return PreparedChartDataset(
            columns=(
                "category",
                "lower_fence",
                "q1",
                "median",
                "q3",
                "upper_fence",
                "source_count",
            ),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="box_quantiles_top_n",
            parameters={
                "category_column": category_column.name,
                "numeric_column": numeric_column.name,
                "limit": limit,
                "omitted_rows": max(original_rows - rendered_source_rows, 0),
            },
            approximate=rendered_source_rows < original_rows,
        )

    def chart_correlation_matrix(
        self,
        table_name: str,
        columns: tuple[WorkspaceColumn, ...],
    ) -> PreparedChartDataset:
        table_sql = quote_identifier(table_name)
        column_sql = tuple(quote_identifier(column.name) for column in columns)
        rows: list[tuple[Any, ...]] = []
        with self._connect() as connection:
            count_row = connection.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            for left_index, left_column in enumerate(columns):
                left_sql = column_sql[left_index]
                for right_index, right_column in enumerate(columns):
                    right_sql = column_sql[right_index]
                    if left_index == right_index:
                        pair_row = connection.execute(
                            f"""
                            SELECT COUNT(*)
                            FROM {table_sql}
                            WHERE {left_sql} IS NOT NULL
                            """
                        ).fetchone()
                        pair_count = int(pair_row[0] or 0) if pair_row is not None else 0
                        correlation = 1.0 if pair_count > 0 else None
                    else:
                        pair_row = connection.execute(
                            f"""
                            SELECT
                                COUNT(*) AS pair_count,
                                CORR(
                                    CAST({left_sql} AS DOUBLE),
                                    CAST({right_sql} AS DOUBLE)
                                ) AS correlation
                            FROM {table_sql}
                            WHERE {left_sql} IS NOT NULL
                              AND {right_sql} IS NOT NULL
                            """
                        ).fetchone()
                        pair_count = int(pair_row[0] or 0) if pair_row is not None else 0
                        correlation = (
                            float(pair_row[1])
                            if pair_row is not None and pair_row[1] is not None
                            else None
                        )
                    rows.append((left_column.name, right_column.name, correlation, pair_count))
        return PreparedChartDataset(
            columns=("x", "y", "value", "source_count"),
            rows=tuple(rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="pearson_correlation_matrix",
            parameters={"fields": tuple(column.name for column in columns)},
            approximate=False,
        )

    def chart_text_category_counts(
        self,
        corpus_id: str,
        *,
        limit: int,
    ) -> PreparedChartDataset:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            original_rows = _text_corpus_row_count(connection, corpus_id)
            rows = connection.execute(
                f"""
                WITH clean AS (
                    SELECT {_text_category_label_sql()} AS label
                    FROM text_records AS r
                    LEFT JOIN text_categories AS c ON r.primary_category_id = c.id
                    WHERE r.corpus_id = ?
                ),
                grouped AS (
                    SELECT label, COUNT(*) AS source_count
                    FROM clean
                    GROUP BY label
                ),
                ranked AS (
                    SELECT
                        label,
                        source_count,
                        ROW_NUMBER() OVER (ORDER BY source_count DESC, label ASC) AS rank
                    FROM grouped
                ),
                aggregated AS (
                    SELECT
                        CASE WHEN rank <= ? THEN label ELSE 'Other' END AS label,
                        SUM(source_count) AS source_count
                    FROM ranked
                    GROUP BY 1
                )
                SELECT label, source_count
                FROM aggregated
                ORDER BY
                    CASE WHEN label = 'Other' THEN 1 ELSE 0 END ASC,
                    source_count DESC,
                    label ASC
                """,
                [corpus_id, limit],
            ).fetchall()
        return PreparedChartDataset(
            columns=("x", "source_count"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="text_category_counts_top_n",
            parameters={"corpus_id": corpus_id, "limit": limit, "other_label": "Other"},
            approximate=False,
        )

    def chart_text_classification_status(self, corpus_id: str) -> PreparedChartDataset:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN primary_category_id IS NOT NULL THEN 1 ELSE 0 END)
                        AS categorized_count
                FROM text_records
                WHERE corpus_id = ?
                """,
                [corpus_id],
            ).fetchone()
        original_rows = int(row[0] or 0) if row is not None else 0
        categorized_count = int(row[1] or 0) if row is not None else 0
        uncategorized_count = max(original_rows - categorized_count, 0)
        rows = (("已分类", categorized_count), ("未分类", uncategorized_count))
        return PreparedChartDataset(
            columns=("x", "source_count"),
            rows=rows,
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="text_classification_status_counts",
            parameters={"corpus_id": corpus_id},
            approximate=False,
        )

    def chart_text_source_category_crosstab(
        self,
        corpus_id: str,
        *,
        x_limit: int,
        y_limit: int,
    ) -> PreparedChartDataset:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            original_rows = _text_corpus_row_count(connection, corpus_id)
            rows = connection.execute(
                f"""
                WITH clean AS (
                    SELECT
                        {_text_source_label_sql()} AS source_label,
                        {_text_category_label_sql()} AS category_label
                    FROM text_records AS r
                    LEFT JOIN text_categories AS c ON r.primary_category_id = c.id
                    WHERE r.corpus_id = ?
                ),
                source_ranked AS (
                    SELECT
                        source_label,
                        ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, source_label ASC) AS rank
                    FROM clean
                    GROUP BY source_label
                ),
                category_ranked AS (
                    SELECT
                        category_label,
                        ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, category_label ASC) AS rank
                    FROM clean
                    GROUP BY category_label
                )
                SELECT
                    CASE WHEN source_ranked.rank <= ? THEN source_label ELSE 'Other' END
                        AS source_label,
                    CASE WHEN category_ranked.rank <= ? THEN category_label ELSE 'Other' END
                        AS category_label,
                    COUNT(*) AS source_count
                FROM clean
                JOIN source_ranked USING (source_label)
                JOIN category_ranked USING (category_label)
                GROUP BY 1, 2
                ORDER BY source_count DESC, source_label ASC, category_label ASC
                """,
                [corpus_id, x_limit, y_limit],
            ).fetchall()
        return PreparedChartDataset(
            columns=("x", "y", "source_count"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="text_source_category_crosstab",
            parameters={
                "corpus_id": corpus_id,
                "x_limit": x_limit,
                "y_limit": y_limit,
                "other_label": "Other",
            },
            approximate=False,
        )

    def chart_text_keyword_counts(
        self,
        corpus_id: str,
        keywords: tuple[str, ...],
        *,
        limit: int,
    ) -> PreparedChartDataset:
        keywords = tuple(dict.fromkeys(keyword.strip() for keyword in keywords if keyword.strip()))
        limited_keywords = keywords[: max(limit, 0)]
        rows: list[tuple[Any, ...]] = []
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            original_rows = _text_corpus_row_count(connection, corpus_id)
            for keyword in limited_keywords:
                row = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM text_records
                    WHERE corpus_id = ?
                      AND LOWER(content) LIKE LOWER(?) ESCAPE '\\'
                    """,
                    [corpus_id, _like_pattern(keyword)],
                ).fetchone()
                rows.append((keyword, int(row[0] or 0) if row is not None else 0))
        rows.sort(key=lambda item: (-int(item[1]), str(item[0])))
        return PreparedChartDataset(
            columns=("x", "source_count"),
            rows=tuple(rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="text_keyword_counts",
            parameters={
                "corpus_id": corpus_id,
                "keywords": limited_keywords,
                "limit": limit,
            },
            approximate=len(limited_keywords) < len(keywords),
        )

    def chart_text_category_keyword_counts(
        self,
        corpus_id: str,
        keywords: tuple[str, ...],
        *,
        keyword_limit: int,
        category_limit: int,
    ) -> PreparedChartDataset:
        keywords = tuple(dict.fromkeys(keyword.strip() for keyword in keywords if keyword.strip()))
        limited_keywords = keywords[: max(keyword_limit, 0)]
        rows: list[tuple[Any, ...]] = []
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            original_rows = _text_corpus_row_count(connection, corpus_id)
            for keyword in limited_keywords:
                keyword_rows = connection.execute(
                    f"""
                    WITH clean AS (
                        SELECT {_text_category_label_sql()} AS category_label
                        FROM text_records AS r
                        LEFT JOIN text_categories AS c ON r.primary_category_id = c.id
                        WHERE r.corpus_id = ?
                          AND LOWER(r.content) LIKE LOWER(?) ESCAPE '\\'
                    ),
                    grouped AS (
                        SELECT category_label, COUNT(*) AS source_count
                        FROM clean
                        GROUP BY category_label
                    ),
                    ranked AS (
                        SELECT
                            category_label,
                            source_count,
                            ROW_NUMBER() OVER (
                                ORDER BY source_count DESC, category_label ASC
                            ) AS rank
                        FROM grouped
                    )
                    SELECT
                        CASE WHEN rank <= ? THEN category_label ELSE 'Other' END
                            AS category_label,
                        SUM(source_count) AS source_count
                    FROM ranked
                    GROUP BY 1
                    ORDER BY source_count DESC, category_label ASC
                    """,
                    [corpus_id, _like_pattern(keyword), category_limit],
                ).fetchall()
                rows.extend((keyword, row[0], row[1]) for row in keyword_rows)
        return PreparedChartDataset(
            columns=("x", "y", "source_count"),
            rows=tuple(tuple(row) for row in rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="text_category_keyword_counts",
            parameters={
                "corpus_id": corpus_id,
                "keywords": limited_keywords,
                "keyword_limit": keyword_limit,
                "category_limit": category_limit,
                "other_label": "Other",
            },
            approximate=len(limited_keywords) < len(keywords),
        )

    def chart_text_tag_cooccurrence(
        self,
        corpus_id: str,
        *,
        tag_limit: int,
    ) -> PreparedChartDataset:
        with self._connect() as connection:
            self._ensure_text_tables(connection)
            original_rows = _text_corpus_row_count(connection, corpus_id)
            total_tag_row = connection.execute(
                """
                SELECT COUNT(DISTINCT t.tag)
                FROM text_record_tags AS t
                JOIN text_records AS r ON t.record_id = r.id
                WHERE r.corpus_id = ?
                """,
                [corpus_id],
            ).fetchone()
            total_tag_count = (
                int(total_tag_row[0] or 0) if total_tag_row is not None else 0
            )
            tag_rows = connection.execute(
                """
                SELECT t.tag, COUNT(DISTINCT t.record_id) AS source_count
                FROM text_record_tags AS t
                JOIN text_records AS r ON t.record_id = r.id
                WHERE r.corpus_id = ?
                GROUP BY t.tag
                ORDER BY source_count DESC, t.tag ASC
                LIMIT ?
                """,
                [corpus_id, tag_limit],
            ).fetchall()
            top_tags = tuple(str(row[0]) for row in tag_rows)
            if not top_tags:
                pair_rows: tuple[tuple[Any, ...], ...] = ()
            else:
                placeholders = ", ".join("?" for _ in top_tags)
                pair_rows = tuple(
                    tuple(row)
                    for row in connection.execute(
                        f"""
                        WITH filtered AS (
                            SELECT t.record_id, t.tag
                            FROM text_record_tags AS t
                            JOIN text_records AS r ON t.record_id = r.id
                            WHERE r.corpus_id = ?
                              AND t.tag IN ({placeholders})
                        )
                        SELECT
                            left_tags.tag AS left_tag,
                            right_tags.tag AS right_tag,
                            COUNT(*) AS source_count
                        FROM filtered AS left_tags
                        JOIN filtered AS right_tags
                          ON left_tags.record_id = right_tags.record_id
                         AND left_tags.tag < right_tags.tag
                        GROUP BY left_tags.tag, right_tags.tag
                        ORDER BY source_count DESC, left_tag ASC, right_tag ASC
                        """,
                        [corpus_id, *top_tags],
                    ).fetchall()
                )
        rows: list[tuple[Any, ...]] = []
        tag_counts = {str(row[0]): int(row[1] or 0) for row in tag_rows}
        for tag in top_tags:
            rows.append((tag, tag, tag_counts.get(tag, 0)))
        for left_tag, right_tag, source_count in pair_rows:
            count = int(source_count or 0)
            rows.append((left_tag, right_tag, count))
            rows.append((right_tag, left_tag, count))
        return PreparedChartDataset(
            columns=("x", "y", "source_count"),
            rows=tuple(rows),
            original_rows=original_rows,
            rendered_rows=len(rows),
            method="text_tag_cooccurrence_counts",
            parameters={"corpus_id": corpus_id, "tag_limit": tag_limit},
            approximate=total_tag_count > len(top_tags),
        )

    def _category_numeric_rows(
        self,
        table_sql: str,
        category_sql: str,
        numeric_sql: str,
        *,
        limit: int,
    ) -> tuple[tuple[tuple[Any, ...], ...], int]:
        with self._connect() as connection:
            count_row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_sql}
                WHERE {category_sql} IS NOT NULL
                  AND {numeric_sql} IS NOT NULL
                """
            ).fetchone()
            original_rows = int(count_row[0] or 0) if count_row is not None else 0
            rows = connection.execute(
                f"""
                WITH grouped AS (
                    SELECT
                        CAST({category_sql} AS VARCHAR) AS category,
                        COUNT(*) AS source_count,
                        AVG(CAST({numeric_sql} AS DOUBLE)) AS mean_value
                    FROM {table_sql}
                    WHERE {category_sql} IS NOT NULL
                      AND {numeric_sql} IS NOT NULL
                    GROUP BY category
                ),
                ranked AS (
                    SELECT
                        category,
                        source_count,
                        mean_value,
                        ROW_NUMBER() OVER (ORDER BY source_count DESC, category ASC) AS rank
                    FROM grouped
                ),
                aggregated AS (
                    SELECT
                        CASE WHEN rank <= ? THEN category ELSE 'Other' END AS category,
                        SUM(mean_value * source_count) / SUM(source_count) AS value,
                        SUM(source_count) AS source_count
                    FROM ranked
                    GROUP BY 1
                )
                SELECT category, value, source_count
                FROM aggregated
                ORDER BY
                    CASE WHEN category = 'Other' THEN 1 ELSE 0 END ASC,
                    source_count DESC,
                    category ASC
                """,
                [limit],
            ).fetchall()
        return tuple(tuple(row) for row in rows), original_rows

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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS text_category_audit (
                id VARCHAR PRIMARY KEY,
                corpus_id VARCHAR NOT NULL,
                action VARCHAR NOT NULL,
                source_category_id VARCHAR,
                source_category_name VARCHAR NOT NULL,
                target_category_id VARCHAR,
                target_category_name VARCHAR,
                affected_record_count INTEGER NOT NULL,
                note VARCHAR NOT NULL,
                created_at TIMESTAMP NOT NULL,
                schema_version INTEGER NOT NULL
            )
            """
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


def _text_corpus_row_count(connection: duckdb.DuckDBPyConnection, corpus_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM text_records WHERE corpus_id = ?",
        [corpus_id],
    ).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _text_category_label_sql() -> str:
    return (
        "COALESCE(c.name, "
        "CASE WHEN r.primary_category_id IS NULL THEN '未分类' ELSE r.primary_category_id END)"
    )


def _text_source_label_sql() -> str:
    return "COALESCE(NULLIF(TRIM(r.source), ''), '未标注来源')"


def _like_pattern(value: str) -> str:
    return f"%{_escape_like(value)}%"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


def _text_export_json_payload(row: tuple[Any, ...]) -> dict[str, object]:
    custom_fields = json.loads(str(row[9] or "{}"))
    if not isinstance(custom_fields, dict):
        custom_fields = {}
    return {
        "id": str(row[0]),
        "content": str(row[1]),
        "primary_category": str(row[2] or ""),
        "tags": _text_export_tags(row[3]),
        "source": _optional_text_export_value(row[4]),
        "location": _optional_text_export_value(row[5]),
        "speaker": _optional_text_export_value(row[6]),
        "record_time": _datetime_text_export_value(row[7]),
        "note": str(row[8] or ""),
        "custom_fields": custom_fields,
        "created_at": _datetime_text_export_value(row[10]),
        "updated_at": _datetime_text_export_value(row[11]),
        "schema_version": int(row[12]),
    }


def _text_export_tags(value: object) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value if str(item)]
    return []


def _optional_text_export_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _datetime_text_export_value(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


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


def _category_audit_from_row(row: tuple[Any, ...]) -> CategoryAuditRecord:
    return CategoryAuditRecord(
        id=str(row[0]),
        corpus_id=str(row[1]),
        action=str(row[2]),
        source_category_id=str(row[3]) if row[3] is not None else None,
        source_category_name=str(row[4]),
        target_category_id=str(row[5]) if row[5] is not None else None,
        target_category_name=str(row[6]) if row[6] is not None else None,
        affected_record_count=int(row[7]),
        note=str(row[8] or ""),
        created_at=_datetime_or_none(row[9]) or datetime.min,
        schema_version=int(row[10]),
    )


def _fetch_category_by_id(
    connection: duckdb.DuckDBPyConnection,
    category_id: str | None,
) -> Category | None:
    if category_id is None:
        return None
    row = connection.execute(
        """
        SELECT id, name, description, color, created_at, updated_at, schema_version
        FROM text_categories
        WHERE id = ?
        """,
        [category_id],
    ).fetchone()
    return _category_from_row(row) if row is not None else None


def _text_category_usage_count(
    connection: duckdb.DuckDBPyConnection,
    corpus_id: str,
    category_id: str,
) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM text_records
        WHERE corpus_id = ? AND primary_category_id = ?
        """,
        [corpus_id, category_id],
    ).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _text_category_usage_outside_corpus_count(
    connection: duckdb.DuckDBPyConnection,
    corpus_id: str,
    category_id: str,
) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM text_records
        WHERE corpus_id <> ? AND primary_category_id = ?
        """,
        [corpus_id, category_id],
    ).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _insert_category_audit(
    connection: duckdb.DuckDBPyConnection,
    audit: CategoryAuditRecord,
) -> None:
    connection.execute(
        """
        INSERT INTO text_category_audit (
            id, corpus_id, action, source_category_id, source_category_name,
            target_category_id, target_category_name, affected_record_count,
            note, created_at, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            audit.id,
            audit.corpus_id,
            audit.action,
            audit.source_category_id,
            audit.source_category_name,
            audit.target_category_id,
            audit.target_category_name,
            audit.affected_record_count,
            audit.note,
            audit.created_at,
            audit.schema_version,
        ],
    )


def _datetime_or_none(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None
