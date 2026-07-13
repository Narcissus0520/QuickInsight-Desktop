# QuickInsight Desktop Tasks

## M0 - Foundation

- [x] Initialize local Git metadata and configure `origin`.
- [x] Create required repository structure and baseline documentation.
- [x] Add Python project metadata, dependency lock strategy, scripts, and Windows CI.
- [x] Add launchable PySide6 bootstrap shell with Chinese welcome page.
- [x] Add three-column workspace shell, bottom status area, and guarded future actions.
- [x] Add light/dark QSS design tokens and theme switching.
- [x] Add app paths, settings, structured logging, user-facing errors, and job abstraction skeleton.
- [x] Add deterministic business, sensor, dirty-table, and text-corpus samples.
- [x] Add unit and UI smoke test coverage for M0 behavior.
- [x] Complete M0 gates on CPython 3.13 x64 and record passing results.

## M1 - Tabular Import And Virtual Preview

M1 is accepted.

- [x] CSV/TSV import wizard with preview/confirmation.
- [x] Excel and Parquet preview path.
- [x] DuckDB workspace for confirmed CSV/TSV imports.
- [x] Normalized Parquet cache and source invalidation.
- [x] Safe paged table model backed by DuckDB.
- [x] Background import jobs with progress, cancellation request, and clear errors.
- [x] Background paged query jobs with stale-result rejection and cancellation.
- [x] Expanded import error-path UI coverage for malformed CSV/Excel/Parquet files.

## M2 - Profiling, One-Click Analysis, And Text Corpus Workflow

M2 is accepted.

- [x] Basic tabular semantic type inference and DuckDB-backed profile service.
- [x] Tabular quality checks, duplicate detection, parse-failure reporting, and profile UI integration.
- [x] Quality-focused structured findings with reproducible evidence.
- [x] One-click analysis findings for trends, correlations, and group differences.
- [x] Text entry/import/splitting and category/tag persistence.
- [x] Text corpus profiling and quality checks.
- [x] Virtualized text labeling workspace.

## M3 - Explainable Chart Recommendation

M3 is accepted.

- [x] Deterministic rule scoring.
- [x] Recommendation cards with reasons, warnings, and data budget.
- [x] Tabular and text chart recommendation tests.

## M4 - Chart Workspace And Export

M4 is accepted.

- [x] Local Plotly/WebEngine renderer.
- [x] Downsampling/binning/top-N strategies.
- [x] HTML/SVG/PNG/JSON export.
- [x] External network blocking for chart views.
- [x] Real data preparation for box plots, correlation heatmaps, and text-corpus chart specs.

## M5 - Transforms And Project Persistence

M5 is accepted.

- [x] No-code transforms and aggregation.
  - [x] Safe transform specification, SQL compiler, and DuckDB preview materialization.
  - [x] GUI transform panel with preview/confirmation for lossy operations.
- [x] `.qiproject` save/reopen with source relocation.
  - [x] Versioned `.qiproject` package service with manifest and `project.duckdb`.
  - [x] Safe archive validation plus source evidence validation/relocation.
  - [x] Main-window save/open actions and project state restoration.
  - [x] User-facing source relocation dialog for missing or mismatched source files.
- [x] Processed data and text export.
- [x] Safe category rename/merge/delete audit for text labels.

## M6 - Performance, Hardening, And Release

M6 is active.

- [x] Benchmarks and memory/cache cleanup.
  - [x] Deterministic benchmark harness, `scripts/benchmark.ps1`, and JSON/Markdown report output.
  - [x] Safe stale app-temp cleanup on startup plus explicit derived normalized-cache cleanup policy.
  - [x] Execute representative 100k, 1m, and 5m row benchmark pass and record results.
  - [x] Tune memory/cache behavior based on benchmark findings.
- [x] Accessibility and DPI pass.
  - [x] Primary accessibility metadata for toolbar, welcome, workspace, transform, text-labeling, status, and chart-export controls.
  - [x] DPI-friendly minimum hit-target baseline for primary actions and workflow buttons.
  - [x] Automated UI smoke coverage for accessible names/descriptions and hit-target minimums.
  - [x] Automated visual sweep at 100%, 125%, 150%, and 200% DPI.
- [ ] Security review.
- [ ] Packaged smoke tests, installer, portable ZIP, license notices, and release docs.
