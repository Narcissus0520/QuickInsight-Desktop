from __future__ import annotations

import pytest

from quick_insight.application.errors import UserFacingError
from quick_insight.application.importing import TabularImportService
from quick_insight.application.transforms import TabularTransformService
from quick_insight.domain.models import TransformStep
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_transform_preview_selects_filters_sorts_fills_converts_and_deduplicates(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "dirty.csv"
    source.write_text(
        "\n".join(
            [
                "region,status,amount,customer",
                "North,open,10,c1",
                "North,open,10,c1",
                "North,open,,c2",
                "South,closed,25,c3",
                "South,open,bad,c3",
                "East,open,5,c4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    result = service.import_csv(service.preview_csv(source))
    transforms = TabularTransformService(workspace)

    preview = transforms.preview_transform(
        result.table_name,
        (
            _step(
                "convert_type",
                {"columns": {"amount": "DOUBLE"}, "on_error": "null"},
            ),
            _step("fill_missing", {"values": {"amount": 0.0}}),
            _step(
                "filter_rows",
                {
                    "expression": {
                        "op": "and",
                        "conditions": [
                            {"column": "status", "op": "==", "value": "open"},
                            {
                                "op": "or",
                                "conditions": [
                                    {"column": "amount", "op": ">=", "value": 10},
                                    {"column": "customer", "op": "==", "value": "c4"},
                                ],
                            },
                        ],
                    }
                },
            ),
            _step("deduplicate_rows", {"columns": ["region", "customer"]}),
            _step(
                "select_columns",
                {
                    "columns": [
                        {"source": "region", "alias": "area"},
                        {"source": "amount", "alias": "amount"},
                        {"source": "customer", "alias": "customer"},
                    ]
                },
            ),
            _step("sort_rows", {"columns": [{"column": "amount", "direction": "desc"}]}),
        ),
        destination_table="dirty_transform_preview",
    )

    assert preview.table_name == "dirty_transform_preview"
    assert preview.source_table == result.table_name
    assert preview.row_count == 2
    assert [column.name for column in preview.columns] == ["area", "amount", "customer"]
    assert workspace.fetch_page(preview.table_name, limit=10, offset=0) == (
        ("North", 10.0, "c1"),
        ("East", 5.0, "c4"),
    )
    assert workspace.fetch_page(result.table_name, limit=1, offset=0)[0][0] == "North"


def test_transform_preview_group_aggregation_uses_duckdb_pushdown(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text(
        "\n".join(
            [
                "region,amount,customer",
                "North,10,c1",
                "North,20,c2",
                "South,5,c3",
                "South,,c3",
                "South,15,c4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    result = service.import_csv(service.preview_csv(source))

    preview = TabularTransformService(workspace).preview_transform(
        result.table_name,
        (
            _step("convert_type", {"columns": {"amount": "DOUBLE"}}),
            _step("drop_missing", {"columns": ["amount"]}),
            _step(
                "group_aggregate",
                {
                    "group_by": ["region"],
                    "aggregations": [
                        {"function": "count", "alias": "row_count"},
                        {
                            "function": "count_distinct",
                            "column": "customer",
                            "alias": "distinct_customers",
                        },
                        {"function": "sum", "column": "amount", "alias": "sum_amount"},
                        {"function": "mean", "column": "amount", "alias": "mean_amount"},
                        {"function": "median", "column": "amount", "alias": "median_amount"},
                        {"function": "min", "column": "amount", "alias": "min_amount"},
                        {"function": "max", "column": "amount", "alias": "max_amount"},
                        {"function": "stddev", "column": "amount", "alias": "stddev_amount"},
                    ],
                },
            ),
        ),
        destination_table="sales_grouped",
    )
    rows = workspace.fetch_page(preview.table_name, limit=10, offset=0)

    assert [column.name for column in preview.columns] == [
        "region",
        "row_count",
        "distinct_customers",
        "sum_amount",
        "mean_amount",
        "median_amount",
        "min_amount",
        "max_amount",
        "stddev_amount",
    ]
    assert rows[0][:7] == ("North", 2, 2, 30.0, 15.0, 15.0, 10.0)
    assert rows[0][7] == 20.0
    assert rows[0][8] == pytest.approx(7.0710678118654755)
    assert rows[1][:8] == ("South", 2, 2, 20.0, 10.0, 10.0, 5.0, 15.0)


def test_transform_preview_rejects_invalid_columns_without_overwriting_source(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text("region,amount\nNorth,10\n", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)
    result = service.import_csv(service.preview_csv(source))

    with pytest.raises(UserFacingError) as exc_info:
        TabularTransformService(workspace).preview_transform(
            result.table_name,
            (_step("filter_rows", {"expression": {"column": "missing", "op": "==", "value": 1}}),),
            destination_table="bad_transform",
        )

    assert exc_info.value.code == "TRANSFORM_SPEC_INVALID"
    assert workspace.row_count(result.table_name) == 1


def _step(operation: str, parameters: dict[str, object]) -> TransformStep:
    return TransformStep(
        id=f"step_{operation}",
        operation=operation,
        parameters=parameters,
        reversible=False,
    )
