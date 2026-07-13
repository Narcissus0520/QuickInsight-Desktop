from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from quick_insight.charts.budgets import DEFAULT_BUDGETS
from quick_insight.domain.enums import AnalysisIntent, ColumnSemanticType
from quick_insight.domain.models import (
    ChartRecommendation,
    ChartSpec,
    ColumnProfile,
    DatasetProfile,
)

_TEXT_DATASET_KIND = "text_corpus"
_CATEGORY_TYPES = {
    ColumnSemanticType.CATEGORICAL,
    ColumnSemanticType.PRIMARY_CATEGORY,
    ColumnSemanticType.BOOLEAN,
    ColumnSemanticType.SOURCE_REFERENCE,
}
_NUMERIC_LIMIT_FOR_CORRELATION = 8


@dataclass(frozen=True)
class ScoreBreakdown:
    field_compatibility: int
    intent_match: int
    cardinality_suitability: int
    data_quality_suitability: int
    performance_readability: int

    @property
    def total(self) -> int:
        return min(
            100,
            max(
                0,
                self.field_compatibility
                + self.intent_match
                + self.cardinality_suitability
                + self.data_quality_suitability
                + self.performance_readability,
            ),
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "field_compatibility": self.field_compatibility,
            "intent_match": self.intent_match,
            "cardinality_suitability": self.cardinality_suitability,
            "data_quality_suitability": self.data_quality_suitability,
            "performance_readability": self.performance_readability,
            "total": self.total,
        }


@dataclass(frozen=True)
class _Candidate:
    chart_type: str
    mappings: dict[str, str]
    aggregation: dict[str, Any]
    score: ScoreBreakdown
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    data_budget: dict[str, Any]


