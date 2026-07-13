# QuickInsight Desktop — Repository Instructions

## 0. Purpose and operating contract

This file is the persistent repository contract for Codex and other coding agents working on `Narcissus0520/QuickInsight-Desktop`.

QuickInsight Desktop is a Windows-first, offline-first desktop application for fast analysis of tabular datasets and manually categorized text records. It is not an Excel clone and must not become a general spreadsheet editor. Its primary value is to turn raw data into an understandable profile, explainable analysis recommendations, and interactive high-quality charts with minimal user effort.

Before changing code:

1. Read this file completely.
2. Inspect `git status`, the existing tree, `TASKS.md`, and `docs/project_status.md` when present.
3. Preserve user changes and never overwrite unrelated work.
4. Resume the first incomplete milestone/task; do not recreate completed work.
5. Make the smallest coherent production-quality change, then test it.
6. Update task/status documentation with factual results.
7. Never claim a feature, test, package, or benchmark succeeded unless it was actually executed and verified.

Explicit user requests may reprioritize scope but do not silently remove safety, privacy, testing, or non-destructive requirements.

## 1. Product mission

Core workflow: `import/paste -> confirm -> profile -> choose intent -> receive explainable recommendations -> generate/refine interactive charts -> save/export`.

The application must be:

- **Local and private:** data stays on the computer by default; no telemetry or implicit upload.
- **Novice-friendly:** users should not need formulas, SQL, Python, pivot-table knowledge, or chart expertise.
- **Explainable:** recommendations and findings must state what fields, calculations, samples, and approximations were used.
- **Scalable:** large datasets must not be copied into GUI widgets or sent unaggregated to the chart renderer.
- **Reproducible:** filters, transforms, analysis settings, and chart specifications must be serializable and restorable.
- **Non-destructive:** imported source files are read-only by default.
- **Windows-distributable:** the final user must not install Python, Node.js, Chrome, DuckDB, or other runtimes.
- **Visually professional:** modern, restrained, clear, high-density when useful, and free of decorative clutter.

Default UI language is Simplified Chinese; code/docs/tests may use English. Errors need clear Chinese guidance plus expandable technical detail.

## 2. Target users and primary use cases

Primary users are Excel newcomers, engineers analyzing logs/experiments/sensors/GNSS/time series/business tables, and users manually categorizing statements extracted from documents or search results.

The application has two first-class dataset kinds:

```text
TABULAR      Structured rows and columns from CSV/TSV/Excel/Parquet.
TEXT_CORPUS  Independent text records created by paste/import and manually categorized.
```

Both modes are first-class; reuse infrastructure without forcing one model into the other.

## 3. Supported platform and delivery definition

Target runtime:

- Windows 10 and Windows 11, x64.
- Development baseline: CPython 3.13 x64.
- DPI scales: 100%, 125%, 150%, and 200%.
- Minimum supported workspace: 1366 x 768; layouts should remain usable on larger displays.

“Environment-independent EXE” means a self-contained Windows application installed or unpacked by the user. Do not sacrifice reliability merely to force every dependency into one physical executable. Preferred release artifacts:

```text
dist/
  QuickInsight-Setup-x64.exe
  QuickInsight-portable-x64.zip
  SHA256SUMS.txt
  release-notes.md
  third-party-licenses/
```

One-file EXE is optional; installer and portable reliability come first.

## 4. Product scope

### P0 — required for the first complete release

- Full Windows GUI: welcome/import/workspace/settings/status, light/dark themes, background jobs, cancellation, and readable errors.
- Tabular import: CSV, TSV, XLSX, XLS, XLSB, Parquet; text input/import: direct entry, paste/clipboard, TXT, Markdown, JSONL; both require preview/confirmation.
- Virtualized preview, profiling, quality checks, one-click analysis, no-code transforms/aggregation, and explainable chart recommendations.
- Offline interactive Plotly charts plus HTML/SVG/PNG/JSON export; processed tabular and text-data export.
- Text labeling with one primary category plus tags; project save/restore, source validation/relocation, and full persistence of internal text.
- Tests, Windows build/package scripts, packaged smoke tests, checksums, and license inventory.

### P1/P2 — only after P0

P1: batch import, joins, calculated columns, dashboards, undo/redo, templates, resampling, reports, saved themes, localization. P2: natural-language analysis, opt-in models, semantic deduplication/clustering, database/plugin/streaming extensions.

