from __future__ import annotations

from dataclasses import dataclass

from quick_insight.application.errors import UserFacingError
from quick_insight.application.jobs import JobContext
from quick_insight.charts import PlotlyChartDocument, build_prepared_document
from quick_insight.domain.models import ChartRecommendation, PreparedChartDataset
from quick_insight.infrastructure.workspace import WorkspaceColumn, WorkspaceDatabase


@dataclass(frozen=True)
class TabularChartPreparationOptions:
    line_target_points: int = 20_000
    scatter_target_points: int = 50_000
    category_limit: int = 30
    histogram_bins: int = 30
    density_x_bins: int = 50
    density_y_bins: int = 50
    crosstab_axis_limit: int = 15


class TabularChartPreparationService:
    def __init__(
        self,
        workspace: WorkspaceDatabase,
        options: TabularChartPreparationOptions | None = None,
    ) -> None:
        self._workspace = workspace
        self._options = options or TabularChartPreparationOptions()

    def prepare(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
        *,
        context: JobContext | None = None,
    ) -> PlotlyChartDocument:
        chart_type = recommendation.spec.chart_type
        columns = {column.name: column for column in self._workspace.columns(table_name)}
        _progress(context, 10, "正在检查图表字段")
        if chart_type in {"line", "area"}:
            prepared = self._prepare_time_series(table_name, recommendation, columns)
        elif chart_type == "bar":
            prepared = self._prepare_bar(table_name, recommendation, columns)
        elif chart_type == "histogram":
            prepared = self._prepare_histogram(table_name, recommendation, columns)
        elif chart_type == "scatter":
            prepared = self._prepare_scatter(table_name, recommendation, columns)
        elif chart_type == "density_heatmap":
            prepared = self._prepare_density_heatmap(table_name, recommendation, columns)
        elif chart_type == "donut":
            prepared = self._prepare_donut(table_name, recommendation, columns)
        elif chart_type in {"crosstab_heatmap", "stacked_bar"}:
            prepared = self._prepare_crosstab(table_name, recommendation, columns)
        else:
            raise _unsupported_chart_type(chart_type)
        _progress(context, 90, "正在生成 Plotly 图表配置")
        return build_prepared_document(recommendation, prepared)

    def _prepare_time_series(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
        columns: dict[str, WorkspaceColumn],
    ) -> PreparedChartDataset:
        time_column = _required_column(columns, recommendation.spec.mappings, "x")
        numeric_column = _required_column(columns, recommendation.spec.mappings, "y")
        return self._workspace.chart_time_series(
            table_name,
            time_column,
            numeric_column,
            target_points=_target_points(
                recommendation,
                self._options.line_target_points,
            ),
        )

    def _prepare_bar(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
        columns: dict[str, WorkspaceColumn],
    ) -> PreparedChartDataset:
        category_column = _required_column(columns, recommendation.spec.mappings, "x", "category")
        numeric_column = _required_column(columns, recommendation.spec.mappings, "y", "value")
        return self._workspace.chart_category_numeric_top_n(
            table_name,
            category_column,
            numeric_column,
            limit=_category_limit(recommendation, self._options.category_limit),
        )

    def _prepare_histogram(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
        columns: dict[str, WorkspaceColumn],
    ) -> PreparedChartDataset:
        numeric_column = _required_column(columns, recommendation.spec.mappings, "x")
        return self._workspace.chart_histogram_bins(
            table_name,
            numeric_column,
            bins=self._options.histogram_bins,
        )

    def _prepare_scatter(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
        columns: dict[str, WorkspaceColumn],
    ) -> PreparedChartDataset:
        x_column = _required_column(columns, recommendation.spec.mappings, "x")
        y_column = _required_column(columns, recommendation.spec.mappings, "y")
        return self._workspace.chart_scatter_sample(
            table_name,
            x_column,
            y_column,
            target_points=_target_points(
                recommendation,
                self._options.scatter_target_points,
            ),
        )

    def _prepare_density_heatmap(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
        columns: dict[str, WorkspaceColumn],
    ) -> PreparedChartDataset:
        x_column = _required_column(columns, recommendation.spec.mappings, "x")
        y_column = _required_column(columns, recommendation.spec.mappings, "y")
        return self._workspace.chart_density_bins(
            table_name,
            x_column,
            y_column,
            x_bins=self._options.density_x_bins,
            y_bins=self._options.density_y_bins,
        )

    def _prepare_donut(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
        columns: dict[str, WorkspaceColumn],
    ) -> PreparedChartDataset:
        category_column = _required_column(columns, recommendation.spec.mappings, "category", "x")
        return self._workspace.chart_category_count_top_n(
            table_name,
            category_column,
            limit=_category_limit(recommendation, self._options.category_limit),
        )

    def _prepare_crosstab(
        self,
        table_name: str,
        recommendation: ChartRecommendation,
        columns: dict[str, WorkspaceColumn],
    ) -> PreparedChartDataset:
        x_column = _required_column(columns, recommendation.spec.mappings, "x")
        y_column = _required_column(columns, recommendation.spec.mappings, "y", "color")
        return self._workspace.chart_categorical_heatmap_top_n(
            table_name,
            x_column,
            y_column,
            x_limit=self._options.crosstab_axis_limit,
            y_limit=self._options.crosstab_axis_limit,
        )


def _progress(context: JobContext | None, percent: int, message_zh: str) -> None:
    if context is not None:
        context.progress(percent, message_zh)


def _target_points(recommendation: ChartRecommendation, default: int) -> int:
    value = recommendation.data_budget.get("target_points")
    if isinstance(value, int) and value > 0:
        return value
    return default


def _category_limit(recommendation: ChartRecommendation, default: int) -> int:
    value = recommendation.data_budget.get("target_points")
    if isinstance(value, int) and value > 0:
        return min(value, default)
    return default


def _required_column(
    columns: dict[str, WorkspaceColumn],
    mappings: dict[str, str],
    primary_role: str,
    fallback_role: str | None = None,
) -> WorkspaceColumn:
    column_name = mappings.get(primary_role)
    if column_name is None and fallback_role is not None:
        column_name = mappings.get(fallback_role)
    if column_name is None:
        raise UserFacingError(
            code="CHART_FIELD_MAPPING_MISSING",
            title_zh="图表字段映射不完整",
            message_zh=f"当前推荐缺少 {primary_role} 字段映射。",
            next_action_zh="请先选择另一条推荐，后续映射编辑功能会允许手动补全字段。",
            technical_detail=f"mappings={mappings!r}",
        )
    column = columns.get(column_name)
    if column is None:
        raise UserFacingError(
            code="CHART_FIELD_NOT_FOUND",
            title_zh="图表字段不存在",
            message_zh=f"字段 {column_name} 不在当前数据表中。",
            next_action_zh="请重新导入数据或选择仍然存在的字段推荐。",
            technical_detail=f"available_columns={tuple(columns)}; mappings={mappings!r}",
        )
    return column


def _unsupported_chart_type(chart_type: str) -> UserFacingError:
    return UserFacingError(
        code="CHART_TYPE_NOT_PREPARED",
        title_zh="图表数据准备尚未支持",
        message_zh=f"当前切片还没有接入 {chart_type} 的真实数据准备。",
        next_action_zh="请选择柱状图、折线图、面积图、直方图、散点图、热图或环形图推荐。",
        technical_detail=f"chart_type={chart_type}",
    )
