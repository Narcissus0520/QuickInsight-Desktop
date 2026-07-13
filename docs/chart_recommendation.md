# Chart Recommendation

P0 chart recommendation is deterministic, explainable, and testable. The current M3
slice implements rule scoring in `quick_insight.charts.recommendation` and
workspace recommendation cards in the Qt shell. Actual Plotly/WebEngine rendering
and chart export remain M4 work.

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
warnings, aggregation, data budget, and score breakdown. The generate/edit actions
are intentionally guarded with a Chinese future-feature error until the M4 chart
workspace connects a renderer and editable chart specifications.
