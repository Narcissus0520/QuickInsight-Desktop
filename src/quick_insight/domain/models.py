from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quick_insight.domain.enums import ColumnSemanticType, DatasetKind


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DatasetHandle:
    id: str
    kind: DatasetKind
    display_name: str
    schema_version: int = 1
    source_path: Path | None = None
    workspace_path: Path | None = None
    row_count: int | None = None
    column_count: int | None = None
    import_options: dict[str, Any] = field(default_factory=dict)
    fingerprint: str | None = None
    cache_key: str | None = None


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    semantic_type: ColumnSemanticType
    null_count: int
    distinct_count: int | None
    approximate: bool = False
    warnings: tuple[str, ...] = ()
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetProfile:
    dataset_id: str
    row_count: int
    column_profiles: tuple[ColumnProfile, ...]
    approximate: bool = False
    sample_row_count: int | None = None
    method: str = "not_profiled"
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    findings: tuple[AnalysisFinding, ...] = ()


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    description: str = ""
    color: str = "#2563eb"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    schema_version: int = 1


@dataclass(frozen=True)
class CategoryAuditRecord:
    id: str
    corpus_id: str
    action: str
    source_category_id: str | None
    source_category_name: str
    target_category_id: str | None = None
    target_category_name: str | None = None
    affected_record_count: int = 0
    note: str = ""
    created_at: datetime = field(default_factory=utc_now)
    schema_version: int = 1


@dataclass(frozen=True)
class TextRecord:
    id: str
    content: str
    primary_category_id: str | None = None
    tags: tuple[str, ...] = ()
    source: str | None = None
    location: str | None = None
    speaker: str | None = None
    record_time: datetime | None = None
    note: str = ""
    custom_fields: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    schema_version: int = 1


@dataclass(frozen=True)
class TransformStep:
    id: str
    operation: str
    parameters: dict[str, Any]
    reversible: bool
    schema_version: int = 1


@dataclass(frozen=True)
class AnalysisFinding:
    statement: str
    evidence: dict[str, Any]
    method: str
    fields: tuple[str, ...] = ()
    sample_query: str | None = None
    approximate: bool = False
    warnings: tuple[str, ...] = ()
    schema_version: int = 1


@dataclass(frozen=True)
class ChartSpec:
    id: str
    chart_type: str
    mappings: dict[str, str]
    aggregation: dict[str, Any] = field(default_factory=dict)
    filters: tuple[TransformStep, ...] = ()
    style: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class ChartRecommendation:
    spec: ChartSpec
    score: int
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    data_budget: dict[str, Any] = field(default_factory=dict)
    export_strategy: str = "not_prepared"
    schema_version: int = 1


@dataclass(frozen=True)
class PreparedChartDataset:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    original_rows: int
    rendered_rows: int
    method: str
    parameters: dict[str, Any] = field(default_factory=dict)
    approximate: bool = False
    schema_version: int = 1

    def metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "original_rows": self.original_rows,
            "rendered_rows": self.rendered_rows,
            "method": self.method,
            "parameters": self.parameters,
            "approximate": self.approximate,
        }
