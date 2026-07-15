from __future__ import annotations

import json
import sys
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
        lambda executable, smoke_seconds, **kwargs: CommandResult(
            command=(str(executable), str(smoke_seconds)),
            return_code=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        release_packaging,
        "_try_build_inno_setup",
        lambda **kwargs: (None, "skipped_missing_inno_setup", None),
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


def test_inno_setup_compiler_is_found_in_user_install_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = tmp_path / "Programs" / "Inno Setup 6" / "ISCC.exe"
    compiler.parent.mkdir(parents=True)
    compiler.write_text("fake compiler", encoding="utf-8")
    monkeypatch.setattr(release_packaging.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "missing-x86"))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "missing"))

    result = release_packaging._locate_inno_setup_compiler()

    assert result == compiler


def test_installer_smoke_installs_launches_and_uninstalls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = tmp_path / "QuickInsight-Setup-x64.exe"
    installer.write_text("fake setup", encoding="utf-8")
    install_dir = tmp_path / "installed"
    commands: list[tuple[str, ...]] = []
    raw_commands: list[str | None] = []

    def fake_run_command(
        command: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
        raw_command_line: str | None = None,
    ) -> CommandResult:
        del cwd, timeout_seconds, env
        commands.append(command)
        raw_commands.append(raw_command_line)
        if command[0] == str(installer):
            _write_fake_portable_contents(install_dir)
            (install_dir / "unins000.exe").write_text("fake uninstaller", encoding="utf-8")
        return CommandResult(command=command, return_code=0, stdout="", stderr="")

    monkeypatch.setattr(release_packaging, "_run_command", fake_run_command)
    monkeypatch.setattr(
        release_packaging,
        "run_packaged_smoke",
        lambda executable, smoke_seconds, **kwargs: CommandResult(
            command=(str(executable), str(smoke_seconds)),
            return_code=0,
            stdout="",
            stderr="",
        ),
    )

    result = release_packaging.run_installer_smoke(
        installer,
        smoke_seconds=2,
        install_dir=install_dir,
    )

    assert result.passed is True
    assert "/VERYSILENT" in commands[0]
    assert any(argument.startswith("/LOG=") for argument in commands[0])
    assert raw_commands[0] is not None
    assert f'/DIR="{install_dir}"' in raw_commands[0]
    assert commands[-1][0] == str(install_dir / "unins000.exe")


def test_inno_setup_script_uses_per_user_privileges(tmp_path: Path) -> None:
    script = release_packaging._inno_setup_script(
        repo_root=tmp_path,
        dist_dir=tmp_path / "dist",
        portable_dir=tmp_path / APP_PACKAGE_NAME,
    )

    assert "PrivilegesRequired=lowest" in script


def test_command_capture_replaces_invalid_utf8_output(tmp_path: Path) -> None:
    result = release_packaging._run_command(
        (sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff')"),
        cwd=tmp_path,
        timeout_seconds=30,
    )

    assert result.succeeded is True
    assert result.stdout == "\N{REPLACEMENT CHARACTER}"


def test_nuitka_build_includes_plotly_validator_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: tuple[str, ...] | None = None

    def fake_run_command(
        command: tuple[str, ...],
        **_: object,
    ) -> CommandResult:
        nonlocal captured
        captured = command
        return CommandResult(command=command, return_code=0, stdout="", stderr="")

    monkeypatch.setattr(release_packaging, "_run_command", fake_run_command)

    release_packaging._build_standalone_with_nuitka(tmp_path, tmp_path / "build")

    assert captured is not None
    assert any(
        argument.endswith("=plotly/validators/_validators.json")
        for argument in captured
    )
    assert any(
        argument.endswith("=plotly/package_data/plotly.min.js")
        for argument in captured
    )


def _fake_portable_tree(base_dir: Path) -> Path:
    portable = base_dir / APP_PACKAGE_NAME
    _write_fake_portable_contents(portable)
    return portable


def _write_fake_portable_contents(portable: Path) -> None:
    (portable / "resources").mkdir(parents=True)
    (portable / "bin").mkdir()
    (portable / APP_EXE_NAME).write_text("fake exe", encoding="utf-8")
    (portable / "bin" / "QtWebEngineProcess.exe").write_text("fake helper", encoding="utf-8")
    (portable / "bin" / "Qt6WebEngineCore.dll").write_text("fake dll", encoding="utf-8")
    (portable / "resources" / "qtwebengine_resources.pak").write_text(
        "fake pak",
        encoding="utf-8",
    )
