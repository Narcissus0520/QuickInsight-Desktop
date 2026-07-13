from __future__ import annotations

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
