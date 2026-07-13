from __future__ import annotations

from pathlib import Path

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


def test_preview_reads_bounded_sample_without_read_text(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "large.csv"
    path.write_text(
        "name,amount\n" + "".join(f"row_{index},{index}\n" for index in range(1000)),
        encoding="utf-8",
    )

    def fail_read_text(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("preview should not read the whole file")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    preview = preview_delimited_file(path, preview_limit=3)

    assert preview.columns == ("name", "amount")
    assert preview.total_preview_rows == 3
    assert preview.rows[0] == ("row_0", "0")


def test_preview_missing_file_raises_user_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    missing = tmp_path / "missing.csv"

    try:
        preview_delimited_file(missing)
    except UserFacingError as exc:
        assert exc.code == "IMPORT_SOURCE_NOT_FOUND"
    else:
        raise AssertionError("Expected UserFacingError")
