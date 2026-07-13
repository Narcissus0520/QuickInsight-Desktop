from __future__ import annotations

from quick_insight.charts import ChartRecommendationEngine
from quick_insight.domain.enums import AnalysisIntent, ColumnSemanticType
from quick_insight.domain.models import ColumnProfile, DatasetProfile


def test_trend_requires_datetime_and_numeric_fields() -> None:
    profile = _profile(
        row_count=100,
        columns=(
            _column("date", ColumnSemanticType.DATETIME, distinct=100),
            _column("revenue", ColumnSemanticType.NUMERIC, distinct=90, summary={"min": 1}),
        ),
    )

    recommendations = ChartRecommendationEngine().recommend(
        profile,
        intent=AnalysisIntent.TREND,
    )

    assert recommendations[0].spec.chart_type == "line"
    assert recommendations[0].spec.mappings == {"x": "date", "y": "revenue"}
    assert recommendations[0].score >= 90
    assert any(item.spec.chart_type == "area" for item in recommendations)


def test_no_time_field_means_no_time_trend() -> None:
    profile = _profile(
        row_count=100,
        columns=(
            _column("category", ColumnSemanticType.PRIMARY_CATEGORY, distinct=4),
            _column("revenue", ColumnSemanticType.NUMERIC, distinct=90),
        ),
    )

    recommendations = ChartRecommendationEngine().recommend(
        profile,
        intent=AnalysisIntent.TREND,
    )

    assert {item.spec.chart_type for item in recommendations}.isdisjoint({"line", "area"})


def test_identifier_is_not_treated_as_category_for_comparison() -> None:
    profile = _profile(
        row_count=100,
        columns=(
            _column("id", ColumnSemanticType.IDENTIFIER, distinct=100),
            _column("amount", ColumnSemanticType.NUMERIC, distinct=95),
        ),
    )

    recommendations = ChartRecommendationEngine().recommend(
        profile,
        intent=AnalysisIntent.COMPARISON,
    )

    assert not any(
        "id" in item.spec.mappings.values()
        for item in recommendations
        if item.spec.chart_type in {"bar", "donut", "stacked_bar", "crosstab_heatmap"}
    )


def test_high_cardinality_category_uses_top_n_warning_and_avoids_donut() -> None:
    profile = _profile(
        row_count=1000,
        columns=(
            _column("city", ColumnSemanticType.CATEGORICAL, distinct=80),
            _column("sales", ColumnSemanticType.NUMERIC, distinct=500),
        ),
    )

    recommendations = ChartRecommendationEngine().recommend(
        profile,
        intent=AnalysisIntent.COMPARISON,
    )
    chart_types = {item.spec.chart_type for item in recommendations}
    bar = next(item for item in recommendations if item.spec.chart_type == "bar")

    assert "donut" not in chart_types
    assert "top_n_with_other_recommended" in bar.warnings
    assert bar.data_budget["strategy"] == "top_n_with_other"


def test_very_large_numeric_relationship_prefers_density_heatmap() -> None:
    profile = _profile(
        row_count=250_000,
        columns=(
            _column("x", ColumnSemanticType.NUMERIC, distinct=200_000),
            _column("y", ColumnSemanticType.NUMERIC, distinct=200_000),
        ),
    )

    recommendations = ChartRecommendationEngine().recommend(
        profile,
        intent=AnalysisIntent.RELATIONSHIP,
    )

    assert recommendations[0].spec.chart_type == "density_heatmap"
    assert "raw_scatter_too_large_density_bins_preferred" in recommendations[0].warnings
    assert recommendations[0].data_budget["requires_preparation"] is True


def test_multiple_numeric_fields_recommend_correlation_heatmap_with_field_limit() -> None:
    columns = tuple(
        _column(f"metric_{index}", ColumnSemanticType.NUMERIC, distinct=100)
        for index in range(10)
    )
    profile = _profile(row_count=500, columns=columns)

    recommendations = ChartRecommendationEngine().recommend(
        profile,
        intent=AnalysisIntent.CORRELATION,
    )
    heatmap = next(
        item for item in recommendations if item.spec.chart_type == "correlation_heatmap"
    )

    assert recommendations[0].spec.chart_type == "correlation_heatmap"
    assert heatmap.score >= 85
    assert len(heatmap.spec.mappings["fields"].split(",")) == 8
    assert "correlation_limited_to_first_8_numeric_fields" in heatmap.warnings


def test_two_categorical_fields_recommend_crosstab_heatmap_and_stacked_bar() -> None:
    profile = _profile(
        row_count=300,
        columns=(
            _column("region", ColumnSemanticType.CATEGORICAL, distinct=5),
            _column("status", ColumnSemanticType.CATEGORICAL, distinct=3),
        ),
    )

    recommendations = ChartRecommendationEngine().recommend(
        profile,
        intent=AnalysisIntent.COMPOSITION,
    )
    chart_types = {item.spec.chart_type for item in recommendations}

    assert {"crosstab_heatmap", "stacked_bar"}.issubset(chart_types)


def test_text_profile_recommends_text_specific_charts() -> None:
    profile = _profile(
        row_count=6,
        columns=(
            _column("content", ColumnSemanticType.LONG_TEXT, distinct=6),
            _column("primary_category", ColumnSemanticType.PRIMARY_CATEGORY, distinct=2),
            _column("tags", ColumnSemanticType.TAG_LIST, distinct=3),
            _column("source", ColumnSemanticType.SOURCE_REFERENCE, distinct=2),
        ),
        summary={
            "dataset_kind": "text_corpus",
            "categorized_count": 5,
            "uncategorized_count": 1,
            "missing_source_count": 1,
            "exact_duplicate_record_count": 0,
            "category_counts": (
                {"name": "体验", "count": 3},
                {"name": "设备", "count": 2},
            ),
            "source_counts": (
                {"source": "访谈", "count": 4},
                {"source": "日志", "count": 1},
            ),
            "keyword_matches": (
                {"keyword": "告警", "record_count": 2},
                {"keyword": "安装", "record_count": 1},
            ),
            "per_category_keyword_counts": (
                {"name": "体验", "keywords": ({"keyword": "安装", "record_count": 1},)},
            ),
            "tag_co_occurrence": (
                {"tags": ("告警", "传感器"), "count": 2},
            ),
        },
    )

    recommendations = ChartRecommendationEngine().recommend(profile)
    chart_types = {item.spec.chart_type for item in recommendations}

    assert {
        "text_category_bar",
        "text_classification_status_bar",
        "text_source_category_heatmap",
        "text_keyword_bar",
        "text_category_keyword_heatmap",
        "text_tag_cooccurrence_heatmap",
    }.issubset(chart_types)
    assert all(item.score <= 100 for item in recommendations)


def _profile(
    *,
    row_count: int,
    columns: tuple[ColumnProfile, ...],
    summary: dict[str, object] | None = None,
) -> DatasetProfile:
    return DatasetProfile(
        dataset_id="dataset",
        row_count=row_count,
        column_profiles=columns,
        method="test_profile",
        summary=summary or {"column_count": len(columns)},
    )


def _column(
    name: str,
    semantic_type: ColumnSemanticType,
    *,
    distinct: int,
    nulls: int = 0,
    summary: dict[str, object] | None = None,
    warnings: tuple[str, ...] = (),
) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        semantic_type=semantic_type,
        null_count=nulls,
        distinct_count=distinct,
        summary=summary or {},
        warnings=warnings,
    )
