from __future__ import annotations

from quick_insight.domain import AnalysisIntent, ColumnSemanticType, DatasetKind


def test_dataset_kinds_are_first_class() -> None:
    assert {item.value for item in DatasetKind} == {"tabular", "text_corpus"}


def test_analysis_intents_match_product_contract() -> None:
    assert [item.name for item in AnalysisIntent] == [
        "AUTO",
        "TREND",
        "COMPARISON",
        "DISTRIBUTION",
        "RELATIONSHIP",
        "COMPOSITION",
        "ANOMALY",
        "CORRELATION",
    ]


def test_column_semantic_types_include_required_values() -> None:
    assert ColumnSemanticType.PRIMARY_CATEGORY.value == "primary_category"
    assert ColumnSemanticType.TAG_LIST.value == "tag_list"
    assert ColumnSemanticType.SOURCE_REFERENCE.value == "source_reference"
