from __future__ import annotations

import sys
from collections.abc import Sequence

from quick_insight.bootstrap import run


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point."""
    return run(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
