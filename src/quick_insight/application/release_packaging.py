from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from quick_insight import __version__

APP_EXE_NAME = "QuickInsight.exe"
APP_PACKAGE_NAME = "QuickInsight-portable-x64"
PORTABLE_ZIP_NAME = f"{APP_PACKAGE_NAME}.zip"
SETUP_EXE_NAME = "QuickInsight-Setup-x64.exe"
SHA256SUMS_NAME = "SHA256SUMS.txt"
RELEASE_NOTES_NAME = "release-notes.md"
PACKAGE_REPORT_NAME = "package-report.json"
BUILD_REPORT_NAME = "package-report.md"

REQUIRED_PORTABLE_FILES = (
    APP_EXE_NAME,
    "QtWebEngineProcess.exe",
    "Qt6WebEngineCore.dll",
    "qtwebengine_resources.pak",
)


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "command": list(self.command),
            "return_code": self.return_code,
            "stdout": self.stdout[-6000:],
            "stderr": self.stderr[-6000:],
        }


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    missing_files: tuple[str, ...]
    located_files: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "missing_files": list(self.missing_files),
            "located_files": self.located_files,
        }


@dataclass(frozen=True)
class LicenseEntry:
    name: str
    version: str
    license_text: str
    metadata_license: str
    source: str
    file_name: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "metadata_license": self.metadata_license,
            "source": self.source,
            "file_name": self.file_name,
        }


