from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256

from quick_insight.application.errors import UserFacingError
from quick_insight.domain.models import Category, TextRecord, utc_now
from quick_insight.infrastructure.workspace import WorkspaceDatabase

UNCATEGORIZED_FILTER = "__uncategorized__"


@dataclass(frozen=True)
class TextRecordFilter:
    search_text: str = ""
    category_id: str | None = None
    uncategorized_only: bool = False


@dataclass(frozen=True)
class TextRecordEdit:
    record_id: str
    content: str
    category_name: str
    tags_text: str
    source: str
    location: str
    speaker: str
    note: str


class TextLabelingService:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def list_categories(self) -> tuple[Category, ...]:
        return self._workspace.list_categories()

    def category_usage_counts(self, corpus_id: str) -> dict[str, int]:
        return self._workspace.category_usage_counts(corpus_id)

    def count_records(self, corpus_id: str, record_filter: TextRecordFilter) -> int:
        return self._workspace.text_record_count_filtered(
            corpus_id,
            search_text=record_filter.search_text,
            category_id=record_filter.category_id,
            uncategorized_only=record_filter.uncategorized_only,
        )

    def fetch_records(
        self,
        corpus_id: str,
        *,
        limit: int,
        offset: int,
        record_filter: TextRecordFilter,
    ) -> tuple[TextRecord, ...]:
        return self._workspace.fetch_text_records_page(
            corpus_id,
            limit=limit,
            offset=offset,
            search_text=record_filter.search_text,
            category_id=record_filter.category_id,
            uncategorized_only=record_filter.uncategorized_only,
        )

    def update_record(
        self,
        corpus_id: str,
        original: TextRecord,
        edit: TextRecordEdit,
    ) -> TextRecord:
        if original.id != edit.record_id:
            raise ValueError("Edited record does not match the selected record.")
        content = edit.content.strip()
        if not content:
            raise UserFacingError(
                code="TEXT_LABEL_EMPTY_CONTENT",
                title_zh="文本内容不能为空",
                message_zh="每条文本记录需要保留可识别的内容。",
                next_action_zh="请填写文本内容，或取消当前编辑。",
            )
        category = self.ensure_category(edit.category_name)
        updated = replace(
            original,
            content=content,
            primary_category_id=category.id if category is not None else None,
            tags=_parse_tags(edit.tags_text),
            source=_optional_text(edit.source),
            location=_optional_text(edit.location),
            speaker=_optional_text(edit.speaker),
            note=edit.note.strip(),
            updated_at=utc_now(),
        )
        self._workspace.update_text_record(corpus_id, updated)
        return updated

    def update_record_category_and_tags(
        self,
        corpus_id: str,
        record: TextRecord,
        *,
        category_name: str,
        tags_text: str,
    ) -> TextRecord:
        category = self.ensure_category(category_name)
        updated = replace(
            record,
            primary_category_id=category.id if category is not None else None,
            tags=_parse_tags(tags_text),
            updated_at=utc_now(),
        )
        self._workspace.update_text_record(corpus_id, updated)
        return updated

    def restore_record(self, corpus_id: str, snapshot: TextRecord) -> None:
        self._workspace.update_text_record(corpus_id, replace(snapshot, updated_at=utc_now()))

    def ensure_category(self, name: str) -> Category | None:
        normalized = name.strip()
        if not normalized:
            return None
        for category in self._workspace.list_categories():
            if category.name.casefold() == normalized.casefold():
                return category
        category = Category(id=_category_id(normalized), name=normalized)
        self._workspace.upsert_category(category)
        return category


def _parse_tags(tags_text: str) -> tuple[str, ...]:
    tags: list[str] = []
    for raw_tag in tags_text.replace("，", ",").split(","):
        tag = raw_tag.strip()
        if tag:
            tags.append(tag)
    return tuple(dict.fromkeys(tags))


def _optional_text(value: str) -> str | None:
    normalized = value.strip()
    return normalized or None


def _category_id(name: str) -> str:
    digest = sha256(name.encode("utf-8", errors="replace"))
    return f"cat_{digest.hexdigest()[:16]}"
