from __future__ import annotations

from quick_insight.application.profiling import infer_semantic_type
from quick_insight.domain.enums import ColumnSemanticType
from quick_insight.infrastructure.workspace import WorkspaceColumnStats


def _stats(
    name: str,
    data_type: str = "VARCHAR",
    *,
    row_count: int = 100,
    null_count: int = 0,
    distinct_count: int = 10,
    avg_text_length: float | None = None,
    max_text_length: int | None = None,
) -> WorkspaceColumnStats:
    return WorkspaceColumnStats(
        name=name,
        data_type=data_type,
        row_count=row_count,
        null_count=null_count,
        distinct_count=distinct_count,
        avg_text_length=avg_text_length,
        max_text_length=max_text_length,
    )


def test_infers_identifier_from_name_and_distinct_ratio() -> None:
    inference = infer_semantic_type(_stats("record_id", distinct_count=99))

    assert inference.semantic_type is ColumnSemanticType.IDENTIFIER
    assert inference.reason == "column_name_and_distinct_ratio"
    assert "candidate_identifier" in inference.warnings


def test_infers_numeric_from_duckdb_type() -> None:
    inference = infer_semantic_type(_stats("amount", "DOUBLE"))

    assert inference.semantic_type is ColumnSemanticType.NUMERIC
    assert inference.reason == "duckdb_numeric_type"


def test_does_not_infer_identifier_from_valid_suffix() -> None:
    inference = infer_semantic_type(_stats("valid", "BOOLEAN", distinct_count=100))

    assert inference.semantic_type is ColumnSemanticType.BOOLEAN
    assert "candidate_identifier" not in inference.warnings


def test_infers_long_text_from_length_distribution() -> None:
    inference = infer_semantic_type(
        _stats("comment", distinct_count=90, avg_text_length=72.5, max_text_length=180)
    )

    assert inference.semantic_type is ColumnSemanticType.LONG_TEXT
    assert inference.reason == "text_length_distribution"


def test_infers_text_metadata_roles_from_column_names() -> None:
    assert (
        infer_semantic_type(_stats("source")).semantic_type
        is ColumnSemanticType.SOURCE_REFERENCE
    )
    assert infer_semantic_type(_stats("tags")).semantic_type is ColumnSemanticType.TAG_LIST
    assert (
        infer_semantic_type(_stats("category")).semantic_type
        is ColumnSemanticType.PRIMARY_CATEGORY
    )


def test_infers_high_cardinality_text_with_warning() -> None:
    inference = infer_semantic_type(_stats("description", distinct_count=95))

    assert inference.semantic_type is ColumnSemanticType.TEXT
    assert "high_cardinality_text" in inference.warnings
