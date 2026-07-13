from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import combinations
from typing import Any

from quick_insight.domain.enums import ColumnSemanticType
from quick_insight.domain.models import (
    AnalysisFinding,
    Category,
    ColumnProfile,
    DatasetProfile,
    TextRecord,
)
from quick_insight.infrastructure.workspace import WorkspaceDatabase

_UNCATEGORIZED_ID = "__uncategorized__"
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")


@dataclass(frozen=True)
class TextProfileOptions:
    keywords: tuple[str, ...] = ()
    extremely_short_chars: int = 5
    extremely_long_chars: int = 500
    top_n_tokens: int = 20


class TextCorpusProfiler:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def profile_corpus(
        self,
        dataset_id: str,
        corpus_id: str,
        *,
        options: TextProfileOptions | None = None,
    ) -> DatasetProfile:
        resolved_options = options or TextProfileOptions()
        records = self._workspace.list_text_records(corpus_id)
        categories = self._workspace.list_categories()
        category_by_id = {category.id: category for category in categories}
        row_count = len(records)

        empty_record_count = sum(1 for record in records if not record.content.strip())
        text_lengths = [len(record.content.strip()) for record in records]
        duplicate_groups, category_conflicts = _duplicate_summaries(records, category_by_id)
        exact_duplicate_record_count = sum(
            _entry_int(group, "count") - 1 for group in duplicate_groups
        )
        short_record_count = sum(
            1
            for length in text_lengths
            if 0 < length <= resolved_options.extremely_short_chars
        )
        long_record_count = sum(
            1 for length in text_lengths if length >= resolved_options.extremely_long_chars
        )
        uncategorized_count = sum(1 for record in records if not record.primary_category_id)
        missing_source_count = sum(1 for record in records if not (record.source or "").strip())
        near_duplicate_category_names = _near_duplicate_category_names(categories)
        tag_co_occurrence = _tag_co_occurrence(records)
        keyword_matches, per_category_keyword_counts = _keyword_summaries(
            records,
            resolved_options,
            category_by_id,
        )
        high_frequency_tokens = _high_frequency_tokens(records, resolved_options.top_n_tokens)

        category_counts = _category_counts(records, category_by_id)
        tag_counts = _counter_entries(_tag_counts(records), key_name="tag")
        source_counts = _counter_entries(_source_counts(records), key_name="source")
        length_summary = _text_length_summary(text_lengths, resolved_options)
        quality = {
            "empty_record_count": empty_record_count,
            "exact_duplicate_record_count": exact_duplicate_record_count,
            "exact_duplicate_content_groups": duplicate_groups,
            "short_record_count": short_record_count,
            "long_record_count": long_record_count,
            "category_conflicts": category_conflicts,
            "near_duplicate_category_names": near_duplicate_category_names,
            "missing_source_count": missing_source_count,
            "missing_source_ratio": _ratio(missing_source_count, row_count),
        }
        summary: dict[str, Any] = {
            "dataset_kind": "text_corpus",
            "record_count": row_count,
            "column_count": 4,
            "categorized_count": row_count - uncategorized_count,
            "uncategorized_count": uncategorized_count,
            "category_counts": category_counts,
            "tag_counts": tag_counts,
            "source_counts": source_counts,
            "text_length": length_summary,
            "quality": quality,
            "empty_record_count": empty_record_count,
            "exact_duplicate_record_count": exact_duplicate_record_count,
            "short_record_count": short_record_count,
            "long_record_count": long_record_count,
            "missing_source_count": missing_source_count,
            "missing_source_ratio": _ratio(missing_source_count, row_count),
            "keyword_matches": keyword_matches,
            "per_category_keyword_counts": per_category_keyword_counts,
            "high_frequency_tokens": high_frequency_tokens,
            "tag_co_occurrence": tag_co_occurrence,
            "processing": {
                "approximate": False,
                "sampling": None,
                "tokenization": "regex_cjk_bigrams_and_alnum_tokens",
                "normalization": "casefold_for_latin_keywords; content_hash_for_duplicates",
                "stop_words": (),
                "method": "python_full_scan_text_records_from_duckdb",
            },
            "semantic_type_counts": {
                ColumnSemanticType.LONG_TEXT.value: 1,
                ColumnSemanticType.PRIMARY_CATEGORY.value: 1,
                ColumnSemanticType.TAG_LIST.value: 1,
                ColumnSemanticType.SOURCE_REFERENCE.value: 1,
            },
        }
        warnings = _dataset_warnings(
            row_count=row_count,
            empty_record_count=empty_record_count,
            exact_duplicate_record_count=exact_duplicate_record_count,
            short_record_count=short_record_count,
            long_record_count=long_record_count,
            uncategorized_count=uncategorized_count,
            missing_source_count=missing_source_count,
            category_conflicts=category_conflicts,
            near_duplicate_category_names=near_duplicate_category_names,
        )
        column_profiles = _column_profiles(
            records=records,
            summary=summary,
            warnings=warnings,
        )
        findings = _build_findings(summary, warnings)
        return DatasetProfile(
            dataset_id=dataset_id,
            row_count=row_count,
            column_profiles=column_profiles,
            approximate=False,
            method="text_corpus_full_scan",
            summary=summary,
            warnings=warnings,
            findings=findings,
        )


