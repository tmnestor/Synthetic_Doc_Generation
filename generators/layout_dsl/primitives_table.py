"""The table primitive and its four row styles.

Row data comes from a named provider; this module only lays it out. Column
positions resolve against the current region, so a table nested inside a
container positions correctly without knowing it is nested.
"""

from decimal import Decimal

from generators.common import (
    draw_fitted_left,
    draw_separator_line,
    draw_text_left,
    draw_text_right,
    fmt_amount,
    load_font,
)
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

    if block.get("header", True):
        y = _draw_header(columns, ctx, y, size=body_size, style=style, row_height=row_height)

    index = 0
    previous_date = None
    for row in rows:
        if style == "grouped" and not row.get("synthetic") and row.get("date") != previous_date:
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
            index=None if row.get("synthetic") else index,
        )
        if not row.get("synthetic"):
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
) -> int:
    """Draw one row; `index` is None for synthetic rows, which are not recorded."""
    font = load_font(size)
    bottom = y + row_height

    for column in columns:
        x = column_x(column, ctx)
        text = _cell_text(row, column["key"])
        if not text:
            continue

        budget_name = column.get("budget")
        if budget_name is not None and column.get("align") != "right":
            field = column.get("field")
            draw_fitted_left(
                ctx.draw,
                text,
                x,
                y,
                budget=field_budget(ctx.layout, ctx.layout_id, budget_name, layout_path=ctx.layout_path),
                nominal_size=size,
                line_spacing=row_height,
                recorder=ctx.recorder if index is not None else None,
                field=f"{field}[{index}]" if field is not None and index is not None else None,
            )
        elif column.get("align") == "right":
            draw_text_right(ctx.draw, text, x_right=x, y=y, font=font)
        else:
            draw_text_left(ctx.draw, text, x, y, font)

    if style == "bordered":
        ctx.draw.rectangle([(ctx.region.x, y), (ctx.region.right, bottom)], outline="#999999")
    elif style == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, bottom, color="#CCCCCC")

    return bottom