class ChartRecommendationEngine:
    def recommend(
        self,
        profile: DatasetProfile,
        *,
        intent: AnalysisIntent = AnalysisIntent.AUTO,
        limit: int = 8,
    ) -> tuple[ChartRecommendation, ...]:
        candidates = (
            self._text_candidates(profile, intent)
            if profile.summary.get("dataset_kind") == _TEXT_DATASET_KIND
            else self._tabular_candidates(profile, intent)
        )
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                -candidate.score.total,
                candidate.chart_type,
                tuple(candidate.mappings.items()),
            ),
        )
        return tuple(_to_recommendation(candidate) for candidate in ordered[:limit])

    def _tabular_candidates(
        self,
        profile: DatasetProfile,
        intent: AnalysisIntent,
    ) -> tuple[_Candidate, ...]:
        numeric = _profiles_by_type(profile, ColumnSemanticType.NUMERIC)
        datetimes = _profiles_by_type(profile, ColumnSemanticType.DATETIME)
        categories = _category_profiles(profile)
        candidates: list[_Candidate] = []

        for time_profile in datetimes[:2]:
            for numeric_profile in numeric[:4]:
                candidates.append(
                    _candidate(
                        profile=profile,
                        chart_type="line",
                        mappings={"x": time_profile.name, "y": numeric_profile.name},
                        aggregation={"time": "auto_window", "value": "mean"},
                        field_score=40,
                        intent_score=_intent_score(intent, {AnalysisIntent.TREND}, auto=20),
                        cardinality_score=15,
                        data_quality_score=_quality_score(profile, (time_profile, numeric_profile)),
                        performance_score=_performance_score(profile, "line"),
                        reasons=(
                            "datetime_numeric_trend",
                            "line_chart_preserves_time_order",
                        ),
                        warnings=_field_warnings((time_profile, numeric_profile))
                        + _budget_warnings(profile, "line"),
                        budget_family="line_area",
                    )
                )
                if _numeric_minimum(numeric_profile) is not None and (
                    _numeric_minimum(numeric_profile) or 0
                ) >= 0:
                    candidates.append(
                        _candidate(
                            profile=profile,
                            chart_type="area",
                            mappings={"x": time_profile.name, "y": numeric_profile.name},
                            aggregation={"time": "auto_window", "value": "mean"},
                            field_score=34,
                            intent_score=_intent_score(intent, {AnalysisIntent.TREND}, auto=15),
                            cardinality_score=14,
                            data_quality_score=_quality_score(
                                profile,
                                (time_profile, numeric_profile),
                            ),
                            performance_score=_performance_score(profile, "area"),
                            reasons=(
                                "datetime_numeric_trend",
                                "non_negative_numeric_values_allow_area_context",
                            ),
                            warnings=_field_warnings((time_profile, numeric_profile))
                            + _budget_warnings(profile, "area"),
                            budget_family="line_area",
                        )
                    )

        for category_profile in categories[:4]:
            for numeric_profile in numeric[:4]:
                category_score, category_warnings = _category_score(category_profile)
                candidates.append(
                    _candidate(
                        profile=profile,
                        chart_type="bar",
                        mappings={"x": category_profile.name, "y": numeric_profile.name},
                        aggregation={"group_by": category_profile.name, "value": "mean"},
                        field_score=38,
                        intent_score=_intent_score(
                            intent,
                            {AnalysisIntent.COMPARISON},
                            auto=19,
                        ),
                        cardinality_score=category_score,
                        data_quality_score=_quality_score(
                            profile,
                            (category_profile, numeric_profile),
                        ),
                        performance_score=_performance_score(profile, "bar"),
                        reasons=("category_numeric_comparison", "mean_by_category"),
                        warnings=category_warnings
                        + _field_warnings((category_profile, numeric_profile)),
                        budget_family="category",
                    )
                )
                candidates.append(
                    _candidate(
                        profile=profile,
                        chart_type="box",
                        mappings={"x": category_profile.name, "y": numeric_profile.name},
                        aggregation={"group_by": category_profile.name, "distribution": "raw"},
                        field_score=36,
                        intent_score=_intent_score(
                            intent,
                            {AnalysisIntent.DISTRIBUTION, AnalysisIntent.COMPARISON},
                            auto=15,
                        ),
                        cardinality_score=max(category_score - 1, 0),
                        data_quality_score=_quality_score(
                            profile,
                            (category_profile, numeric_profile),
                        ),
                        performance_score=_performance_score(profile, "box"),
                        reasons=("category_numeric_distribution", "box_plot_shows_spread"),
                        warnings=category_warnings
                        + _field_warnings((category_profile, numeric_profile)),
                        budget_family="category",
                    )
                )

        for numeric_profile in numeric[:6]:
            candidates.append(
                _candidate(
                    profile=profile,
                    chart_type="histogram",
                    mappings={"x": numeric_profile.name},
                    aggregation={"bins": "auto"},
                    field_score=34,
                    intent_score=_intent_score(
                        intent,
                        {AnalysisIntent.DISTRIBUTION, AnalysisIntent.ANOMALY},
                        auto=16,
                    ),
                    cardinality_score=15,
                    data_quality_score=_quality_score(profile, (numeric_profile,)),
                    performance_score=_performance_score(profile, "histogram"),
                    reasons=("single_numeric_distribution", "histogram_uses_aggregated_bins"),
                    warnings=_field_warnings((numeric_profile,)),
                    budget_family="category",
                )
            )

        for left_index, left_profile in enumerate(numeric[:5]):
            for right_profile in numeric[left_index + 1 : 6]:
                chart_type = "density_heatmap" if profile.row_count > 200_000 else "scatter"
                candidates.append(
                    _candidate(
                        profile=profile,
                        chart_type=chart_type,
                        mappings={"x": left_profile.name, "y": right_profile.name},
                        aggregation=(
                            {"density": "2d_bins"}
                            if chart_type == "density_heatmap"
                            else {}
                        ),
                        field_score=40,
                        intent_score=_intent_score(
                            intent,
                            {AnalysisIntent.RELATIONSHIP},
                            auto=17,
                        ),
                        cardinality_score=15,
                        data_quality_score=_quality_score(profile, (left_profile, right_profile)),
                        performance_score=_performance_score(profile, chart_type),
                        reasons=(
                            "two_numeric_relationship",
                            "density_bins_preferred_for_very_large_scatter"
                            if chart_type == "density_heatmap"
                            else "scatter_shows_pairwise_pattern",
                        ),
                        warnings=_field_warnings((left_profile, right_profile))
                        + _budget_warnings(profile, chart_type),
                        budget_family="scatter"
                        if chart_type == "scatter"
                        else "scatter_webgl",
                    )
                )

        for left_index, left_profile in enumerate(categories[:4]):
            for right_profile in categories[left_index + 1 : 5]:
                left_score, left_warnings = _category_score(left_profile)
                right_score, right_warnings = _category_score(right_profile)
                candidates.append(
                    _candidate(
                        profile=profile,
                        chart_type="crosstab_heatmap",
                        mappings={"x": left_profile.name, "y": right_profile.name},
                        aggregation={"value": "count"},
                        field_score=38,
                        intent_score=_intent_score(
                            intent,
                            {AnalysisIntent.COMPARISON, AnalysisIntent.COMPOSITION},
                            auto=16,
                        ),
                        cardinality_score=max(min(left_score, right_score) - 1, 0),
                        data_quality_score=_quality_score(profile, (left_profile, right_profile)),
                        performance_score=_performance_score(profile, "heatmap"),
                        reasons=("two_categorical_crosstab", "heatmap_uses_count_aggregation"),
                        warnings=left_warnings
                        + right_warnings
                        + _field_warnings((left_profile, right_profile)),
                        budget_family="category",
                    )
                )
                candidates.append(
                    _candidate(
                        profile=profile,
                        chart_type="stacked_bar",
                        mappings={"x": left_profile.name, "color": right_profile.name},
                        aggregation={"value": "count"},
                        field_score=34,
                        intent_score=_intent_score(
                            intent,
                            {AnalysisIntent.COMPOSITION, AnalysisIntent.COMPARISON},
                            auto=12,
                        ),
                        cardinality_score=max(min(left_score, right_score) - 3, 0),
                        data_quality_score=_quality_score(profile, (left_profile, right_profile)),
                        performance_score=_performance_score(profile, "bar"),
                        reasons=("two_categorical_composition", "stacked_bar_counts_records"),
                        warnings=left_warnings
                        + right_warnings
                        + _field_warnings((left_profile, right_profile)),
                        budget_family="category",
                    )
                )

        if len(numeric) >= 3:
            selected_numeric = numeric[:_NUMERIC_LIMIT_FOR_CORRELATION]
            warnings: tuple[str, ...] = ()
            if len(numeric) > _NUMERIC_LIMIT_FOR_CORRELATION:
                warnings = ("correlation_limited_to_first_8_numeric_fields",)
            candidates.append(
                _candidate(
                    profile=profile,
                    chart_type="correlation_heatmap",
                    mappings={"fields": ",".join(column.name for column in selected_numeric)},
                    aggregation={"method": "pearson"},
                    field_score=40,
                    intent_score=_intent_score(
                        intent,
                        {AnalysisIntent.CORRELATION, AnalysisIntent.RELATIONSHIP},
                        auto=17,
                    ),
                    cardinality_score=15 if len(numeric) <= _NUMERIC_LIMIT_FOR_CORRELATION else 10,
                    data_quality_score=_quality_score(profile, selected_numeric),
                    performance_score=_performance_score(profile, "correlation_heatmap"),
                    reasons=("multiple_numeric_correlation", "field_limit_keeps_heatmap_readable"),
                    warnings=warnings + _field_warnings(selected_numeric),
                    budget_family="category",
                )
            )

        for category_profile in categories[:4]:
            if (category_profile.distinct_count or 0) <= 6:
                candidates.append(
                    _candidate(
                        profile=profile,
                        chart_type="donut",
                        mappings={"category": category_profile.name},
                        aggregation={"value": "count"},
                        field_score=34,
                        intent_score=_intent_score(
                            intent,
                            {AnalysisIntent.COMPOSITION},
                            auto=8,
                        ),
                        cardinality_score=15,
                        data_quality_score=_quality_score(profile, (category_profile,)),
                        performance_score=_performance_score(profile, "donut"),
                        reasons=(
                            "small_category_composition",
                            "donut_allowed_for_at_most_6_categories",
                        ),
                        warnings=_field_warnings((category_profile,)),
                        budget_family="category",
                    )
                )

        return tuple(candidates)

    def _text_candidates(
        self,
        profile: DatasetProfile,
        intent: AnalysisIntent,
    ) -> tuple[_Candidate, ...]:
        candidates: list[_Candidate] = []
        summary = profile.summary
        category_counts = _summary_entries(summary, "category_counts")
        source_counts = _summary_entries(summary, "source_counts")
        keyword_matches = _summary_entries(summary, "keyword_matches")
        per_category_keywords = _summary_entries(summary, "per_category_keyword_counts")
        tag_co_occurrence = _summary_entries(summary, "tag_co_occurrence")
        keyword_values = _keywords_from_keyword_matches(keyword_matches)
        category_keyword_values = _keywords_from_category_keyword_entries(per_category_keywords)
        categorized_count = _summary_int(summary, "categorized_count")
        uncategorized_count = _summary_int(summary, "uncategorized_count")

        if category_counts:
            category_score = _text_count_cardinality_score(len(category_counts))
            candidates.append(
                _candidate(
                    profile=profile,
                    chart_type="text_category_bar",
                    mappings={"x": "primary_category", "y": "record_count"},
                    aggregation={"source": "profile.category_counts"},
                    field_score=40,
                    intent_score=_intent_score(
                        intent,
                        {AnalysisIntent.COMPARISON, AnalysisIntent.AUTO},
                        auto=22,
                    ),
                    cardinality_score=category_score,
                    data_quality_score=_text_quality_score(profile),
                    performance_score=10,
                    reasons=("text_category_counts", "uses_persisted_primary_category"),
                    warnings=_text_cardinality_warnings(len(category_counts)),
                    budget_family="category",
                )
            )
        if categorized_count or uncategorized_count:
            candidates.append(
                _candidate(
                    profile=profile,
                    chart_type="text_classification_status_bar",
                    mappings={"x": "classification_status", "y": "record_count"},
                    aggregation={"source": "profile.categorized_uncategorized_counts"},
                    field_score=38,
                    intent_score=_intent_score(intent, {AnalysisIntent.COMPOSITION}, auto=18),
                    cardinality_score=15,
                    data_quality_score=_text_quality_score(profile),
                    performance_score=10,
                    reasons=(
                        "classified_uncategorized_status",
                        "two_status_categories_are_readable",
                    ),
                    warnings=(),
                    budget_family="category",
                )
            )
        if category_counts and source_counts:
            candidates.append(
                _candidate(
                    profile=profile,
                    chart_type="text_source_category_heatmap",
                    mappings={"x": "source", "y": "primary_category", "value": "record_count"},
                    aggregation={"source": "workspace_crosstab_required"},
                    field_score=36,
                    intent_score=_intent_score(
                        intent,
                        {AnalysisIntent.COMPARISON, AnalysisIntent.COMPOSITION},
                        auto=14,
                    ),
                    cardinality_score=min(
                        _text_count_cardinality_score(len(category_counts)),
                        _text_count_cardinality_score(len(source_counts)),
                    ),
                    data_quality_score=_text_quality_score(profile),
                    performance_score=9,
                    reasons=(
                        "source_category_crosstab",
                        "heatmap_summarizes_two_text_metadata_fields",
                    ),
                    warnings=_text_cardinality_warnings(len(category_counts) + len(source_counts)),
                    budget_family="category",
                )
            )
        if keyword_matches:
            candidates.append(
                _candidate(
                    profile=profile,
                    chart_type="text_keyword_bar",
                    mappings={"x": "keyword", "y": "matching_record_count"},
                    aggregation={
                        "source": "profile.keyword_matches",
                        "keywords": keyword_values,
                    },
                    field_score=36,
                    intent_score=_intent_score(intent, {AnalysisIntent.COMPARISON}, auto=13),
                    cardinality_score=_text_count_cardinality_score(len(keyword_matches)),
                    data_quality_score=_text_quality_score(profile),
                    performance_score=10,
                    reasons=("keyword_ranking", "keyword_counts_are_surface_level"),
                    warnings=("keyword_matches_are_not_semantic_topics",),
                    budget_family="category",
                )
            )
        if per_category_keywords:
            candidates.append(
                _candidate(
                    profile=profile,
                    chart_type="text_category_keyword_heatmap",
                    mappings={"x": "keyword", "y": "primary_category", "value": "record_count"},
                    aggregation={
                        "source": "profile.per_category_keyword_counts",
                        "keywords": category_keyword_values,
                    },
                    field_score=34,
                    intent_score=_intent_score(
                        intent,
                        {AnalysisIntent.COMPARISON, AnalysisIntent.RELATIONSHIP},
                        auto=12,
                    ),
                    cardinality_score=_text_count_cardinality_score(len(per_category_keywords)),
                    data_quality_score=_text_quality_score(profile),
                    performance_score=9,
                    reasons=(
                        "category_keyword_differences",
                        "heatmap_compares_literal_keyword_counts",
                    ),
                    warnings=("keyword_matches_are_surface_level",),
                    budget_family="category",
                )
            )
        if tag_co_occurrence:
            candidates.append(
                _candidate(
                    profile=profile,
                    chart_type="text_tag_cooccurrence_heatmap",
                    mappings={"x": "tag", "y": "tag", "value": "cooccurrence_count"},
                    aggregation={"source": "profile.tag_co_occurrence"},
                    field_score=34,
                    intent_score=_intent_score(
                        intent,
                        {AnalysisIntent.RELATIONSHIP, AnalysisIntent.COMPARISON},
                        auto=12,
                    ),
                    cardinality_score=_text_count_cardinality_score(len(tag_co_occurrence)),
                    data_quality_score=_text_quality_score(profile),
                    performance_score=9,
                    reasons=("tag_co_occurrence", "co_occurrence_is_not_causation"),
                    warnings=("co_occurrence_is_not_causation",),
                    budget_family="category",
                )
            )
        return tuple(candidates)


