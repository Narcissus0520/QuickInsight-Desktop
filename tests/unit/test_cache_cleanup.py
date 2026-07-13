from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quick_insight.infrastructure.cache_cleanup import CacheCleanupPolicy, cleanup_app_cache
from quick_insight.infrastructure.paths import AppPaths


def test_cache_cleanup_dry_run_and_safe_policy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = AppPaths.under(tmp_path / "app").ensure()
    now = datetime(2026, 7, 13, tzinfo=UTC)
    stale_file = paths.temp_dir / "stale.tmp"
    fresh_file = paths.temp_dir / "fresh.tmp"
    stale_dir = paths.temp_dir / "stale-workspace"
    stale_child = stale_dir / "workspace.duckdb"
    normalized_dir = paths.cache_dir / "normalized"
    normalized_file = normalized_dir / "derived.parquet"

    stale_dir.mkdir()
    normalized_dir.mkdir()
    _write_with_mtime(stale_file, "old", now - timedelta(days=5))
    _write_with_mtime(stale_child, "workspace", now - timedelta(days=5))
    _write_with_mtime(fresh_file, "new", now)
    _write_with_mtime(normalized_file, "cache", now - timedelta(days=5))
    os.utime(stale_dir, (stale_child.stat().st_mtime, stale_child.stat().st_mtime))

    dry_run = cleanup_app_cache(
        paths,
        policy=CacheCleanupPolicy(
            max_age=timedelta(days=2),
            include_normalized_cache=True,
            dry_run=True,
        ),
        now=now,
    )

    assert dry_run.dry_run is True
    assert {candidate.path.name for candidate in dry_run.candidates} == {
        "stale.tmp",
        "stale-workspace",
        "derived.parquet",
    }
    assert stale_file.exists()
    assert normalized_file.exists()

    temp_only = cleanup_app_cache(
        paths,
        policy=CacheCleanupPolicy(max_age=timedelta(days=2)),
        now=now,
    )

    assert {path.name for path in temp_only.removed_paths} == {
        "stale.tmp",
        "stale-workspace",
    }
    assert temp_only.removed_bytes >= len("old") + len("workspace")
    assert not stale_file.exists()
    assert not stale_dir.exists()
    assert fresh_file.exists()
    assert normalized_file.exists()

    normalized_cleanup = cleanup_app_cache(
        paths,
        policy=CacheCleanupPolicy(
            max_age=timedelta(days=2),
            include_temp=False,
            include_normalized_cache=True,
        ),
        now=now,
    )

    assert tuple(path.name for path in normalized_cleanup.removed_paths) == ("derived.parquet",)
    assert not normalized_file.exists()


def _write_with_mtime(path: Path, content: str, modified_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    timestamp = modified_at.timestamp()
    os.utime(path, (timestamp, timestamp))
