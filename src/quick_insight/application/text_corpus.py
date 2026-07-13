from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from quick_insight.application.errors import UserFacingError
from quick_insight.domain.enums import DatasetKind
from quick_insight.domain.models import Category, DatasetHandle, TextRecord, utc_now
from quick_insight.infrastructure.csv_import import fingerprint_file
from quick_insight.infrastructure.workspace import WorkspaceDatabase


class TextSplitMode(StrEnum):
    NON_EMPTY_LINE = "non_empty_line"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    CUSTOM_DELIMITER = "custom_delimiter"
    WHOLE_INPUT = "whole_input"


@dataclass(frozen=True)
class TextImportOptions:
    split_mode: TextSplitMode = TextSplitMode.NON_EMPTY_LINE
    custom_delimiter: str = ""
    default_category: str = ""
    default_tags: tuple[str, ...] = ()
    default_source: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["split_mode"] = self.split_mode.value
        payload["default_tags"] = list(self.default_tags)
        return payload


@dataclass(frozen=True)
class TextCorpusPreview:
    display_name: str
    records: tuple[TextRecord, ...]
    categories: tuple[Category, ...]
    options: TextImportOptions
    source_path: Path | None = None
    fingerprint: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextCorpusImportResult:
    handle: DatasetHandle
    records: tuple[TextRecord, ...]
    categories: tuple[Category, ...]