def _candidate(
    *,
    profile: DatasetProfile,
    chart_type: str,
    mappings: dict[str, str],
    aggregation: dict[str, Any],
    field_score: int,
    intent_score: int,
    cardinality_score: int,
    data_quality_score: int,
    performance_score: int,
    reasons: tuple[str, ...],
    warnings: tuple[str, ...],
    budget_family: str,
) -> _Candidate:
    budget = _budget(profile, chart_type, budget_family)
    score = ScoreBreakdown(
        field_compatibility=field_score,
        intent_match=intent_score,
        cardinality_suitability=cardinality_score,
        data_quality_suitability=data_quality_score,
        performance_readability=performance_score,
    )
    return _Candidate(
        chart_type=chart_type,
        mappings=mappings,
        aggregation={**aggregation, "score_breakdown": score.as_dict()},
        score=score,
        reasons=tuple(dict.fromkeys((*reasons, f"score={score.total}"))),
        warnings=tuple(dict.fromkeys(warnings)),
        data_budget=budget,
    )


def _to_recommendation(candidate: _Candidate) -> ChartRecommendation:
    spec = ChartSpec(
        id=_recommendation_id(candidate.chart_type, candidate.mappings),
        chart_type=candidate.chart_type,
        mappings=candidate.mappings,
        aggregation=candidate.aggregation,
    )
    return ChartRecommendation(
        spec=spec,
        score=candidate.score.total,
        reasons=candidate.reasons,
        warnings=candidate.warnings,
        data_budget=candidate.data_budget,
        export_strategy="plotly_offline_json",
    )


