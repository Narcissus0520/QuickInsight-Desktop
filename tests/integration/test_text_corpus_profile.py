from __future__ import annotations

from quick_insight.application.text_profiling import (
    TextCorpusProfiler,
    TextProfileOptions,
    tokenize_text,
)
from quick_insight.domain.enums import ColumnSemanticType
from quick_insight.domain.models import Category, TextRecord
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_text_corpus_profiler_reports_quality_and_surface_statistics(tmp_path) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    categories = (
        Category(id="cat_experience", name="产品体验"),
        Category(id="cat_experience_space", name="产品 体验"),
        Category(id="cat_device", name="设备"),
    )
    records = (
        TextRecord(
            id="r-1",
            content="安装体验很好",
            primary_category_id="cat_experience",
            tags=("安装", "好评"),
            source="访谈",
        ),
        TextRecord(
            id="r-2",
            content="安装体验很好",
            primary_category_id="cat_experience_space",
            tags=("安装", "问题"),
        ),
        TextRecord(id="r-3", content="差", tags=()),
        TextRecord(
            id="r-4",
            content="性能告警持续出现告警",
            primary_category_id="cat_device",
            tags=("告警", "传感器"),
            source="日志",
        ),
        TextRecord(
            id="r-5",
            content="x" * 501,
            primary_category_id="cat_device",
            tags=("告警", "传感器"),
            source="日志",
        ),
        TextRecord(id="r-6", content=""),
    )
    workspace.save_text_corpus("profile-corpus", records, categories)

    profile = TextCorpusProfiler(workspace).profile_corpus(
        "dataset-profile",
        "profile-corpus",
        options=TextProfileOptions(keywords=("告警", "安装")),
    )
    profiles = {column.name: column for column in profile.column_profiles}
    quality = profile.summary["quality"]

    assert profile.method == "text_corpus_full_scan"
    assert profile.row_count == 6
    assert profile.approximate is False
    assert profiles["content"].semantic_type is ColumnSemanticType.LONG_TEXT
    assert profiles["primary_category"].semantic_type is ColumnSemanticType.PRIMARY_CATEGORY
    assert profiles["tags"].semantic_type is ColumnSemanticType.TAG_LIST
    assert profiles["source"].semantic_type is ColumnSemanticType.SOURCE_REFERENCE
    assert profile.summary["categorized_count"] == 4
    assert profile.summary["uncategorized_count"] == 2
    assert profile.summary["missing_source_count"] == 3
    assert quality["empty_record_count"] == 1
    assert quality["exact_duplicate_record_count"] == 1
    assert quality["short_record_count"] == 1
    assert quality["long_record_count"] == 1
    assert len(quality["category_conflicts"]) == 1
    assert len(quality["near_duplicate_category_names"]) == 1
    assert "安装体验很好" not in repr(quality["exact_duplicate_content_groups"])
    assert "exact_duplicate_text_present" in profile.warnings
    assert "uncategorized_records_present" in profile.warnings
    assert "missing_sources_present" in profile.warnings

    keyword_counts = {
        entry["keyword"]: entry["record_count"] for entry in profile.summary["keyword_matches"]
    }
    assert keyword_counts == {"告警": 1, "安装": 2}
    tag_pairs = {entry["tags"]: entry["count"] for entry in profile.summary["tag_co_occurrence"]}
    assert tag_pairs[("传感器", "告警")] == 2
    finding_methods = {finding.method for finding in profile.findings}
    assert {
        "text_records_primary_category_null_count",
        "sha256_exact_content_grouping",
        "duplicate_content_category_comparison",
        "character_length_distribution",
        "normalized_name_similarity",
        "casefold_substring_keyword_count",
        "tag_pair_co_occurrence_count",
    }.issubset(finding_methods)


def test_text_tokenizer_uses_cjk_bigrams_and_latin_tokens() -> None:
    assert tokenize_text("安装体验很好 HTTP 500") == (
        "安装",
        "装体",
        "体验",
        "验很",
        "很好",
        "http",
        "500",
    )
