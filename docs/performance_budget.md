# Performance Budget

The current application can import, preview, profile, recommend charts, and render
prepared tabular Plotly charts. Real chart data preparation enforces these
constraints before dataset-derived chart data is sent to Plotly/WebEngine:

- GUI widgets must not own full large datasets.
- Preview will use a paged `QAbstractTableModel` backed by DuckDB.
- Long work must run through a cancellable background job protocol.
- Chart rendering must respect visible point budgets before sending real data to Plotly/WebEngine.
- Benchmarks will generate representative datasets at test time rather than committing giant fixtures.
- Startup cleanup removes stale files/directories under the application temp directory only. Derived normalized Parquet cache cleanup is explicit and age-gated because projects may still reference recent derived cache paths.

Default chart budgets are defined in `quick_insight.charts.budgets`. Implemented
M4 strategies are:

- `top_n_with_other` for category counts and category/numeric means.
- `time_window_mean` for line/area charts over the visible point budget.
- `uniform_sample` for oversized scatter charts.
- `histogram_bins` for single numeric distributions.
- `density_2d_bins` for very large numeric pair views.
- `categorical_top_n_crosstab` for categorical heatmap and stacked-bar data.

Every prepared dataset records original rows, rendered rows, method, parameters,
approximation state, and schema version.

## Benchmark Harness

M6 adds a deterministic tabular benchmark runner:

```powershell
.\scripts\benchmark.ps1 -Rows 100000
.\scripts\benchmark.ps1 -Profile P0
```

The smoke/default profile is intentionally smaller for local validation. The P0
profile generates 100k, 1m, and 5m row CSV datasets under `build/benchmarks`
without committing generated data. Reports are emitted as JSON and Markdown and
record:

- machine and Python details;
- data shape and generated source size;
- elapsed milliseconds per operation;
- `tracemalloc` Python allocation peak memory per operation;
- query/operation description;
- rendered points for preview/chart-preparation steps.

Latest local P0 run after CSV preview tuning:

- Report: `build/benchmarks/p0-reports/benchmark-report-20260713T121823Z.json`
  and `.md`.
- Machine: Windows 10, CPython 3.13.14 x64, 6 logical CPUs.
- 5m-row generated CSV source size: 309,343,518 bytes.
- 5m-row preview: 16.183 ms and 157,986 bytes Python allocation peak.
- 5m-row import plus normalized Parquet cache: 11,325.179 ms.
- 5m-row paged preview fetch: 29.646 ms, 200 rendered rows.
- 5m-row full DuckDB profile: 11,633.988 ms.
- 5m-row chart preparation: 125.855 ms, 4 rendered points via `top_n_with_other`.

The previous P0 run (`benchmark-report-20260713T121140Z.json`) showed 5m-row
CSV preview at 1,306,727,599 bytes peak because `_read_sample` used
`Path.read_text(... )[:8192]`. M6 changed CSV preview to read a bounded sample
from the text stream; the 5m preview peak dropped to 157,986 bytes.
