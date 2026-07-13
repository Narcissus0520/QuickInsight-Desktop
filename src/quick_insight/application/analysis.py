from __future__ import annotations

from dataclasses import dataclass

from quick_insight.domain.enums import ColumnSemanticType
from quick_insight.domain.models import AnalysisFinding, ColumnProfile, DatasetProfile
from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase


@dataclass(frozen=True)
class TabularAnalysisOptions:
    min_rows: int = 3
    strong_correlation_threshold: float = 0.7
    trend_correlation_threshold: float = 0.6
    max_findings: int = 8


class TabularAnalysisService:
    def __init__(
        self,
        workspace: WorkspaceDatabase,
        options: TabularAnalysisOptions | None = None,
    ) -> None:
        self._workspace = workspace
        self._options = options or TabularAnalysisOptions()

    def analyze_table(
        self,
        table_name: str,
        profile: DatasetProfile,
    ) -> tuple[AnalysisFinding, ...]:
        workspace_columns = {
            column.name: column for column in self._workspace.columns(table_name)
        }
        numeric_columns = _profiles_by_type(profile, ColumnSemanticType.NUMERIC)
        datetime_columns = _profiles_by_type(profile, ColumnSemanticType.DATETIME)
        category_columns = _category_profiles(profile)
        findings: list[AnalysisFinding] = []
        findings.extend(
            self._trend_findings(
                table_name,
                workspace_columns,
                datetime_columns,
                numeric_columns,
            )
        )
        findings.extend(
            self._correlation_findings(
                table_name,
                workspace_columns,
                numeric_columns,
            )
        )
        findings.extend(
            self._group_difference_findings(
                table_name,
                workspace_columns,
                category_columns,
                numeric_columns,
            )
        )
        if findings:
            return tuple(findings[: self._options.max_findings])
        return (
            AnalysisFinding(
                statement="当前字段组合不足，暂未生成趋势、相关性或组间差异发现。",
                evidence={
                    "row_count": profile.row_count,
                    "numeric_columns": tuple(column.name for column in numeric_columns),
                    "datetime_columns": tuple(column.name for column in datetime_columns),
                    "category_columns": tuple(column.name for column in category_columns),
                },
                method="tabular_one_click_analysis_field_screening",
                warnings=("insufficient_structured_evidence",),
            ),
        )

    def _trend_findings(
        self,
        table_name: str,
        workspace_columns: dict[str, WorkspaceColumn],
        datetime_columns: tuple[ColumnProfile, ...],
        numeric_columns: tuple[ColumnProfile, ...],
    ) -> tuple[AnalysisFinding, ...]:
        findings: list[AnalysisFinding] = []
        for time_profile in datetime_columns:
            time_column = workspace_columns.get(time_profile.name)
            if time_column is None:
                continue
            for numeric_profile in numeric_columns:
                numeric_column = workspace_columns.get(numeric_profile.name)
                if numeric_column is None:
                    continue
                stats = self._workspace.trend_stats(table_name, time_column, numeric_column)
                if stats.row_count < self._options.min_rows or stats.correlation is None:
                    continue
                if abs(stats.correlation) < self._options.trend_correlation_threshold:
                    continue
                direction = "上升" if (stats.slope_per_day or 0) >= 0 else "下降"
                findings.append(
                    AnalysisFinding(
                        statement=(
                            f"{numeric_profile.name} 随 {time_profile.name} 呈明显{direction}趋势。"
                        ),
                        evidence={
                            "row_count": stats.row_count,
                            "time_column": stats.time_column,
                            "numeric_column": stats.numeric_column,
                            "pearson_correlation": _rounded(stats.correlation),
                            "slope_per_day": _rounded(stats.slope_per_day),
                            "first_time": stats.first_time,
                            "last_time": stats.last_time,
                            "first_value": stats.first_value,
                            "last_value": stats.last_value,
                        },
                        method="duckdb_time_numeric_correlation_regr_slope",
                        fields=(time_profile.name, numeric_profile.name),
                        sample_query="CORR(EPOCH(time), value) and REGR_SLOPE(value, EPOCH(time))",
                        warnings=("correlation_not_causation",),
                    )
                )
        return tuple(
            sorted(
                findings,
                key=lambda finding: abs(float(finding.evidence["pearson_correlation"])),
                reverse=True,
            )[:2]
        )

    def _correlation_findings(
        self,
        table_name: str,
        workspace_columns: dict[str, WorkspaceColumn],
        numeric_columns: tuple[ColumnProfile, ...],
    ) -> tuple[AnalysisFinding, ...]:
        findings: list[AnalysisFinding] = []
        for left_index, left_profile in enumerate(numeric_columns):
            left_column = workspace_columns.get(left_profile.name)
            if left_column is None:
                continue
            for right_profile in numeric_columns[left_index + 1 :]:
                right_column = workspace_columns.get(right_profile.name)
                if right_column is None:
                    continue
                stats = self._workspace.correlation_stats(table_name, left_column, right_column)
                if stats.row_count < self._options.min_rows or stats.correlation is None:
                    continue
                if abs(stats.correlation) < self._options.strong_correlation_threshold:
                    continue
                direction = "正相关" if stats.correlation >= 0 else "负相关"
                findings.append(
                    AnalysisFinding(
                        statement=(
                            f"{left_profile.name} 与 {right_profile.name} 呈较强{direction}。"
                        ),
                        evidence={
                            "row_count": stats.row_count,
                            "left_column": stats.left_column,
                            "right_column": stats.right_column,
                            "pearson_correlation": _rounded(stats.correlation),
                        },
                        method="duckdb_pearson_correlation",
                        fields=(left_profile.name, right_profile.name),
                        sample_query="CORR(left_numeric, right_numeric)",
                        warnings=("correlation_not_causation",),
                    )
                )
        return tuple(
            sorted(
                findings,
                key=lambda finding: abs(float(finding.evidence["pearson_correlation"])),
                reverse=True,
            )[:2]
        )

    def _group_difference_findings(
        self,
        table_name: str,
        workspace_columns: dict[str, WorkspaceColumn],
        category_columns: tuple[ColumnProfile, ...],
        numeric_columns: tuple[ColumnProfile, ...],
    ) -> tuple[AnalysisFinding, ...]:
        findings: list[AnalysisFinding] = []
        for category_profile in category_columns:
            if (category_profile.distinct_count or 0) > 30:
                continue
            category_column = workspace_columns.get(category_profile.name)
            if category_column is None:
                continue
            for numeric_profile in numeric_columns:
                numeric_column = workspace_columns.get(numeric_profile.name)
                if numeric_column is None:
                    continue
                stats = self._workspace.group_difference_stats(
                    table_name,
                    category_column,
                    numeric_column,
                )
                if stats is None or stats.row_count < self._options.min_rows:
                    continue
                if stats.mean_difference == 0:
                    continue
                findings.append(
                    AnalysisFinding(
                        statement=(
                            f"{category_profile.name} 的不同类别在 {numeric_profile.name} "
                            "均值上存在明显差异。"
                        ),
                        evidence={
                            "row_count": stats.row_count,
                            "category_count": stats.category_count,
                            "category_column": stats.category_column,
                            "numeric_column": stats.numeric_column,
                            "top_category": stats.top_category,
                            "top_mean": _rounded(stats.top_mean),
                            "top_count": stats.top_count,
                            "bottom_category": stats.bottom_category,
                            "bottom_mean": _rounded(stats.bottom_mean),
                            "bottom_count": stats.bottom_count,
                            "mean_difference": _rounded(stats.mean_difference),
                            "mean_ratio": _rounded(stats.mean_ratio),
                        },
                        method="duckdb_group_mean_difference",
                        fields=(category_profile.name, numeric_profile.name),
                        sample_query="GROUP BY category; compare highest and lowest AVG(value)",
                        warnings=("group_difference_not_causation",),
                    )
                )
        return tuple(
            sorted(
                findings,
                key=lambda finding: abs(float(finding.evidence["mean_difference"])),
                reverse=True,
            )[:4]
        )


def _profiles_by_type(
    profile: DatasetProfile,
    semantic_type: ColumnSemanticType,
) -> tuple[ColumnProfile, ...]:
    return tuple(
        column
        for column in profile.column_profiles
        if column.semantic_type is semantic_type and "constant_column" not in column.warnings
    )


def _category_profiles(profile: DatasetProfile) -> tuple[ColumnProfile, ...]:
    return tuple(
        column
        for column in profile.column_profiles
        if column.semantic_type
        in {
            ColumnSemanticType.CATEGORICAL,
            ColumnSemanticType.PRIMARY_CATEGORY,
            ColumnSemanticType.SOURCE_REFERENCE,
        }
        and "constant_column" not in column.warnings
        and "candidate_identifier" not in column.warnings
    )


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)