def _recommendation_id(chart_type: str, mappings: dict[str, str]) -> str:
    digest = sha256()
    digest.update(chart_type.encode("utf-8"))
    for key, value in sorted(mappings.items()):
        digest.update(f"\0{key}={value}".encode("utf-8", errors="replace"))
    return f"rec_{chart_type}_{digest.hexdigest()[:10]}"


def _profiles_by_type(
    profile: DatasetProfile,
    semantic_type: ColumnSemanticType,
) -> tuple[ColumnProfile, ...]:
    return tuple(
        column for column in profile.column_profiles if column.semantic_type is semantic_type
    )


def _category_profiles(profile: DatasetProfile) -> tuple[ColumnProfile, ...]:
    return tuple(
        column
        for column in profile.column_profiles
        if column.semantic_type in _CATEGORY_TYPES
        and column.semantic_type is not ColumnSemanticType.IDENTIFIER
    )


def _intent_score(
    intent: AnalysisIntent,
    preferred: set[AnalysisIntent],
    *,
    auto: int,
) -> int:
    if intent is AnalysisIntent.AUTO:
        return auto
    if intent in preferred:
        return 25
    if AnalysisIntent.AUTO in preferred:
        return 18
    return 6


def _category_score(profile: ColumnProfile) -> tuple[int, tuple[str, ...]]:
    distinct_count = profile.distinct_count or 0
    if distinct_count <= 0:
        return 4, ("category_count_unknown",)
    if distinct_count <= 6:
        return 15, ()
    if distinct_count <= 30:
        return 12, ("too_many_categories_for_donut",)
    if distinct_count <= 100:
        return 6, ("top_n_with_other_recommended", "high_cardinality_category")
    return 3, ("filter_or_top_n_required", "very_high_cardinality_category")


