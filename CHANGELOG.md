# Changelog

## 0.0.0 - 2026-07-13

- Initialized the M0 foundation for QuickInsight Desktop.
- Added PySide6 bootstrap shell, theme tokens, welcome page, workspace frame, app paths/settings/logging, error model, job abstraction, deterministic samples, scripts, tests, and baseline documentation.
- Fixed the development setup script for Windows PowerShell argument quoting and validated M0 on CPython 3.13.14 x64.
- Added the first M1 tabular import slice: CSV/TSV detection, preview confirmation dialog, DuckDB workspace import, and paged `QTableView` preview.
- Added Excel/Parquet preview and confirmed-import paths using Polars, DuckDB, and `fastexcel` for the Calamine Excel engine.
- Added normalized Parquet cache export and source fingerprint invalidation checks for confirmed tabular imports.
- Moved confirmed tabular imports into a Qt background job with progress, cancellation request, and user-facing failure handling.
- Moved DuckDB preview page reads into background jobs with cancellation and stale-result rejection.
- Added direct malformed-file import UI coverage and closed M1 tabular import/virtual preview tasks.
- Added the first M2 profiling slice: DuckDB-backed column statistics, deterministic semantic type inference, dataset/profile warnings, and tests.
- Added tabular quality checks for duplicate rows, missing values, constants, mixed-type hints, datetime ranges, IQR outlier candidates, parse-failure status, quality findings, and a background GUI overview page.
- Added one-click tabular analysis findings for time trends, numeric correlations, and category group differences, with reproducible DuckDB evidence and no causation claims.
- Added text corpus entry/import preview, TXT/Markdown/JSONL splitting, category/tag/source defaults, and DuckDB persistence for text records, categories, and tags.
- Added text corpus profiling and quality checks for category/tag/source counts, text lengths, duplicates, category conflicts, keyword matches, surface token frequencies, and tag co-occurrence.
- Added a virtualized text labeling workspace with paged `QTableView` records, search/category filters, inline category creation, detail editing, save-next, undo, and bulk category/tag updates.
- Added deterministic chart recommendation rule scoring with score breakdowns, reasons, warnings, data budgets, and tabular/text rule coverage.
- Added workspace recommendation cards with analysis-intent selection, scores, field mappings, reasons, warnings, aggregation, data budgets, score breakdowns, and guarded future chart actions.
- Added the first M4 chart workspace slice: pinned Plotly, offline Plotly HTML generation, a Qt WebEngine chart view, local renderer preview documents, and recommendation-card generate actions that open the guarded chart workspace.
- Added DuckDB-backed tabular chart data preparation for Top N plus Other category aggregation, time-window downsampling, scatter uniform sampling, histogram bins, 2D density bins, and categorical cross-tab aggregation.
- Added chart export for self-contained HTML, figure/config JSON, and SVG/PNG through local Plotly.js `toImage`, including WebGL SVG vector warnings.
- Added stronger chart request blocking: only local chart schemes are allowed, file/network/script schemes are rejected, WebEngine local-content access is hardened, and blocked requests are surfaced in the chart view.
- Completed M4 chart data preparation for box plots, correlation heatmaps, and current text-corpus chart specs, including text category/status/source/keyword/category-keyword/tag-cooccurrence charts.
- Added the first M5 transform foundation: safe transform steps, restricted DuckDB SQL compilation, non-destructive preview materialization, and tests for select/rename/filter/sort/deduplicate/missing/type-conversion/group aggregation paths.
- Added a right-panel no-code transform UI for tabular datasets with field selection/rename, filters, sorting, deduplication, missing-value handling, type conversion, group aggregation, lossy-operation confirmation, background preview, cancellation, and non-destructive preview table activation.
- Added the first `.qiproject` persistence foundation: versioned ZIP project packages with `manifest.json` and `project.duckdb`, atomic save/open, safe archive path and size checks, source-file evidence validation, and guarded source relocation.
- Added main-window project open/save/save-as actions that run in background jobs, track tabular/text/derived transform datasets in the project manifest, restore DuckDB-backed previews and text labeling state after reopen, and surface source-reference warnings.
- Added a user-facing source relocation dialog for missing or mismatched external source files; moved files are accepted only after saved size and content sample evidence match the project record.
- Added processed-data export: current tabular/imported/transform-preview tables export to CSV or Parquet, current text corpora export to JSONL or CSV with category/tag metadata, exports run in background jobs, and existing target files are refused by default.
- Added safe text category governance: transactional rename/merge/delete, category descriptions, affected-record counts, privacy-conscious audit records, and text-labeling UI controls.
- Added the first M6 performance hardening slice: deterministic tabular benchmark generation/reporting, a `scripts/benchmark.ps1` runner, startup stale-temp cleanup, explicit normalized-cache cleanup policy, and tests for benchmark evidence plus cleanup safety.
- Completed the first M6 benchmark pass for 100k, 1m, and 5m generated rows and fixed CSV preview sample reading so large-file preview uses bounded memory.
- Added the first M6 accessibility/DPI baseline: accessible names/descriptions/tooltips for primary controls, minimum hit-target sizes for key actions, and UI smoke tests for the baseline.
- Added an automated M6 DPI visual sweep with `scripts/dpi_sweep.ps1`, per-scale screenshots, geometry/text-fit checks, and reports for 100%, 125%, 150%, and 200% scaling; adjusted high-content workspace pages to remain usable at 1366 x 768.
