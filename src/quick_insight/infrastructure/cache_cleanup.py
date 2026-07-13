from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quick_insight.infrastructure.paths import AppPaths


@dataclass(frozen=True)
class CacheCleanupPolicy:
    max_age: timedelta = timedelta(days=2)
    include_temp: bool = True
    include_normalized_cache: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    root: Path
    reason: str
    size_bytes: int
    modified_at: datetime
    is_dir: bool


@dataclass(frozen=True)
class CacheCleanupReport:
    scanned_roots: tuple[Path, ...]
    candidates: tuple[CleanupCandidate, ...]
    removed_paths: tuple[Path, ...]
    removed_bytes: int
    skipped_paths: tuple[Path, ...]
    dry_run: bool
    schema_version: int = 1

    @property
    def removed_count(self) -> int:
        return len(self.removed_paths)


def cleanup_app_cache(
    paths: AppPaths,
    *,
    policy: CacheCleanupPolicy | None = None,
    now: datetime | None = None,
) -> CacheCleanupReport:
    resolved_policy = policy or CacheCleanupPolicy()
    resolved_now = now or datetime.now(UTC)
    roots = _cleanup_roots(paths, resolved_policy)
    candidates: list[CleanupCandidate] = []
    for root in roots:
        candidates.extend(_find_candidates(root, resolved_policy, resolved_now))

    removed_paths: list[Path] = []
    skipped_paths: list[Path] = []
    removed_bytes = 0
    for candidate in candidates:
        if resolved_policy.dry_run:
            continue
        try:
            _remove_candidate(candidate)
        except OSError:
            skipped_paths.append(candidate.path)
            continue
        removed_paths.append(candidate.path)
        removed_bytes += candidate.size_bytes

    return CacheCleanupReport(
        scanned_roots=tuple(roots),
        candidates=tuple(candidates),
        removed_paths=tuple(removed_paths),
        removed_bytes=removed_bytes,
        skipped_paths=tuple(skipped_paths),
        dry_run=resolved_policy.dry_run,
    )


def _cleanup_roots(paths: AppPaths, policy: CacheCleanupPolicy) -> tuple[Path, ...]:
    roots: list[Path] = []
    if policy.include_temp:
        roots.append(paths.temp_dir)
    if policy.include_normalized_cache:
        roots.append(paths.cache_dir / "normalized")
    return tuple(root for root in roots if root.exists())


def _find_candidates(
    root: Path,
    policy: CacheCleanupPolicy,
    now: datetime,
) -> tuple[CleanupCandidate, ...]:
    root_path = root.resolve(strict=False)
    cutoff = now - policy.max_age
    candidates: list[CleanupCandidate] = []
    for entry in root_path.iterdir():
        if not _is_under_root(entry, root_path):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
        if modified_at > cutoff:
            continue
        is_dir = entry.is_dir() and not entry.is_symlink()
        candidates.append(
            CleanupCandidate(
                path=entry,
                root=root_path,
                reason="stale_temp"
                if root_path.name == "tmp"
                else "stale_normalized_cache",
                size_bytes=_path_size(entry),
                modified_at=modified_at,
                is_dir=is_dir,
            )
        )
    return tuple(candidates)


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return path.resolve(strict=False) != root


def _path_size(path: Path) -> int:
    try:
        if path.is_file() or path.is_symlink():
            return path.stat().st_size
        if path.is_dir():
            total = 0
            for child in path.rglob("*"):
                if child.is_file() and not child.is_symlink():
                    total += child.stat().st_size
            return total
    except OSError:
        return 0
    return 0


def _remove_candidate(candidate: CleanupCandidate) -> None:
    if not _is_under_root(candidate.path, candidate.root):
        raise OSError(f"Refusing to remove outside cleanup root: {candidate.path}")
    if candidate.path.is_symlink() or candidate.path.is_file():
        candidate.path.unlink(missing_ok=True)
        return
    if candidate.path.is_dir():
        shutil.rmtree(candidate.path)
