# Packaging

Release packaging is implemented during M6 and must be validated on a Windows x64 release machine before a release is claimed.

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

`scripts/package.ps1` invokes the release packager directly. It builds a Nuitka standalone application, verifies the Qt WebEngine executable/DLL/resources, writes third-party license notices, creates a portable ZIP, attempts an Inno Setup installer, launches the packaged application with an auto-exit timer, and writes a JSON/Markdown package report.

```powershell
.\scripts\package.ps1
```

Useful development-only switches are `-SkipInstaller`, `-SkipSmoke`, and `-SkipBuild`. They produce diagnostic partial output, but the package report remains `passed=false` and they must not be used to claim a complete release.

## Prerequisites and verification

- Run `scripts/setup_dev.ps1` first; the locked environment includes Nuitka.
- The build machine needs the Windows C/C++ build toolchain required by Nuitka.
- Install Inno Setup and expose `ISCC.exe` on `PATH` to produce `QuickInsight-Setup-x64.exe`.
- A successful release requires the portable ZIP, installer, SHA-256 sums, release notes, third-party license inventory, Qt WebEngine resource verification, and a successful packaged smoke launch.

The package report is generated at `dist/package-report.json` and `build/package/package-report.md`. The report is authoritative evidence; no artifact is considered released merely because the scripts or intermediate cache directories exist.
