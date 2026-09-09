import pytest
from PIL import Image, ImageDraw

from generators.common import FitError
from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.defaults import PARAMETER_DEFAULTS, DefaultsError
from generators.layout_dsl.engine import PRIMITIVE_DRAWERS, EngineError, render_blocks, render_body
from generators.layout_dsl.primitives_text import RoleError
from generators.layout_dsl.schema import PRIMITIVES
from conftest import assert_diagnostic_error

# A complete, literal-transcribed defaults: mapping (matching bank_statements.yml's
# shared _dsl_defaults_values anchor), for tests that render through a primitive
# needing a layout default -- e.g. a panel's border color, never set on the block.
DEFAULTS = {
    "role": "body",
    "color": "black",
    "align": "left",
    "bold": False,
    "family": "carlito",
    "line_advance": {"body": 44},  # int(32 * 1.4), this fixture's only font_sizes role.
    "rule_thickness": 1,
    "rule_pad_above": 0,
    "rule_pad_below": 0,
    "rule_fill_char": "none",
    "spacer_height": 0,
    "pair_value_align": "left",
    "pair_min_gap": 0,
    "pair_separator": ": ",
    "table_header": True,
    "table_header_bold": True,
    "table_row_inset_y": 0,
    "table_cell_line_spacing": "row_height",
    "table_header_rule_top": True,
    "table_header_rule_gap": 16,
    "table_group_gap": 10,
    "table_fill_inset": 0,
    "table_dividers": [],
    "table_offset_y": 0,
    "table_capture": True,
    "table_sub_line_height": 0,
    "banner_text_color": "white",
    "banner_text_y": 0,
    "banner_role": "header",
    "panel_padding": 0,
    "panel_border_color": "black",
    "split_gap": 0,
    "split_divider_color": "black",
}
assert set(DEFAULTS) == PARAMETER_DEFAULTS, sorted(PARAMETER_DEFAULTS - set(DEFAULTS))


def _ctx() -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry={"fields": {"PAYER_NAME": "Robin Wood", "STATEMENT_DATE_RANGE": "NOT_FOUND"}},
        layout={"font_sizes": {"body": 32}, "row_height": 72, "defaults": DEFAULTS},
        layout_id="test",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        render_children=render_blocks,
    )


def test_every_schema_primitive_has_a_drawer():
    assert set(PRIMITIVES) == set(PRIMITIVE_DRAWERS)


def test_render_blocks_advances_through_the_list():
    end = render_blocks([{"type": "spacer", "height": 40}, {"type": "spacer", "height": 60}], _ctx(), 0)
    assert end == 100


def test_when_suppresses_a_block_whose_field_is_absent():
    body = [{"type": "spacer", "height": 40, "when": "STATEMENT_DATE_RANGE"}]
    assert render_blocks(body, _ctx(), 0) == 0


def test_when_admits_a_block_whose_field_is_present():
    body = [{"type": "spacer", "height": 40, "when": "PAYER_NAME"}]
    assert render_blocks(body, _ctx(), 0) == 40


def test_unknown_primitive_fails_with_diagnostic():
    with pytest.raises(EngineError) as exc_info:
        render_blocks([{"type": "hologram"}], _ctx(), 0)
    assert_diagnostic_error(str(exc_info.value))


def test_nested_panel_renders_through_the_walker():
    body = [{"type": "panel", "padding": 10, "children": [{"type": "spacer", "height": 50}]}]
    assert render_blocks(body, _ctx(), 0) == 70


def _render_body(layout: dict, *, entry: dict | None = None, y: int = 0) -> int:
    image = Image.new("RGB", (1800, 3508), "white")
    # field_providers is a required layout key (see apply_field_providers);
    # none of the tests using this helper are about field providers, so
    # default it to [] here -- the same reasoning test_schema.py's
    # _validate_layout helper uses for the same key.
    return render_body(
        {"field_providers": [], **layout},
        entry or {"fields": {"PAYER_NAME": "Robin Wood", "STATEMENT_DATE_RANGE": "NOT_FOUND"}},
        layout_id="test",
        layout_path="config/layouts/bank_statements.yml",
        draw=ImageDraw.Draw(image),
        region=Region(x=100, width=1600),
        y=y,
    )


