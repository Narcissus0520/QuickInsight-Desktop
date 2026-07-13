# Performance Budget

The current application can import, preview, profile, recommend charts, and render
prepared tabular Plotly charts. Real chart data preparation enforces these
constraints before dataset-derived chart data is sent to Plotly/WebEngine:

- GUI widgets must not own full large datasets.
- Preview will use a paged `QAbstractTableModel` backed by DuckDB.
- Long work must run through a cancellable background job protocol.
- Chart rendering must respect visible point budgets before sending real data to Plotly/WebEngine.
- Benchmarks will generate representative datasets at test time rather than committing giant fixtures.

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
