"""The table primitive and its four row styles.

Row data comes from a named provider; this module only lays it out. Column
positions resolve against the current region, so a table nested inside a
container positions correctly without knowing it is nested.
"""

from decimal import Decimal

from PIL import ImageDraw

from generators.common import (
    Font,
    draw_fitted_left,
    draw_fitted_right,
    draw_separator_line,
    draw_text_left,
    draw_text_right,
    fit_text,
    fmt_amount,
    load_font,
)
from generators.exporters.geometry import BoxRecorder
from generators.layout_budgets import field_budget
from generators.layout_dsl.context import RenderContext
from generators.layout_dsl.primitives_text import resolve_role
from generators.layout_dsl.providers import get_provider

_ABSENT = "NOT_FOUND"


class TableError(RuntimeError):
    """Raised when a table block cannot resolve the geometry it needs to render."""


def column_x(column: dict, ctx: RenderContext) -> int:
    """Resolve a column's anchor x-coordinate against the current region.

    Args:
        column: The column spec, carrying `x` or `x_right`.
        ctx: Render context supplying the region.

    Returns:
        The absolute pixel x: an anchor's left edge for `align: left`, or its
        right edge for `align: right`.
    """
    if "x" in column:
        return ctx.region.x + int(column["x"])
    return ctx.region.right + int(column["x_right"])


def _resolve_row_height(block: dict, ctx: RenderContext) -> int:
    """Resolve the table's row height from the block, falling back to the layout.

    Args:
        block: The `table` block, which may carry its own `row_height`.
        ctx: Render context supplying the layout.

    Returns:
        The row height in pixels.

    Raises:
        TableError: If neither the block nor the layout defines `row_height`.
    """
    if "row_height" in block:
        return int(block["row_height"])
    if "row_height" in ctx.layout:
        return int(ctx.layout["row_height"])
    raise TableError(
        "Table cannot resolve a row height.\n"
        "  What:     neither the table block nor the layout defines row_height.\n"
        f"  Where:    {ctx.layout_path} -> {ctx.layout_id} (a table block)\n"
        "  Expected: row_height: <int px> on the layout, or on the table block "
        "itself, e.g. {type: table, row_height: 60, ...}.\n"
        "  Recover:  add row_height to the layout (config/layouts/*.yml), or set "
        "it on this table block if it needs a value other than the layout's."
    )


def _cell_text(row: dict, key: str) -> str:
    """Render one cell's value as display text."""
    value = row.get(key, "")
    if isinstance(value, Decimal):
        return fmt_amount(value)
    text = str(value)
    return "" if text == _ABSENT else text


def draw_table(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a table's header and rows.

    Args:
        block: The `table` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.

    Raises:
        TableError: If no row height is available from the block or layout.
    """
    style = block.get("row_style", "plain")
    columns = block["columns"]
    row_height = _resolve_row_height(block, ctx)
    body_size = resolve_role(ctx.layout, "body")
    rows = get_provider(block["rows"])(ctx.entry, block.get("params", {}))
    total_real = sum(1 for row in rows if not row.get("synthetic"))

    if block.get("header", True):
        y = _draw_header(columns, ctx, y, size=body_size, style=style, row_height=row_height)

    index = 0
    previous_date = None
    for row in rows:
        synthetic = bool(row.get("synthetic"))
        if style == "grouped" and not synthetic and row.get("date") != previous_date:
            if previous_date is not None:
                y += 10  # Gap between date groups, matching the legacy renderers.
            draw_text_left(
                ctx.draw, str(row.get("date", "")), ctx.region.x, y, load_font(body_size, bold=True)
            )
            previous_date = row.get("date")
            y += row_height

        y = _draw_row(
            row,
            columns,
            ctx,
            y,
            size=body_size,
            style=style,
            row_height=row_height,
            index=None if synthetic else index,
            is_last=(not synthetic and index == total_real - 1),
        )
        if not synthetic:
            index += 1

    return y


def _draw_header(
    columns: list, ctx: RenderContext, y: int, *, size: int, style: str, row_height: int
) -> int:
    """Draw the column-header row in the table's style."""
    font = load_font(size, bold=True)
    if style == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, y, color="black")
        y += 12

    for column in columns:
        x = column_x(column, ctx)
        if column.get("align") == "right":
            draw_text_right(ctx.draw, column["label"], x_right=x, y=y, font=font)
        else:
            draw_text_left(ctx.draw, column["label"], x, y, font)

    y += row_height
    if style == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, y, color="black")
        y += 16
    return y


