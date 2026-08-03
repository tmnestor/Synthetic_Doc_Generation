"""The table primitive and its frame/grouping axes.

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
    fmt_amount,
    load_font,
)
from generators.exporters.geometry import BoxRecorder
from generators.layout_budgets import field_budget
from generators.layout_dsl.context import RenderContext
from generators.layout_dsl.primitives_text import line_height, resolve_role
from generators.layout_dsl.providers import get_provider

_ABSENT = "NOT_FOUND"

# Frames whose header label block is vertically centred within header_height
# rather than pinned to its top: `bordered` draws an outlined box, `filled`
# a solid one, and both need their labels centred inside it, matching the
# legacy Westpac (bordered) and NAB (filled) header bars.
_BOXED_FRAMES = ("bordered", "filled")


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


def _cell_text(row: dict, column: dict) -> str:
    """Render one cell's value as display text.

    A column may set `currency: plain` to drop the `$` prefix `fmt_amount`
    otherwise adds — Westpac's legacy renderer prints amounts as `1,234.56`,
    not `$1,234.56`, and the ground truth the table draws must match the
    bank's real formatting, not just land in the right place. A column may
    also set `currency_suffix` (e.g. NAB's `"Cr"`) to append a fixed suffix
    after the formatted amount — a separate, composable concern from the `$`
    prefix, since a suffix is a per-column display choice, not a property
    `fmt_amount` itself needs to know about.
    """
    value = row.get(column["key"], "")
    if isinstance(value, Decimal):
        text = fmt_amount(value)
        if column.get("currency") == "plain":
            text = text.lstrip("$")
        suffix = column.get("currency_suffix")
        return f"{text} {suffix}" if suffix else text
    text = str(value)
    return "" if text == _ABSENT else text


def draw_table(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a table's header and rows.

    Args:
        block: The `table` block. Two more keys support `grouping:
            dedicated_row`: `group_gap` (default 10px, the gap inserted
            between consecutive date sub-header rows — CBA's real value;
            NAB's legacy renderer inserts none, so NAB's layout sets
            `group_gap: 0`), and `synthetic_row_placement` (default
            `leading`, a provider's synthetic row renders first, before any
            group header — CBA's "Opening Balance"; NAB's "Brought forward"
            instead renders *under* the first date-group header, expressed
            as `synthetic_row_placement: after_first_group_header`).
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.

    Raises:
        TableError: If no row height is available from the block or layout.
    """
    frame = block["frame"]
    grouping = block["grouping"]
    fill_color = block.get("fill_color")
    fill_inset = int(block.get("fill_inset", 0))
    group_gap = int(block.get("group_gap", 10))
    synthetic_after_header = block.get("synthetic_row_placement") == "after_first_group_header"
    label_inset_y = block.get("label_inset_y")
    if label_inset_y is not None:
        label_inset_y = int(label_inset_y)
    columns = block["columns"]
    dividers = block.get("dividers", [])
    row_height = _resolve_row_height(block, ctx)
    body_size = resolve_role(ctx.layout, "body")
    rows = get_provider(block["rows"])(ctx.entry, block.get("params", {}))

    # A leading synthetic row normally renders first, ahead of any group
    # header (CBA's Opening Balance). NAB's Brought-forward row instead
    # belongs *under* the first date-group header, so it is set aside here
    # and spliced in once that header has been drawn, below.
    deferred_synthetic = None
    if synthetic_after_header and rows and rows[0].get("synthetic"):
        deferred_synthetic = rows[0]
        rows = rows[1:]

    if block.get("header", True):
        header_height = int(block["header_height"]) if "header_height" in block else line_height(body_size)
        fill_height = int(block["fill_height"]) if "fill_height" in block else header_height
        y = _draw_header(
            columns,
            ctx,
            y,
            size=body_size,
            frame=frame,
            header_height=header_height,
            fill_height=fill_height,
            dividers=dividers,
            fill_color=fill_color,
            label_inset_y=label_inset_y,
        )

    table_body_start = y
    total_rows = len(rows)
    index = 0
    previous_date = None
    first_row = True
    for position, row in enumerate(rows):
        synthetic = bool(row.get("synthetic"))
        if grouping == "dedicated_row" and not synthetic and row.get("date") != previous_date:
            if previous_date is not None:
                y += group_gap  # Gap between date groups; 0 for NAB, 10 (CBA's real value) by default.
            if frame == "filled":
                ctx.draw.rectangle(
                    [(ctx.region.x, y), (ctx.region.right, y + row_height - fill_inset)], fill=fill_color
                )
            draw_text_left(
                ctx.draw, str(row.get("date", "")), ctx.region.x, y, load_font(body_size, bold=True)
            )
            previous_date = row.get("date")
            y += row_height

            if deferred_synthetic is not None:
                y = _draw_row(
                    deferred_synthetic,
                    columns,
                    ctx,
                    y,
                    size=body_size,
                    frame=frame,
                    grouping=grouping,
                    row_height=row_height,
                    index=None,
                    is_last=False,
                    first_row=first_row,
                    is_new_group=False,
                )
                first_row = False
                deferred_synthetic = None

        is_new_group = not synthetic and row.get("date") != previous_date
        y = _draw_row(
            row,
            columns,
            ctx,
            y,
            size=body_size,
            frame=frame,
            grouping=grouping,
            row_height=row_height,
            index=None if synthetic else index,
            is_last=(position == total_rows - 1),
            first_row=first_row,
            is_new_group=is_new_group,
        )
        if grouping == "inline" and not synthetic:
            previous_date = row.get("date")
        if not synthetic:
            index += 1
        first_row = False

    if frame == "bordered":
        # Mirrors the legacy renderers' one-shot outer box + column dividers,
        # drawn once across the whole table body rather than per row — the
        # header already closed the top edge, so only left/right/bottom and
        # the interior dividers remain.
        ctx.draw.line([(ctx.region.x, table_body_start), (ctx.region.x, y)], fill="black")
        ctx.draw.line([(ctx.region.right, table_body_start), (ctx.region.right, y)], fill="black")
        ctx.draw.line([(ctx.region.x, y), (ctx.region.right, y)], fill="black")
        for divider in dividers:
            dx = column_x(divider, ctx)
            ctx.draw.line([(dx, table_body_start), (dx, y)], fill="black")

    return y


def _draw_header(
    columns: list,
    ctx: RenderContext,
    y: int,
    *,
    size: int,
    frame: str,
    header_height: int,
    fill_height: int,
    dividers: list,
    fill_color: str | None,
    label_inset_y: int | None,
) -> int:
    """Draw the column-header row in the table's frame.

    `header_height` is the label row's own advance — a function of the header
    font's line height, not the data row pitch (`row_height`). The two are
    independent: a table's data rows may be taller or shorter than its single
    header line, and conflating them drifts the header away from wherever the
    legacy renderer being compared against actually puts it.

    The `bordered` frame additionally decorates: a bordered rectangle spans
    the header height and `dividers` cut it into columns, matching the legacy
    Westpac renderer's bordered header. The `filled` frame instead fills a
    rectangle of `fill_height` (defaulting to `header_height`, but settable
    independently — legacy NAB fills a 44px bar and then advances 50px, a gap
    `header_height` alone cannot express) with `fill_color` and draws no
    dividers, matching the legacy NAB renderer's light-blue header bar.

    Both box frames centre their labels vertically within the header rather
    than pinning them to its top by default — the geometry-only equivalence
    harness cannot see this (no field box is recorded for header labels), and
    it would otherwise silently regress to bare text. `label_inset_y`, when
    given, overrides that computed centring with an exact declared offset
    from `y`, for a legacy renderer (like NAB, whose labels sit at `y + 10`
    inside a 44px bar) whose real offset the centring formula does not
    reproduce. A label may contain "\\n" for a legacy-matching multi-line
    header cell (e.g. Westpac's "Date of" / "Transaction"); each line is
    positioned relative to that same start, one `line_height` apart.
    """
    font = load_font(size, bold=True)
    if frame == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, y, color="black")
        y += 12
    elif frame == "bordered":
        ctx.draw.rectangle([(ctx.region.x, y), (ctx.region.right, y + header_height)], outline="black")
        for divider in dividers:
            dx = column_x(divider, ctx)
            ctx.draw.line([(dx, y), (dx, y + header_height)], fill="black")
    elif frame == "filled":
        ctx.draw.rectangle([(ctx.region.x, y), (ctx.region.right, y + fill_height)], fill=fill_color)

    for column in columns:
        x = column_x(column, ctx)
        lines = str(column["label"]).split("\n")
        if label_inset_y is not None:
            start = y + label_inset_y
        elif frame in _BOXED_FRAMES:
            block_height = line_height(size) * len(lines)
            start = y + max(0, (header_height - block_height) // 2)
        else:
            start = y
        for position, text in enumerate(lines):
            line_y = start + position * line_height(size)
            if column.get("align") == "right":
                draw_text_right(ctx.draw, text, x_right=x, y=line_y, font=font)
            else:
                draw_text_left(ctx.draw, text, x, line_y, font)

    y += header_height
    if frame == "ruled":
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
    frame: str,
    grouping: str,
    row_height: int,
    index: int | None,
    is_last: bool,
    first_row: bool = False,
    is_new_group: bool = True,
) -> int:
    """Draw one row; `index` is None for synthetic rows, which are not recorded.

    `is_last` marks the final row in the table's own row list — real or
    synthetic — which is where a column's `last_row_field`, if any,
    additionally records unindexed geometry, matching legacy renderers that
    record a closing balance once. For CBA (a leading synthetic row, or
    none) this is always the final real transaction; for NAB (a *trailing*
    synthetic "Carried forward" row, via `carried_forward` on the provider)
    it is that synthetic row instead, since `last_row_field`'s redraw does
    not gate on `index is not None` the way ordinary `field` recording does.

    `first_row`/`is_new_group` drive the `bordered` frame combined with
    `inline` grouping: plain `bordered` (grouping `none`) draws a divider
    above every row but the first; `bordered` + `inline` draws one only when
    `is_new_group` is true (and blanks the `date` cell otherwise), matching
    the legacy Westpac renderer's date-grouped table, which shows one row per
    transaction — never a dedicated date-only row the way `dedicated_row`
    grouping does for CBA/NAB.

    Cells are drawn first, and `bottom` is derived from the tallest cell's own
    returned advance — the same advance `draw_fitted_left`/`draw_fitted_right`
    already compute while wrapping a budgeted cell — rather than a second,
    separate wrap computation that could drift out of sync with the one the
    draw call actually used. Only then is the row's own decoration (a border
    or rule, which needs the final `bottom`) drawn.
    """
    font = load_font(size)
    bottom = y + row_height  # Floor: every unbudgeted cell is exactly one row tall.

    for column in columns:
        if grouping == "inline" and column["key"] == "date" and not is_new_group:
            continue  # Blank the repeated date cell within a date group.
        x = column_x(column, ctx)
        text = _cell_text(row, column)
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
        cell_bottom = _draw_cell(
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
        bottom = max(bottom, cell_bottom)

        last_row_field = column.get("last_row_field")
        if last_row_field is not None and is_last and ctx.recorder is not None:
            # Redraw the identical cell — same text, same coordinates, same fit —
            # purely to reuse the tested measurement logic in draw_text_*/
            # draw_fitted_* for the second, unindexed record. Pixels are
            # unchanged: this draws over itself, so it cannot change `bottom`.
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

    bottom += _draw_sub_lines(row, columns, ctx, y)

    if frame == "bordered" and not first_row and (grouping != "inline" or is_new_group):
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, y, color="black")
    elif frame == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, bottom, color="#CCCCCC")

    return bottom


