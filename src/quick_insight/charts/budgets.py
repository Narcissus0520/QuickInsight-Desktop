from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartBudget:
    chart_family: str
    target_points: int
    strategy: str


DEFAULT_BUDGETS: tuple[ChartBudget, ...] = (
    ChartBudget("line_area", 20_000, "time_window_or_lttb_downsample"),
    ChartBudget("scatter", 50_000, "raw_until_budget_then_sample"),
    ChartBudget("scatter_webgl", 200_000, "explicit_sampling_required"),
    ChartBudget("category", 30, "top_n_with_other"),
)