def _row_line_count(row: dict, columns: list, ctx: RenderContext, *, size: int) -> int:
    """Return how many lines this row's tallest budgeted cell wraps to.

    Mirrors the legacy bank renderers, which size every row from the
    transaction description's wrap result — the only cell that can span
    multiple lines — so a wrapped description pushes every following row
    down by the same amount in both renderers.
    """
    lines = 1
    for column in columns:
        budget_name = column.get("budget")
        if budget_name is None:
            continue
        text = _cell_text(row, column["key"])
        if not text:
            continue
        budget = field_budget(ctx.layout, ctx.layout_id, budget_name, layout_path=ctx.layout_path)
        result = fit_text(
            text,
            width=budget["width"],
            fit=budget["fit"],
            min_font=budget["min_font"],
            max_lines=budget["max_lines"],
            nominal_size=size,
        )
        lines = max(lines, len(result.lines))
    return lines


def _draw_row(
    row: dict,
    columns: list,
    ctx: RenderContext,
    y: int,
    *,
    size: int,
    style: str,
    row_height: int,
    index: int | None,
    is_last: bool,
) -> int:
    """Draw one row; `index` is None for synthetic rows, which are not recorded.

    `is_last` marks the final REAL (non-synthetic) row, which is where a
    column's `last_row_field` — if any — additionally records unindexed
    geometry, matching legacy renderers that record a closing balance once.
    """
    font = load_font(size)
    bottom = y + row_height * _row_line_count(row, columns, ctx, size=size)

    for column in columns:
        x = column_x(column, ctx)
        text = _cell_text(row, column["key"])
        if not text:
            continue

        right = column.get("align") == "right"
        budget = None
        budget_name = column.get("budget")
        if budget_name is not None:
            budget = field_budget(ctx.layout, ctx.layout_id, budget_name, layout_path=ctx.layout_path)

        field = column.get("field")
        record_field = f"{field}[{index}]" if field is not None and index is not None else None
        recorder = ctx.recorder if index is not None else None
        _draw_cell(
            ctx.draw,
            text,
            x,
            y,
            right=right,
            budget=budget,
            size=size,
            row_height=row_height,
            font=font,
            recorder=recorder,
            field=record_field,
        )

        last_row_field = column.get("last_row_field")
        if last_row_field is not None and is_last and ctx.recorder is not None:
            # Redraw the identical cell — same text, same coordinates, same fit —
            # purely to reuse the tested measurement logic in draw_text_*/
            # draw_fitted_* for the second, unindexed record. Pixels are
            # unchanged: this draws over itself.
            _draw_cell(
                ctx.draw,
                text,
                x,
                y,
                right=right,
                budget=budget,
                size=size,
                row_height=row_height,
                font=font,
                recorder=ctx.recorder,
                field=last_row_field,
            )

    if style == "bordered":
        ctx.draw.rectangle([(ctx.region.x, y), (ctx.region.right, bottom)], outline="#999999")
    elif style == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, bottom, color="#CCCCCC")

    return bottom


def _draw_cell(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    *,
    right: bool,
    budget: dict | None,
    size: int,
    row_height: int,
    font: Font,
    recorder: BoxRecorder | None,
    field: str | None,
) -> None:
    """Draw one cell, dispatching on alignment and whether it has a fit budget."""
    if budget is not None:
        if right:
            draw_fitted_right(
                draw,
                text,
                x,
                y,
                budget=budget,
                nominal_size=size,
                line_spacing=row_height,
                recorder=recorder,
                field=field,
            )
        else:
            draw_fitted_left(
                draw,
                text,
                x,
                y,
                budget=budget,
                nominal_size=size,
                line_spacing=row_height,
                recorder=recorder,
                field=field,
            )
    elif right:
        draw_text_right(draw, text, x_right=x, y=y, font=font, recorder=recorder, field=field)
    else:
        draw_text_left(draw, text, x, y, font, recorder=recorder, field=field)