def _text_count_cardinality_score(count: int) -> int:
    if count <= 6:
        return 15
    if count <= 30:
        return 12
    if count <= 100:
        return 6
    return 3


def _text_cardinality_warnings(count: int) -> tuple[str, ...]:
    if count > 30:
        return ("top_n_with_other_recommended",)
    if count > 6:
        return ("too_many_categories_for_donut",)
    return ()


def _quality_score(
    profile: DatasetProfile,
    columns: tuple[ColumnProfile, ...],
) -> int:
    if not columns:
        return 0
    max_missing_ratio = max(_missing_ratio(profile, column) for column in columns)
    warning_count = sum(len(column.warnings) for column in columns)
    if max_missing_ratio == 0 and warning_count == 0:
        return 10
    if max_missing_ratio <= 0.05 and warning_count <= 1:
        return 9
    if max_missing_ratio <= 0.2 and warning_count <= 3:
        return 7
    if max_missing_ratio <= 0.5:
        return 4
    return 2


def _text_quality_score(profile: DatasetProfile) -> int:
    uncategorized = _summary_int(profile.summary, "uncategorized_count")
    missing_source = _summary_int(profile.summary, "missing_source_count")
    duplicate_text = _summary_int(profile.summary, "exact_duplicate_record_count")
    issue_ratio = (uncategorized + missing_source + duplicate_text) / max(profile.row_count, 1)
    if issue_ratio == 0:
        return 10
    if issue_ratio <= 0.1:
        return 8
    if issue_ratio <= 0.35:
        return 6
    return 4


