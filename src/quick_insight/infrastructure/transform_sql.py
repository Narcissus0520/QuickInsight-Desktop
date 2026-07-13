from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from quick_insight.domain.models import TransformStep
from quick_insight.infrastructure.sql import quote_identifier


class SourceColumn(Protocol):
    @property
    def name(self) -> str: ...


@dataclass(frozen=True)
class CompiledTransformQuery:
    sql: str
    parameters: tuple[object, ...]


_ALLOWED_CAST_TYPES = frozenset(
    {
        "VARCHAR",
        "DOUBLE",
        "BIGINT",
        "BOOLEAN",
        "TIMESTAMP",
        "DATE",
    }
)
_AGGREGATIONS = {
    "count": "COUNT(*)",
    "count_distinct": "COUNT(DISTINCT {column})",
    "sum": "SUM(CAST({column} AS DOUBLE))",
    "mean": "AVG(CAST({column} AS DOUBLE))",
    "median": "MEDIAN(CAST({column} AS DOUBLE))",
    "min": "MIN({column})",
    "max": "MAX({column})",
    "stddev": "STDDEV_SAMP(CAST({column} AS DOUBLE))",
}


def compile_transform_query(
    source_table: str,
    source_columns: Sequence[SourceColumn],
    steps: tuple[TransformStep, ...],
) -> CompiledTransformQuery:
    current_columns = tuple(column.name for column in source_columns)
    relation = quote_identifier(source_table)
    ctes: list[str] = []
    parameters: list[object] = []
    for index, step in enumerate(steps, start=1):
        cte_name = f"transform_step_{index}"
        relation_sql, current_columns, step_parameters = _compile_step(
            step,
            relation=relation,
            current_columns=current_columns,
        )
        ctes.append(f"{quote_identifier(cte_name)} AS ({relation_sql})")
        parameters.extend(step_parameters)
        relation = quote_identifier(cte_name)
    query = f"SELECT * FROM {relation}"
    if ctes:
        query = "WITH " + ",\n".join(ctes) + "\n" + query
    return CompiledTransformQuery(sql=query, parameters=tuple(parameters))


