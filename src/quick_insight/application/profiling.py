from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from quick_insight.domain.enums import ColumnSemanticType
from quick_insight.domain.models import AnalysisFinding, ColumnProfile, DatasetProfile
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

    def profile_table(
        self,
        dataset_id: str,
        table_name: str,
        *,
        import_options: Mapping[str, object] | None = None,
    ) -> DatasetProfile:
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
        duplicate_row_count = self._workspace.duplicate_row_count(table_name, columns)
        quality = _quality_summary(row_count, duplicate_row_count, column_profiles)
        warnings = _dataset_warnings(row_count, duplicate_row_count, column_profiles)
        summary = {
            "column_count": len(columns),
            "semantic_type_counts": _semantic_type_counts(column_profiles),
            "quality": quality,
            "time_ranges": _time_ranges(column_profiles),
            "parse_failures": _parse_failure_summary(import_options),
        }
        findings = _build_findings(row_count, column_profiles, summary, warnings)
        return DatasetProfile(
            dataset_id=dataset_id,
            row_count=row_count,
            column_profiles=column_profiles,
            approximate=False,
            method="duckdb_full_scan",
            summary=summary,
            warnings=warnings,
            findings=findings,
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
                    "quantile_25": stats.quantile_25,
                    "quantile_75": stats.quantile_75,
                    "mean": stats.mean_value,
                    "median": stats.median_value,
                    "stddev": stats.stddev_value,
                    "outlier_count": stats.outlier_count,
                }
            )
        if inference.semantic_type is ColumnSemanticType.DATETIME:
            summary.update({"min": stats.min_value, "max": stats.max_value})
        if stats.avg_text_length is not None:
            summary["avg_text_length"] = stats.avg_text_length
        if stats.max_text_length is not None:
            summary["max_text_length"] = stats.max_text_length
        if stats.non_empty_count:
            summary["non_empty_count"] = stats.non_empty_count
            summary["numeric_like_count"] = stats.numeric_like_count
            summary["datetime_like_count"] = stats.datetime_like_count
            summary["top_value_ratio"] = _top_value_ratio(stats)
        warnings = _column_warnings(inference, stats)
        return ColumnProfile(
            name=column_name,
            semantic_type=inference.semantic_type,
            null_count=stats.null_count,
            distinct_count=stats.distinct_count,
            approximate=False,
            warnings=warnings,
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


def _column_warnings(
    inference: SemanticInference,
    stats: WorkspaceColumnStats,
) -> tuple[str, ...]:
    warnings = list(inference.warnings)
    if inference.semantic_type is ColumnSemanticType.CATEGORICAL and stats.distinct_count > 30:
        warnings.append("high_cardinality_category")
    if _has_mixed_type_values(inference.semantic_type, stats):
        warnings.append("mixed_type_values")
    if (stats.outlier_count or 0) > 0:
        warnings.append("numeric_outlier_candidates")
    return tuple(dict.fromkeys(warnings))


def _dataset_warnings(
    row_count: int,
    duplicate_row_count: int,
    column_profiles: tuple[ColumnProfile, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if row_count == 0:
        warnings.append("empty_table")
    if duplicate_row_count:
        warnings.append("duplicate_rows_present")
    if any("candidate_identifier" in profile.warnings for profile in column_profiles):
        warnings.append("candidate_identifier_columns")
    if any("missing_values" in profile.warnings for profile in column_profiles):
        warnings.append("missing_values_present")
    if any("constant_column" in profile.warnings for profile in column_profiles):
        warnings.append("constant_columns_present")
    if any("mixed_type_values" in profile.warnings for profile in column_profiles):
        warnings.append("mixed_type_values_present")
    if any("numeric_outlier_candidates" in profile.warnings for profile in column_profiles):
        warnings.append("numeric_outlier_candidates_present")
    return tuple(warnings)


def _quality_summary(
    row_count: int,
    duplicate_row_count: int,
    column_profiles: tuple[ColumnProfile, ...],
) -> dict[str, object]:
    missing_by_column = {
        profile.name: profile.null_count for profile in column_profiles if profile.null_count
    }
    constant_columns = [
        profile.name for profile in column_profiles if "constant_column" in profile.warnings
    ]
    high_cardinality_columns = [
        profile.name
        for profile in column_profiles
        if "high_cardinality_category" in profile.warnings
        or "high_cardinality_text" in profile.warnings
    ]
    mixed_type_columns = [
        profile.name for profile in column_profiles if "mixed_type_values" in profile.warnings
    ]
    outlier_columns = {
        profile.name: int(profile.summary["outlier_count"])
        for profile in column_profiles
        if isinstance(profile.summary.get("outlier_count"), int)
        and int(profile.summary["outlier_count"]) > 0
    }
    total_missing = sum(missing_by_column.values())
    return {
        "row_count": row_count,
        "duplicate_row_count": duplicate_row_count,
        "duplicate_row_ratio": _ratio(duplicate_row_count, row_count),
        "total_missing_values": total_missing,
        "columns_with_missing_values": missing_by_column,
        "constant_columns": tuple(constant_columns),
        "high_cardinality_columns": tuple(high_cardinality_columns),
        "mixed_type_columns": tuple(mixed_type_columns),
        "numeric_outlier_columns": outlier_columns,
    }


def _time_ranges(column_profiles: tuple[ColumnProfile, ...]) -> dict[str, dict[str, object]]:
    ranges: dict[str, dict[str, object]] = {}
    for profile in column_profiles:
        if profile.semantic_type is not ColumnSemanticType.DATETIME:
            continue
        ranges[profile.name] = {
            "min": profile.summary.get("min"),
            "max": profile.summary.get("max"),
        }
    return ranges


def _parse_failure_summary(import_options: Mapping[str, object] | None) -> dict[str, object]:
    if import_options is None:
        return {
            "reported": False,
            "count": None,
            "method": "not_available",
        }
    count = import_options.get("parse_failure_count")
    if isinstance(count, int):
        return {
            "reported": True,
            "count": count,
            "method": "import_options",
        }
    return {
        "reported": True,
        "count": 0,
        "method": "strict_import_aborts_on_parse_error",
    }


def _build_findings(
    row_count: int,
    column_profiles: tuple[ColumnProfile, ...],
    summary: dict[str, object],
    warnings: tuple[str, ...],
) -> tuple[AnalysisFinding, ...]:
    quality = summary["quality"]
    if not isinstance(quality, dict):
        return ()
    columns_with_missing = cast(dict[str, int], quality["columns_with_missing_values"])
    constant_columns = cast(tuple[str, ...], quality["constant_columns"])
    mixed_type_columns = cast(tuple[str, ...], quality["mixed_type_columns"])
    outlier_columns = cast(dict[str, int], quality["numeric_outlier_columns"])
    findings: list[AnalysisFinding] = []
    if "duplicate_rows_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="发现重复行，需要在分析前确认是否保留。",
                evidence={
                    "row_count": row_count,
                    "duplicate_row_count": quality["duplicate_row_count"],
                    "duplicate_row_ratio": quality["duplicate_row_ratio"],
                },
                method="duckdb_group_by_all_columns",
                sample_query="GROUP BY all imported columns HAVING COUNT(*) > 1",
                warnings=("deduplicate_only_after_user_confirmation",),
            )
        )
    if "missing_values_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="部分字段存在缺失值，聚合或图表生成时需要说明处理方式。",
                evidence={
                    "total_missing_values": quality["total_missing_values"],
                    "columns": columns_with_missing,
                },
                method="duckdb_column_null_counts",
                warnings=("missing_values_present",),
            )
        )
    if "constant_columns_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="发现常量列，这些字段通常不适合作为分组或筛选依据。",
                evidence={"columns": constant_columns},
                method="distinct_count_equals_one",
                fields=constant_columns,
                warnings=("constant_columns_present",),
            )
        )
    if "mixed_type_values_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="部分文本字段包含混合类型值，建议先确认字段含义或做类型转换预览。",
                evidence={"columns": mixed_type_columns},
                method="duckdb_try_cast_numeric_datetime_counts",
                fields=mixed_type_columns,
                warnings=("mixed_type_values_present",),
            )
        )
    if "numeric_outlier_candidates_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="发现数值异常候选点，当前仅按 IQR 规则标记，不能直接解释为错误或因果。",
                evidence={"columns": outlier_columns},
                method="iqr_1_5_full_scan",
                fields=tuple(outlier_columns),
                warnings=("outlier_candidates_require_review",),
            )
        )
    return tuple(findings)


def _semantic_type_counts(column_profiles: tuple[ColumnProfile, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for profile in column_profiles:
        key = profile.semantic_type.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def _ratio(part: int, whole: int) -> float:
    return 0.0 if whole <= 0 else part / whole


def _top_value_ratio(stats: WorkspaceColumnStats) -> float:
    if not stats.top_values:
        return 0.0
    return _ratio(stats.top_values[0][1], max(stats.row_count - stats.null_count, 0))


def _has_mixed_type_values(
    semantic_type: ColumnSemanticType,
    stats: WorkspaceColumnStats,
) -> bool:
    if semantic_type not in {
        ColumnSemanticType.TEXT,
        ColumnSemanticType.LONG_TEXT,
        ColumnSemanticType.CATEGORICAL,
    }:
        return False
    if stats.non_empty_count <= 1:
        return False
    numeric_ratio = _ratio(stats.numeric_like_count, stats.non_empty_count)
    datetime_ratio = _ratio(stats.datetime_like_count, stats.non_empty_count)
    return 0.2 <= numeric_ratio < 1.0 or 0.2 <= datetime_ratio < 1.0


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
