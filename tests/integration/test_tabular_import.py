from __future__ import annotations

from quick_insight.application.importing import TabularImportService
from quick_insight.infrastructure.workspace import WorkspaceDatabase


def test_tabular_import_writes_duckdb_and_reads_pages(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "sales.csv"
    source.write_text("name,amount\nalpha,1\nbeta,2\n", encoding="utf-8")
    workspace = WorkspaceDatabase(tmp_path / "workspace.duckdb")
    service = TabularImportService(workspace)

    preview = service.preview_csv(source)
    result = service.import_csv(preview)

    assert result.handle.row_count == 2
    assert result.handle.column_count == 2
    assert result.handle.source_path == source.resolve()
    assert [column.name for column in result.columns] == ["name", "amount"]
    assert workspace.fetch_page(result.table_name, limit=1, offset=1) == (("beta", 2),)
