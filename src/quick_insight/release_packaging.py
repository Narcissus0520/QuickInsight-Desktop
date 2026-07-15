from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from quick_insight.application.release_packaging import build_release_package


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quick-insight-package")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path("dist"),
        help="Release artifact output directory.",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=Path("build") / "package",
        help="Intermediate build and report directory.",
    )
    parser.add_argument(
        "--smoke-seconds",
        type=float,
        default=2.0,
        help="Seconds before the packaged app auto-exits during smoke launch.",
    )
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--skip-installer", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    result = build_release_package(
        repo_root=args.root,
        dist_dir=args.dist_dir,
        build_dir=args.build_dir,
        smoke_seconds=args.smoke_seconds,
        skip_build=args.skip_build,
        skip_smoke=args.skip_smoke,
        skip_installer=args.skip_installer,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
