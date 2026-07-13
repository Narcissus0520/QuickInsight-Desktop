from __future__ import annotations

import pytest

from quick_insight.application.errors import UserFacingError
from quick_insight.application.text_labeling import (
    TextLabelingService,
    TextRecordEdit,
    TextRecordFilter,
)
from quick_insight.domain.models import Category, TextRecord
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_text_labeling_service_updates_filters_and_restores_records(tmp_path) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    category = Category(id="cat_initial", name="初始")
    records = (
        TextRecord(id="r-1", content="第一条安装反馈", primary_category_id=category.id),
        TextRecord(id="r-2", content="第二条告警记录"),
    )
    workspace.save_text_corpus("label-corpus", records, (category,))
    service = TextLabelingService(workspace)

    updated = service.update_record(
        "label-corpus",
        records[0],
        TextRecordEdit(
            record_id="r-1",
            content="第一条安装反馈 已核对",
            category_name="体验",
            tags_text="安装, 新手, 安装",
            source="访谈",
            location="上海",
            speaker="工程师",
            note="已确认",
        ),
    )

    stored = {record.id: record for record in workspace.list_text_records("label-corpus")}
    categories = {category.name: category for category in service.list_categories()}
    assert updated.primary_category_id == categories["体验"].id
    assert stored["r-1"].content == "第一条安装反馈 已核对"
    assert stored["r-1"].tags == ("安装", "新手")
    assert stored["r-1"].source == "访谈"
    assert service.count_records("label-corpus", TextRecordFilter(search_text="核对")) == 1
    assert service.count_records(
        "label-corpus",
        TextRecordFilter(category_id=categories["体验"].id),
    ) == 1
    assert service.count_records(
        "label-corpus",
        TextRecordFilter(uncategorized_only=True),
    ) == 1

    service.update_record_category_and_tags(
        "label-corpus",
        stored["r-2"],
        category_name="体验",
        tags_text="告警,传感器",
    )
    assert service.category_usage_counts("label-corpus")[categories["体验"].id] == 2

    service.restore_record("label-corpus", records[0])
    restored = {record.id: record for record in workspace.list_text_records("label-corpus")}
    assert restored["r-1"].content == "第一条安装反馈"
    assert restored["r-1"].primary_category_id == category.id
    assert restored["r-1"].tags == ()


def test_text_category_governance_writes_audit_and_updates_records(tmp_path) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    source = Category(id="cat_source", name="待整理", description="旧说明")
    target = Category(id="cat_target", name="体验")
    delete_me = Category(id="cat_delete", name="临时")
    records = (
        TextRecord(id="r-1", content="安装路径不清楚", primary_category_id=source.id),
        TextRecord(id="r-2", content="按钮响应很快", primary_category_id=target.id),
        TextRecord(id="r-3", content="需要复核", primary_category_id=delete_me.id),
    )
    workspace.save_text_corpus("label-corpus", records, (source, target, delete_me))
    service = TextLabelingService(workspace)

    rename_result = service.rename_category(
        "label-corpus",
        source.id,
        new_name="安装问题",
        new_description="用户安装阶段的问题",
        note="清理分类名称",
    )
    renamed = {category.id: category for category in rename_result.categories}[source.id]
    assert renamed.name == "安装问题"
    assert renamed.description == "用户安装阶段的问题"
    assert rename_result.audit.action == "rename"
    assert rename_result.audit.affected_record_count == 1
    assert rename_result.audit.note == "清理分类名称"

    merge_result = service.merge_categories(
        "label-corpus",
        source_category_id=source.id,
        target_category_id=target.id,
        note="并入体验类",
    )
    stored_after_merge = {
        record.id: record for record in workspace.list_text_records("label-corpus")
    }
    assert stored_after_merge["r-1"].primary_category_id == target.id
    assert source.id not in {category.id for category in merge_result.categories}
    assert merge_result.usage_counts[target.id] == 2
    assert merge_result.audit.action == "merge"
    assert merge_result.audit.affected_record_count == 1

    delete_result = service.delete_category(
        "label-corpus",
        category_id=delete_me.id,
        replacement_category_id=None,
        note="无效临时类",
    )
    stored_after_delete = {
        record.id: record for record in workspace.list_text_records("label-corpus")
    }
    assert stored_after_delete["r-3"].primary_category_id is None
    assert delete_me.id not in {category.id for category in delete_result.categories}
    assert delete_result.audit.action == "delete_to_uncategorized"
    assert delete_result.audit.affected_record_count == 1

    audit_actions = [record.action for record in service.list_category_audit("label-corpus")]
    assert audit_actions == ["delete_to_uncategorized", "merge", "rename"]


def test_text_category_governance_rejects_cross_corpus_changes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    category = Category(id="cat_shared", name="共享分类")
    workspace.save_text_corpus(
        "corpus-a",
        (TextRecord(id="a-1", content="第一条", primary_category_id=category.id),),
        (category,),
    )
    workspace.save_text_corpus(
        "corpus-b",
        (TextRecord(id="b-1", content="第二条", primary_category_id=category.id),),
        (category,),
    )
    service = TextLabelingService(workspace)

    with pytest.raises(UserFacingError):
        service.rename_category(
            "corpus-a",
            category.id,
            new_name="只改当前语料",
            new_description="",
        )

    assert {category.name for category in workspace.list_categories()} == {"共享分类"}
