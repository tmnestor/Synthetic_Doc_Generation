"""Nesting containers: panel and split.

These are the only primitives that create child regions, which is why all the
region arithmetic lives in `Region` rather than being duplicated here. Children
render through `ctx.render_children` — injected by the engine — so this module
never imports the engine, which imports it.
"""

from typing import Any

from generators.layout_dsl.context import RenderContext
from generators.layout_dsl.defaults import resolve_param


class ContainerError(RuntimeError):
    """Raised when a container is asked to render without a walker."""


def _resolve(block: dict, ctx: RenderContext, param: str, *, block_key: str | None = None) -> Any:
    """Resolve one parameter honouring a block's own key before the layout default.

    `resolve_param`'s single `key` argument does double duty as both the
    block's own key and the layout `defaults:` key. Where those differ --
    `PARAMETER_DEFAULTS` namespaces a key a primitive shares with another
    (e.g. panel's `padding:` maps to the `panel_padding` default, since
    `padding` alone could not carry two different primitives' defaults in one
    flat namespace) -- this shims the block's own value under the namespaced
    name first, so a per-block override still wins exactly as it did before
    this parameter had a layout-level default to fall back to.

    Typed `Any`, not `object` (`resolve_param`'s own return type): a block's
    values were untyped `dict` values before this resolution existed, and
    callers already cast the ones that need it (`int(...)`) exactly as they
    did against the bare `.get()` call this replaces.

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
    padding = int(_resolve(block, ctx, "panel_padding", block_key="padding"))
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
        outline=_resolve(block, ctx, "panel_border_color", block_key="border_color"),
    )
    return bottom


def draw_split(block: dict, ctx: RenderContext, y: int) -> int:
    """Render child block lists side by side in equal columns.

    Args:
        block: The `split` block, carrying `children` (a list of block lists,
            one per column), an optional `gap`, and an optional `divider`
            (draws a vertical rule down the middle of each gap, e.g. Westpac's
            rewards panel, which splits into a points summary and a message
            column separated by a ruled line — decorative only, so unlike
            column geometry it is never checked by the equivalence harness).
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor: the bottom of the tallest column.
    """
    render_children = _walker(ctx)
    columns = block["children"]
    gap = int(_resolve(block, ctx, "split_gap", block_key="gap"))
    regions = ctx.region.divide(len(columns), gap=gap)
    ends = [
        render_children(child_blocks, ctx.within(region), y)
        for child_blocks, region in zip(columns, regions, strict=True)
    ]
    bottom = max(ends)
    if block.get("divider"):
        color = _resolve(block, ctx, "split_divider_color", block_key="divider_color")
        for left_region, right_region in zip(regions, regions[1:]):
            divider_x = (left_region.right + right_region.x) // 2
            ctx.draw.line([(divider_x, y), (divider_x, bottom)], fill=color)
    return bottom