def _missing_ratio(profile: DatasetProfile, column: ColumnProfile) -> float:
    if profile.row_count <= 0:
        return 0.0
    return column.null_count / profile.row_count


def _field_warnings(columns: tuple[ColumnProfile, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    for column in columns:
        if column.null_count:
            warnings.append(f"{column.name}:missing_values")
        warnings.extend(f"{column.name}:{warning}" for warning in column.warnings)
    return tuple(warnings)


def _performance_score(profile: DatasetProfile, chart_type: str) -> int:
    rows = profile.row_count
    if chart_type in {"line", "area"}:
        return 10 if rows <= 20_000 else 7
    if chart_type == "scatter":
        if rows <= 50_000:
            return 10
        return 7
    if chart_type == "density_heatmap":
        return 9
    if chart_type in {"histogram", "bar", "box", "donut", "stacked_bar", "crosstab_heatmap"}:
        return 10
    return 9


def _budget_warnings(profile: DatasetProfile, chart_type: str) -> tuple[str, ...]:
    rows = profile.row_count
    if chart_type in {"line", "area"} and rows > 20_000:
        return ("time_series_downsampling_required",)
    if chart_type == "scatter" and rows > 50_000:
        return ("scatter_sampling_or_webgl_required",)
    if chart_type == "density_heatmap":
        return ("raw_scatter_too_large_density_bins_preferred",)
    return ()


def _budget(
    profile: DatasetProfile,
    chart_type: str,
    family: str,
) -> dict[str, Any]:
    budget = next(
        (candidate for candidate in DEFAULT_BUDGETS if candidate.chart_family == family),
        None,
    )
    target_points = budget.target_points if budget is not None else 30
    strategy = budget.strategy if budget is not None else "aggregate_before_render"
    return {
        "chart_family": family,
        "chart_type": chart_type,
        "original_rows": profile.row_count,
        "target_points": target_points,
        "strategy": strategy,
        "requires_preparation": profile.row_count > target_points,
        "approximate": profile.approximate,
    }


def _numeric_minimum(profile: ColumnProfile) -> float | None:
    value = profile.summary.get("min")
    if isinstance(value, int | float):
        return float(value)
    return None


def _summary_entries(summary: dict[str, Any], key: str) -> tuple[object, ...]:
    value = summary.get(key)
    return value if isinstance(value, tuple) else ()


def _summary_int(summary: dict[str, Any], key: str) -> int:
    value = summary.get(key)
    return value if isinstance(value, int) else 0


def _keywords_from_keyword_matches(entries: tuple[object, ...]) -> tuple[str, ...]:
    keywords: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        keyword = entry.get("keyword")
        if isinstance(keyword, str) and keyword.strip():
            keywords.append(keyword.strip())
    return tuple(dict.fromkeys(keywords))


def _keywords_from_category_keyword_entries(entries: tuple[object, ...]) -> tuple[str, ...]:
    keywords: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("keywords")
        if not isinstance(nested, tuple | list):
            continue
        for keyword_entry in nested:
            if not isinstance(keyword_entry, dict):
                continue
            keyword = keyword_entry.get("keyword")
            if isinstance(keyword, str) and keyword.strip():
                keywords.append(keyword.strip())
    return tuple(dict.fromkeys(keywords))
