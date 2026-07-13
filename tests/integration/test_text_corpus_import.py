from __future__ import annotations

from quick_insight.application.text_corpus import (
    TextCorpusService,
    TextImportOptions,
    TextSplitMode,
)
from quick_insight.domain.enums import DatasetKind
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_text_corpus_service_imports_pasted_text_with_category_and_tags(tmp_path) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TextCorpusService(workspace)
    preview = service.preview_text(
        "第一条反馈\n\n第二条反馈",
        display_name="访谈片段",
        options=TextImportOptions(
            split_mode=TextSplitMode.NON_EMPTY_LINE,
            default_category="产品体验",
            default_tags=("安装", "新手"),
            default_source="访谈",
        ),
    )

    result = service.import_preview(preview)
    stored_records = workspace.list_text_records(result.handle.cache_key or "")
    categories = workspace.list_categories()
    category_counts = workspace.category_usage_counts(result.handle.cache_key or "")

    assert result.handle.kind is DatasetKind.TEXT_CORPUS
    assert result.handle.row_count == 2
    assert result.handle.display_name == "访谈片段"
    assert [record.content for record in stored_records] == ["第一条反馈", "第二条反馈"]
    assert stored_records[0].tags == ("安装", "新手")
    assert stored_records[0].source == "访谈"
    assert categories[0].name == "产品体验"
    assert category_counts == {categories[0].id: 2}


def test_text_corpus_service_imports_jsonl_metadata(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "records.jsonl"
    source.write_text(
        "\n".join(
            [
                '{"id":"r-1","content":"需要改进安装体验","primary_category":"体验","tags":["安装"],"source":"访谈"}',
                '{"id":"r-2","content":"告警需要核对","primary_category":"设备","tags":"告警,传感器"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TextCorpusService(workspace)

    preview = service.preview_file(source)
    result = service.import_preview(preview)
    stored_records = workspace.list_text_records(result.handle.cache_key or "")
    categories = {category.name for category in workspace.list_categories()}

    assert result.handle.source_path == source.resolve()
    assert result.handle.row_count == 2
    assert {record.id for record in stored_records} == {"r-1", "r-2"}
    assert stored_records[1].tags == ("告警", "传感器")
    assert categories == {"体验", "设备"}
