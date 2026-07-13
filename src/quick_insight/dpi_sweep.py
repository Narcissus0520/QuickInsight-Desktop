from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from quick_insight import __version__
from quick_insight.ui.dpi_sweep import (
    DpiSweepSettings,
    run_single_scale_sweep,
    write_scale_evidence,
)

_DEFAULT_SCALES = (1.0, 1.25, 1.5, 2.0)


@dataclass(frozen=True)
class DpiSweepSuiteResult:
    generated_at: datetime
    output_dir: Path
    machine: dict[str, object]
    scales: tuple[dict[str, object], ...]
    schema_version: int = 1

    @property
    def passed(self) -> bool:
        return all(bool(scale.get("passed")) for scale in self.scales)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "app_version": __version__,
            "machine": self.machine,
            "scales": list(self.scales),
            "passed": self.passed,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quick-insight-dpi-sweep")
    parser.add_argument(
        "--scale",
        type=float,
        action="append",
        default=[],
        help="Scale factor to sweep. Defaults to 1.0, 1.25, 1.5, and 2.0.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build") / "dpi-sweep",
        help="Directory for screenshots plus JSON and Markdown reports.",
    )
    parser.add_argument(
        "--theme",
        choices=("light", "dark"),
        default="light",
        help="Theme to render during the DPI sweep.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="Timeout for each isolated scale-factor child process.",
    )
    parser.add_argument(
        "--single-scale",
        type=float,
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.single_scale is not None:
        return _run_single_scale_command(
            scale_factor=args.single_scale,
            output_dir=args.output_dir,
            theme=args.theme,
        )
    scales = tuple(args.scale) if args.scale else _DEFAULT_SCALES
    result = run_dpi_sweep(
        scales=scales,
        output_dir=args.output_dir,
        theme=args.theme,
        timeout_seconds=args.timeout_seconds,
    )
    json_path, markdown_path = write_dpi_sweep_reports(result)
    print(f"DPI sweep JSON report: {json_path}")
    print(f"DPI sweep Markdown report: {markdown_path}")
    return 0 if result.passed else 1


def run_dpi_sweep(
    *,
    scales: tuple[float, ...],
    output_dir: Path,
    theme: str,
    timeout_seconds: float,
) -> DpiSweepSuiteResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    scale_results = tuple(
        _run_isolated_scale(
            scale_factor=scale_factor,
            output_dir=output_dir,
            theme=theme,
            timeout_seconds=timeout_seconds,
        )
        for scale_factor in scales
    )
    return DpiSweepSuiteResult(
        generated_at=datetime.now(UTC),
        output_dir=output_dir,
        machine=_machine_details(),
        scales=scale_results,
    )


def write_dpi_sweep_reports(result: DpiSweepSuiteResult) -> tuple[Path, Path]:
    result.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = result.generated_at.strftime("%Y%m%dT%H%M%SZ")
    json_path = result.output_dir / f"dpi-sweep-report-{timestamp}.json"
    markdown_path = result.output_dir / f"dpi-sweep-report-{timestamp}.md"
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_dpi_sweep_markdown(result), encoding="utf-8")
    return json_path, markdown_path


def _run_single_scale_command(*, scale_factor: float, output_dir: Path, theme: str) -> int:
    result = run_single_scale_sweep(
        DpiSweepSettings(
            scale_factor=scale_factor,
            output_dir=output_dir,
            theme=theme,
        )
    )
    write_scale_evidence(result, output_dir / "single-scale-result.json")
    failed = [check for check in result.checks if not check.passed]
    if failed:
        for check in failed:
            print(f"FAIL {check.name}: {check.details}", file=sys.stderr)
        return 1
    return 0


def _run_isolated_scale(
    *,
    scale_factor: float,
    output_dir: Path,
    theme: str,
    timeout_seconds: float,
) -> dict[str, object]:
    scale_dir = output_dir / f"scale-{int(scale_factor * 100):03d}"
    scale_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["QT_SCALE_FACTOR"] = _scale_text(scale_factor)
    command = [
        sys.executable,
        "-m",
        "quick_insight.dpi_sweep",
        "--single-scale",
        _scale_text(scale_factor),
        "--output-dir",
        str(scale_dir),
        "--theme",
        theme,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )
    result_path = scale_dir / "single-scale-result.json"
    if result_path.exists():
        payload = cast(dict[str, object], json.loads(result_path.read_text(encoding="utf-8")))
    else:
        payload = {
            "schema_version": 1,
            "scale_factor": scale_factor,
            "theme": theme,
            "generated_at": datetime.now(UTC).isoformat(),
            "app_version": __version__,
            "logical_window": {},
            "pages": [],
            "widgets": [],
            "checks": [
                {
                    "name": "child_process_completed",
                    "passed": False,
                    "details": (
                        f"exit={completed.returncode}; stdout={completed.stdout}; "
                        f"stderr={completed.stderr}"
                    ),
                }
            ],
            "passed": False,
        }
    payload["child_exit_code"] = completed.returncode
    if completed.stdout:
        payload["child_stdout"] = completed.stdout
    if completed.stderr:
        payload["child_stderr"] = completed.stderr
    if completed.returncode != 0:
        payload["passed"] = False
    return payload


def _machine_details() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count() or 0,
    }


def _dpi_sweep_markdown(result: DpiSweepSuiteResult) -> str:
    lines = [
        "# QuickInsight DPI Sweep Report",
        "",
        f"Generated: {result.generated_at.isoformat()}",
        f"App version: {__version__}",
        f"Passed: {result.passed}",
        "",
        "## Machine",
        "",
    ]
    for key, value in result.machine.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Scale Factors", ""])
    for scale in result.scales:
        lines.append(
            f"### {scale.get('scale_factor')} ({'PASS' if scale.get('passed') else 'FAIL'})"
        )
        logical_window = scale.get("logical_window", {})
        lines.append(f"- Logical window: `{logical_window}`")
        pages = scale.get("pages", [])
        if isinstance(pages, list):
            lines.append(f"- Screenshots: {len(pages)}")
            for page in pages:
                if isinstance(page, dict):
                    lines.append(
                        "  - "
                        f"{page.get('name')}: `{page.get('screenshot_path')}` "
                        f"({page.get('screenshot_width')}x{page.get('screenshot_height')}, "
                        f"dpr={page.get('device_pixel_ratio')})"
                    )
        raw_checks = scale.get("checks", [])
        checks = raw_checks if isinstance(raw_checks, list) else []
        failed = [
            check
            for check in checks
            if isinstance(check, dict) and not bool(check.get("passed"))
        ]
        if failed:
            lines.append("- Failed checks:")
            for check in failed:
                lines.append(f"  - {check.get('name')}: {check.get('details')}")
        lines.append("")
    return "\n".join(lines)


def _scale_text(scale_factor: float) -> str:
    return f"{scale_factor:.2f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    raise SystemExit(main())
