# Chart Recommendation

P0 chart recommendation will be deterministic, explainable, and testable.

M0 only records the planned budget constants in `quick_insight.charts.budgets`; no recommendation engine or chart generation is implemented yet.

Future implementation must preserve these rules:

- No time field means no time trend recommendation.
- Identifier fields are not treated as ordinary categories without explicit user choice.
- Donut charts are low priority above six categories and avoided for high-cardinality data.
- Every recommendation explains fields, aggregation, warnings, approximation, and data budget.
