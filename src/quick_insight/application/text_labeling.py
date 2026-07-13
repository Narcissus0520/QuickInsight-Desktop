from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from uuid import uuid4

from quick_insight.application.errors import UserFacingError
from quick_insight.domain.models import Category, CategoryAuditRecord, TextRecord, utc_now
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


@dataclass(frozen=True)
class CategoryOperationResult:
    audit: CategoryAuditRecord
    categories: tuple[Category, ...]
    usage_counts: dict[str, int]


class TextLabelingService:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def list_categories(self) -> tuple[Category, ...]:
        return self._workspace.list_categories()

    def category_usage_counts(self, corpus_id: str) -> dict[str, int]:
        return self._workspace.category_usage_counts(corpus_id)

    def list_category_audit(
        self,
        corpus_id: str,
        *,
        limit: int = 100,
    ) -> tuple[CategoryAuditRecord, ...]:
        return self._workspace.list_category_audit(corpus_id, limit=limit)

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

    def rename_category(
        self,
        corpus_id: str,
        category_id: str,
        *,
        new_name: str,
        new_description: str,
        note: str = "",
    ) -> CategoryOperationResult:
        normalized_name = new_name.strip()
        if not normalized_name:
            raise UserFacingError(
                code="TEXT_CATEGORY_EMPTY_NAME",
                title_zh="分类名称不能为空",
                message_zh="重命名分类需要一个可显示的名称。",
                next_action_zh="请输入分类名称后再保存。",
            )
        changed_at = utc_now()
        try:
            audit = self._workspace.rename_category(
                corpus_id,
                category_id,
                new_name=normalized_name,
                new_description=new_description.strip(),
                audit_id=_audit_id("rename"),
                note=note.strip(),
                changed_at=changed_at,
            )
        except ValueError as exc:
            raise _category_operation_error(exc) from exc
        return self._category_operation_result(corpus_id, audit)

    def merge_categories(
        self,
        corpus_id: str,
        *,
        source_category_id: str,
        target_category_id: str,
        note: str = "",
    ) -> CategoryOperationResult:
        if not source_category_id or not target_category_id:
            raise UserFacingError(
                code="TEXT_CATEGORY_MISSING_SELECTION",
                title_zh="请选择分类",
                message_zh="合并分类需要同时选择来源分类和目标分类。",
                next_action_zh="请在分类管理区域选择两个不同的分类。",
            )
        if source_category_id == target_category_id:
            raise UserFacingError(
                code="TEXT_CATEGORY_SAME_TARGET",
                title_zh="不能合并到自身",
                message_zh="来源分类和目标分类相同，数据不会发生变化。",
                next_action_zh="请选择另一个目标分类后再合并。",
            )
        changed_at = utc_now()
        try:
            audit = self._workspace.merge_categories(
                corpus_id,
                source_category_id,
                target_category_id,
                audit_id=_audit_id("merge"),
                note=note.strip(),
                changed_at=changed_at,
            )
        except ValueError as exc:
            raise _category_operation_error(exc) from exc
        return self._category_operation_result(corpus_id, audit)

    def delete_category(
        self,
        corpus_id: str,
        *,
        category_id: str,
        replacement_category_id: str | None,
        note: str = "",
    ) -> CategoryOperationResult:
        if not category_id:
            raise UserFacingError(
                code="TEXT_CATEGORY_MISSING_SELECTION",
                title_zh="请选择分类",
                message_zh="删除分类需要先选择一个现有分类。",
                next_action_zh="请在分类管理区域选择要删除的分类。",
            )
        if replacement_category_id == category_id:
            raise UserFacingError(
                code="TEXT_CATEGORY_SAME_TARGET",
                title_zh="不能替换到自身",
                message_zh="删除分类时不能把记录替换到同一个分类。",
                next_action_zh="请选择其它分类，或改为删除后设为未分类。",
            )
        changed_at = utc_now()
        try:
            audit = self._workspace.delete_category(
                corpus_id,
                category_id,
                replacement_category_id=replacement_category_id,
                audit_id=_audit_id("delete"),
                note=note.strip(),
                changed_at=changed_at,
            )
        except ValueError as exc:
            raise _category_operation_error(exc) from exc
        return self._category_operation_result(corpus_id, audit)

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

    def _category_operation_result(
        self,
        corpus_id: str,
        audit: CategoryAuditRecord,
    ) -> CategoryOperationResult:
        return CategoryOperationResult(
            audit=audit,
            categories=self.list_categories(),
            usage_counts=self.category_usage_counts(corpus_id),
        )


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


def _audit_id(action: str) -> str:
    return f"category_audit_{action}_{uuid4().hex}"


def _category_operation_error(error: ValueError) -> UserFacingError:
    return UserFacingError(
        code="TEXT_CATEGORY_OPERATION_FAILED",
        title_zh="分类操作失败",
        message_zh="分类未被修改，现有文本记录保持不变。",
        next_action_zh="请检查分类是否存在、名称是否重复，或是否仍被其它语料引用。",
        technical_detail=str(error),
    )
