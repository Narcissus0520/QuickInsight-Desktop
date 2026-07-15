from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quick_insight.application import release_packaging
from quick_insight.application.release_packaging import (
    APP_EXE_NAME,
    APP_PACKAGE_NAME,
    PACKAGE_REPORT_NAME,
    PORTABLE_ZIP_NAME,
    RELEASE_NOTES_NAME,
    SHA256SUMS_NAME,
    CommandResult,
    build_release_package,
    create_portable_zip,
    verify_portable_tree,
    write_release_notes,
    write_sha256sums,
    write_third_party_license_inventory,
)


def test_verify_portable_tree_requires_exe_and_webengine_resources(tmp_path: Path) -> None:
    portable = _fake_portable_tree(tmp_path)

    result = verify_portable_tree(portable)

    assert result.passed is True
    assert result.missing_files == ()
    assert result.located_files[APP_EXE_NAME] == APP_EXE_NAME


def test_verify_portable_tree_reports_missing_resources(tmp_path: Path) -> None:
    portable = tmp_path / APP_PACKAGE_NAME
    portable.mkdir()
    (portable / APP_EXE_NAME).write_text("fake", encoding="utf-8")

    result = verify_portable_tree(portable)

    assert result.passed is False
    assert "QtWebEngineProcess.exe" in result.missing_files
    assert "qtwebengine_resources.pak" in result.missing_files


def test_portable_zip_contains_root_folder(tmp_path: Path) -> None:
    portable = _fake_portable_tree(tmp_path)

    zip_path = create_portable_zip(portable, tmp_path / PORTABLE_ZIP_NAME)

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert f"{APP_PACKAGE_NAME}/{APP_EXE_NAME}" in names
    assert f"{APP_PACKAGE_NAME}/resources/qtwebengine_resources.pak" in names


def test_release_notes_and_checksums_are_written(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("quick insight", encoding="utf-8")

    notes = write_release_notes(
        tmp_path / RELEASE_NOTES_NAME,
        generated_at=datetime(2026, 7, 13, tzinfo=UTC),
        license_entries=(),
        installer_status="skipped_missing_inno_setup",
    )
    sums = write_sha256sums(tmp_path / SHA256SUMS_NAME, [artifact, notes])

    assert "QuickInsight Desktop Release Notes" in notes.read_text(encoding="utf-8")
    sums_text = sums.read_text(encoding="utf-8")
    assert "artifact.txt" in sums_text
    assert RELEASE_NOTES_NAME in sums_text


def test_license_inventory_writes_summary(tmp_path: Path) -> None:
    entries = write_third_party_license_inventory(tmp_path / "licenses")

    summary = tmp_path / "licenses" / "THIRD_PARTY_LICENSES.md"
    assert summary.exists()
    assert entries
    assert "Third-Party License Inventory" in summary.read_text(encoding="utf-8")


def test_build_release_package_can_reuse_existing_portable_tree(tmp_path: Path) -> None:
    repo_root = tmp_path
    dist_dir = repo_root / "dist"
    build_dir = repo_root / "build" / "package"
    _fake_portable_tree(dist_dir)

    result = build_release_package(
        repo_root=repo_root,
        dist_dir=dist_dir,
        build_dir=build_dir,
        skip_build=True,
        skip_smoke=True,
        skip_installer=True,
    )

    assert result.verification.passed is True
    assert (dist_dir / PORTABLE_ZIP_NAME).exists()
    assert (dist_dir / RELEASE_NOTES_NAME).exists()
    assert (dist_dir / SHA256SUMS_NAME).exists()
    payload = json.loads((dist_dir / PACKAGE_REPORT_NAME).read_text(encoding="utf-8"))
    assert payload["build_status"] == "skipped_by_request"
    assert payload["installer_status"] == "skipped_by_request"


def test_release_package_requires_a_successful_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path
    dist_dir = repo_root / "dist"
    build_dir = repo_root / "build" / "package"
    _fake_portable_tree(dist_dir)

    monkeypatch.setattr(
        release_packaging,
        "run_packaged_smoke",
        lambda executable, smoke_seconds: CommandResult(
            command=(str(executable), str(smoke_seconds)),
            return_code=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        release_packaging,
        "_try_build_inno_setup",
        lambda **kwargs: (None, "skipped_missing_inno_setup"),
    )

    result = build_release_package(
        repo_root=repo_root,
        dist_dir=dist_dir,
        build_dir=build_dir,
        skip_build=True,
    )

    assert result.smoke_result is not None and result.smoke_result.succeeded
    assert result.installer_status == "skipped_missing_inno_setup"
    assert result.passed is False


def _fake_portable_tree(base_dir: Path) -> Path:
    portable = base_dir / APP_PACKAGE_NAME
    (portable / "resources").mkdir(parents=True)
    (portable / "bin").mkdir()
    (portable / APP_EXE_NAME).write_text("fake exe", encoding="utf-8")
    (portable / "bin" / "QtWebEngineProcess.exe").write_text("fake helper", encoding="utf-8")
    (portable / "bin" / "Qt6WebEngineCore.dll").write_text("fake dll", encoding="utf-8")
    (portable / "resources" / "qtwebengine_resources.pak").write_text(
        "fake pak",
        encoding="utf-8",
    )
    return portable
