# Project Status

Date: 2026-07-13

## Current Version And Milestone

- Version: `0.0.0`
- Milestone: M4 chart workspace and export is active
- Status: M1 tabular import and virtual preview accepted; M2 profiling, one-click analysis, and text corpus workflow accepted; M3 explainable chart recommendation accepted.

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
- Moved paged table reads into background jobs with cancellation and stale-result rejection.
- Added direct UI coverage for malformed CSV, Excel, Parquet, and missing-source import error paths.
- Added the first M2 slice: DuckDB-backed full-scan column statistics, deterministic semantic type inference, dataset/profile warnings, and unit/integration tests.
- Added tabular quality checks for duplicate rows, missing values, constants, mixed-type hints, datetime ranges, IQR outlier candidates, and strict-import parse-failure status.
- Added quality-focused `AnalysisFinding` output with reproducible evidence and a GUI overview page that profiles imported datasets in a background job.
- Added one-click tabular analysis findings for time trends, numeric correlations, and category group differences; every finding records DuckDB evidence and explicitly avoids causation claims.
- Added text corpus entry/import preview, TXT/Markdown/JSONL splitting, category/tag/source defaults, and DuckDB persistence for `TextRecord`, `Category`, and tag data.
- Added text corpus profiling and quality checks for category/tag/source counts, text-length distribution, empty/duplicate/extreme-length checks, category conflicts, near-duplicate category names, keyword matches, surface token frequencies, and tag co-occurrence.
- Added a virtualized text labeling workspace backed by a paged `QTableView`, with search/category filters, inline category creation, full record detail editing, save-next, undo restore, and bulk category/tag updates.
- Added deterministic chart recommendation rule scoring for tabular and text profiles, with score breakdowns, reasons, warnings, export strategy, and data-budget metadata.
- Added workspace recommendation cards with analysis-intent selection, scores, field mappings, reasons, warnings, aggregation, data budgets, score breakdowns, and guarded future chart actions.
- Added the first M4 chart workspace slice: `plotly==6.9.0`, offline Plotly HTML generation, a Qt WebEngine chart view, CSP/network-blocking chart profile, renderer preview documents, and recommendation-card generate actions that open the chart workspace with explicit preview warnings.

## Remaining Work

- Add real chart data preparation from DuckDB/profile outputs with data budgets, downsampling/binning/top-N strategies, and background jobs.
- Add HTML/SVG/PNG/JSON export flows and stronger runtime validation for blocked external chart requests.
- Continue committing once per completed milestone or coherent stage.

## Known Issues

- Full packaging is intentionally deferred to M6.
- Chart rendering currently shows an explicit renderer preview, not a chart prepared from real dataset aggregates.
- Chart export, transforms, and project persistence are not implemented yet.
- Recommendation-card edit actions remain guarded until editable chart specifications are implemented.
- Text corpus data can be entered/imported, persisted, profiled, and labeled locally; safe category rename/merge/delete audit and project-level reopen/migration are deferred to later P0 hardening milestones.
- Text corpus profiling currently performs a full application-level scan through the workspace adapter; future large-corpus hardening should push more aggregate work into DuckDB or bounded iterators.

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
- Background paged query slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 34 source files, pytest passed 26 tests on Python 3.13.14 / PySide6 6.11.1.
- Background paged query slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- `git commit -m "feat: fetch preview pages in background"`: exit 0; created commit `627ed95`.
- `git push`: exit 0; pushed `627ed95` to `origin/main`.
- M1 error-path slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 34 source files, pytest passed 30 tests on Python 3.13.14 / PySide6 6.11.1.
- M1 error-path slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- M2 tabular profiling slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 35 source files, pytest passed 37 tests on Python 3.13.14 / PySide6 6.11.1.
- M2 tabular profiling slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- M2 tabular quality/profile UI slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 35 source files, pytest passed 38 tests on Python 3.13.14 / PySide6 6.11.1.
- M2 tabular quality/profile UI slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- M2 one-click tabular analysis slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 36 source files, pytest passed 40 tests on Python 3.13.14 / PySide6 6.11.1.
- M2 one-click tabular analysis slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- M2 text corpus import/persistence slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 38 source files, pytest passed 47 tests on Python 3.13.14 / PySide6 6.11.1.
- M2 text corpus import/persistence slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- M2 text corpus profiling slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 39 source files, pytest passed 49 tests on Python 3.13.14 / PySide6 6.11.1.
- M2 text corpus profiling slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- M2 virtualized text labeling workspace slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 40 source files, pytest passed 52 tests on Python 3.13.14 / PySide6 6.11.1.
- M2 virtualized text labeling workspace slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- M3 deterministic chart recommendation scoring slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 41 source files, pytest passed 60 tests on Python 3.13.14 / PySide6 6.11.1.
- M3 deterministic chart recommendation scoring slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- M3 recommendation card UI slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 41 source files, pytest passed 61 tests on Python 3.13.14 / PySide6 6.11.1.
- M3 recommendation card UI slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.
- Dependency refresh `.\scripts\setup_dev.ps1 -RefreshLock`: exit 0; installed and locked `plotly==6.9.0` with `narwhals==2.23.0`.
- M4 local renderer slice `.\scripts\test.ps1`: exit 0; ruff passed, mypy passed for 43 source files, pytest passed 63 tests on Python 3.13.14 / PySide6 6.11.1.
- M4 local renderer slice `.\scripts\run.ps1 -SmokeSeconds 2`: exit 0; Qt app launched through the project script and auto-exited.

## Next Action

Implement real chart data preparation with point budgets, Top N, and downsampling before sending data to Plotly/WebEngine.
