# Performance Budget

The current application can import, preview, profile, recommend charts, and render
a guarded Plotly preview. Real chart data preparation must still enforce these
constraints before any dataset-derived chart is sent to Plotly/WebEngine:

- GUI widgets must not own full large datasets.
- Preview will use a paged `QAbstractTableModel` backed by DuckDB.
- Long work must run through a cancellable background job protocol.
- Chart rendering must respect visible point budgets before sending real data to Plotly/WebEngine.
- Benchmarks will generate representative datasets at test time rather than committing giant fixtures.

Default chart budgets are defined in `quick_insight.charts.budgets`. The first M4
renderer slice uses a tiny static preview and records `renderer_preview_static`;
it is not a substitute for the upcoming DuckDB-backed preparation strategies.