def _compile_step(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    if step.operation == "select_columns":
        return _compile_select(step, relation=relation, current_columns=current_columns)
    if step.operation == "filter_rows":
        return _compile_filter(step, relation=relation, current_columns=current_columns)
    if step.operation == "sort_rows":
        return _compile_sort(step, relation=relation, current_columns=current_columns)
    if step.operation == "deduplicate_rows":
        return _compile_deduplicate(step, relation=relation, current_columns=current_columns)
    if step.operation == "drop_missing":
        return _compile_drop_missing(step, relation=relation, current_columns=current_columns)
    if step.operation == "fill_missing":
        return _compile_fill_missing(step, relation=relation, current_columns=current_columns)
    if step.operation == "convert_type":
        return _compile_convert_type(step, relation=relation, current_columns=current_columns)
    if step.operation == "group_aggregate":
        return _compile_group_aggregate(step, relation=relation, current_columns=current_columns)
    raise ValueError(f"Unsupported transform operation: {step.operation}")


def _compile_select(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    entries = _list_parameter(step, "columns")
    select_parts: list[str] = []
    output_columns: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("select_columns entries must be objects.")
        source = _string_value(entry.get("source"), "source")
        alias = _string_value(entry.get("alias", source), "alias")
        _require_columns(current_columns, (source,))
        select_parts.append(f"{quote_identifier(source)} AS {quote_identifier(alias)}")
        output_columns.append(alias)
    _require_unique(output_columns)
    return f"SELECT {', '.join(select_parts)} FROM {relation}", tuple(output_columns), ()


def _compile_filter(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    expression = step.parameters.get("expression")
    sql, parameters = _compile_expression(expression, current_columns)
    return f"SELECT * FROM {relation} WHERE {sql}", current_columns, parameters


def _compile_sort(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    entries = _list_parameter(step, "columns")
    order_parts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("sort_rows entries must be objects.")
        column = _string_value(entry.get("column"), "column")
        direction = str(entry.get("direction", "asc")).casefold()
        if direction not in {"asc", "desc"}:
            raise ValueError(f"Unsupported sort direction: {direction}")
        _require_columns(current_columns, (column,))
        order_parts.append(f"{quote_identifier(column)} {direction.upper()} NULLS LAST")
    return (
        f"SELECT * FROM {relation} ORDER BY {', '.join(order_parts)}",
        current_columns,
        (),
    )


def _compile_deduplicate(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    columns = _string_tuple(step.parameters.get("columns", ()))
    if not columns:
        return f"SELECT DISTINCT * FROM {relation}", current_columns, ()
    _require_columns(current_columns, columns)
    partition_sql = ", ".join(quote_identifier(column) for column in columns)
    select_sql = ", ".join(quote_identifier(column) for column in current_columns)
    return (
        f"""
        SELECT {select_sql}
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY {partition_sql} ORDER BY {partition_sql}) AS _qi_row
            FROM {relation}
        )
        WHERE _qi_row = 1
        """,
        current_columns,
        (),
    )


def _compile_drop_missing(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    columns = _string_tuple(step.parameters.get("columns", ()))
    if not columns:
        columns = current_columns
    _require_columns(current_columns, columns)
    predicates = [f"{quote_identifier(column)} IS NOT NULL" for column in columns]
    return f"SELECT * FROM {relation} WHERE {' AND '.join(predicates)}", current_columns, ()


def _compile_fill_missing(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    values = step.parameters.get("values")
    if not isinstance(values, dict) or not values:
        raise ValueError("fill_missing requires a non-empty values object.")
    _require_columns(current_columns, tuple(str(key) for key in values))
    select_parts: list[str] = []
    parameters: list[object] = []
    for column in current_columns:
        if column in values:
            select_parts.append(
                f"COALESCE({quote_identifier(column)}, ?) AS {quote_identifier(column)}"
            )
            parameters.append(values[column])
        else:
            select_parts.append(quote_identifier(column))
    return f"SELECT {', '.join(select_parts)} FROM {relation}", current_columns, tuple(parameters)


def _compile_convert_type(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    conversions = step.parameters.get("columns")
    if not isinstance(conversions, dict) or not conversions:
        raise ValueError("convert_type requires a non-empty columns object.")
    on_error = str(step.parameters.get("on_error", "null")).casefold()
    if on_error not in {"null", "raise"}:
        raise ValueError("convert_type on_error must be 'null' or 'raise'.")
    _require_columns(current_columns, tuple(str(key) for key in conversions))
    select_parts: list[str] = []
    for column in current_columns:
        if column not in conversions:
            select_parts.append(quote_identifier(column))
            continue
        target_type = str(conversions[column]).upper()
        if target_type not in _ALLOWED_CAST_TYPES:
            raise ValueError(f"Unsupported cast target type: {target_type}")
        cast_function = "TRY_CAST" if on_error == "null" else "CAST"
        select_parts.append(
            f"{cast_function}({quote_identifier(column)} AS {target_type}) "
            f"AS {quote_identifier(column)}"
        )
    return f"SELECT {', '.join(select_parts)} FROM {relation}", current_columns, ()


def _compile_group_aggregate(
    step: TransformStep,
    *,
    relation: str,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[object, ...]]:
    group_by = _string_tuple(step.parameters.get("group_by", ()))
    aggregations = _list_parameter(step, "aggregations")
    _require_columns(current_columns, group_by)
    group_select = [quote_identifier(column) for column in group_by]
    output_columns = list(group_by)
    aggregate_select: list[str] = []
    for aggregation in aggregations:
        if not isinstance(aggregation, dict):
            raise ValueError("group_aggregate aggregations must be objects.")
        function = str(aggregation.get("function", "")).casefold()
        template = _AGGREGATIONS.get(function)
        if template is None:
            raise ValueError(f"Unsupported aggregation function: {function}")
        alias = _string_value(aggregation.get("alias"), "alias")
        column = aggregation.get("column")
        if "{column}" in template:
            column_name = _string_value(column, "column")
            _require_columns(current_columns, (column_name,))
            expression = template.format(column=quote_identifier(column_name))
        else:
            expression = template
        aggregate_select.append(f"{expression} AS {quote_identifier(alias)}")
        output_columns.append(alias)
    _require_unique(output_columns)
    select_sql = ", ".join((*group_select, *aggregate_select))
    group_sql = ", ".join(group_select)
    group_clause = f" GROUP BY {group_sql}" if group_select else ""
    order_clause = f" ORDER BY {group_sql}" if group_select else ""
    return (
        f"SELECT {select_sql} FROM {relation}{group_clause}{order_clause}",
        tuple(output_columns),
        (),
    )


def _compile_expression(
    expression: object,
    current_columns: tuple[str, ...],
) -> tuple[str, tuple[object, ...]]:
    if not isinstance(expression, dict):
        raise ValueError("filter_rows expression must be an object.")
    op = str(expression.get("op", "")).casefold()
    if op in {"and", "or"}:
        conditions = expression.get("conditions")
        if not isinstance(conditions, list | tuple) or not conditions:
            raise ValueError(f"{op} expression requires non-empty conditions.")
        compiled = [_compile_expression(condition, current_columns) for condition in conditions]
        joiner = f" {op.upper()} "
        sql = "(" + joiner.join(item[0] for item in compiled) + ")"
        parameters = tuple(parameter for item in compiled for parameter in item[1])
        return sql, parameters
    if op == "not":
        sql, parameters = _compile_expression(expression.get("condition"), current_columns)
        return f"(NOT {sql})", parameters
    column = _string_value(expression.get("column"), "column")
    _require_columns(current_columns, (column,))
    return _compile_predicate(
        column=column,
        operator=op,
        value=expression.get("value"),
    )


def _compile_predicate(
    *,
    column: str,
    operator: str,
    value: object,
) -> tuple[str, tuple[object, ...]]:
    column_sql = quote_identifier(column)
    if operator in {"==", "eq"}:
        return (f"{column_sql} IS NULL", ()) if value is None else (f"{column_sql} = ?", (value,))
    if operator in {"!=", "ne"}:
        return (
            (f"{column_sql} IS NOT NULL", ())
            if value is None
            else (f"{column_sql} <> ?", (value,))
        )
    if operator in {">", ">=", "<", "<="}:
        return f"{column_sql} {operator} ?", (value,)
    if operator == "in":
        values = value if isinstance(value, list | tuple) else ()
        if not values:
            raise ValueError("in expression requires a non-empty value list.")
        placeholders = ", ".join("?" for _ in values)
        return f"{column_sql} IN ({placeholders})", tuple(values)
    if operator == "contains":
        return f"CAST({column_sql} AS VARCHAR) LIKE ? ESCAPE '\\'", (
            f"%{_escape_like(str(value))}%",
        )
    if operator == "starts_with":
        return f"CAST({column_sql} AS VARCHAR) LIKE ? ESCAPE '\\'", (
            f"{_escape_like(str(value))}%",
        )
    if operator == "ends_with":
        return f"CAST({column_sql} AS VARCHAR) LIKE ? ESCAPE '\\'", (
            f"%{_escape_like(str(value))}",
        )
    if operator == "is_null":
        return f"{column_sql} IS NULL", ()
    if operator == "is_not_null":
        return f"{column_sql} IS NOT NULL", ()
    raise ValueError(f"Unsupported filter operator: {operator}")


def _list_parameter(step: TransformStep, key: str) -> list[object]:
    value = step.parameters.get(key)
    if not isinstance(value, list | tuple) or not value:
        raise ValueError(f"{step.operation} requires non-empty {key}.")
    return list(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError("Expected a list of strings.")
    return tuple(_string_value(item, "column") for item in value)


def _string_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    return value.strip()


def _require_columns(available_columns: tuple[str, ...], required_columns: tuple[str, ...]) -> None:
    missing = [column for column in required_columns if column not in available_columns]
    if missing:
        raise ValueError(f"Unknown column(s): {', '.join(missing)}")


def _require_unique(columns: list[str]) -> None:
    duplicates = sorted({column for column in columns if columns.count(column) > 1})
    if duplicates:
        raise ValueError(f"Duplicate output column(s): {', '.join(duplicates)}")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
