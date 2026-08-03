"""Text-bearing primitives: text, pair, block, rule, spacer.

Each takes (block, ctx, y) and returns the advanced y-cursor, matching the
convention the existing renderers already use.
"""

from generators.common import draw_separator_line, load_font
from generators.layout_dsl.binding import interpolate
from generators.layout_dsl.context import RenderContext

_ALIGNMENTS = ("left", "center", "right")


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

    Args:
        block: The `text` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    size = resolve_role(ctx.layout, block.get("role", "body"))
    text = interpolate(block["content"], ctx.entry["fields"])
    left, right = _draw_line(
        ctx,
        text,
        y,
        size=size,
        align=block.get("align", "left"),
        color=block.get("color", "black"),
    )
    end = y + line_height(size)
    field = block.get("field")
    if ctx.recorder is not None and field is not None:
        ctx.recorder.record(field, (left, y, right, end))
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
    size = resolve_role(ctx.layout, block.get("role", "body"))
    label = interpolate(block["label"], ctx.entry["fields"])
    value = interpolate(block["value"], ctx.entry["fields"])
    text = f"{label}: {value}"
    left, right = _draw_line(ctx, text, y, size=size, align="left", color=block.get("color", "black"))
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
    size = resolve_role(ctx.layout, block.get("role", "body"))
    color = block.get("color", "black")
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
    y += int(block.get("pad_above", 0))
    thickness = int(block.get("thickness", 1))
    draw_separator_line(
        ctx.draw, ctx.region.x, ctx.region.right, y, color=block.get("color", "black"), width=thickness
    )
    y += thickness + int(block.get("pad_below", 0))
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
    return y + int(block.get("height", 0))