def tokenize_text(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text.casefold()):
        token = match.group(0)
        if _CJK_RE.match(token):
            if len(token) < 2:
                continue
            if len(token) <= 4:
                tokens.append(token)
                continue
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
            continue
        if len(token) >= 2:
            tokens.append(token)
    return tuple(tokens)


def _column_profiles(
    *,
    records: tuple[TextRecord, ...],
    summary: dict[str, Any],
    warnings: tuple[str, ...],
) -> tuple[ColumnProfile, ...]:
    distinct_contents = len({record.content for record in records})
    distinct_categories = len(
        {record.primary_category_id for record in records if record.primary_category_id}
    )
    distinct_tags = len({tag for record in records for tag in record.tags})
    distinct_sources = len(
        {record.source.strip() for record in records if record.source and record.source.strip()}
    )
    content_warnings = tuple(
        warning
        for warning in (
            "empty_text_records" if "empty_text_records_present" in warnings else "",
            "exact_duplicate_text" if "exact_duplicate_text_present" in warnings else "",
            "extreme_text_lengths" if "extreme_text_lengths_present" in warnings else "",
        )
        if warning
    )
    category_warnings = tuple(
        warning
        for warning in (
            "uncategorized_records" if "uncategorized_records_present" in warnings else "",
            "category_conflicts" if "category_conflicts_present" in warnings else "",
            "near_duplicate_category_names"
            if "near_duplicate_category_names_present" in warnings
            else "",
        )
        if warning
    )
    source_warnings = (
        ("missing_sources",) if "missing_sources_present" in warnings else ()
    )
    return (
        ColumnProfile(
            name="content",
            semantic_type=ColumnSemanticType.LONG_TEXT,
            null_count=int(summary["empty_record_count"]),
            distinct_count=distinct_contents,
            warnings=content_warnings,
            summary={
                "text_length": summary["text_length"],
                "empty_record_count": summary["empty_record_count"],
                "exact_duplicate_record_count": summary["exact_duplicate_record_count"],
                "exact_duplicate_content_groups": summary["quality"][
                    "exact_duplicate_content_groups"
                ],
                "short_record_count": summary["short_record_count"],
                "long_record_count": summary["long_record_count"],
                "high_frequency_tokens": summary["high_frequency_tokens"],
            },
        ),
        ColumnProfile(
            name="primary_category",
            semantic_type=ColumnSemanticType.PRIMARY_CATEGORY,
            null_count=int(summary["uncategorized_count"]),
            distinct_count=distinct_categories,
            warnings=category_warnings,
            summary={
                "categorized_count": summary["categorized_count"],
                "uncategorized_count": summary["uncategorized_count"],
                "category_counts": summary["category_counts"],
                "category_conflicts": summary["quality"]["category_conflicts"],
                "near_duplicate_category_names": summary["quality"][
                    "near_duplicate_category_names"
                ],
            },
        ),
        ColumnProfile(
            name="tags",
            semantic_type=ColumnSemanticType.TAG_LIST,
            null_count=sum(1 for record in records if not record.tags),
            distinct_count=distinct_tags,
            summary={
                "tag_counts": summary["tag_counts"],
                "tag_co_occurrence": summary["tag_co_occurrence"],
            },
        ),
        ColumnProfile(
            name="source",
            semantic_type=ColumnSemanticType.SOURCE_REFERENCE,
            null_count=int(summary["missing_source_count"]),
            distinct_count=distinct_sources,
            warnings=source_warnings,
            summary={
                "source_counts": summary["source_counts"],
                "missing_source_count": summary["missing_source_count"],
                "missing_source_ratio": summary["missing_source_ratio"],
            },
        ),
    )