### Explicit non-goals for P0

- Full spreadsheet cell editing, Excel formula compatibility, VBA/macros, cloud accounts, collaboration, mandatory AI/LLM use, arbitrary user code execution, 3D chart spectacle, or default dual-axis charts.
- Do not implement speculative P1/P2 systems while required P0 behavior remains incomplete or untested.

## 5. Mandatory technology choices

Use these choices unless a concrete blocker is documented and approved:

- **Language:** Python 3.13 x64 with type annotations.
- **GUI:** PySide6, Qt Widgets, QSS design tokens, and Qt WebEngine for charts.
- **Table view:** `QTableView` plus custom `QAbstractTableModel`; never use `QTableWidget` to hold the full dataset.
- **Query/storage engine:** DuckDB for scan, query, filter, sort, aggregation, paging, local project tables, and export.
- **Data-frame/import engine:** Polars for Excel ingestion, fast conversions, and Arrow-compatible exchange. Prefer the Calamine/fastexcel path for XLSX/XLSB/XLS; keep OpenPyXL only as a documented fallback.
- **Charts:** Plotly Python produces figure/config JSON; a bundled local `plotly.min.js` renders in `QWebEngineView`.
- **Testing/tooling:** pytest, pytest-qt, ruff, and pyright or mypy. Use deterministic fixtures and generated benchmark data.
- **Packaging:** prefer `pyside6-deploy`/Nuitka, with explicit Qt WebEngine resource verification. An alternative packager requires a documented reason and equivalent validation.
- **Dependency definition:** `pyproject.toml` is authoritative; produce a reproducible lock file and record licenses. Do not use unbounded dependency ranges for releases.

Hard constraints:

- Pandas is not the primary data engine. A narrow compatibility use requires a comment and architecture note.
- Do not depend on a third-party Fluent UI framework in P0.
- Do not use CDN-hosted JavaScript, fonts, icons, or styles.
- Do not require Plotly Cloud, Kaleido, or a user-installed Chrome for core export.
- Do not load arbitrary remote web content in Qt WebEngine.
- Do not use `eval`, `exec`, or an unrestricted expression interpreter.

## 6. Architecture and dependency boundaries

Use a layered package under `src/quick_insight/`:

```text
src/quick_insight/
  main.py
  bootstrap.py
  domain/           Pure models, enums, value objects, rules; no PySide6 imports.
  application/      Use cases/services and ports; orchestrates domain + infrastructure.
  infrastructure/   DuckDB, file importers, cache, persistence, logging, settings.
  charts/           Recommendation rules, data budgets, downsampling, specs, rendering.
  ui/               Windows, pages, dialogs, widgets, Qt models, themes, presenters.
  resources/        Icons, local web assets, translations, bundled samples.
```

Top-level support: `docs/`, `tests/{unit,integration,ui,performance,fixtures}/`, `scripts/`, and `samples/`.

Rules:

- Domain and chart recommendation logic must be testable without constructing a GUI.
- UI event handlers call application services; they do not contain SQL, profiling algorithms, persistence logic, or large transforms.
- DuckDB access is centralized behind repositories/query services.
- Plotly HTML templates and JavaScript bridge code are isolated from business logic.
- Services depend on interfaces/ports where a real alternative exists; avoid ceremonial abstractions with only hypothetical value.
- Use structured result/error types at subsystem boundaries rather than silent `None` returns.
- Keep modules cohesive and reasonably small; do not turn `main.py` or the main window into a service locator.

## 7. Core domain model

At minimum define and evolve these concepts:

```text
DatasetKind: TABULAR | TEXT_CORPUS
AnalysisIntent: AUTO | TREND | COMPARISON | DISTRIBUTION | RELATIONSHIP |
                COMPOSITION | ANOMALY | CORRELATION
ColumnSemanticType: NUMERIC | CATEGORICAL | DATETIME | BOOLEAN | TEXT |
                    LONG_TEXT | IDENTIFIER | GEO_LATITUDE | GEO_LONGITUDE |
                    PRIMARY_CATEGORY | TAG_LIST | SOURCE_REFERENCE | UNKNOWN
```

Required models and minimum content:

- `DatasetHandle`: ID, kind, source/workspace, schema/rows, import options, fingerprint/cache.
- `DatasetProfile`/`ColumnProfile`: summaries; null/distinct metrics; ranges, moments, quantiles/top values; datetime/monotonicity; ID/constant/cardinality/outlier flags; quality and approximation metadata.
- `TextRecord`: ID, content, primary category, tags, source/location, speaker, time, note, timestamps, custom fields; `Category`: ID/name/description/color/timestamps.
- `TransformStep`: versioned/serializable, reversible where practical, never mutating source.
- `AnalysisFinding`: statement plus evidence, method, fields, sample/query, approximation/warnings.
- `ChartSpec`/`ChartRecommendation`: type, mappings, aggregation/filter/style, score/reasons/warnings, field requirements, data budget/export strategy.

Use typed lightweight models; all persisted objects need schema versions and migrations.

## 8. Data import requirements

### Tabular data

The wizard supports drag/drop/picker, format override, CSV/TSV encoding+delimiter detection/manual override, UTF-8/BOM/GB18030/Shift-JIS, quoted multiline fields, Excel sheet/header/type/empty-sheet handling, Parquet metadata preview, progress, cancellation, and actionable errors.

Preferred Excel flow:

`Excel -> Polars/Calamine -> normalized Parquet workspace cache -> DuckDB queries.`

Keep originals read-only; record import options/fingerprint and never silently rebind by filename.

### Text corpus data

Each statement is one `TextRecord`. Support quick entry, batch paste/clipboard, TXT/Markdown/JSONL, split by non-empty line/paragraph/sentence/custom delimiter/or whole input, preview before commit, batch metadata defaults, and visible reversible normalization.

Never irreversibly split, normalize, merge, or overwrite text without preview.

## 9. Query, preview, and transform behavior

The GUI must never own a full copy of a large dataset. It should hold metadata, the active query, current pages, bounded caches, and chart aggregates.

Implement:

- `QAbstractTableModel` backed by paged DuckDB queries.
- Default page size around 200 rows with bounded LRU caching and adjacent-page prefetch.
- Sort/filter/aggregate pushdown into DuckDB.
- Background query execution, stale-result rejection, cancellation, and recovery after errors.
- Debouncing for rapidly changing filters.
- Stable row/record IDs for editing text metadata.

All identifiers must be safely quoted and all values parameterized. The UI must not concatenate raw user values into SQL. User-facing filters are compiled from a restricted typed expression model.

P0 transform operations:

- Select/hide/rename columns.
- Safe type conversion with error policy and preview.
- Single and compound AND/OR filters.
- Sorting and deduplication.
- Drop/fill missing values.
- Group aggregation: count, distinct count, sum, mean, median, min, max, and standard deviation.

Store operations as ordered `TransformStep` objects. Preview before potentially large or lossy operations. Export creates a new file and never overwrites the source by default.

## 10. Profiling and one-click analysis

### Tabular profiling

Generate:

- Row/column count, estimated size, field-type summary, and time range where present.
- Missing values, duplicate rows, constant columns, mixed-type fields, candidate ID columns, high-cardinality categories, and parsing failures.
- Numeric range, quantiles, mean/median/std, distribution and outlier candidates.
- Category top values and concentration.
- Time-series candidates, trend/change candidates, correlation candidates, and meaningful group differences.

Large data may use sampling or approximate functions, but the result must state `approximate=true`, original/sample row counts, method, and parameters.

### Text corpus profiling

Generate:

- Total, categorized, and uncategorized record counts.
- Category, tag, and source counts.
- Text-length distribution.
- Empty, exact-duplicate, extremely short/long, and category-conflict checks.
- Missing-source ratio and possible near-duplicate category names.
- User-specified keyword matches, high-frequency tokens, per-category keyword differences, and basic tag co-occurrence.

Record whether stop words, tokenization, normalization, sampling, or approximation were used. Do not present weak semantic guesses as facts.

### Finding integrity

Findings must come from structured calculations with reproducible provenance. Never fabricate or imply causation; state insufficient evidence plainly.

One-click analysis normally returns 3-8 useful chart recommendations.

## 11. Text labeling workspace

Use one primary category plus zero or more tags per record. Categories are user-defined project data, not source-code enums.

Required: category search/inline creation; safe rename/merge/delete with counts, descriptions, transaction and undo/audit; virtualized searchable/filterable text list; bulk category/tag edits; full record detail editor; keyboard/save-next/undo/optional `1`-`9` shortcuts; crash-safe autosave.

