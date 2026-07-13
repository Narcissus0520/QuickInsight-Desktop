from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quick_insight.domain.enums import ColumnSemanticType
from quick_insight.domain.models import ColumnProfile, DatasetProfile
from quick_insight.infrastructure.workspace import (
    WorkspaceColumnStats,
    WorkspaceDatabase,
)


@dataclass(frozen=True)
class SemanticInference:
    semantic_type: ColumnSemanticType
    reason: str
    warnings: tuple[str, ...] = ()


class TabularProfiler:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def profile_table(self, dataset_id: str, table_name: str) -> DatasetProfile:
        row_count = self._workspace.row_count(table_name)
        columns = self._workspace.columns(table_name)
        column_profiles = tuple(
            self._profile_column(
                table_name,
                column.name,
                self._workspace.column_stats(table_name, column),
            )
            for column in columns
        )
        warnings = _dataset_warnings(row_count, column_profiles)
        return DatasetProfile(
            dataset_id=dataset_id,
            row_count=row_count,
            column_profiles=column_profiles,
            approximate=False,
            method="duckdb_full_scan",
            summary={
                "column_count": len(columns),
                "semantic_type_counts": _semantic_type_counts(column_profiles),
            },
            warnings=warnings,
        )

    def _profile_column(
        self,
        table_name: str,
        column_name: str,
        stats: WorkspaceColumnStats,
    ) -> ColumnProfile:
        inference = infer_semantic_type(stats)
        summary: dict[str, Any] = {
            "table": table_name,
            "data_type": stats.data_type,
            "missing_ratio": _ratio(stats.null_count, stats.row_count),
            "semantic_reason": inference.reason,
            "top_values": stats.top_values,
        }
        if inference.semantic_type is ColumnSemanticType.NUMERIC:
            summary.update(
                {
                    "min": stats.min_value,
                    "max": stats.max_value,
                    "mean": stats.mean_value,
                    "median": stats.median_value,
                    "stddev": stats.stddev_value,
                }
            )
        if stats.avg_text_length is not None:
            summary["avg_text_length"] = stats.avg_text_length
        if stats.max_text_length is not None:
            summary["max_text_length"] = stats.max_text_length
        return ColumnProfile(
            name=column_name,
            semantic_type=inference.semantic_type,
            null_count=stats.null_count,
            distinct_count=stats.distinct_count,
            approximate=False,
            warnings=inference.warnings,
            summary=summary,
        )


def infer_semantic_type(stats: WorkspaceColumnStats) -> SemanticInference:
    name = stats.name.lower()
    data_type = stats.data_type.upper()
    row_count = max(stats.row_count, 1)
    distinct_ratio = stats.distinct_count / row_count
    warnings: list[str] = []

    if stats.distinct_count == 1 and stats.row_count > 1:
        warnings.append("constant_column")
    if stats.null_count:
        warnings.append("missing_values")
    if _looks_like_latitude(name):
        return SemanticInference(
            ColumnSemanticType.GEO_LATITUDE,
            "column_name_latitude",
            tuple(warnings),
        )
    if _looks_like_longitude(name):
        return SemanticInference(
            ColumnSemanticType.GEO_LONGITUDE,
            "column_name_longitude",
            tuple(warnings),
        )
    if name in {"category", "class", "label", "primary_category"}:
        return SemanticInference(
            ColumnSemanticType.PRIMARY_CATEGORY,
            "column_name_category",
            tuple(warnings),
        )
    if name in {"tags", "tag_list"}:
        return SemanticInference(ColumnSemanticType.TAG_LIST, "column_name_tags", tuple(warnings))
    if name in {"source", "source_file", "source_reference"}:
        return SemanticInference(
            ColumnSemanticType.SOURCE_REFERENCE,
            "column_name_source",
            tuple(warnings),
        )
    if _looks_like_identifier(name, distinct_ratio):
        warnings.append("candidate_identifier")
        return SemanticInference(
            ColumnSemanticType.IDENTIFIER,
            "column_name_and_distinct_ratio",
            tuple(warnings),
        )
    if _is_boolean_type(data_type):
        return SemanticInference(ColumnSemanticType.BOOLEAN, "duckdb_boolean_type", tuple(warnings))
    if _is_datetime_type(data_type):
        return SemanticInference(
            ColumnSemanticType.DATETIME,
            "duckdb_datetime_type",
            tuple(warnings),
        )
    if _is_numeric_type(data_type):
        return SemanticInference(ColumnSemanticType.NUMERIC, "duckdb_numeric_type", tuple(warnings))
    if (stats.max_text_length or 0) >= 120 or (stats.avg_text_length or 0) >= 60:
        return SemanticInference(
            ColumnSemanticType.LONG_TEXT,
            "text_length_distribution",
            tuple(warnings),
        )
    if stats.distinct_count <= min(100, max(20, int(row_count * 0.5))):
        return SemanticInference(
            ColumnSemanticType.CATEGORICAL,
            "low_distinct_count",
            tuple(warnings),
        )
    warnings.append("high_cardinality_text")
    return SemanticInference(ColumnSemanticType.TEXT, "high_distinct_text", tuple(warnings))


def _dataset_warnings(
    row_count: int,
    column_profiles: tuple[ColumnProfile, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if row_count == 0:
        warnings.append("empty_table")
    if any("candidate_identifier" in profile.warnings for profile in column_profiles):
        warnings.append("candidate_identifier_columns")
    if any("missing_values" in profile.warnings for profile in column_profiles):
        warnings.append("missing_values_present")
    return tuple(warnings)


def _semantic_type_counts(column_profiles: tuple[ColumnProfile, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for profile in column_profiles:
        key = profile.semantic_type.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def _ratio(part: int, whole: int) -> float:
    return 0.0 if whole <= 0 else part / whole


def _looks_like_identifier(name: str, distinct_ratio: float) -> bool:
    normalized = name.replace("-", "_").replace(" ", "_")
    return (normalized == "id" or normalized.endswith("_id")) and distinct_ratio >= 0.9


def _looks_like_latitude(name: str) -> bool:
    return name in {"lat", "latitude", "geo_latitude"} or name.endswith("_lat")


def _looks_like_longitude(name: str) -> bool:
    return name in {"lon", "lng", "longitude", "geo_longitude"} or name.endswith("_lon")


def _is_boolean_type(data_type: str) -> bool:
    return "BOOL" in data_type


def _is_datetime_type(data_type: str) -> bool:
    return "DATE" in data_type or "TIME" in data_type


def _is_numeric_type(data_type: str) -> bool:
    return any(
        token in data_type
        for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "REAL")
    )
