from __future__ import annotations

import polars as pl
from tests.fixtures.xlsx import write_minimal_xlsx

from quick_insight.infrastructure.tabular_files import preview_excel_file, preview_parquet_file


def test_preview_parquet_file_reads_first_rows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "data.parquet"
    pl.DataFrame({"name": ["alpha", "beta"], "amount": [1, 2]}).write_parquet(path)

    preview = preview_parquet_file(path, preview_limit=1)

    assert preview.file_format == "parquet"
    assert preview.columns == ("name", "amount")
    assert preview.rows == (("alpha", "1"),)


def test_preview_excel_file_uses_calamine_engine(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "data.xlsx"
    write_minimal_xlsx(path)

    preview = preview_excel_file(path)

    assert preview.file_format == "excel"
    assert preview.options["engine"] == "calamine"
    assert preview.columns == ("name", "amount")
    assert preview.rows == (("alpha", "1"),)
