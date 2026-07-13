# Performance Budget

M0 does not process large datasets. It establishes these forward constraints:

- GUI widgets must not own full large datasets.
- Preview will use a paged `QAbstractTableModel` backed by DuckDB.
- Long work must run through a cancellable background job protocol.
- Chart rendering must respect visible point budgets before sending data to Plotly/WebEngine.
- Benchmarks will generate representative datasets at test time rather than committing giant fixtures.

Default future chart budgets are defined in `quick_insight.charts.budgets`.
