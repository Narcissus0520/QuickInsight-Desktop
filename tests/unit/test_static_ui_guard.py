from __future__ import annotations

from pathlib import Path


def test_production_code_does_not_use_qtablewidget() -> None:
    src_dir = Path(__file__).resolve().parents[2] / "src"
    offenders: list[Path] = []
    for path in src_dir.rglob("*.py"):
        if "QTableWidget" in path.read_text(encoding="utf-8"):
            offenders.append(path)

    assert offenders == []
