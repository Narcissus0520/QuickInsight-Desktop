from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from quick_insight.application.security_review import (
    run_security_review,
    write_security_review_reports,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quick-insight-security-review")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to scan. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build") / "security-review",
        help="Directory for JSON and Markdown security review reports.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    result = run_security_review(args.root)
    json_path, markdown_path = write_security_review_reports(result, args.output_dir)
    print(f"Security review JSON report: {json_path}")
    print(f"Security review Markdown report: {markdown_path}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
