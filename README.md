# QuickInsight Desktop

QuickInsight Desktop is a Windows-first, offline-first desktop application for fast analysis of tabular datasets and manually categorized text records.

M0 through M6 are accepted for the current P0 scope. The current application provides:

- A real PySide6 desktop shell with Simplified Chinese workflow screens.
- Tabular CSV/TSV/Excel/Parquet import previews, DuckDB-backed virtual preview, profiling, findings, transforms, and processed-data export.
- Text corpus import, profiling, virtualized labeling, category governance, and text export.
- Deterministic chart recommendations, offline Plotly/WebEngine rendering, data-budgeted chart preparation, and HTML/SVG/PNG/JSON export.
- `.qiproject` save/reopen with source validation and relocation.
- Benchmarks, cache cleanup, accessibility metadata, and automated high-DPI visual sweep tooling.

Verified local release automation produces a standalone portable ZIP and x64 installer with Qt WebEngine resource checks, functional workflow smoke tests, checksums, release notes, and license inventory. Publication remains a separate release-management action.

## Development

Target development runtime is CPython 3.13 x64 on Windows.

```powershell
.\scripts\setup_dev.ps1
.\scripts\test.ps1
.\scripts\run.ps1
```

For a launch smoke check:

```powershell
.\scripts\run.ps1 -SmokeSeconds 2
```

For M6 hardening evidence:

```powershell
.\scripts\benchmark.ps1 -Profile P0
.\scripts\dpi_sweep.ps1
.\scripts\security_review.ps1
```

If Python 3.13 x64 is missing, `setup_dev.ps1` fails with an actionable message instead of accepting another interpreter.

## Privacy

The app is offline by default. It has no telemetry, analytics, remote assets, or implicit upload behavior.