class TextCorpusService:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def preview_text(
        self,
        content: str,
        *,
        display_name: str = "手动文本语料",
        options: TextImportOptions | None = None,
    ) -> TextCorpusPreview:
        resolved_options = options or TextImportOptions()
        segments, warnings = split_text(content, resolved_options)
        if not segments:
            raise UserFacingError(
                code="TEXT_CORPUS_EMPTY",
                title_zh="没有可导入的文本",
                message_zh="当前输入为空，或按拆分规则没有得到任何文本语句。",
                next_action_zh="请输入文本，或调整拆分方式后重新预览。",
            )
        categories = _categories_for_names([resolved_options.default_category])
        records = _records_from_segments(
            segments,
            display_name=display_name,
            options=resolved_options,
            source_path=None,
            categories=categories,
        )
        fingerprint = _fingerprint_text(display_name, content, resolved_options)
        return TextCorpusPreview(
            display_name=display_name,
            records=records,
            categories=categories,
            options=resolved_options,
            fingerprint=fingerprint,
            warnings=warnings,
        )

    def preview_file(
        self,
        path: Path,
        *,
        options: TextImportOptions | None = None,
    ) -> TextCorpusPreview:
        source = path.expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise UserFacingError(
                code="TEXT_CORPUS_SOURCE_NOT_FOUND",
                title_zh="找不到文本文件",
                message_zh="请选择一个存在的 TXT、Markdown 或 JSONL 文件。",
                next_action_zh="检查文件路径后重新选择。",
                technical_detail=str(source),
            )
        resolved_options = options or TextImportOptions()
        suffix = source.suffix.lower()
        if suffix == ".jsonl":
            records, categories, warnings = self._preview_jsonl(source, resolved_options)
        elif suffix in {".txt", ".md", ".markdown"}:
            content = _read_text_source(source)
            segments, warnings = split_text(content, resolved_options)
            categories = _categories_for_names([resolved_options.default_category])
            records = _records_from_segments(
                segments,
                display_name=source.name,
                options=resolved_options,
                source_path=source,
                categories=categories,
            )
        else:
            raise UserFacingError(
                code="TEXT_CORPUS_UNSUPPORTED_FORMAT",
                title_zh="不支持的文本格式",
                message_zh="文本语料导入当前支持 TXT、Markdown 和 JSONL。",
                next_action_zh="请转换文件格式后重新导入。",
                technical_detail=str(source),
            )
        if not records:
            raise UserFacingError(
                code="TEXT_CORPUS_EMPTY",
                title_zh="没有可导入的文本",
                message_zh="文件中没有找到有效的文本语句。",
                next_action_zh="请检查文件内容或拆分方式。",
                technical_detail=str(source),
            )
        return TextCorpusPreview(
            display_name=source.name,
            records=records,
            categories=categories,
            options=resolved_options,
            source_path=source,
            fingerprint=fingerprint_file(source),
            warnings=warnings,
        )

    def import_preview(self, preview: TextCorpusPreview) -> TextCorpusImportResult:
        corpus_id = preview.fingerprint or _fingerprint_preview(preview)
        self._workspace.save_text_corpus(corpus_id, preview.records, preview.categories)
        handle = DatasetHandle(
            id=corpus_id[:16],
            kind=DatasetKind.TEXT_CORPUS,
            display_name=preview.display_name,
            source_path=preview.source_path,
            workspace_path=self._workspace.path,
            row_count=len(preview.records),
            column_count=None,
            import_options=preview.options.to_dict(),
            fingerprint=preview.fingerprint,
            cache_key=corpus_id,
        )
        return TextCorpusImportResult(
            handle=handle,
            records=preview.records,
            categories=preview.categories,
        )

    def _preview_jsonl(
        self,
        source: Path,
        options: TextImportOptions,
    ) -> tuple[tuple[TextRecord, ...], tuple[Category, ...], tuple[str, ...]]:
        warnings: list[str] = []
        raw_records: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(_read_text_source(source).splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise UserFacingError(
                    code="TEXT_CORPUS_JSONL_PARSE_FAILED",
                    title_zh="JSONL 解析失败",
                    message_zh=f"第 {line_number} 行不是有效 JSON。",
                    next_action_zh="请修正该行后重新预览。",
                    technical_detail=str(exc),
                ) from exc
            if not isinstance(payload, dict):
                warnings.append(f"第 {line_number} 行不是对象，已跳过。")
                continue
            raw_records.append(payload)
        category_names = [
            str(payload.get("primary_category") or "").strip() for payload in raw_records
        ]
        if options.default_category:
            category_names.append(options.default_category)
        categories = _categories_for_names(category_names)
        category_by_name = {category.name: category for category in categories}
        records = tuple(
            _record_from_json_payload(
                payload,
                source=source,
                index=index,
                default_options=options,
                category_by_name=category_by_name,
            )
            for index, payload in enumerate(raw_records)
            if str(payload.get("content") or "").strip()
        )
        skipped_empty = len(raw_records) - len(records)
        if skipped_empty:
            warnings.append(f"跳过 {skipped_empty} 条空 content 记录。")
        return records, categories, tuple(warnings)


def split_text(content: str, options: TextImportOptions) -> tuple[tuple[str, ...], tuple[str, ...]]:
    warnings: list[str] = []
    if options.split_mode is TextSplitMode.WHOLE_INPUT:
        raw_segments = [content]
    elif options.split_mode is TextSplitMode.PARAGRAPH:
        raw_segments = re.split(r"(?:\r?\n\s*){2,}", content)
    elif options.split_mode is TextSplitMode.SENTENCE:
        raw_segments = re.split(r"(?<=[。！？!?\.])\s*", content)
    elif options.split_mode is TextSplitMode.CUSTOM_DELIMITER:
        if not options.custom_delimiter:
            raise UserFacingError(
                code="TEXT_CORPUS_MISSING_DELIMITER",
                title_zh="缺少自定义分隔符",
                message_zh="选择自定义分隔方式时需要填写分隔符。",
                next_action_zh="填写分隔符后重新预览。",
            )
        raw_segments = content.split(options.custom_delimiter)
    else:
        raw_segments = content.splitlines()
    if options.split_mode is TextSplitMode.SENTENCE and raw_segments and raw_segments[-1] == "":
        raw_segments = raw_segments[:-1]
    segments = tuple(segment.strip() for segment in raw_segments if segment.strip())
    skipped = len(raw_segments) - len(segments)
    if skipped:
        warnings.append(f"已跳过 {skipped} 个空片段。")
    return segments, tuple(warnings)


def _records_from_segments(
    segments: tuple[str, ...],
    *,
    display_name: str,
    options: TextImportOptions,
    source_path: Path | None,
    categories: tuple[Category, ...],
) -> tuple[TextRecord, ...]:
    category_id = categories[0].id if categories else None
    source = options.default_source or (str(source_path) if source_path is not None else None)
    now = utc_now()
    return tuple(
        TextRecord(
            id=_record_id(display_name, index, content),
            content=content,
            primary_category_id=category_id,
            tags=options.default_tags,
            source=source,
            created_at=now,
            updated_at=now,
        )
        for index, content in enumerate(segments)
    )


def _record_from_json_payload(
    payload: dict[str, Any],
    *,
    source: Path,
    index: int,
    default_options: TextImportOptions,
    category_by_name: dict[str, Category],
) -> TextRecord:
    content = str(payload.get("content") or "").strip()
    category_name = str(
        payload.get("primary_category") or default_options.default_category or ""
    ).strip()
    category = category_by_name.get(category_name)
    tags = _tags_from_payload(payload.get("tags"), default_options.default_tags)
    record_time = _parse_datetime(payload.get("record_time") or payload.get("time"))
    custom_fields = {
        str(key): value
        for key, value in payload.items()
        if key
        not in {
            "id",
            "content",
            "primary_category",
            "tags",
            "source",
            "location",
            "speaker",
            "time",
            "record_time",
            "note",
        }
    }
    now = utc_now()
    return TextRecord(
        id=str(payload.get("id") or _record_id(source.name, index, content)),
        content=content,
        primary_category_id=category.id if category is not None else None,
        tags=tags,
        source=str(payload.get("source") or default_options.default_source or source),
        location=_optional_string(payload.get("location")),
        speaker=_optional_string(payload.get("speaker")),
        record_time=record_time,
        note=str(payload.get("note") or ""),
        custom_fields=custom_fields,
        created_at=now,
        updated_at=now,
    )


def _categories_for_names(names: list[str]) -> tuple[Category, ...]:
    categories: list[Category] = []
    seen: set[str] = set()
    for name in names:
        normalized = name.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        categories.append(Category(id=_category_id(normalized), name=normalized))
    return tuple(categories)


def _tags_from_payload(value: object, defaults: tuple[str, ...]) -> tuple[str, ...]:
    tags: list[str] = list(defaults)
    if isinstance(value, list):
        tags.extend(str(item).strip() for item in value if str(item).strip())
    elif isinstance(value, str):
        tags.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(dict.fromkeys(tags))


def _read_text_source(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "shift_jis"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise UserFacingError(
        code="TEXT_CORPUS_ENCODING_FAILED",
        title_zh="无法识别文本编码",
        message_zh="文件不是支持的文本编码。",
        next_action_zh="请转换为 UTF-8、GB18030 或 Shift-JIS 后重试。",
        technical_detail=str(last_error),
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _optional_string(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _fingerprint_text(display_name: str, content: str, options: TextImportOptions) -> str:
    digest = sha256()
    digest.update(display_name.encode("utf-8", errors="replace"))
    digest.update(content.encode("utf-8", errors="replace"))
    digest.update(json.dumps(options.to_dict(), sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _fingerprint_preview(preview: TextCorpusPreview) -> str:
    digest = sha256()
    digest.update(preview.display_name.encode("utf-8", errors="replace"))
    for record in preview.records:
        digest.update(record.id.encode("utf-8", errors="replace"))
        digest.update(record.content.encode("utf-8", errors="replace"))
    return digest.hexdigest()


def _record_id(scope: str, index: int, content: str) -> str:
    digest = sha256(f"{scope}\0{index}\0{content}".encode("utf-8", errors="replace"))
    return f"text_{digest.hexdigest()[:16]}"


def _category_id(name: str) -> str:
    digest = sha256(name.encode("utf-8", errors="replace"))
    return f"cat_{digest.hexdigest()[:16]}"
