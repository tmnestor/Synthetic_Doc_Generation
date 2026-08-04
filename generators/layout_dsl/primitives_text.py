"""Text-bearing primitives: text, pair, block, rule, spacer.

Each takes (block, ctx, y) and returns the advanced y-cursor, matching the
convention the existing renderers already use.
"""

from generators.common import (
    Font,
    draw_fitted_center,
    draw_fitted_left,
    draw_fitted_right,
    draw_separator_line,
    load_font,
)
from generators.layout_budgets import field_budget
from generators.layout_dsl.binding import interpolate
from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.defaults import DefaultsError, resolve_param

# Public: schema.py imports this as the single source of truth for validating
# a `text` block's `align:` key, so a typo (e.g. "centre") fails at validate
# time rather than silently left-aligning (the pre-typo-check default here).
ALIGNMENTS = ("left", "center", "right")


class RoleError(RuntimeError):
    """Raised when a block names a typographic role the layout does not define."""


def resolve_role(layout: dict, role: str) -> int:
    """Return the font size a role maps to.

    Args:
        layout: The resolved layout dict, carrying a `font_sizes` mapping.
        role: The role name, e.g. "body".

    Returns:
        The font size in points.

    Raises:
        RoleError: If the layout defines no such role.
    """
    sizes = layout.get("font_sizes")
    if not isinstance(sizes, dict) or role not in sizes:
        available = sorted(sizes) if isinstance(sizes, dict) else []
        raise RoleError(
            "Unknown typographic role.\n"
            f"  What:     role '{role}' is not defined by this layout.\n"
            f"  Where:    config/layouts/*.yml -> <layout>.font_sizes.{role}\n"
            f"  Expected: one of {available}, e.g. font_sizes: {{body: 32}}.\n"
            f"  Recover:  add '{role}:' under the layout's font_sizes, or use "
            f"an existing role."
        )
    return int(sizes[role])


def line_advance(layout: dict, block: dict, *, layout_id: str, layout_path: str) -> int:
    """Return the vertical advance for one line, in pixels.

    Replaces the former `line_height(size) = int(size * 1.4)`. That ratio
    was a function of the drawing block's own *role* font size -- CBA's
    header logo line advanced by a different amount than its footer ABN
    block. A single flat number per layout cannot express that (a first
    attempt at this tried exactly that and needed 29 hand-computed
    per-block overrides across the 8 bank layouts to stay pixel-identical
    -- see the plan's fix-round-1 note). Receipts also contradict the old
    ratio outright: `receipts.yml` declares `line_height: 20` against
    `font_size: 18`, a ratio of 1.11, not 1.4.

    So a layout's `defaults.line_advance` is a mapping of role -> pixels
    (e.g. `{header: 61, body: 44, footer: 25}`), and this resolves the
    block's own role first, then looks that role up in the mapping. A block
    may instead carry its own bare-integer `line_advance:` to override the
    per-role mapping entirely, for the rare line that is not simply "this
    role's usual advance" -- `resolve_param`'s block-key-wins-over-layout
    resolution already gives us that for free: if the block supplies a
    plain int, that int is what comes back below, and the `isinstance`
    check falls through the role lookup entirely.

    Args:
        layout: The resolved layout dict, carrying a `defaults:` mapping.
        block: The block requesting the advance; its own `line_advance` key,
            if present, wins over the layout default (and if it is a bare
            int, wins outright, without any role lookup).
        layout_id: Layout id, used in the diagnostic.
        layout_path: Path to the layout YAML, used in the diagnostic.

    Returns:
        The vertical advance in pixels.

    Raises:
        DefaultsError: If the block's role is absent from a layout-level
            `line_advance` mapping (and the block carries no override of
            its own).
    """
    value = resolve_param(block, layout, "line_advance", layout_id=layout_id, layout_path=layout_path)
    if not isinstance(value, dict):
        return int(value)

    role = str(resolve_param(block, layout, "role", layout_id=layout_id, layout_path=layout_path))
    if role not in value:
        raise DefaultsError(
            "Missing line_advance for role.\n"
            f"  What:     layout '{layout_id}' declares line_advance for role(s) "
            f"{sorted(value)}, but this block's role is '{role}'.\n"
            f"  Where:    {layout_path} -> {layout_id}.defaults.line_advance.{role}\n"
            "  Expected: a defaults.line_advance mapping covering every role this "
            f"layout draws, e.g.\n"
            f"              defaults:\n"
            f"                line_advance:\n"
            f"                  {role}: <int(font_sizes.{role} * 1.4)>\n"
            f"  Recover:  add '{role}:' under {layout_id}.defaults.line_advance, or "
            "set 'line_advance: <int>' directly on the block if it needs a value "
            "unrelated to any role."
        )
    return int(value[role])


