# Packaging

Release packaging is implemented and validated on the Windows x64 development machine. Publishing the generated files remains a separate release-management action.

Preferred artifacts:

- `dist/QuickInsight-Setup-x64.exe`
- `dist/QuickInsight-portable-x64.zip`
- `dist/SHA256SUMS.txt`
- `dist/release-notes.md`
- `dist/third-party-licenses/`

## Build workflow

`scripts/build.ps1` runs the test and security-review gates before invoking packaging:

```powershell
.\scripts\build.ps1
```

`scripts/package.ps1` invokes the release packager directly. It builds a Nuitka standalone application, verifies the Qt WebEngine executable/DLL/resources, writes third-party license notices, creates a portable ZIP, builds an Inno Setup installer, and writes a JSON/Markdown package report.

```powershell
.\scripts\package.ps1
```

Useful development-only switches are `-SkipInstaller`, `-SkipSmoke`, and `-SkipBuild`. They produce diagnostic partial output, but the package report remains `passed=false` and they must not be used to claim a complete release.

## Prerequisites and verification

- Run `scripts/setup_dev.ps1` first; the locked environment includes Nuitka.
- The build machine needs the Windows C/C++ build toolchain required by Nuitka.
- Install Inno Setup 6.7.3 or later. The packager locates `ISCC.exe` from `PATH` or the standard per-user/system Inno Setup locations.
- A successful package requires the portable ZIP, installer, SHA-256 sums, release notes, third-party license inventory, Qt WebEngine resource verification, and successful packaged functional workflows. Each workflow creates a CSV, imports it, profiles it, gets a chart recommendation, prepares chart data, and produces a CSP-restricted offline Plotly HTML document.

The package report is generated at `dist/package-report.json` and `build/package/package-report.md`. The report is authoritative evidence; no artifact is considered released merely because the scripts or intermediate cache directories exist.

## Verified 2026-07-15 build

- `./scripts/package.ps1` exited 0 with `dist/package-report.json` reporting `passed=true`.
- The portable ZIP was 258,849,949 bytes and passed ZIP integrity and required-file checks.
- The installer was 171,555,549 bytes; silent install, resource verification, functional workflow, and silent uninstall all passed.
- The portable functional workflow imported 6 rows, prepared a bar chart with 3 rendered rows, and generated 4,862,239 bytes of offline chart HTML.
- `SHA256SUMS.txt` was recomputed and independently checked against every listed artifact.
