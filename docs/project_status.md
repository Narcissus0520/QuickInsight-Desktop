# Project Status

Date: 2026-07-13

## Current Version And Milestone

- Version: `0.0.0`
- Milestone: M1 tabular import and virtual preview
- Status: M0 foundation accepted; M1 is the next active milestone.

## Completed Work

- Initialized the repository foundation around the existing `AGENTS.md` contract.
- Added PySide6 launch bootstrap, Chinese welcome page, three-column workspace shell, bottom status area, and light/dark themes.
- Added domain enums/models, user-facing error model, app paths/settings/logging, job abstraction, chart budget constants, deterministic samples, tests, scripts, and Windows CI.
- Configured `origin` for `git@github.com:Narcissus0520/QuickInsight-Desktop.git`.
- Installed CPython 3.13.14 x64 with `winget` and completed M0 gates on the target runtime.
- Committed and pushed M0 as `a8b3315 chore: bootstrap M0 foundation`.
- Added the first M1 slice: CSV/TSV preview detection, confirmation dialog, DuckDB import, paged `QAbstractTableModel`, and main-window preview.
- Added Excel/Parquet preview paths using Polars and the Calamine/fastexcel Excel engine; confirmed imports write to the same DuckDB preview pipeline.
- Added normalized Parquet cache export for confirmed imports and source fingerprint invalidation checks.
- Moved confirmed tabular import execution into a Qt background job with progress, cancellation request, and user-facing error display.

## Remaining Work

- Move paged query execution onto cancellable background jobs with stale-result rejection.
- Expand import error-path UI coverage.
- Continue committing once per completed milestone or coherent stage.

## Known Issues

- Full packaging is intentionally deferred to M6.
- Profiling, charting, transforms, and project persistence are not implemented yet.
- Paged table reads still execute synchronously on demand; background query jobs remain an M1 task.

## Latest Test And Build Results

- `winget show --id Python.Python.3.13 --exact --accept-source-agreements`: exit 0; resolved Python 3.13.14 from Python Software Foundation, installer URL `https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.exe`, SHA256 `c54d9b9bbb8a36e6489363ddd01139707fd781d72f1f9e90c7ec65d0061368e0`.
- `winget install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity`: exit 0; installer hash verified and package installed.
- `py -3.13 -c "..."`: exit 0; reports `C:\Users\12776\AppData\Local\Programs\Python\Python313\python.exe`, Python 3.13.14, 64-bit.
- `.\scripts\setup_dev.ps1`: exit 0; created `.venv`, installed `requirements.lock`, and installed `quick-insight-desktop` editable package.
- M0 `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 25 source files, pytest passed 14 tests on Python 3.13.14 / PySide6 6.11.1.
- M0 `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- `git commit -m "chore: bootstrap M0 foundation"`: exit 0; created commit `a8b3315`.
- `git push -u origin main`: exit 0; pushed `main` to `origin/main`.
- M1 slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 33 source files, pytest passed 19 tests on Python 3.13.14 / PySide6 6.11.1.
- M1 slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- `git commit -m "feat: add csv import preview slice"`: exit 0; created commit `50a68b4`.
- `git push`: exit 0; pushed `50a68b4` to `origin/main`.
- Excel/Parquet slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 34 source files, pytest passed 23 tests on Python 3.13.14 / PySide6 6.11.1.
- Excel/Parquet slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- `git commit -m "feat: add excel and parquet preview"`: exit 0; created commit `6be36f2`.
- `git push`: exit 0; pushed `6be36f2` to `origin/main`.
- Normalized cache slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 34 source files, pytest passed 23 tests on Python 3.13.14 / PySide6 6.11.1.
- Normalized cache slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- `git commit -m "feat: add normalized parquet cache"`: exit 0; created commit `5c700f5`.
- `git push`: exit 0; pushed `5c700f5` to `origin/main`.
- Background import slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 34 source files, pytest passed 24 tests on Python 3.13.14 / PySide6 6.11.1.
- Background import slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- `git commit -m "feat: run imports in background job"`: exit 0; created the background import stage commit.
- `git push`: exit 0; pushed the background import stage to `origin/main`.

## Next Action

Continue M1 with background paged query jobs, stale-result rejection, and broader import error-path UI coverage.
