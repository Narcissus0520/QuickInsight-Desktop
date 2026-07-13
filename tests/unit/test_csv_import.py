from __future__ import annotations

from quick_insight.application.errors import UserFacingError
from quick_insight.infrastructure.csv_import import preview_delimited_file


def test_preview_csv_detects_encoding_header_and_delimiter(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "sales.csv"
    path.write_text("name,amount\nalpha,1\nbeta,2\n", encoding="utf-8-sig")

    preview = preview_delimited_file(path)

    assert preview.options.encoding == "utf-8-sig"
    assert preview.options.delimiter == ","
    assert preview.columns == ("name", "amount")
    assert preview.rows == (("alpha", "1"), ("beta", "2"))


def test_preview_tsv_uses_tab_delimiter(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "sensor.tsv"
    path.write_text("device\tvalue\nA\t10\n", encoding="utf-8")

    preview = preview_delimited_file(path)

    assert preview.options.delimiter == "\t"
    assert preview.columns == ("device", "value")


def test_preview_missing_file_raises_user_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    missing = tmp_path / "missing.csv"

    try:
        preview_delimited_file(missing)
    except UserFacingError as exc:
        assert exc.code == "IMPORT_SOURCE_NOT_FOUND"
    else:
        raise AssertionError("Expected UserFacingError")