def _dataset_warnings(
    *,
    row_count: int,
    empty_record_count: int,
    exact_duplicate_record_count: int,
    short_record_count: int,
    long_record_count: int,
    uncategorized_count: int,
    missing_source_count: int,
    category_conflicts: tuple[dict[str, object], ...],
    near_duplicate_category_names: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if row_count == 0:
        warnings.append("empty_text_corpus")
    if empty_record_count:
        warnings.append("empty_text_records_present")
    if exact_duplicate_record_count:
        warnings.append("exact_duplicate_text_present")
    if short_record_count or long_record_count:
        warnings.append("extreme_text_lengths_present")
    if uncategorized_count:
        warnings.append("uncategorized_records_present")
    if missing_source_count:
        warnings.append("missing_sources_present")
    if category_conflicts:
        warnings.append("category_conflicts_present")
    if near_duplicate_category_names:
        warnings.append("near_duplicate_category_names_present")
    return tuple(warnings)


def _build_findings(
    summary: dict[str, Any],
    warnings: tuple[str, ...],
) -> tuple[AnalysisFinding, ...]:
    findings: list[AnalysisFinding] = []
    quality = summary["quality"]
    if "uncategorized_records_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="部分文本尚未设置主类别，后续分类统计需要先补齐或单独标记。",
                evidence={
                    "record_count": summary["record_count"],
                    "uncategorized_count": summary["uncategorized_count"],
                    "uncategorized_ratio": _ratio(
                        int(summary["uncategorized_count"]),
                        int(summary["record_count"]),
                    ),
                },
                method="text_records_primary_category_null_count",
                fields=("primary_category",),
                warnings=("uncategorized_records_present",),
            )
        )
    if "missing_sources_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="部分文本缺少来源，追溯或按来源比较时需要谨慎。",
                evidence={
                    "missing_source_count": summary["missing_source_count"],
                    "missing_source_ratio": summary["missing_source_ratio"],
                },
                method="text_records_source_empty_count",
                fields=("source",),
                warnings=("source_missing_limits_traceability",),
            )
        )
    if "exact_duplicate_text_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="发现完全重复的文本内容，去重前需要确认它们是否代表独立记录。",
                evidence={
                    "duplicate_record_count": summary["exact_duplicate_record_count"],
                    "groups": quality["exact_duplicate_content_groups"],
                },
                method="sha256_exact_content_grouping",
                fields=("content",),
                warnings=("deduplicate_only_after_user_confirmation",),
            )
        )
    if "category_conflicts_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="相同文本被分到多个主类别，建议人工核对分类口径。",
                evidence={"conflicts": quality["category_conflicts"]},
                method="duplicate_content_category_comparison",
                fields=("content", "primary_category"),
                warnings=("category_conflicts_require_review",),
            )
        )
    if "extreme_text_lengths_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="存在极短或极长文本，可能需要在分析前确认拆分规则。",
                evidence={
                    "short_record_count": summary["short_record_count"],
                    "long_record_count": summary["long_record_count"],
                    "text_length": summary["text_length"],
                },
                method="character_length_distribution",
                fields=("content",),
                warnings=("review_split_rules_before_analysis",),
            )
        )
    if "near_duplicate_category_names_present" in warnings:
        findings.append(
            AnalysisFinding(
                statement="类别名称可能存在近似重复，合并前需要查看各类别记录数量。",
                evidence={"pairs": quality["near_duplicate_category_names"]},
                method="normalized_name_similarity",
                fields=("primary_category",),
                warnings=("review_before_merging_categories",),
            )
        )
    keyword_matches = tuple(summary["keyword_matches"])
    if keyword_matches:
        findings.append(
            AnalysisFinding(
                statement="已按指定关键字统计命中记录，结果仅说明字面匹配。",
                evidence={"keyword_matches": keyword_matches},
                method="casefold_substring_keyword_count",
                fields=("content",),
                warnings=("keyword_matches_are_surface_level",),
            )
        )
    high_frequency_tokens = tuple(summary["high_frequency_tokens"])
    if high_frequency_tokens and int(high_frequency_tokens[0]["count"]) >= 2:
        findings.append(
            AnalysisFinding(
                statement="已生成高频表面词线索，不能直接当作语义主题结论。",
                evidence={"top_tokens": high_frequency_tokens[:5]},
                method="regex_surface_token_frequency",
                fields=("content",),
                warnings=("token_frequency_is_not_semantic_topic_modeling",),
            )
        )
    tag_co_occurrence = tuple(summary["tag_co_occurrence"])
    if tag_co_occurrence and int(tag_co_occurrence[0]["count"]) >= 2:
        findings.append(
            AnalysisFinding(
                statement="部分标签经常共同出现，可作为后续筛选或交叉分析线索。",
                evidence={"top_pairs": tag_co_occurrence[:5]},
                method="tag_pair_co_occurrence_count",
                fields=("tags",),
                warnings=("co_occurrence_is_not_causation",),
            )
        )
    return tuple(findings)


