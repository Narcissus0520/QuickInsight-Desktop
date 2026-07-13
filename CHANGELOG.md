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
- Packaging, charting, transforms, text labeling workspace, and project persistence remain future milestones.
