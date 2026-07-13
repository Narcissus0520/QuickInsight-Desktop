from __future__ import annotations

from PySide6.QtWidgets import QWidget

DEFAULT_CONTROL_MIN_HEIGHT = 32
DEFAULT_ACTION_MIN_WIDTH = 96


def describe_widget(
    widget: QWidget,
    *,
    name: str,
    description: str = "",
    tooltip: str | None = None,
) -> None:
    widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
    if tooltip is not None:
        widget.setToolTip(tooltip)


def ensure_hit_target(
    widget: QWidget,
    *,
    min_width: int | None = None,
    min_height: int = DEFAULT_CONTROL_MIN_HEIGHT,
) -> None:
    if widget.minimumHeight() < min_height:
        widget.setMinimumHeight(min_height)
    if min_width is not None and widget.minimumWidth() < min_width:
        widget.setMinimumWidth(min_width)
