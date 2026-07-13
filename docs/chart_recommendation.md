# Chart Recommendation

P0 chart recommendation is deterministic, explainable, and testable. M3 implemented
rule scoring in `quick_insight.charts.recommendation` and workspace recommendation
cards in the Qt shell. The first M4 slice adds an offline Plotly/WebEngine renderer
preview. M4 connects tabular and text recommendations to DuckDB-backed prepared
chart datasets; chart export supports self-contained HTML, figure/config JSON,
SVG, and PNG.

Scoring uses the repository contract's 100-point breakdown:

- Field and semantic compatibility: 40.
- Analysis intent match: 25.
- Cardinality suitability: 15.
- Data-quality suitability: 10.
- Performance/readability: 10.

Implemented rules:

- No time field means no line or area time trend recommendation.
- Identifier fields are not treated as ordinary categories without explicit user choice.
- Donut charts are generated only for small category counts, at most six categories.
- Categories above 30 values receive Top N plus Other warnings.
- Numeric pairs above the raw scatter budget prefer density heatmaps.
- Multiple numeric fields can produce a correlation heatmap with a readable field limit.
- Text corpus profiles can recommend category counts, classification status,
  source-category heatmaps, keyword ranking, category-keyword heatmaps, and
  tag co-occurrence heatmaps.
- Every recommendation records fields, aggregation, warnings, approximation state,
  score breakdown, export strategy, and data budget.

Workspace cards show the recommendation title, score, field mappings, reasons,
warnings, aggregation, data budget, and score breakdown. The generate action now
opens the chart workspace. For supported tabular recommendations it prepares real
DuckDB aggregates or samples before rendering through Plotly Python and local
Plotly.js. Supported strategies currently include Top N plus Other category
aggregation, time-window mean downsampling, deterministic scatter sampling,
histogram bins, 2D density bins, categorical cross-tab aggregation, grouped box
quantiles, and Pearson correlation matrices. Text recommendations prepare
category counts, classification status, source-category heatmaps, keyword bars,
category-keyword heatmaps, and tag co-occurrence heatmaps from persisted local
text tables. The edit action remains guarded until editable chart specifications
are implemented.

Chart export writes self-contained interactive HTML and versioned JSON directly
from the prepared `PlotlyChartDocument`. SVG and PNG export use local Plotly.js
`toImage` inside the chart `QWebEngineView`; SVG export reports a warning when a
WebGL trace may prevent a fully vector result.

Chart rendering remains offline-only. The HTML template uses a restrictive CSP,
the WebEngine view disables local-content access to remote and file URLs, and the
Qt request interceptor allows only `about`, `blob`, `data`, and `qrc` schemes.
Blocked external/file/script requests are recorded in the chart view so runtime
behavior can be tested instead of only inferred from static HTML.
