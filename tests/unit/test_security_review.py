from __future__ import annotations

import json
from pathlib import Path

from quick_insight.application.security_review import (
    run_security_review,
    write_security_review_reports,
)


def test_security_review_detects_prohibited_patterns(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source_root = tmp_path / "src" / "demo"
    source_root.mkdir(parents=True)
    (source_root / "__init__.py").write_text("", encoding="utf-8")
    (source_root / "bad.py").write_text(
        "\n".join(
            [
                "import pickle",
                "import subprocess",
                "eval('1 + 1')",
                "subprocess.run('dir', shell=True)",
                "REMOTE = 'https://example.com/asset.js'",
                "archive.extractall('target')",
            ]
        ),
        encoding="utf-8",
    )

    result = run_security_review(tmp_path)

    rule_ids = {finding.rule_id for finding in result.findings}
    assert result.passed is False
    assert {
        "banned_import",
        "banned_dynamic_execution",
        "subprocess_shell_true",
        "remote_url_literal",
        "unsafe_archive_extraction",
    }.issubset(rule_ids)


def test_current_src_security_review_passes_and_writes_report(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repo_root = Path(__file__).resolve().parents[2]

    result = run_security_review(repo_root)
    json_path, markdown_path = write_security_review_reports(result, tmp_path / "reports")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert markdown_path.read_text(encoding="utf-8").startswith("# QuickInsight Security Review")
    assert result.passed is True
    assert payload["passed"] is True
    assert payload["findings"] == []
    assert any(
        path.as_posix().endswith("src/quick_insight/bootstrap.py")
        for path in result.scanned_files
    )
