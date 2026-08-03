"""Nesting containers: panel and split.

These are the only primitives that create child regions, which is why all the
region arithmetic lives in `Region` rather than being duplicated here. Children
render through `ctx.render_children` — injected by the engine — so this module
never imports the engine, which imports it.
"""

from generators.layout_dsl.context import RenderContext


class ContainerError(RuntimeError):
    """Raised when a container is asked to render without a walker."""


def _walker(ctx: RenderContext):
    """Return the injected child renderer, or fail with a diagnostic.

    Args:
        ctx: The render context.

    Returns:
        The injected `render_children` callable.

    Raises:
        ContainerError: If no walker was injected.
    """
    if ctx.render_children is None:
        raise ContainerError(
            "Container cannot render its children.\n"
            "  What:     RenderContext.render_children is None.\n"
            f"  Where:    {ctx.layout_path} -> {ctx.layout_id}.body\n"
            "  Expected: the engine injects render_children before rendering.\n"
            "  Recover:  render through generators.layout_dsl.engine.render_body, "
            "which sets it, rather than constructing a RenderContext by hand."
        )
    return ctx.render_children


def draw_panel(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a bordered container around a nested list of blocks.

    Args:
        block: The `panel` block, carrying `children` and optional `padding`,
            `border_color`, and a fixed `height`.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor: past the panel's border and padding.

    Raises:
        ContainerError: If a fixed height is given but children overflow it.
    """
    render_children = _walker(ctx)
    padding = int(block.get("padding", 0))
    inner_ctx = ctx.within(ctx.region.indent(padding, padding))
    inner_end = render_children(block["children"], inner_ctx, y + padding)

    fixed = block.get("height")
    if fixed is not None:
        natural = inner_end + padding
        limit = y + int(fixed)
        if natural > limit:
            raise ContainerError(
                "Panel content overflows its fixed height.\n"
                f"  What:     children need {natural - y}px but the panel declares "
                f"height: {int(fixed)}.\n"
                f"  Where:    {ctx.layout_path} -> {ctx.layout_id}.body (a panel block)\n"
                f"  Expected: height >= {natural - y}, or fewer/smaller children.\n"
                f"  Recover:  raise the panel's height to at least {natural - y}, or "
                "reduce its children."
            )
        bottom = limit
    else:
        bottom = inner_end + padding

    ctx.draw.rectangle(
        [(ctx.region.x, y), (ctx.region.right, bottom)],
        outline=block.get("border_color", "black"),
    )
    return bottom


def draw_split(block: dict, ctx: RenderContext, y: int) -> int:
    """Render child block lists side by side in equal columns.

    Args:
        block: The `split` block, carrying `children` (a list of block lists,
            one per column) and an optional `gap`.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor: the bottom of the tallest column.
    """
    render_children = _walker(ctx)
    columns = block["children"]
    regions = ctx.region.divide(len(columns), gap=int(block.get("gap", 0)))
    ends = [
        render_children(child_blocks, ctx.within(region), y)
        for child_blocks, region in zip(columns, regions, strict=True)
    ]
    return max(ends)