def font_for(
    layout: dict, block: dict, size: int, *, bold: bool = False, layout_id: str, layout_path: str
) -> Font:
    """Load a font honouring the layout's declared face.

    Every `load_font` call in the primitives used to omit `mono=`, silently
    defaulting to the sans face even for layouts (e.g. receipts) declaring
    `font_family: monospace`. This resolves `mono` the same way every other
    primitive parameter resolves -- block key, then layout `defaults:`.

    Args:
        layout: The resolved layout dict, carrying a `defaults:` mapping.
        block: The block requesting the font; its own `mono` key, if
            present, wins over the layout default.
        size: Font size in points.
        bold: Whether to load the bold weight.
        layout_id: Layout id, used in the diagnostic.
        layout_path: Path to the layout YAML, used in the diagnostic.

    Returns:
        The loaded font.
    """
    mono = bool(resolve_param(block, layout, "mono", layout_id=layout_id, layout_path=layout_path))
    return load_font(size, mono=mono, bold=bold)


def _draw_line(
    ctx: RenderContext, text: str, y: int, *, font: Font, align: str, color: str
) -> tuple[int, int]:
    """Draw one line honouring alignment; return (left, right) pixel extent."""
    bbox = font.getbbox(text)
    text_width = int(bbox[2] - bbox[0])
    if align == "right":
        x = ctx.region.right - text_width
    elif align == "center":
        x = ctx.region.x + (ctx.region.width - text_width) // 2
    else:
        x = ctx.region.x
    ctx.draw.text((x, y), text, font=font, fill=color)
    return x, x + text_width


