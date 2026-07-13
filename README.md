# QuickInsight Desktop

QuickInsight Desktop is a Windows-first, offline-first desktop application for fast analysis of tabular datasets and manually categorized text records.

The project is in M0 foundation work. The current shell provides:

- A real PySide6 application bootstrap.
- A Simplified Chinese welcome page.
- A three-column workspace frame with a bottom status strip.
- Light and dark QSS token themes.
- Structured app paths, settings, logging, user-facing errors, and a testable job abstraction.
- Deterministic small samples for future import/profile/chart work.

It does **not** yet implement data import, profiling, chart generation, project persistence, or packaging. Those are tracked in `TASKS.md`.

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

If Python 3.13 x64 is missing, `setup_dev.ps1` fails with an actionable message instead of accepting another interpreter.

## Privacy

The app is offline by default. M0 has no telemetry, analytics, remote assets, or upload behavior.
