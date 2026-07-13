from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from quick_insight.application.benchmarks import (
    BenchmarkSettings,
    run_benchmark_suite,
    write_benchmark_reports,
)
from quick_insight.infrastructure.cache_cleanup import CacheCleanupPolicy, cleanup_app_cache
from quick_insight.infrastructure.paths import AppPaths

_PRESET_ROWS = {
    "smoke": (10_000,),
    "p0": (100_000, 1_000_000, 5_000_000),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quick-insight-benchmark")
    parser.add_argument(
        "--profile",
        choices=tuple(_PRESET_ROWS),
        default="smoke",
        help="Benchmark row-count preset. p0 generates 100k, 1m, and 5m rows.",
    )
    parser.add_argument(
        "--rows",
        type=int,
        action="append",
        default=[],
        help="Override preset with one or more row counts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build") / "benchmarks" / "reports",
        help="Directory for JSON and Markdown benchmark reports.",
    )
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=Path("build") / "benchmarks" / "workspace",
        help="Directory for generated data and DuckDB benchmark workspaces.",
    )
    parser.add_argument(
        "--skip-chart",
        action="store_true",
        help="Skip chart-data preparation after import/profile.",
    )
    parser.add_argument(
        "--cleanup-cache",
        action="store_true",
        help="Clean stale app temp and normalized cache before running benchmarks.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.cleanup_cache:
        cleanup_app_cache(
            AppPaths.default().ensure(),
            policy=CacheCleanupPolicy(include_normalized_cache=True),
        )
    row_counts = tuple(args.rows) if args.rows else _PRESET_ROWS[args.profile]
    settings = BenchmarkSettings(
        row_counts=row_counts,
        output_dir=args.output_dir,
        workspace_root=args.workspace_dir,
        run_chart_preparation=not args.skip_chart,
    )
    result = run_benchmark_suite(settings)
    json_path, markdown_path = write_benchmark_reports(result)
    print(f"Benchmark JSON report: {json_path}")
    print(f"Benchmark Markdown report: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
