from PIL import Image, ImageDraw

import pytest

from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.primitives_container import ContainerError, draw_panel, draw_split


def _stub_walker(blocks: list, ctx: RenderContext, y: int) -> int:
    """Minimal stand-in for the engine: advance by each spacer's height."""
    for block in blocks:
        y += int(block.get("height", 0))
    return y


def _ctx(render_children=_stub_walker) -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry={"fields": {"PAYER_NAME": "Robin Wood"}},
        layout={
            "font_sizes": {"body": 32, "footer": 18},
            "defaults": {
                "panel_padding": 0,
                "panel_border_color": "black",
                "split_gap": 0,
                "split_divider_color": "black",
            },
        },
        layout_id="test",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        render_children=render_children,
    )


def test_container_without_injected_walker_fails_loudly():
    block = {"type": "panel", "children": [{"type": "spacer", "height": 10}]}
    with pytest.raises(ContainerError, match="render_children"):
        draw_panel(block, _ctx(render_children=None), 0)


def test_panel_advances_past_its_children():
    block = {
        "type": "panel",
        "padding": 10,
        "children": [{"type": "spacer", "height": 50}, {"type": "spacer", "height": 30}],
    }
    assert draw_panel(block, _ctx(), 200) == 200 + 10 + 80 + 10


def test_panel_honours_fixed_height():
    block = {"type": "panel", "height": 260, "children": [{"type": "spacer", "height": 10}]}
    assert draw_panel(block, _ctx(), 200) == 460


def test_split_returns_tallest_column():
    block = {
        "type": "split",
        "gap": 40,
        "children": [
            [{"type": "spacer", "height": 100}],
            [{"type": "spacer", "height": 250}],
        ],
    }
    assert draw_split(block, _ctx(), 200) == 450


def test_split_gives_each_column_its_own_non_overlapping_region():
    seen: list[Region] = []

    def recording_walker(blocks: list, ctx: RenderContext, y: int) -> int:
        seen.append(ctx.region)
        return _stub_walker(blocks, ctx, y)

    block = {
        "type": "split",
        "gap": 40,
        "children": [[{"type": "spacer", "height": 10}], [{"type": "spacer", "height": 10}]],
    }
    draw_split(block, _ctx(render_children=recording_walker), 0)

    left, right = seen
    assert left.right < right.x
    assert left.width == right.width == 780


def test_split_widths_gives_each_column_its_explicit_region():
    """Invoice totals occupy a fixed 400px column at the right edge, which
    equal division (the default path) cannot express."""
    seen: list[Region] = []

    def recording_walker(blocks: list, ctx: RenderContext, y: int) -> int:
        seen.append(ctx.region)
        return _stub_walker(blocks, ctx, y)

    block = {
        "type": "split",
        "widths": [1200, 400],
        "children": [[{"type": "spacer", "height": 10}], [{"type": "spacer", "height": 10}]],
    }
    draw_split(block, _ctx(render_children=recording_walker), 0)

    left, right = seen
    assert (left.x, left.width) == (100, 1200)
    assert (right.x, right.width) == (1300, 400)
    assert right.right == 1700  # _ctx()'s own region (x=100, width=1600) right edge


def test_split_without_widths_still_divides_equally():
    """Absent `widths`, draw_split's default path is unchanged."""
    seen: list[Region] = []

    def recording_walker(blocks: list, ctx: RenderContext, y: int) -> int:
        seen.append(ctx.region)
        return _stub_walker(blocks, ctx, y)

    block = {
        "type": "split",
        "children": [[{"type": "spacer", "height": 10}], [{"type": "spacer", "height": 10}]],
    }
    draw_split(block, _ctx(render_children=recording_walker), 0)

    left, right = seen
    assert left.width == right.width == 800  # 1600 // 2, 0 gap


def test_split_without_injected_walker_fails_loudly():
    block = {
        "type": "split",
        "gap": 40,
        "children": [[{"type": "spacer", "height": 10}], [{"type": "spacer", "height": 10}]],
    }
    with pytest.raises(ContainerError, match="render_children"):
        draw_split(block, _ctx(render_children=None), 0)


def test_panel_with_fixed_height_overflowing_children_fails():
    block = {
        "type": "panel",
        "height": 50,
        "padding": 5,
        "children": [{"type": "spacer", "height": 100}],
    }
    with pytest.raises(ContainerError, match="overflows"):
        draw_panel(block, _ctx(), 0)


def test_panel_border_rectangle_encloses_padded_children():
    rectangles: list = []

    def recording_draw(xy, **kwargs):
        rectangles.append((xy, kwargs))

    block = {
        "type": "panel",
        "padding": 10,
        "children": [{"type": "spacer", "height": 50}],
    }
    ctx = _ctx()
    ctx.draw.rectangle = recording_draw
    draw_panel(block, ctx, 200)

    assert len(rectangles) == 1
    (top_left, bottom_right), kwargs = rectangles[0]
    assert top_left == (100, 200)
    assert bottom_right == (1700, 270)
    assert kwargs["outline"] == "black"


def test_split_without_divider_draws_no_line():
    block = {
        "type": "split",
        "gap": 30,
        "children": [[{"type": "spacer", "height": 10}], [{"type": "spacer", "height": 10}]],
    }
    ctx = _ctx()
    ctx.draw.line = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no line expected"))
    draw_split(block, ctx, 200)  # must not raise


def test_split_with_divider_draws_a_line_at_the_gap_midpoint():
    """Westpac's rewards panel splits into two equal columns with a ruled line between them."""
    lines: list = []
    block = {
        "type": "split",
        "gap": 30,
        "divider": True,
        "children": [[{"type": "spacer", "height": 10}], [{"type": "spacer", "height": 40}]],
    }
    ctx = _ctx()
    ctx.draw.line = lambda points, **k: lines.append((points, k))
    bottom = draw_split(block, ctx, 200)

    assert len(lines) == 1
    (x1, y1), (x2, y2) = lines[0][0]
    assert x1 == x2  # vertical line
    assert y1 == 200  # starts at the split's own y
    assert y2 == bottom  # spans to the tallest column's bottom
    assert lines[0][1]["fill"] == "black"


def test_split_divider_color_is_configurable():
    lines: list = []
    block = {
        "type": "split",
        "gap": 30,
        "divider": True,
        "divider_color": "#CCCCCC",
        "children": [[{"type": "spacer", "height": 10}], [{"type": "spacer", "height": 10}]],
    }
    ctx = _ctx()
    ctx.draw.line = lambda points, **k: lines.append(k)
    draw_split(block, ctx, 200)
    assert lines[0]["fill"] == "#CCCCCC"