def _draw_fitted_text(
    block: dict,
    ctx: RenderContext,
    y: int,
    *,
    text: str,
    size: int,
    bold: bool,
    align: str,
    color: str,
    budget_name: str,
) -> int:
    """Draw `text` through its declared fit budget, dispatching on alignment.

    Shared by `draw_text_block` and `draw_pair` (for the value only -- see
    there). The `draw_fitted_*` helpers in `generators.common` already return
    the y *below* whatever they wrapped to, so that return value is the
    advance here, not a fresh `line_advance()` computation -- a wrapped
    budget consumes more vertical space than one line, and the whole point of
    a budget is that the caller does not have to know in advance how much.

    `draw_fitted_center` centres within a canvas width, not a region: a
    receipt centres its header within the full page width (see
    `receipt.py`'s legacy `draw_fitted_center(draw, text, y, width, ...)`
    call, where `width` is the page width, not a margin-inset region).
    `ctx.region.x * 2 + ctx.region.width` reconstructs that page width from a
    symmetric margin -- region.x is the margin, and region.width is the page
    width minus twice that same margin, so doubling region.x and adding it
    back gives the page width without the region ever needing to know it.

    Args:
        block: The block requesting the budget; its own `mono`, if present,
            wins over the layout default (the same resolution `font_for`
            uses, preserved here since these helpers build their own font
            internally rather than accepting a pre-built one).
        ctx: Render context.
        y: Current y-cursor.
        text: The already-interpolated string to fit and draw.
        size: The resolved role's nominal font size.
        bold: Whether to draw bold.
        align: "left", "center", or "right".
        color: Fill colour.
        budget_name: The `field_budgets` key to resolve.

    Returns:
        The y below the fitted (possibly wrapped) text.

    Raises:
        LayoutBudgetError: If `budget_name` is not a valid budget in this
            layout's `field_budgets`.
    """
    budget = field_budget(ctx.layout, ctx.layout_id, budget_name, layout_path=ctx.layout_path)
    mono = bool(
        resolve_param(block, ctx.layout, "mono", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    spacing = line_advance(ctx.layout, block, layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    field = block.get("field")
    if align == "right":
        return draw_fitted_right(
            ctx.draw,
            text,
            ctx.region.right,
            y,
            budget=budget,
            nominal_size=size,
            mono=mono,
            bold=bold,
            fill=color,
            line_spacing=spacing,
            recorder=ctx.recorder,
            field=field,
        )
    if align == "center":
        canvas_width = ctx.region.x * 2 + ctx.region.width
        return draw_fitted_center(
            ctx.draw,
            text,
            y,
            canvas_width,
            budget=budget,
            nominal_size=size,
            mono=mono,
            bold=bold,
            fill=color,
            line_spacing=spacing,
            recorder=ctx.recorder,
            field=field,
        )
    return draw_fitted_left(
        ctx.draw,
        text,
        ctx.region.x,
        y,
        budget=budget,
        nominal_size=size,
        mono=mono,
        bold=bold,
        fill=color,
        line_spacing=spacing,
        recorder=ctx.recorder,
        field=field,
    )


def draw_text_block(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a single line of text, or a fitted (possibly wrapped) block.

    `content` and `from_layout` are mutually exclusive alternatives for
    *what* to draw (enforced at validate time, in schema.py's
    `_validate_block`); `suppress_if_equals` separately controls *whether*
    to draw at all. Together they let a letterhead/supplier pair share one
    block vocabulary instead of hand-written Python (mirrors the legacy
    renderers' `_draw_supplier_line`):

    - `content: '{FIELD}'` interpolates an entry field, as usual.
    - `from_layout: <layout_key>` reads that key directly off the layout
      dict instead — e.g. `from_layout: logo_text` — so the drawn brand
      genuinely comes from the layout, not a Python or YAML literal that
      can drift from it. Unlike `content`, this is not a template: the
      layout's value is used verbatim, with no `{FIELD}` substitution.
    - `suppress_if_equals: <layout_key>` skips drawing (and recording)
      entirely when the resolved text is empty or equals that layout key's
      value — the content supplier line is redundant whenever it already
      matches the letterhead already on the page.

    `budget: <FIELD_BUDGET_NAME>` opts the block into a fit budget (see
    `_draw_fitted_text`) instead of the plain, always-one-line path below --
    the field may shrink, wrap onto up to `max_lines`, or both, per its
    `field_budgets` entry. A block without `budget:` renders exactly as
    before; this is an additive, opt-in engine capability.

    Args:
        block: The `text` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor (unchanged if the block was suppressed).
    """
    role = str(
        resolve_param(block, ctx.layout, "role", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    size = resolve_role(ctx.layout, role)
    if "from_layout" in block:
        text = str(ctx.layout[block["from_layout"]])
    else:
        text = interpolate(block["content"], ctx.entry["fields"])

    suppress_key = block.get("suppress_if_equals")
    if suppress_key is not None and (not text or text == str(ctx.layout.get(suppress_key))):
        return y

    bold = bool(
        resolve_param(block, ctx.layout, "bold", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    align = str(
        resolve_param(block, ctx.layout, "align", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    color = str(
        resolve_param(block, ctx.layout, "color", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )

    budget_name = block.get("budget")
    if budget_name is not None:
        return _draw_fitted_text(
            block,
            ctx,
            y,
            text=text,
            size=size,
            bold=bold,
            align=align,
            color=color,
            budget_name=budget_name,
        )

    font = font_for(
        ctx.layout, block, size, bold=bold, layout_id=ctx.layout_id, layout_path=ctx.layout_path
    )
    left, right = _draw_line(ctx, text, y, font=font, align=align, color=color)
    end = y + line_advance(
        ctx.layout, block, layout_id=ctx.layout_id, layout_path=ctx.layout_path
    )  # Flow advance: unrelated to the recorded box below.
    field = block.get("field")
    if ctx.recorder is not None and field is not None:
        # Ink extent, not the line-advance `end` -- matches draw_pair and
        # four of common.py's five text recorders (draw_text_left/right/
        # center, capture_label_prefixed_value); the advance box is 1.43-
        # 1.70x too tall for a single line, which systematically depresses
        # IoU against a localisation benchmark's ground truth.
        bbox = font.getbbox(text)
        text_height = int(bbox[3] - bbox[1])
        ctx.recorder.record(field, (left, y, right, y + text_height))
    return end


def draw_pair(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a label and value on one line, separated by a colon and gap.

    `budget: <FIELD_BUDGET_NAME>` fits the *value* only -- the label always
    draws in full, unshrunk and unwrapped, exactly as it does today. This
    forks the drawing itself, not just the recording: the unbudgeted path
    below draws `"{label}: {value}"` as a single string in one `draw.text`
    call (so the two stay pixel-identical to before when no budget is
    given), while the budgeted path draws the label first and then fits the
    value into the space after it via `_draw_fitted_text`, since a fit
    budget must know the value's own text to shrink or wrap it -- it cannot
    operate on a combined "label: value" string without also constraining
    the label.

    Args:
        block: The `pair` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.

    Raises:
        LayoutBudgetError: If `budget` is present but not a valid budget in
            this layout's `field_budgets`.
    """
    role = str(
        resolve_param(block, ctx.layout, "role", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    size = resolve_role(ctx.layout, role)
    label = interpolate(block["label"], ctx.entry["fields"])
    value = interpolate(block["value"], ctx.entry["fields"])
    color = str(
        resolve_param(block, ctx.layout, "color", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    font = font_for(ctx.layout, block, size, layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    field = block.get("field")

    budget_name = block.get("budget")
    if budget_name is not None:
        prefix = f"{label}: "
        ctx.draw.text((ctx.region.x, y), prefix, font=font, fill=color)
        label_width = int(ctx.draw.textlength(prefix, font=font))
        value_ctx = ctx.within(Region(x=ctx.region.x + label_width, width=ctx.region.width - label_width))
        return _draw_fitted_text(
            block,
            value_ctx,
            y,
            text=value,
            size=size,
            bold=False,
            align="left",
            color=color,
            budget_name=budget_name,
        )

    text = f"{label}: {value}"
    left, _ = _draw_line(ctx, text, y, font=font, align="left", color=color)
    end = y + line_advance(ctx.layout, block, layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    if ctx.recorder is not None and field is not None:
        # Record the value's own extent, not the label's.
        label_width = int(ctx.draw.textlength(f"{label}: ", font=font))
        value_bbox = font.getbbox(value)
        value_width = int(value_bbox[2] - value_bbox[0])
        value_height = int(value_bbox[3] - value_bbox[1])
        ctx.recorder.record(
            field, (left + label_width, y, left + label_width + value_width, y + value_height)
        )
    return end


def draw_block(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a group of lines, optionally under a heading.

    Args:
        block: The `block` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    role = str(
        resolve_param(block, ctx.layout, "role", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    size = resolve_role(ctx.layout, role)
    color = str(
        resolve_param(block, ctx.layout, "color", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    advance = line_advance(ctx.layout, block, layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    heading = block.get("heading")
    if heading is not None:
        heading_font = font_for(
            ctx.layout, block, size, bold=True, layout_id=ctx.layout_id, layout_path=ctx.layout_path
        )
        _draw_line(
            ctx,
            interpolate(heading, ctx.entry["fields"]),
            y,
            font=heading_font,
            align="left",
            color=color,
        )
        y += advance
    line_font = font_for(ctx.layout, block, size, layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    for line in block["lines"]:
        _draw_line(
            ctx, interpolate(line, ctx.entry["fields"]), y, font=line_font, align="left", color=color
        )
        y += advance
    return y


def draw_rule(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a horizontal separator across the region.

    Args:
        block: The `rule` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    y += int(
        resolve_param(
            block,
            ctx.layout,
            "rule_pad_above",
            layout_id=ctx.layout_id,
            layout_path=ctx.layout_path,
            block_key="pad_above",
        )
    )
    thickness = int(
        resolve_param(
            block,
            ctx.layout,
            "rule_thickness",
            layout_id=ctx.layout_id,
            layout_path=ctx.layout_path,
            block_key="thickness",
        )
    )
    color = str(
        resolve_param(block, ctx.layout, "color", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, y, color=color, width=thickness)
    y += thickness + int(
        resolve_param(
            block,
            ctx.layout,
            "rule_pad_below",
            layout_id=ctx.layout_id,
            layout_path=ctx.layout_path,
            block_key="pad_below",
        )
    )
    return y


def draw_spacer(block: dict, ctx: RenderContext, y: int) -> int:
    """Advance the cursor by a fixed height.

    Args:
        block: The `spacer` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    return y + int(
        resolve_param(
            block,
            ctx.layout,
            "spacer_height",
            layout_id=ctx.layout_id,
            layout_path=ctx.layout_path,
            block_key="height",
        )
    )


def draw_banner(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a full-bleed colour bar at the very top of the page.

    Every other primitive draws inside `ctx.region` — inset from the page
    edge by the layout's margin. A masthead like ANZ's blue header bar does
    not: it spans edge-to-edge, ignoring the margin entirely. This is the one
    primitive allowed to paint outside the region, and it always paints at
    the fixed page position `(0, 0)` regardless of the cursor, matching the
    legacy renderer it replaces, which draws it before establishing any
    cursor-driven layout and then jumps straight to a hardcoded y for the
    content below. It leaves the y-cursor untouched for the same reason — a
    `spacer` placed after it in the layout's `body:` reaches whichever y the
    content below the bar actually starts at.

    Args:
        block: The `banner` block, carrying `height`, `color`, and either
            `content` or `from_layout` (mutually exclusive — see
            `draw_text_block`), plus optional `text_color` (default white),
            `role` (font-size role, default "header"), `bold` (default
            False), and `text_y` (the text's absolute y from the page top,
            default 0).
        ctx: Render context.
        y: Current y-cursor, returned unchanged.

    Returns:
        `y`, unchanged — this primitive never advances the flow.
    """
    width = int(ctx.layout["page_dimensions"]["width"])
    height = int(block["height"])
    ctx.draw.rectangle([(0, 0), (width, height)], fill=block["color"])

    role = str(
        resolve_param(
            block,
            ctx.layout,
            "banner_role",
            layout_id=ctx.layout_id,
            layout_path=ctx.layout_path,
            block_key="role",
        )
    )
    size = resolve_role(ctx.layout, role)
    bold = bool(
        resolve_param(block, ctx.layout, "bold", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
    )
    font = font_for(
        ctx.layout, block, size, bold=bold, layout_id=ctx.layout_id, layout_path=ctx.layout_path
    )
    if "from_layout" in block:
        text = str(ctx.layout[block["from_layout"]])
    else:
        text = interpolate(block["content"], ctx.entry["fields"])
    text_y = int(
        resolve_param(
            block,
            ctx.layout,
            "banner_text_y",
            layout_id=ctx.layout_id,
            layout_path=ctx.layout_path,
            block_key="text_y",
        )
    )
    text_color = str(
        resolve_param(
            block,
            ctx.layout,
            "banner_text_color",
            layout_id=ctx.layout_id,
            layout_path=ctx.layout_path,
            block_key="text_color",
        )
    )
    ctx.draw.text((ctx.region.x, text_y), text, font=font, fill=text_color)
    return y
