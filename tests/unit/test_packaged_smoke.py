from __future__ import annotations

import json
from pathlib import Path

from quick_insight.application.packaged_smoke import run_packaged_workflow_smoke


def test_packaged_workflow_smoke_imports_data_and_builds_chart(tmp_path: Path) -> None:
    result_path = tmp_path / "workflow-smoke.json"

    exit_code = run_packaged_workflow_smoke(result_path)

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["source_rows"] == 6
    assert payload["chart_type"] == "bar"
    assert payload["rendered_rows"] == 3
    assert payload["html_bytes"] > 10_000