Never create one QWidget per text record.

## 12. Chart recommendation engine

P0 uses a deterministic, explainable, testable rule-scoring engine; no LLM is required.

Suggested score out of 100:

```text
Field/semantic compatibility  40
Analysis-intent match         25
Cardinality suitability       15
Data-quality suitability      10
Performance/readability       10
```

Required chart families:

- Line and area.
- Bar, grouped bar, stacked bar, horizontal ranked bar.
- Scatter.
- Histogram and box plot.
- Heatmap and correlation heatmap.
- Donut only when composition is valid and category count is small.

Text mode also supports category counts, classified/unclassified status, source-category cross-tab, category-over-time, keyword ranking, category-keyword heatmap, and tag co-occurrence heatmap.

Core recommendation rules:

- Datetime + numeric -> trend charts.
- Category + numeric -> bar or box plots depending on intent/distribution.
- Two numeric fields -> scatter; high density -> binned/density alternative.
- One numeric field -> histogram/box.
- Two categorical fields -> cross-tab heatmap or stacked bar.
- Multiple numeric fields -> correlation heatmap, with sensible field limits.
- More than 6 categories -> do not prioritize donut/pie.
- More than 30 categories -> Top N plus “Other”, or prompt for filtering.
- No time field -> never recommend a time trend.
- No category/source -> never recommend category/source analysis.
- Identifier fields should not be treated as ordinary categories without an explicit user decision.
- Word clouds may be decorative secondary output only, never the main analytical result.

Cards show chart, score, fields, reasons, warnings, aggregation, approximation, and generate/edit actions.

Write table-driven unit tests for valid recommendations, invalid combinations, high cardinality, missing data, ID misuse, time fields, and performance degradation.

## 13. Chart data budgets, rendering, and export

Never send millions of raw points to Plotly/WebEngine.

Default rendering budgets:

```text
Line/area       target <= 20,000 visible points
Regular scatter target <= 50,000 points
50k-200k scatter: WebGL plus explicit sampling
>200k scatter   prefer 2D binning/density or aggregate view
Categories      default Top 30, with “Other” where meaningful
```

Implement isolated strategies for time-window aggregation, uniform/random sampling, LTTB or equivalent time-series downsampling, Top N, and 2D binning. Every prepared chart dataset carries:

```text
original_rows, rendered_rows, method, parameters, approximate
```

Rendering requirements:

- Bundle and load local Plotly.js only.
- Use a controlled offline HTML template and a narrow Qt-JavaScript bridge.
- Support zoom, pan, hover, legend toggle, selection when applicable, reset view, and responsive resizing.
- Block external network requests from the chart profile/page.
- Escape data/config inserted into HTML/JavaScript contexts.
- Handle Chinese fonts and Windows DPI correctly.

Export requirements:

- Self-contained interactive HTML.
- SVG and PNG through local Plotly.js `toImage` or a verified equivalent not requiring external Chrome.
- Figure/config JSON with schema version.
- Clear warning when a WebGL trace cannot provide fully vector SVG output.

## 14. Background work, responsiveness, and performance

Use `QThreadPool`/`QRunnable` or another well-tested Qt-compatible worker abstraction. Define a unified job protocol with started, progress, message, completed, failed, and cancelled states.

Run import, Excel conversion, profiling, queries, aggregation, chart preparation, project I/O, and exports outside the GUI thread. Any operation expected to exceed roughly 200 ms should expose a busy/progress state; operations expected to exceed 1 second should be cancelable where the underlying library permits it.

Performance principles:

- No unbounded caches.
- No redundant full-table copies between DuckDB, Polars, Python objects, and Qt.
- Prefer Arrow-compatible transfer.
- Cache normalized Parquet and reusable profile results with source/version invalidation.
- Clean stale temporary workspaces safely on startup/exit.
- Benchmark representative datasets, including 100k, 1m, and 5m rows, without committing giant fixtures.
- Record machine details, data shape, elapsed time, peak memory, query, and rendered points in benchmark reports.

Slow may be acceptable; frozen or memory-explosive is not.

## 15. Project persistence

Use a versioned project format with the extension `.qiproject`. The final format should appear as one user file and may be an atomic ZIP package containing at least:

```text
manifest.json
project.duckdb
chart/config JSON and optional small cached artifacts
```

An extracted working directory is allowed; save atomically via a new package.

Persist:

- Project/app/schema versions and timestamps.
- Dataset definitions, source references, fingerprints, and import options.
- Transform steps, filters, analysis settings/results, chart specs, and layout state.
- All manually entered `TextRecord`, category, tag, source metadata, custom fields, and edit/audit information.

External tabular source data is referenced and not embedded by default. Internal text data must be fully stored. When a source moves, ask the user to relocate it and validate size, modification metadata, and content hash/sample fingerprint; never silently bind the wrong file.

After format release, add migration fixtures.

## 16. Security, privacy, logging, and error handling

Mandatory:

- Offline by default; no telemetry, analytics, upload, or remote assets.
- Explicit opt-in is required for any future network/AI feature.
- Source data read-only; no default overwrite.
- Parameterized SQL and safely quoted identifiers.
- No arbitrary code, macros, scripts, embedded HTML execution, `eval`, or unsafe deserialization.
- Sanitize/escape text inserted into HTML, JSON, logs, filenames, and generated reports.
- Limit archive extraction paths/sizes to prevent traversal or zip bombs.
- Use application-specific config/cache/temp/log directories.
- Rotate logs by size and retain a bounded history.
- Do not log full rows, full text content, secrets, or sensitive field values by default.

Log app/OS/operation/format/size/time and useful stacks without content.

GUI errors need Chinese explanation, next action, and copyable details. Never swallow errors or poison the whole session.

## 17. UI and interaction requirements

Welcome page:

- `导入表格数据`
- `录入文本语句`
- `打开最近项目`
- `打开示例数据`
- Drag-and-drop area

Main workspace uses a three-column structure:

- Left: datasets, sheets/corpora, fields, categories.
- Center: preview, overview, recommendations, chart workspace, or text labeling page.
- Right: filters, field mapping, aggregation, category/record details, and chart style.
- Bottom: row/record count, query time, approximation state, background jobs, and errors.

Analysis-intent labels:

- `自动帮我分析`
- `看数据随时间怎么变化`
- `比较不同类别`
- `查看数据分布`
- `查看两个指标是否有关`
- `查看各类别占比`
- `查找异常数据`
- `查看指标相关性`

Design: centralized color/type/spacing/radius/border/shadow/state tokens; light/dark themes; clear empty/loading/error/disabled states; keyboard focus and tooltips; restrained styling without excessive gradients/glow/animation; test long Chinese names and high DPI.

## 18. Repository files and documentation

Maintain at least:

```text
README.md
AGENTS.md
TASKS.md
CHANGELOG.md
LICENSE
pyproject.toml
requirements.lock or equivalent reproducible lock
.gitignore
docs/product_requirements.md
docs/architecture.md
docs/chart_recommendation.md
docs/performance_budget.md
docs/packaging.md
docs/acceptance_criteria.md
docs/project_status.md
scripts/setup_dev.ps1
scripts/run.ps1
scripts/test.ps1
scripts/build.ps1
scripts/package.ps1
```

`docs/project_status.md` must state current version/milestone, completed work, remaining work, known issues, latest test/build results, and next action. `TASKS.md` is the executable checkbox backlog and must reflect reality. Record material dependency/storage/security/data/packaging/performance decisions in architecture docs or ADRs.

Provide small generated business, sensor, dirty-data, and text samples; generate large benchmarks at test time.

## 19. Testing and acceptance discipline

Test layers:

- **Unit:** inference/profile/text split/categories/query safety/transforms/project serialization/recommendation/downsampling/Top N/chart specs.
- **Integration:** all importers, DuckDB paging/filter/aggregate, cache, project reopen/migration, local chart HTML, exports.
- **UI:** startup/import/navigation/table/recommendations/labeling/progress-cancel/errors.
- **Performance/package:** generated data timings+memory+point budgets, then launch built EXE in isolated Windows, import, chart, exit.

Quality gates for a completed milestone:

1. Relevant tests exist and pass.
2. Ruff and type checking pass for changed production code, or every exception is documented.
3. No placeholder implementation is counted as complete.
4. Error paths and cancellation are exercised where applicable.
5. Documentation and task status match the code.
6. Manual smoke steps and their result are recorded.

Execute tests; never weaken valid tests merely to make CI green.

