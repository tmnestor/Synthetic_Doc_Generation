"""Text-bearing primitives: text, pair, block, rule, spacer.

Each takes (block, ctx, y) and returns the advanced y-cursor, matching the
convention the existing renderers already use.
"""

from typing import Any

from generators.common import draw_separator_line, load_font
from generators.layout_dsl.binding import interpolate
from generators.layout_dsl.context import RenderContext
from generators.layout_dsl.defaults import resolve_param

# Public: schema.py imports this as the single source of truth for validating
# a `text` block's `align:` key, so a typo (e.g. "centre") fails at validate
# time rather than silently left-aligning (the pre-typo-check default here).
ALIGNMENTS = ("left", "center", "right")


def _resolve(block: dict, ctx: RenderContext, param: str, *, block_key: str | None = None) -> Any:
    """Resolve one parameter honouring a block's own key before the layout default.

    `resolve_param`'s single `key` argument does double duty as both the
    block's own key and the layout `defaults:` key. Where those differ --
    `PARAMETER_DEFAULTS` namespaces a key a primitive shares with another
    (e.g. banner's `role:` maps to the `banner_role` default, since a bare
    `role` default could not simultaneously be "body" for text/pair/block
    and "header" for banner) -- this shims the block's own value under the
    namespaced name first, so a per-block override still wins exactly as it
    did before this parameter had a layout-level default to fall back to.

    Typed `Any`, not `object` (`resolve_param`'s own return type): a block's
    values were untyped `dict` values before this resolution existed, and
    callers already cast the ones that need it (`int(...)`, `bool(...)`)
    exactly as they did against the bare `.get()` call this replaces.

    Args:
        block: The block dict, whose own `block_key` wins if present.
        ctx: Render context supplying the layout and its diagnostics.
        param: The `PARAMETER_DEFAULTS` name, used against the layout's
            `defaults:` mapping.
        block_key: The block's own literal YAML key for this value, if it
            differs from `param`. Defaults to `param` itself.

    Returns:
        The block's value if it carries `block_key`, otherwise the layout
        default for `param`.
    """
    block_key = param if block_key is None else block_key
    shimmed = {param: block[block_key]} if block_key in block else block
    return resolve_param(shimmed, ctx.layout, param, layout_id=ctx.layout_id, layout_path=ctx.layout_path)


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


def line_height(size: int) -> int:
    """Return the vertical advance for a font size."""
    return int(size * 1.4)


def _draw_line(
    ctx: RenderContext, text: str, y: int, *, size: int, align: str, color: str, bold: bool = False
) -> tuple[int, int]:
    """Draw one line honouring alignment; return (left, right) pixel extent."""
    font = load_font(size, bold=bold)
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


def draw_text_block(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a single line of text.

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

    Args:
        block: The `text` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor (unchanged if the block was suppressed).
    """
    size = resolve_role(ctx.layout, _resolve(block, ctx, "role"))
    if "from_layout" in block:
        text = str(ctx.layout[block["from_layout"]])
    else:
        text = interpolate(block["content"], ctx.entry["fields"])

    suppress_key = block.get("suppress_if_equals")
    if suppress_key is not None and (not text or text == str(ctx.layout.get(suppress_key))):
        return y

    bold = bool(_resolve(block, ctx, "bold"))
    left, right = _draw_line(
        ctx,
        text,
        y,
        size=size,
        align=_resolve(block, ctx, "align"),
        color=_resolve(block, ctx, "color"),
        bold=bold,
    )
    end = y + line_height(size)  # Flow advance: unrelated to the recorded box below.
    field = block.get("field")
    if ctx.recorder is not None and field is not None:
        # Ink extent, not the line-height advance `end` -- matches draw_pair
        # and four of common.py's five text recorders (draw_text_left/right/
        # center, capture_label_prefixed_value); the advance box is 1.43-
        # 1.70x too tall for a single line, which systematically depresses
        # IoU against a localisation benchmark's ground truth.
        bbox = load_font(size, bold=bold).getbbox(text)
        text_height = int(bbox[3] - bbox[1])
        ctx.recorder.record(field, (left, y, right, y + text_height))
    return end


def draw_pair(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a label and value on one line, separated by a colon and gap.

    Args:
        block: The `pair` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    size = resolve_role(ctx.layout, _resolve(block, ctx, "role"))
    label = interpolate(block["label"], ctx.entry["fields"])
    value = interpolate(block["value"], ctx.entry["fields"])
    text = f"{label}: {value}"
    left, _ = _draw_line(ctx, text, y, size=size, align="left", color=_resolve(block, ctx, "color"))
    end = y + line_height(size)
    field = block.get("field")
    if ctx.recorder is not None and field is not None:
        # Record the value's own extent, not the label's.
        font = load_font(size)
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
    size = resolve_role(ctx.layout, _resolve(block, ctx, "role"))
    color = _resolve(block, ctx, "color")
    heading = block.get("heading")
    if heading is not None:
        _draw_line(
            ctx,
            interpolate(heading, ctx.entry["fields"]),
            y,
            size=size,
            align="left",
            color=color,
            bold=True,
        )
        y += line_height(size)
    for line in block["lines"]:
        _draw_line(ctx, interpolate(line, ctx.entry["fields"]), y, size=size, align="left", color=color)
        y += line_height(size)
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
    y += int(_resolve(block, ctx, "rule_pad_above", block_key="pad_above"))
    thickness = int(_resolve(block, ctx, "rule_thickness", block_key="thickness"))
    draw_separator_line(
        ctx.draw, ctx.region.x, ctx.region.right, y, color=_resolve(block, ctx, "color"), width=thickness
    )
    y += thickness + int(_resolve(block, ctx, "rule_pad_below", block_key="pad_below"))
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
    return y + int(_resolve(block, ctx, "spacer_height", block_key="height"))


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

    size = resolve_role(ctx.layout, _resolve(block, ctx, "banner_role", block_key="role"))
    font = load_font(size, bold=bool(_resolve(block, ctx, "bold")))
    if "from_layout" in block:
        text = str(ctx.layout[block["from_layout"]])
    else:
        text = interpolate(block["content"], ctx.entry["fields"])
    ctx.draw.text(
        (ctx.region.x, int(_resolve(block, ctx, "banner_text_y", block_key="text_y"))),
        text,
        font=font,
        fill=_resolve(block, ctx, "banner_text_color", block_key="text_color"),
    )
    return y