@dataclass(frozen=True)
class PackageResult:
    generated_at: datetime
    repo_root: Path
    dist_dir: Path
    build_dir: Path
    portable_dir: Path
    portable_zip: Path | None
    setup_exe: Path | None
    release_notes: Path
    sha256sums: Path
    license_dir: Path
    verification: VerificationResult
    smoke_result: CommandResult | None
    build_status: str
    installer_status: str
    commands: tuple[CommandResult, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    schema_version: int = 1

    @property
    def passed(self) -> bool:
        return (
            self.build_status == "created"
            and self.verification.passed
            and self.portable_zip is not None
            and self.portable_zip.exists()
            and self.smoke_result is not None
            and self.smoke_result.succeeded
            and self.installer_status == "created"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "app_version": __version__,
            "repo_root": str(self.repo_root),
            "dist_dir": str(self.dist_dir),
            "build_dir": str(self.build_dir),
            "portable_dir": str(self.portable_dir),
            "portable_zip": _optional_path(self.portable_zip),
            "setup_exe": _optional_path(self.setup_exe),
            "release_notes": str(self.release_notes),
            "sha256sums": str(self.sha256sums),
            "license_dir": str(self.license_dir),
            "verification": self.verification.to_dict(),
            "smoke_result": None if self.smoke_result is None else self.smoke_result.to_dict(),
            "build_status": self.build_status,
            "installer_status": self.installer_status,
            "commands": [command.to_dict() for command in self.commands],
            "warnings": list(self.warnings),
            "passed": self.passed,
        }


def build_release_package(
    *,
    repo_root: Path,
    dist_dir: Path,
    build_dir: Path,
    smoke_seconds: float = 2.0,
    skip_build: bool = False,
    skip_smoke: bool = False,
    skip_installer: bool = False,
) -> PackageResult:
    resolved_root = repo_root.resolve()
    resolved_dist = _resolve_under_root(resolved_root, dist_dir)
    resolved_build = _resolve_under_root(resolved_root, build_dir)
    generated_at = datetime.now(UTC)
    portable_dir = resolved_dist / APP_PACKAGE_NAME
    license_dir = resolved_dist / "third-party-licenses"
    commands: list[CommandResult] = []
    warnings: list[str] = []
    build_status = "skipped_by_request" if skip_build else "created"

    if skip_build:
        resolved_dist.mkdir(parents=True, exist_ok=True)
        resolved_build.mkdir(parents=True, exist_ok=True)
        if not portable_dir.exists():
            raise FileNotFoundError(
                f"{portable_dir} does not exist; skip-build requires an existing portable tree."
            )
    else:
        _clean_directory(resolved_dist, resolved_root)
        _clean_directory(resolved_build, resolved_root)
        resolved_dist.mkdir(parents=True, exist_ok=True)
        resolved_build.mkdir(parents=True, exist_ok=True)
        build_output = _build_standalone_with_nuitka(resolved_root, resolved_build)
        commands.append(build_output)
        if not build_output.succeeded:
            _write_failure_report(
                generated_at=generated_at,
                dist_dir=resolved_dist,
                build_dir=resolved_build,
                command=build_output,
            )
            raise RuntimeError("Nuitka standalone build failed; see package-report.json.")
        standalone_dir = _find_standalone_dir(resolved_build)
        shutil.copytree(standalone_dir, portable_dir)

    verification = verify_portable_tree(portable_dir)
    if not verification.passed:
        raise RuntimeError(
            "Portable package verification failed; missing "
            + ", ".join(verification.missing_files)
        )

    license_entries = write_third_party_license_inventory(license_dir)
    release_notes = write_release_notes(
        resolved_dist / RELEASE_NOTES_NAME,
        generated_at=generated_at,
        license_entries=license_entries,
        installer_status="pending",
    )
    portable_zip = create_portable_zip(portable_dir, resolved_dist / PORTABLE_ZIP_NAME)
    setup_exe: Path | None = None
    installer_status = "skipped_by_request" if skip_installer else "skipped_missing_inno_setup"
    if not skip_installer:
        setup_exe, installer_status = _try_build_inno_setup(
            repo_root=resolved_root,
            build_dir=resolved_build,
            dist_dir=resolved_dist,
            portable_dir=portable_dir,
        )
        if setup_exe is None:
            warnings.append(
                "Inno Setup compiler was not found; installer EXE was not produced."
            )

    smoke_result: CommandResult | None = None
    if skip_smoke:
        warnings.append("Packaged smoke launch was skipped by request.")
    else:
        smoke_result = run_packaged_smoke(portable_dir / APP_EXE_NAME, smoke_seconds)
        commands.append(smoke_result)
        if not smoke_result.succeeded:
            raise RuntimeError("Packaged smoke launch failed; see package-report.json.")

    release_notes = write_release_notes(
        resolved_dist / RELEASE_NOTES_NAME,
        generated_at=generated_at,
        license_entries=license_entries,
        installer_status=installer_status,
    )
    sha256sums = write_sha256sums(
        resolved_dist / SHA256SUMS_NAME,
        [
            portable_zip,
            release_notes,
            resolved_dist / PACKAGE_REPORT_NAME,
            *(tuple() if setup_exe is None else (setup_exe,)),
        ],
    )
    result = PackageResult(
        generated_at=generated_at,
        repo_root=resolved_root,
        dist_dir=resolved_dist,
        build_dir=resolved_build,
        portable_dir=portable_dir,
        portable_zip=portable_zip,
        setup_exe=setup_exe,
        release_notes=release_notes,
        sha256sums=sha256sums,
        license_dir=license_dir,
        verification=verification,
        smoke_result=smoke_result,
        build_status=build_status,
        installer_status=installer_status,
        commands=tuple(commands),
        warnings=tuple(warnings),
    )
    _write_package_reports(result)
    write_sha256sums(
        resolved_dist / SHA256SUMS_NAME,
        [
            portable_zip,
            release_notes,
            resolved_dist / PACKAGE_REPORT_NAME,
            *(tuple() if setup_exe is None else (setup_exe,)),
        ],
    )
    return result


def verify_portable_tree(portable_dir: Path) -> VerificationResult:
    located: dict[str, str] = {}
    missing: list[str] = []
    for required_name in REQUIRED_PORTABLE_FILES:
        match = _find_file(portable_dir, required_name)
        if match is None:
            missing.append(required_name)
        else:
            located[required_name] = str(match.relative_to(portable_dir))
    return VerificationResult(
        passed=not missing,
        missing_files=tuple(missing),
        located_files=located,
    )


def create_portable_zip(portable_dir: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    root_name = portable_dir.name
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(portable_dir.rglob("*")):
            if path.is_file():
                relative = Path(root_name) / path.relative_to(portable_dir)
                archive.write(path, relative.as_posix())
    return destination


def run_packaged_smoke(executable: Path, smoke_seconds: float) -> CommandResult:
    seconds = str(smoke_seconds)
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return _run_command(
        (
            str(executable),
            "--smoke-seconds",
            seconds,
            "--theme",
            "dark",
        ),
        cwd=executable.parent,
        env=env,
        timeout_seconds=max(30, int(smoke_seconds) + 20),
    )


def write_third_party_license_inventory(output_dir: Path) -> tuple[LicenseEntry, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    entries: list[LicenseEntry] = []
    for dist in sorted(metadata.distributions(), key=lambda item: _dist_name(item).casefold()):
        name = _dist_name(dist)
        if name == "quick-insight-desktop":
            continue
        version = dist.version
        metadata_license = _metadata_value(dist, "License") or _metadata_value(
            dist,
            "License-Expression",
        )
        source, license_text = _read_distribution_license(dist)
        file_name = f"{_safe_file_stem(name)}-{version}.md"
        path = output_dir / file_name
        path.write_text(
            _license_entry_markdown(
                name=name,
                version=version,
                metadata_license=metadata_license,
                source=source,
                license_text=license_text,
            ),
            encoding="utf-8",
        )
        entries.append(
            LicenseEntry(
                name=name,
                version=version,
                license_text=license_text,
                metadata_license=metadata_license,
                source=source,
                file_name=file_name,
            )
        )
    summary_path = output_dir / "THIRD_PARTY_LICENSES.md"
    summary_path.write_text(_license_summary_markdown(tuple(entries)), encoding="utf-8")
    return tuple(entries)


def write_release_notes(
    destination: Path,
    *,
    generated_at: datetime,
    license_entries: tuple[LicenseEntry, ...],
    installer_status: str,
) -> Path:
    destination.write_text(
        "\n".join(
            [
                "# QuickInsight Desktop Release Notes",
                "",
                f"Generated: {generated_at.isoformat()}",
                f"Version: {__version__}",
                "",
                "## Artifacts",
                "",
                f"- `{PORTABLE_ZIP_NAME}`: verified portable Windows x64 package.",
                f"- `{SETUP_EXE_NAME}`: {installer_status}.",
                f"- `{SHA256SUMS_NAME}`: SHA-256 checksums for release artifacts.",
                "- `third-party-licenses/`: generated license inventory.",
                "",
                "## Validation",
                "",
                "- Standalone package must contain QuickInsight.exe and Qt WebEngine resources.",
                "- Packaged smoke launch runs the application with an auto-exit timer.",
                "- The app remains offline-first; no telemetry or remote assets are enabled.",
                "",
                "## Known Limitations",
                "",
                "- Installer generation requires Inno Setup (`ISCC.exe`) on the build machine.",
                "- SVG/PNG chart export still requires a loaded desktop Qt WebEngine view.",
                "- License inventory contains "
                f"{len(license_entries)} installed third-party packages.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return destination


def write_sha256sums(destination: Path, files: list[Path]) -> Path:
    lines: list[str] = []
    for path in files:
        if not path.exists() or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    destination.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    return destination


def _build_standalone_with_nuitka(repo_root: Path, build_dir: Path) -> CommandResult:
    nuitka_dir = build_dir / "nuitka"
    cache_dir = build_dir / "nuitka-cache"
    temp_dir = build_dir / "temp"
    nuitka_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    source = repo_root / "src" / "quick_insight" / "main.py"
    resources = repo_root / "src" / "quick_insight" / "resources"
    env = os.environ.copy()
    env["NUITKA_CACHE_DIR"] = str(cache_dir)
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    command = (
        sys.executable,
        "-m",
        "nuitka",
        str(source),
        "--standalone",
        "--enable-plugin=pyside6",
        "--include-package=quick_insight",
        f"--include-data-dir={resources}=quick_insight/resources",
        f"--output-dir={nuitka_dir}",
        f"--output-filename={APP_EXE_NAME}",
        "--noinclude-qt-translations",
        "--include-qt-plugins=platforminputcontexts",
        "--assume-yes-for-downloads",
        "--quiet",
    )
    return _run_command(command, cwd=repo_root, env=env, timeout_seconds=1800)


def _find_standalone_dir(build_dir: Path) -> Path:
    candidates = sorted(build_dir.rglob(f"{APP_EXE_NAME}"))
    for executable in candidates:
        if executable.parent.name.endswith(".dist"):
            return executable.parent
    if candidates:
        return candidates[0].parent
    raise FileNotFoundError(f"{APP_EXE_NAME} was not produced by Nuitka.")


def _try_build_inno_setup(
    *,
    repo_root: Path,
    build_dir: Path,
    dist_dir: Path,
    portable_dir: Path,
) -> tuple[Path | None, str]:
    compiler = shutil.which("ISCC.exe")
    if compiler is None:
        return None, "skipped_missing_inno_setup"
    iss_path = build_dir / "QuickInsight.iss"
    iss_path.write_text(
        _inno_setup_script(
            repo_root=repo_root,
            dist_dir=dist_dir,
            portable_dir=portable_dir,
        ),
        encoding="utf-8",
    )
    command = _run_command((compiler, str(iss_path)), cwd=repo_root, timeout_seconds=600)
    if not command.succeeded:
        return None, f"failed_exit_{command.return_code}"
    setup_exe = dist_dir / SETUP_EXE_NAME
    if setup_exe.exists():
        return setup_exe, "created"
    return None, "failed_missing_output"


def _inno_setup_script(*, repo_root: Path, dist_dir: Path, portable_dir: Path) -> str:
    app_id = "{{B63DB8F6-2FAF-44FE-82A2-2C8D17B25370}"
    return "\n".join(
        [
            "[Setup]",
            f"AppId={app_id}",
            "AppName=QuickInsight Desktop",
            f"AppVersion={__version__}",
            "DefaultDirName={autopf}\\QuickInsight Desktop",
            "DefaultGroupName=QuickInsight Desktop",
            "DisableProgramGroupPage=yes",
            f"OutputDir={dist_dir}",
            "OutputBaseFilename=QuickInsight-Setup-x64",
            "Compression=lzma2",
            "SolidCompression=yes",
            "ArchitecturesAllowed=x64compatible",
            "ArchitecturesInstallIn64BitMode=x64compatible",
            "",
            "[Files]",
            f'Source: "{portable_dir}\\*"; DestDir: "{{app}}"; Flags: recursesubdirs ignoreversion',
            "",
            "[Icons]",
            f'Name: "{{group}}\\QuickInsight Desktop"; Filename: "{{app}}\\{APP_EXE_NAME}"',
            'Name: "{autodesktop}\\QuickInsight Desktop"; '
            f'Filename: "{{app}}\\{APP_EXE_NAME}"; Tasks: desktopicon',
            "",
            "[Tasks]",
            'Name: "desktopicon"; Description: "Create a desktop shortcut"; '
            'GroupDescription: "Shortcuts:"',
            "",
            "[Run]",
            f'Filename: "{{app}}\\{APP_EXE_NAME}"; '
            'Description: "Launch QuickInsight Desktop"; '
            "Flags: nowait postinstall skipifsilent",
            "",
            f"; Generated from {repo_root}",
            "",
        ]
    )


def _write_package_reports(result: PackageResult) -> None:
    json_path = result.dist_dir / PACKAGE_REPORT_NAME
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path = result.build_dir / BUILD_REPORT_NAME
    markdown_path.write_text(_package_report_markdown(result), encoding="utf-8")


def _write_failure_report(
    *,
    generated_at: datetime,
    dist_dir: Path,
    build_dir: Path,
    command: CommandResult,
) -> None:
    dist_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "app_version": __version__,
        "passed": False,
        "failed_command": command.to_dict(),
    }
    (dist_dir / PACKAGE_REPORT_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (build_dir / BUILD_REPORT_NAME).write_text(
        "\n".join(
            [
                "# QuickInsight Package Report",
                "",
                f"Generated: {generated_at.isoformat()}",
                "Passed: false",
                "",
                "Nuitka standalone build failed.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _package_report_markdown(result: PackageResult) -> str:
    setup = result.setup_exe.name if result.setup_exe is not None else result.installer_status
    smoke = "skipped" if result.smoke_result is None else str(result.smoke_result.succeeded)
    return "\n".join(
        [
            "# QuickInsight Package Report",
            "",
            f"Generated: {result.generated_at.isoformat()}",
            f"Version: {__version__}",
            f"Passed: {result.passed}",
            "",
            "## Artifacts",
            "",
            f"- Portable ZIP: {result.portable_zip.name if result.portable_zip else 'missing'}",
            f"- Installer: {setup}",
            f"- SHA256 sums: {result.sha256sums.name}",
            f"- Release notes: {result.release_notes.name}",
            "",
            "## Verification",
            "",
            f"- Portable resources present: {result.verification.passed}",
            f"- Standalone build completed: {result.build_status == 'created'}",
            f"- Packaged smoke passed: {smoke}",
            "",
        ]
    )


def _run_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _resolve_under_root(root: Path, path: Path) -> Path:
    resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{resolved} must stay within {root}") from exc
    return resolved


def _clean_directory(path: Path, root: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Refusing to clean {resolved}; it is outside {root}.") from exc
    if resolved.exists():
        shutil.rmtree(resolved)


def _find_file(root: Path, name: str) -> Path | None:
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


def _optional_path(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _dist_name(dist: metadata.Distribution) -> str:
    return _metadata_value(dist, "Name") or "unknown"


def _metadata_value(dist: metadata.Distribution, key: str) -> str:
    value = dist.metadata.get(key)
    return "" if value is None else str(value)


def _read_distribution_license(dist: metadata.Distribution) -> tuple[str, str]:
    candidate_names = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "NOTICE")
    for file in dist.files or ():
        name = Path(str(file)).name
        if name.upper() in {candidate.upper() for candidate in candidate_names}:
            path = Path(str(dist.locate_file(file)))
            try:
                return str(file), path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return "metadata", "No packaged license file was found; see package metadata."


def _license_summary_markdown(entries: tuple[LicenseEntry, ...]) -> str:
    lines = [
        "# Third-Party License Inventory",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "| Package | Version | Metadata License | Notice File |",
        "| --- | --- | --- | --- |",
    ]
    for entry in entries:
        license_text = entry.metadata_license or "unspecified"
        lines.append(f"| {entry.name} | {entry.version} | {license_text} | {entry.file_name} |")
    lines.append("")
    return "\n".join(lines)


def _license_entry_markdown(
    *,
    name: str,
    version: str,
    metadata_license: str,
    source: str,
    license_text: str,
) -> str:
    return "\n".join(
        [
            f"# {name} {version}",
            "",
            f"Metadata license: {metadata_license or 'unspecified'}",
            f"License source: {source}",
            "",
            "```text",
            license_text.strip(),
            "```",
            "",
        ]
    )


def _safe_file_stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "package"
