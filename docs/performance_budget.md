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

Full P0 performance acceptance still requires running the 100k/1m/5m profile on
the target Windows machine and recording the resulting report path and findings.