def _draw_sub_lines(row: dict, columns: list, ctx: RenderContext, y: int) -> int:
    """Draw each column's sub-line, if it has data this row, and report its height.

    A column may carry `sub_line: {key, role, color, offset_y, height}` to
    render a second line of text beneath its main cell — NAB's dotted-leader
    reference number beneath the transaction description. `key` names the row
    key the text comes from; `role` (default "body") resolves a font size the
    same way any other text primitive does; `offset_y` (default 0) positions
    it as an offset from the row's own start `y` — not the wrapped main
    cell's bottom — matching the legacy renderer, which draws the reference
    line at a fixed offset regardless of how many lines the description
    wrapped to (a legacy quirk, reproduced rather than "fixed", since
    equivalence means matching the renderer being replaced, bugs included).
    `height` is a flat addition to the row's own advance, contributed once
    per row even if more than one column happens to carry a sub_line with
    data (the tallest of them wins, not their sum).

    Args:
        row: The row dict; a sub_line draws only when `row[sub_line["key"]]`
            is present and not the absent-value sentinel.
        columns: The table's column specs.
        ctx: Render context.
        y: The row's own start y, before any wrapping advance.

    Returns:
        The extra height claimed by the tallest sub_line drawn this row (0 if
        no column has a sub_line, or none has data for this row).
    """
    extra = 0
    for column in columns:
        sub_line = column.get("sub_line")
        if sub_line is None:
            continue
        text = str(row.get(sub_line["key"], ""))
        if not text or text == _ABSENT:
            continue
        x = column_x(column, ctx)
        size = resolve_role(ctx.layout, sub_line.get("role", "body"))
        draw_text_left(
            ctx.draw,
            text,
            x,
            y + int(sub_line.get("offset_y", 0)),
            load_font(size),
            fill=sub_line.get("color", "black"),
        )
        extra = max(extra, int(sub_line.get("height", 0)))
    return extra


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
) -> int:
    """Draw one cell, dispatching on alignment and whether it has a fit budget.

    Returns:
        The cell's own bottom y: the wrapped advance from `draw_fitted_left`/
        `draw_fitted_right` for a budgeted cell, or `y + row_height` for an
        unbudgeted (always single-line) cell.
    """
    if budget is not None:
        if right:
            return draw_fitted_right(
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
        return draw_fitted_left(
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
    if right:
        draw_text_right(draw, text, x_right=x, y=y, font=font, recorder=recorder, field=field)
    else:
        draw_text_left(draw, text, x, y, font, recorder=recorder, field=field)
    return y + row_height
