from __future__ import annotations

import csv
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

from quick_insight.application.errors import UserFacingError

SUPPORTED_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "gb18030", "shift_jis")
DELIMITER_BY_NAME: dict[str, str] = {
    "comma": ",",
    "tab": "\t",
    "semicolon": ";",
    "pipe": "|",
}
DELIMITER_LABELS: dict[str, str] = {value: key for key, value in DELIMITER_BY_NAME.items()}


@dataclass(frozen=True)
class CsvImportOptions:
    encoding: str
    delimiter: str
    has_header: bool = True
    preview_limit: int = 200

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CsvPreview:
    path: Path
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    options: CsvImportOptions
    total_preview_rows: int
    warnings: tuple[str, ...] = ()


def preview_delimited_file(
    path: Path,
    *,
    encoding: str | None = None,
    delimiter: str | None = None,
    has_header: bool = True,
    preview_limit: int = 200,
) -> CsvPreview:
    source = path.expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise UserFacingError(
            code="IMPORT_SOURCE_NOT_FOUND",
            title_zh="找不到文件",
            message_zh="请选择一个存在的 CSV 或 TSV 文件。",
            next_action_zh="检查文件路径后重新选择。",
            technical_detail=str(source),
        )

    sample, detected_encoding = _read_sample(source, encoding)
    detected_delimiter = delimiter or _detect_delimiter(sample, source)
    options = CsvImportOptions(
        encoding=detected_encoding,
        delimiter=detected_delimiter,
        has_header=has_header,
        preview_limit=preview_limit,
    )
    rows = _read_rows(source, options, preview_limit + 1)
    if not rows:
        raise UserFacingError(
            code="IMPORT_EMPTY_FILE",
            title_zh="文件没有可预览内容",
            message_zh="当前文件为空，或无法识别出任何记录。",
            next_action_zh="请选择包含表头和数据行的 CSV/TSV 文件。",
            technical_detail=str(source),
        )

    if has_header:
        raw_columns = rows[0]
        preview_rows = rows[1 : preview_limit + 1]
    else:
        max_width = max(len(row) for row in rows)
        raw_columns = [f"column_{index + 1}" for index in range(max_width)]
        preview_rows = rows[:preview_limit]

    columns = _unique_columns(raw_columns)
    normalized_rows = tuple(_pad_row(row, len(columns)) for row in preview_rows)
    warnings = _collect_warnings(raw_columns, rows)
    return CsvPreview(
        path=source,
        columns=columns,
        rows=normalized_rows,
        options=options,
        total_preview_rows=len(normalized_rows),
        warnings=warnings,
    )


def fingerprint_file(path: Path) -> str:
    source = path.expanduser().resolve()
    stat = source.stat()
    digest = hashlib.sha256()
    digest.update(str(source).encode("utf-8", errors="replace"))
    digest.update(str(stat.st_size).encode("ascii"))
    digest.update(str(int(stat.st_mtime_ns)).encode("ascii"))
    with source.open("rb") as stream:
        digest.update(stream.read(64 * 1024))
        if stat.st_size > 64 * 1024:
            stream.seek(max(0, stat.st_size - 64 * 1024))
            digest.update(stream.read(64 * 1024))
    return digest.hexdigest()


def table_name_for_fingerprint(fingerprint: str) -> str:
    return f"dataset_{fingerprint[:16]}"


def _read_sample(path: Path, override_encoding: str | None) -> tuple[str, str]:
    encodings = (override_encoding,) if override_encoding else SUPPORTED_ENCODINGS
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, newline="") as stream:
                return stream.read(8192), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise UserFacingError(
        code="IMPORT_ENCODING_DETECTION_FAILED",
        title_zh="无法识别文件编码",
        message_zh="文件不是支持的文本编码，或手动选择的编码不匹配。",
        next_action_zh="请尝试 UTF-8、GB18030 或 Shift-JIS 编码后重新预览。",
        technical_detail=str(last_error),
    )


def _detect_delimiter(sample: str, path: Path) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return ","


def _read_rows(path: Path, options: CsvImportOptions, limit: int) -> list[list[str]]:
    try:
        with path.open("r", encoding=options.encoding, newline="") as stream:
            reader = csv.reader(stream, delimiter=options.delimiter)
            return [row for _, row in zip(range(limit), reader, strict=False)]
    except csv.Error as exc:
        raise UserFacingError(
            code="IMPORT_CSV_PARSE_FAILED",
            title_zh="CSV 解析失败",
            message_zh="文件包含无法按当前分隔符解析的内容。",
            next_action_zh="请调整分隔符或检查引号、换行等格式后重试。",
            technical_detail=str(exc),
        ) from exc


def _unique_columns(raw_columns: list[str]) -> tuple[str, ...]:
    seen: dict[str, int] = {}
    columns: list[str] = []
    for index, raw_name in enumerate(raw_columns):
        base = raw_name.strip() or f"column_{index + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        columns.append(base if count == 0 else f"{base}_{count + 1}")
    return tuple(columns)


def _pad_row(row: list[str], width: int) -> tuple[str, ...]:
    if len(row) >= width:
        return tuple(row[:width])
    return tuple([*row, *([""] * (width - len(row)))])


def _collect_warnings(raw_columns: list[str], rows: list[list[str]]) -> tuple[str, ...]:
    warnings: list[str] = []
    if any(not name.strip() for name in raw_columns):
        warnings.append("检测到空表头，已在预览中使用 column_N 名称。")
    widths = {len(row) for row in rows}
    if len(widths) > 1:
        warnings.append("检测到行宽不一致，预览会补齐缺失单元格。")
    return tuple(warnings)