## 20. Build and release automation

PowerShell scripts must be usable from a fresh Windows checkout:

- `setup_dev.ps1`: verify Python 3.13 x64, create `.venv`, install locked dependencies, and report actionable failures.
- `run.ps1`: start the application from the controlled environment.
- `test.ps1`: run lint, type checks, unit/integration/UI tests, and emit a summary.
- `build.ps1`: clean prior output, run gates, package with pyside6-deploy/Nuitka, verify resources/DLLs/QtWebEngineProcess, launch a smoke test, and write a build report.
- `package.ps1`: create installer/portable artifacts, license inventory, release notes, and SHA-256 sums.

CI includes Windows; packaging success requires launching the built EXE and validating bundled web assets.

## 21. Milestone plan

### M0 — foundation

- Repository/doc structure, `pyproject.toml`, lock strategy, scripts, logging, settings, error model, job abstraction, design tokens, light/dark theme, welcome page, three-column workspace shell, test/CI skeleton, and generated samples.

### M1 — tabular import and virtual preview

- CSV/TSV, Excel, Parquet, import wizard, DuckDB workspace, Parquet cache, dataset models, safe paged table model, background jobs, cancellation, and import errors.

### M2 — profiling, one-click analysis, and text corpus workflow

- Semantic type inference, data-quality/profile services, structured findings, text entry/import/splitting, category/tag persistence, labeling workspace, text profiling, and tests.

### M3 — explainable chart recommendation

- Analysis intents, rule scoring, recommendation reasons/warnings, recommendation cards, text/tabular rules, and exhaustive unit tests.

### M4 — chart workspace and export

- Local Plotly/WebEngine renderer, chart specs, data budgets, downsampling/binning, interaction, network blocking, and HTML/SVG/PNG/JSON export.

### M5 — transforms and project persistence

- No-code transforms, aggregation, operation history foundation, `.qiproject` atomic save/reopen, source relocation, migrations, and processed-data/text exports.

### M6 — performance, hardening, and release

- Benchmarks, memory/cache cleanup, accessibility/DPI pass, security review, packaged smoke tests, installer, portable ZIP, license notices, release documentation, and P0 acceptance review.

Do not start broad next-milestone work while current gates fail.

## 22. Autonomous execution protocol

For every Codex run:

1. Inspect repository state and active instructions.
2. Read `TASKS.md` and `docs/project_status.md`; if absent in an empty repository, initialize them during M0.
3. Select the first incomplete task in the active milestone.
4. State a brief implementation plan in the task response, not in generated code.
5. Implement a coherent vertical slice, including errors and tests.
6. Run the narrowest relevant tests first, then the milestone gates.
7. Self-review the diff for correctness, data loss, privacy, performance, and scope creep.
8. Update `TASKS.md`, `CHANGELOG.md`, and `docs/project_status.md` with exact commands/results.
9. Summarize changed files, behavior, validation, known limitations, and the next task.

Choose and record ordinary defaults. Ask only about destructive behavior, privacy/security, irreversible formats, licensing, or core scope. Never claim background work.

Do not commit/push/open PR or use destructive Git commands unless explicitly requested.

When the user says “继续”, “下一步”, or equivalent, resume the first incomplete task rather than re-planning the whole project.

## 23. Initial bootstrap directive for this repository

On the first run, execute **M0 only** and produce a runnable tested shell.

M0 deliverables:

1. Create required structure, baseline files, accurate docs, and task/status records.
2. Configure Python 3.13, PySide6, pytest/pytest-qt, ruff, type checking, lock strategy, and Windows CI.
3. Build a real launchable PySide6 bootstrap, Chinese welcome page, navigable three-column shell, and working light/dark tokens.
4. Add structured logging, app paths/settings, user error model, and testable job abstraction skeleton.
5. Add deterministic business/sensor/dirty/text sample generators plus unit/UI smoke tests.
6. Run available gates and record exact results in `docs/project_status.md`.

M0 acceptance:

- The app launches through `scripts/run.ps1` on the development machine.
- Welcome and workspace shell are visible and theme switching works.
- No large-data or chart feature is falsely presented as implemented.
- Tests and static checks pass, or a concrete environment blocker is documented with evidence.
- `TASKS.md` clearly identifies M1 as the next milestone after M0 gates pass.

After M0, report and stop unless explicitly authorized to continue.
