# Architecture

The application uses a layered package under `src/quick_insight/`.

- `domain`: pure typed models, enums, and rules; no PySide6 imports.
- `application`: use-case level primitives such as user-facing errors and jobs; no SQL or widget logic in M0.
- `infrastructure`: app paths, settings, logging, future DuckDB/import/persistence adapters.
- `charts`: chart recommendation, budgets, specs, and rendering adapters.
- `ui`: Qt Widgets windows, pages, themes, models, and presenters.
- `resources`: icons, local web assets, translations, and bundled samples.

M0 deliberately keeps data import, DuckDB repositories, chart rendering, and project persistence out of the shell. Future milestones must keep UI handlers thin and route data work through application services and infrastructure adapters.

## Dependency Decisions

- Runtime target is CPython 3.13 x64.
- GUI is PySide6 Qt Widgets.
- DuckDB, Polars, PyArrow, and Qt WebEngine are reserved for upcoming milestones and locked now so environment validation starts early.
- The app has no telemetry or remote asset loading.
- `requirements.lock` pins direct and resolved dependencies for Windows x64 CPython 3.13; refresh it from a valid 3.13 environment before release.