def _duplicate_summaries(
    records: tuple[TextRecord, ...],
    category_by_id: dict[str, Category],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    by_content: dict[str, list[TextRecord]] = {}
    for record in records:
        by_content.setdefault(record.content, []).append(record)
    duplicate_groups: list[dict[str, object]] = []
    category_conflicts: list[dict[str, object]] = []
    for content, group in by_content.items():
        if len(group) <= 1:
            continue
        category_ids = tuple(
            sorted({record.primary_category_id or _UNCATEGORIZED_ID for record in group})
        )
        summary = {
            "content_hash": _content_hash(content),
            "count": len(group),
            "record_ids": tuple(record.id for record in group[:20]),
            "category_ids": category_ids,
            "category_names": tuple(
                _category_name(category_id, category_by_id) for category_id in category_ids
            ),
        }
        duplicate_groups.append(summary)
        if len(category_ids) > 1:
            category_conflicts.append(summary)
    duplicate_groups.sort(
        key=lambda item: (-_entry_int(item, "count"), str(item["content_hash"]))
    )
    category_conflicts.sort(
        key=lambda item: (-_entry_int(item, "count"), str(item["content_hash"]))
    )
    return tuple(duplicate_groups[:20]), tuple(category_conflicts[:20])


def _category_counts(
    records: tuple[TextRecord, ...],
    category_by_id: dict[str, Category],
) -> tuple[dict[str, object], ...]:
    counter: Counter[str] = Counter(
        record.primary_category_id or _UNCATEGORIZED_ID for record in records
    )
    return tuple(
        {
            "category_id": None if category_id == _UNCATEGORIZED_ID else category_id,
            "name": _category_name(category_id, category_by_id),
            "count": count,
        }
        for category_id, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    )


def _tag_counts(records: tuple[TextRecord, ...]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for record in records:
        counter.update(tag for tag in record.tags if tag.strip())
    return counter


def _source_counts(records: tuple[TextRecord, ...]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for record in records:
        source = (record.source or "").strip()
        if source:
            counter[source] += 1
    return counter


def _counter_entries(counter: Counter[str], *, key_name: str) -> tuple[dict[str, object], ...]:
    return tuple(
        {key_name: key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    )


def _keyword_summaries(
    records: tuple[TextRecord, ...],
    options: TextProfileOptions,
    category_by_id: dict[str, Category],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    keywords = tuple(
        dict.fromkeys(keyword.strip() for keyword in options.keywords if keyword.strip())
    )
    if not keywords:
        return (), ()
    keyword_entries: list[dict[str, object]] = []
    per_category: dict[str, Counter[str]] = {}
    for keyword in keywords:
        needle = keyword.casefold()
        matched_count = 0
        for record in records:
            if needle not in record.content.casefold():
                continue
            matched_count += 1
            category_id = record.primary_category_id or _UNCATEGORIZED_ID
            per_category.setdefault(category_id, Counter())[keyword] += 1
        keyword_entries.append({"keyword": keyword, "record_count": matched_count})
    per_category_entries: list[dict[str, object]] = []
    for category_id, counter in sorted(per_category.items(), key=lambda item: item[0]):
        per_category_entries.append(
            {
                "category_id": None if category_id == _UNCATEGORIZED_ID else category_id,
                "name": _category_name(category_id, category_by_id),
                "keywords": tuple(
                    {"keyword": keyword, "record_count": count}
                    for keyword, count in sorted(
                        counter.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ),
            }
        )
    return tuple(keyword_entries), tuple(per_category_entries)


def _high_frequency_tokens(
    records: tuple[TextRecord, ...],
    limit: int,
) -> tuple[dict[str, object], ...]:
    counter: Counter[str] = Counter()
    for record in records:
        counter.update(tokenize_text(record.content))
    return tuple(
        {"token": token, "count": count}
        for token, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[
            : max(limit, 0)
        ]
    )


def _tag_co_occurrence(records: tuple[TextRecord, ...]) -> tuple[dict[str, object], ...]:
    counter: Counter[tuple[str, str]] = Counter()
    for record in records:
        tags = tuple(sorted({tag.strip() for tag in record.tags if tag.strip()}))
        for left, right in combinations(tags, 2):
            counter[(left, right)] += 1
    return tuple(
        {"tags": tags, "count": count}
        for tags, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    )


def _near_duplicate_category_names(
    categories: tuple[Category, ...],
) -> tuple[dict[str, object], ...]:
    pairs: list[dict[str, object]] = []
    for left_index, left in enumerate(categories):
        left_normalized = _normalize_category_name(left.name)
        if not left_normalized:
            continue
        for right in categories[left_index + 1 :]:
            right_normalized = _normalize_category_name(right.name)
            if not right_normalized:
                continue
            similarity = SequenceMatcher(None, left_normalized, right_normalized).ratio()
            normalized_equal = left_normalized == right_normalized
            if not normalized_equal and similarity < 0.88:
                continue
            pairs.append(
                {
                    "left_id": left.id,
                    "left_name": left.name,
                    "right_id": right.id,
                    "right_name": right.name,
                    "similarity": round(similarity, 3),
                    "reason": "normalized_equal" if normalized_equal else "high_similarity",
                }
            )
    pairs.sort(key=lambda item: (-_entry_float(item, "similarity"), str(item["left_name"])))
    return tuple(pairs[:10])


def _text_length_summary(
    lengths: list[int],
    options: TextProfileOptions,
) -> dict[str, object]:
    if not lengths:
        return {
            "min": 0,
            "max": 0,
            "mean": 0.0,
            "median": 0.0,
            "p90": 0,
            "short_threshold_chars": options.extremely_short_chars,
            "long_threshold_chars": options.extremely_long_chars,
        }
    sorted_lengths = sorted(lengths)
    return {
        "min": sorted_lengths[0],
        "max": sorted_lengths[-1],
        "mean": sum(sorted_lengths) / len(sorted_lengths),
        "median": _median(sorted_lengths),
        "p90": _nearest_percentile(sorted_lengths, 0.9),
        "short_threshold_chars": options.extremely_short_chars,
        "long_threshold_chars": options.extremely_long_chars,
    }


def _median(sorted_values: list[int]) -> float:
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return float(sorted_values[midpoint])
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2


def _nearest_percentile(sorted_values: list[int], quantile: float) -> int:
    if not sorted_values:
        return 0
    index = round((len(sorted_values) - 1) * quantile)
    return sorted_values[index]


def _content_hash(content: str) -> str:
    return sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]


def _category_name(category_id: str, category_by_id: dict[str, Category]) -> str:
    if category_id == _UNCATEGORIZED_ID:
        return "未分类"
    category = category_by_id.get(category_id)
    return category.name if category is not None else category_id


def _normalize_category_name(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", name.casefold())


def _ratio(part: int, whole: int) -> float:
    return 0.0 if whole <= 0 else part / whole


def _entry_int(entry: dict[str, object], key: str) -> int:
    value = entry[key]
    if isinstance(value, int):
        return value
    return int(str(value))


def _entry_float(entry: dict[str, object], key: str) -> float:
    value = entry[key]
    if isinstance(value, int | float):
        return float(value)
    return float(str(value))
