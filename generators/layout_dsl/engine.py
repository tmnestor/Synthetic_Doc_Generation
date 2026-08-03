"""The walker: dispatch each block in a layout body to its primitive drawer."""

from collections.abc import Callable

from PIL import ImageDraw

from generators.exporters.geometry import BoxRecorder
from generators.layout_dsl.binding import is_present
from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.primitives_container import draw_panel, draw_split
from generators.layout_dsl.primitives_table import draw_table
from generators.layout_dsl.primitives_text import (
    draw_block,
    draw_pair,
    draw_rule,
    draw_spacer,
    draw_text_block,
)

Drawer = Callable[[dict, RenderContext, int], int]

PRIMITIVE_DRAWERS: dict[str, Drawer] = {
    "text": draw_text_block,
    "pair": draw_pair,
    "block": draw_block,
    "rule": draw_rule,
    "spacer": draw_spacer,
    "panel": draw_panel,
    "split": draw_split,
    "table": draw_table,
}


class EngineError(RuntimeError):
    """Raised when a block cannot be dispatched at render time."""


def render_blocks(blocks: list, ctx: RenderContext, y: int) -> int:
    """Render a list of blocks in order, threading the y-cursor.

    Args:
        blocks: Block dicts to render.
        ctx: Render context, already scoped to the right region.
        y: Starting y-cursor.

    Returns:
        The y-cursor after the last block.

    Raises:
        EngineError: If a block names a primitive with no registered drawer.
    """
    for block in blocks:
        when = block.get("when")
        if when is not None and not is_present(ctx.entry["fields"], when):
            continue

        kind = block.get("type")
        drawer = PRIMITIVE_DRAWERS.get(str(kind))
        if drawer is None:
            raise EngineError(
                "Cannot render layout block.\n"
                f"  What:     no drawer registered for primitive '{kind}'.\n"
                f"  Where:    {ctx.layout_path} -> {ctx.layout_id}.body\n"
                f"  Expected: one of {sorted(PRIMITIVE_DRAWERS)}.\n"
                f"  Recover:  use a supported primitive, or register a drawer in "
                f"PRIMITIVE_DRAWERS in generators/layout_dsl/engine.py."
            )
        y = drawer(block, ctx, y)
    return y


def render_body(
    layout: dict,
    entry: dict,
    *,
    layout_id: str,
    layout_path: str,
    draw: ImageDraw.ImageDraw,
    region: Region,
    y: int,
    recorder: BoxRecorder | None = None,
) -> int:
    """Render a layout's whole body onto a drawing surface.

    Args:
        layout: The resolved layout dict, carrying `body`.
        entry: The ground-truth entry.
        layout_id: Layout id, used in diagnostics.
        layout_path: Path to the layout YAML, used in diagnostics.
        draw: The PIL drawing surface.
        region: The page's content region.
        y: Starting y-cursor, normally the layout's top margin.
        recorder: Optional draw-time bounding-box capture.

    Returns:
        The y-cursor after the last block.
    """
    ctx = RenderContext(
        draw=draw,
        entry=entry,
        layout=layout,
        layout_id=layout_id,
        layout_path=layout_path,
        region=region,
        recorder=recorder,
        render_children=render_blocks,
    )
    return render_blocks(layout["body"], ctx, y)
