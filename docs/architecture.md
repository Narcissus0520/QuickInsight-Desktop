# Architecture

The application uses a layered package under `src/quick_insight/`.

- `domain`: pure typed models, enums, and rules; no PySide6 imports.
- `application`: use-case level primitives such as user-facing errors, jobs, imports, profiling, and structured findings; no widget logic.
- `infrastructure`: app paths, settings, logging, DuckDB workspace/query adapters, tabular import helpers, and local cache support.
- `charts`: chart recommendation, budgets, specs, and rendering adapters.
- `ui`: Qt Widgets windows, pages, themes, models, and presenters.
- `resources`: icons, local web assets, translations, and bundled samples.

The UI keeps handlers thin and routes data work through application services and infrastructure adapters. DuckDB SQL stays centralized in `infrastructure.workspace`, where identifiers are quoted and values are parameterized. M1 added confirmed tabular imports, normalized Parquet cache writing, and background paged preview. M2 profiling currently uses full-scan DuckDB statistics for semantic inference, quality checks, trend/correlation/group-difference analysis, reproducible `AnalysisFinding` objects, and a background overview page after import. M2 text corpus ingestion uses `application.text_corpus` for preview/splitting and stores records, categories, and tags in DuckDB text tables. Text corpus profiling lives in `application.text_profiling`: it reads persisted text records through the workspace adapter, produces privacy-conscious hashes for duplicate evidence instead of full text snippets, records tokenization/normalization choices, and presents quality findings through the same `DatasetProfile` model as tabular data. Text labeling lives in `application.text_labeling` plus `TextRecordTableModel`: the model uses paged background reads for a virtualized `QTableView`, while record edits, inline category creation, bulk category/tag updates, and undo restoration are persisted through the workspace adapter. M3 chart recommendation scoring lives in `charts.recommendation`, consumes `DatasetProfile`, and produces deterministic `ChartRecommendation` objects without constructing Qt widgets or querying source data directly. M4 chart rendering begins in `charts.rendering` and `ui.chart_view`: Plotly Python builds preview figure JSON, an offline HTML template embeds local Plotly.js from the pinned Plotly package, and `QWebEngineView` renders inside a chart profile with CSP and URL interception. Recommendation-card generate actions open this renderer preview, while real DuckDB-backed chart data preparation remains a separate charts/application concern.

## Dependency Decisions

- Runtime target is CPython 3.13 x64.
- GUI is PySide6 Qt Widgets.
- DuckDB is the local query/storage engine for confirmed imports, preview paging, and profiling statistics.
- Polars/PyArrow handle Excel/Parquet preview and normalized cache exchange.
- Qt WebEngine is used for the M4 chart workspace. Chart views use an offline profile, local Plotly.js, and no remote assets.
- Plotly is pinned as a runtime dependency so figure/config JSON and local Plotly.js come from a reproducible package.
- The app has no telemetry or remote asset loading.
- `requirements.lock` pins direct and resolved dependencies for Windows x64 CPython 3.13; refresh it from a valid 3.13 environment before release.