def test_render_body_missing_body_key_fails_with_diagnostic():
    with pytest.raises(EngineError) as exc_info:
        _render_body({"font_sizes": {"body": 32}})
    assert_diagnostic_error(str(exc_info.value))


def test_render_body_renders_a_valid_layout_and_returns_advanced_y():
    layout = {"font_sizes": {"body": 32}, "row_height": 72, "body": [{"type": "spacer", "height": 40}]}
    assert _render_body(layout) == 40


def test_render_body_injects_render_children_so_a_panel_renders_its_contents():
    layout = {
        "font_sizes": {"body": 32},
        "row_height": 72,
        "defaults": DEFAULTS,
        "body": [{"type": "panel", "padding": 10, "children": [{"type": "spacer", "height": 50}]}],
    }
    assert _render_body(layout) == 70


def test_render_body_reports_the_failing_blocks_nested_location():
    layout = {
        "font_sizes": {"body": 32},
        "row_height": 72,
        "defaults": DEFAULTS,
        "body": [
            {"type": "spacer", "height": 10},
            {
                "type": "panel",
                "padding": 5,
                "children": [{"type": "text", "content": "x", "role": "nope"}],
            },
        ],
    }
    with pytest.raises(RoleError) as exc_info:
        _render_body(layout)
    message = str(exc_info.value)
    assert "[1](panel)" in message
    assert "[0](text)" in message


def test_render_body_reports_the_nested_location_of_a_missing_default():
    """A missing `defaults:` entry is the likeliest render-time DSL failure --
    every primitive parameter resolves through resolve_param -- and it was the
    one error escaping the walker untagged. resolve_param can only name the
    parameter and the layout; only the walker knows which block asked."""
    layout = {
        "font_sizes": {"body": 32},
        "row_height": 72,
        "defaults": {k: v for k, v in DEFAULTS.items() if k != "pair_separator"},
        "body": [
            {"type": "spacer", "height": 10},
            {
                "type": "panel",
                "padding": 5,
                "children": [{"type": "pair", "label": "Date", "value": "01/07/2024"}],
            },
        ],
    }
    with pytest.raises(DefaultsError) as exc_info:
        _render_body(layout)
    message = str(exc_info.value)
    assert "pair_separator" in message
    assert "[1](panel)" in message
    assert "[0](pair)" in message


def _fit_error_layout() -> dict:
    """A layout whose table column budget can never fit its content.

    `width: 1` with `fit: shrink` is unsatisfiable at any font size down to
    `min_font`, so `fit_text` always raises `FitError` — used to prove the
    walker locates a FitError the same as any other DSL error.
    """
    return {
        "font_sizes": {"body": 32},
        "row_height": 72,
        "defaults": DEFAULTS,
        "field_budgets": {"DESC": {"width": 1, "fit": "shrink", "min_font": 10, "max_lines": 1}},
        "body": [
            {"type": "spacer", "height": 10},
            {
                "type": "panel",
                "padding": 5,
                "children": [
                    {
                        "type": "table",
                        "rows": "pipe_fields",
                        "frame": "plain",
                        "grouping": "none",
                        "header": False,
                        "params": {"fields": {"desc": "LONG_FIELD"}},
                        "columns": [
                            {
                                "key": "desc",
                                "label": "Description",
                                "x": 0,
                                "budget": "DESC",
                                "field": "LONG_FIELD",
                            }
                        ],
                    }
                ],
            },
        ],
    }


def test_render_body_reports_nested_location_for_a_fit_error():
    entry = {"fields": {"LONG_FIELD": "This description is far too long to fit its budget"}}
    with pytest.raises(FitError) as exc_info:
        _render_body(_fit_error_layout(), entry=entry)
    message = str(exc_info.value)
    assert "[1](panel)" in message
    assert "[0](table)" in message
