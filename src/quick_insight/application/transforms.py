from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256

from quick_insight.application.errors import UserFacingError
from quick_insight.domain.models import TransformStep
from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase


@dataclass(frozen=True)
class TransformPreviewResult:
    source_table: str
    table_name: str
    columns: tuple[WorkspaceColumn, ...]
    row_count: int
    steps: tuple[TransformStep, ...]


class TabularTransformService:
    def __init__(self, workspace: WorkspaceDatabase) -> None:
        self._workspace = workspace

    def preview_transform(
        self,
        source_table: str,
        steps: tuple[TransformStep, ...],
        *,
        destination_table: str | None = None,
    ) -> TransformPreviewResult:
        if destination_table is None:
            destination_table = _transform_preview_table_name(source_table, steps)
        if destination_table == source_table:
            raise UserFacingError(
                code="TRANSFORM_DESTINATION_OVERWRITES_SOURCE",
                title_zh="转换目标不能覆盖源数据",
                message_zh="转换预览必须写入新的本地工作表，不能覆盖导入的源表。",
                next_action_zh="请使用新的预览名称，或重新生成转换预览。",
                technical_detail=(
                    f"source_table={source_table}; destination_table={destination_table}"
                ),
            )
        try:
            self._workspace.materialize_transform(source_table, destination_table, steps)
        except ValueError as exc:
            raise UserFacingError(
                code="TRANSFORM_SPEC_INVALID",
                title_zh="转换设置无效",
                message_zh="当前转换步骤无法安全编译为 DuckDB 查询。",
                next_action_zh="请检查字段、筛选条件、排序方向和聚合函数后重试。",
                technical_detail=str(exc),
            ) from exc
        except Exception as exc:
            raise UserFacingError(
                code="TRANSFORM_EXECUTION_FAILED",
                title_zh="转换预览失败",
                message_zh="执行转换预览时发生错误，源数据没有被修改。",
                next_action_zh="请复制技术细节并保留源文件，稍后重试或提交问题。",
                technical_detail=repr(exc),
            ) from exc
        return TransformPreviewResult(
            source_table=source_table,
            table_name=destination_table,
            columns=self._workspace.columns(destination_table),
            row_count=self._workspace.row_count(destination_table),
            steps=steps,
        )


def _transform_preview_table_name(source_table: str, steps: tuple[TransformStep, ...]) -> str:
    payload = json.dumps(
        [
            {
                "id": step.id,
                "operation": step.operation,
                "parameters": step.parameters,
                "schema_version": step.schema_version,
            }
            for step in steps
        ],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{source_table}__transform_{digest}"
