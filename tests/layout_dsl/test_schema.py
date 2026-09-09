import pytest
from copy import deepcopy
from pathlib import Path

from generators.layout_dsl.defaults import PARAMETER_DEFAULTS
from generators.layout_dsl.schema import (
    LayoutSchemaError,
    known_layout_keys,
    validate_body,
    validate_layout,
)
from conftest import assert_diagnostic_error

FIELDS = {"PAYER_NAME", "SUPPLIER_NAME", "STATEMENT_DATE_RANGE"}

# A complete defaults: mapping, for tests exercising validate_layout's other
# checks (geometry, body/content_width presence) rather than the coverage
# check itself -- see test_incomplete_defaults_block_is_rejected in
# test_defaults.py for that one. Values are irrelevant to these tests; only
# completeness (every PARAMETER_DEFAULTS name present) matters.
DEFAULTS: dict[str, object] = dict.fromkeys(PARAMETER_DEFAULTS, "unused")
# line_advance is exempt from the "value is irrelevant" note above:
# validate_layout shape-checks it (a role -> pixels mapping, not a scalar)
# and role-coverage-checks it (every role the body actually resolves through
# it), so the fixture's usual bare "unused" placeholder cannot stand in.
# `defaults.role` is "unused" too (same fromkeys), and every body built from
# this fixture below is either role-free (rule/panel/split-of-rules) or a
# `table` block, which always resolves its own advance through the layout's
# default role -- so a single {"unused": 0} entry covers all of them.
DEFAULTS["line_advance"] = {"unused": 0}
# Likewise exempt: validate_layout checks defaults.family against
# FONT_FAMILIES (a bad family would otherwise surface as a FontFamilyError on
# the first block that draws, long after startup), so the bare "unused"
# placeholder is rejected before any test's own assertion can run. Any
# vendored family serves; these tests never draw.
DEFAULTS["family"] = "carlito"
# Likewise exempt: _validate_geometry resolves a panel's `padding:` and a
# split's `gap:` against these two, exactly as draw_panel and draw_split do,
# so both must be the integers a layout would really carry. Zero is what all
# three shipped layout files declare.
DEFAULTS["panel_padding"] = 0
DEFAULTS["split_gap"] = 0


def _validate(body: list) -> None:
    validate_body(
        body,
        layout_id="cba_standard",
        layout_path="config/layouts/bank_statements.yml",
        known_fields=FIELDS,
    )


def test_accepts_a_minimal_valid_body():
    _validate([{"type": "text", "content": "{PAYER_NAME}"}, {"type": "rule"}])


def test_rejects_unknown_primitive_and_lists_allowed():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "hologram"}])
    message = str(exc_info.value)
    assert "hologram" in message
    assert "text" in message and "table" in message
    assert_diagnostic_error(message)


def test_rejects_block_without_type():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"content": "hi"}])
    assert_diagnostic_error(str(exc_info.value))


def test_rejects_missing_required_key():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "text"}])
    message = str(exc_info.value)
    assert "content" in message
    assert_diagnostic_error(message)


def test_rejects_unknown_field_reference():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "text", "content": "{NOT_A_FIELD}"}])
    message = str(exc_info.value)
    assert "NOT_A_FIELD" in message
    assert_diagnostic_error(message)


def test_rejects_unknown_when_field():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "rule", "when": "MYSTERY"}])
    assert "MYSTERY" in str(exc_info.value)


def test_rejects_unregistered_row_provider():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(
            [
                {
                    "type": "table",
                    "rows": "nope",
                    "frame": "plain",
                    "grouping": "none",
                    "columns": [{"key": "a", "label": "A"}],
                }
            ]
        )
    message = str(exc_info.value)
    assert "nope" in message and "pipe_fields" in message
    assert_diagnostic_error(message)


def test_recurses_into_containers():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "panel", "children": [{"type": "text", "content": "{BAD}"}]}])
    message = str(exc_info.value)
    assert "BAD" in message
    assert "children[0]" in message


def test_recurses_into_split_columns():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(
            [{"type": "split", "children": [[{"type": "rule"}], [{"type": "text", "content": "{BAD}"}]]}]
        )
    assert "BAD" in str(exc_info.value)


def test_rejects_table_column_without_key():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(
            [
                {
                    "type": "table",
                    "rows": "pipe_fields",
                    "frame": "plain",
                    "grouping": "none",
                    "columns": [{"label": "A"}],
                }
            ]
        )
    assert_diagnostic_error(str(exc_info.value))


def test_table_requires_frame():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "grouping": "none",
            "columns": [{"key": "a", "label": "A"}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "frame" in message
    assert_diagnostic_error(message)


def test_table_requires_grouping():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "columns": [{"key": "a", "label": "A"}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "grouping" in message
    assert_diagnostic_error(message)


def test_rejects_unknown_frame():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "sparkly",
            "grouping": "none",
            "columns": [{"key": "a", "label": "A"}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "sparkly" in message and "ruled" in message
    assert_diagnostic_error(message)


def test_rejects_unknown_grouping():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "clustered",
            "columns": [{"key": "a", "label": "A"}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "clustered" in message and "dedicated_row" in message
    assert_diagnostic_error(message)


def test_bordered_frame_with_inline_grouping_is_accepted():
    """Westpac premium's date-grouped bordered table -- must not be rejected."""
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "bordered",
            "grouping": "inline",
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    _validate(body)  # must not raise


def test_filled_frame_without_fill_color_is_rejected():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "filled",
            "grouping": "dedicated_row",
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "fill_color" in message
    assert_diagnostic_error(message)


def test_fill_color_without_filled_frame_is_rejected():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "fill_color": "#E8F0FE",
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "fill_color" in message
    assert_diagnostic_error(message)


def test_filled_frame_with_fill_color_is_accepted():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "filled",
            "grouping": "dedicated_row",
            "fill_color": "#E8F0FE",
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    _validate(body)  # must not raise


def test_accepts_fill_inset_fill_height_and_label_inset_y():
    """Fix round 1's three geometry overrides -- all optional, all schema-legal."""
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "filled",
            "grouping": "dedicated_row",
            "fill_color": "#E8F0FE",
            "fill_inset": 2,
            "fill_height": 44,
            "header_height": 50,
            "label_inset_y": 10,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    _validate(body)  # must not raise


def test_rejects_table_divider_without_x_or_x_right():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "bordered",
            "grouping": "none",
            "columns": [{"key": "a", "label": "A", "x": 0}],
            "dividers": [{"color": "black"}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    assert_diagnostic_error(str(exc_info.value))


def test_accepts_table_dividers_with_x_and_x_right():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "bordered",
            "grouping": "none",
            "columns": [{"key": "a", "label": "A", "x": 0}],
            "dividers": [{"x": 200}, {"x_right": -320}],
        }
    ]
    _validate(body)  # must not raise


def test_rejects_dividers_on_a_non_bordered_frame():
    """dividers only cuts the header/body into columns under frame: bordered."""
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "columns": [{"key": "a", "label": "A", "x": 0}],
            "dividers": [{"x": 200}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "dividers" in message and "bordered" in message
    assert_diagnostic_error(message)


def test_rejects_fill_height_on_a_non_filled_frame():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "bordered",
            "grouping": "none",
            "fill_height": 44,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "fill_height" in message and "filled" in message
    assert_diagnostic_error(message)


def test_rejects_fill_inset_on_a_non_filled_frame():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "ruled",
            "grouping": "none",
            "fill_inset": 2,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "fill_inset" in message and "filled" in message
    assert_diagnostic_error(message)


def test_accepts_fill_height_and_fill_inset_with_filled_frame():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "filled",
            "grouping": "dedicated_row",
            "fill_color": "#E8F0FE",
            "fill_height": 44,
            "fill_inset": 2,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    _validate(body)  # must not raise


def test_rejects_group_gap_on_non_dedicated_row_grouping():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "group_gap": 0,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "group_gap" in message and "dedicated_row" in message
    assert_diagnostic_error(message)


def test_accepts_group_gap_with_dedicated_row_grouping():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "dedicated_row",
            "group_gap": 0,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    _validate(body)  # must not raise


def test_rejects_synthetic_row_placement_on_non_dedicated_row_grouping():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "inline",
            "synthetic_row_placement": "after_first_group_header",
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "synthetic_row_placement" in message and "dedicated_row" in message
    assert_diagnostic_error(message)


def test_rejects_unknown_synthetic_row_placement_value():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "dedicated_row",
            "synthetic_row_placement": "sideways",
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "sideways" in message and "leading" in message
    assert_diagnostic_error(message)


def test_accepts_synthetic_row_placement_after_first_group_header():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "dedicated_row",
            "synthetic_row_placement": "after_first_group_header",
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    _validate(body)  # must not raise


def test_rejects_column_sub_line_without_key():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "columns": [{"key": "a", "label": "A", "x": 0, "sub_line": {"color": "#999999"}}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "sub_line" in message and "key" in message
    assert_diagnostic_error(message)


def test_accepts_column_sub_line_with_key():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "columns": [
                {
                    "key": "a",
                    "label": "A",
                    "x": 0,
                    "sub_line": {
                        "key": "reference",
                        "role": "sub_description",
                        "offset_y": 34,
                        "height": 32,
                    },
                }
            ],
        }
    ]
    _validate(body)  # must not raise


def test_accepts_split_divider_keys():
    body = [
        {
            "type": "split",
            "divider": True,
            "divider_color": "#CCCCCC",
            "children": [[{"type": "rule"}], [{"type": "rule"}]],
        }
    ]
    _validate(body)  # must not raise


# --- split.widths and table.capture (invoice primitives) -------------------


def test_accepts_split_with_widths_matching_children_count():
    body = [
        {
            "type": "split",
            "widths": [1200, 400],
            "children": [[{"type": "rule"}], [{"type": "rule"}]],
        }
    ]
    _validate(body)  # must not raise


def test_rejects_split_widths_with_wrong_entry_count():
    body = [
        {
            "type": "split",
            "widths": [1200, 400, 100],
            "children": [[{"type": "rule"}], [{"type": "rule"}]],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "3" in message and "2" in message
    assert_diagnostic_error(message)


def test_rejects_split_widths_that_is_empty():
    body = [{"type": "split", "widths": [], "children": [[{"type": "rule"}], [{"type": "rule"}]]}]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    assert_diagnostic_error(str(exc_info.value))


def test_rejects_split_widths_with_a_non_positive_entry():
    body = [
        {
            "type": "split",
            "widths": [1200, 0],
            "children": [[{"type": "rule"}], [{"type": "rule"}]],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    assert_diagnostic_error(str(exc_info.value))


def test_rejects_split_widths_with_a_non_int_entry():
    body = [
        {
            "type": "split",
            "widths": [1200, "400"],
            "children": [[{"type": "rule"}], [{"type": "rule"}]],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    assert_diagnostic_error(str(exc_info.value))


def test_accepts_table_capture_true_and_false():
    for capture in (True, False):
        body = [
            {
                "type": "table",
                "rows": "pipe_fields",
                "frame": "plain",
                "grouping": "none",
                "capture": capture,
                "columns": [{"key": "a", "label": "A", "x": 0}],
            }
        ]
        _validate(body)  # must not raise


def test_rejects_table_capture_that_is_not_a_bool():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "capture": "false",
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "capture" in message
    assert_diagnostic_error(message)


# --- table role / header_bold / row_inset_y / cell_line_spacing / label anchor
# (invoice bodies) -------------------------------------------------------------


def _table_body(**table_keys) -> list:
    return [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "columns": [{"key": "a", "label": "A", "x": 0}],
            **table_keys,
        }
    ]


def test_accepts_the_invoice_table_typography_keys():
    _validate(
        _table_body(
            role="subheader",
            header_bold=False,
            row_inset_y=12,
            cell_line_spacing="font",
        )
    )  # must not raise


def test_rejects_unknown_cell_line_spacing():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(_table_body(cell_line_spacing="rowheight"))
    message = str(exc_info.value)
    assert "rowheight" in message
    assert "row_height" in message and "font" in message
    assert_diagnostic_error(message)


def test_accepts_a_column_label_anchor_that_differs_from_its_cells():
    body = _table_body(
        columns=[
            {"key": "a", "label": "A", "align": "right", "x": 1750, "label_x": 1550, "label_align": "left"}
        ]
    )
    _validate(body)  # must not raise


def test_rejects_unknown_column_label_align():
    body = _table_body(columns=[{"key": "a", "label": "A", "x": 0, "label_align": "centre"}])
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "centre" in message and "label_align" in message
    assert_diagnostic_error(message)


def test_rejects_non_int_column_label_x():
    body = _table_body(columns=[{"key": "a", "label": "A", "x": 0, "label_x": "1550"}])
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "label_x" in message
    assert_diagnostic_error(message)


def test_a_tables_own_role_is_what_the_line_advance_coverage_check_requires():
    """A table draws its labels and cells at its own role, and resolves that
    role's advance -- so covering only the layout's default role is not enough."""
    layout = {
        "content_width": 1600,
        "field_providers": [],
        "defaults": {**DEFAULTS, "role": "body", "line_advance": {"body": 44}},
        "field_budgets": {},
        "body": _table_body(role="subheader"),
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "subheader" in message
    assert_diagnostic_error(message)

    layout["defaults"]["line_advance"] = {"body": 44, "subheader": 39}
    _validate_layout(layout)  # must not raise once the table's own role is covered


# --- validate_layout: spec checks 4 and 5 ---

BUDGETED_LAYOUT = {
    "content_width": 1600,
    "defaults": DEFAULTS,
    "field_budgets": {"DESC": {"width": 760, "fit": "wrap", "min_font": 10, "max_lines": 2}},
    "body": [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "columns": [
                {"key": "description", "label": "Description", "align": "left", "x": 200, "budget": "DESC"},
                {"key": "debit", "label": "Debit", "align": "right", "x_right": -420},
            ],
        }
    ],
}


def _validate_layout(layout: dict) -> None:
    # field_providers is a required layout key (see validate_layout); none of
    # the tests below are about field providers, so default it to [] here,
    # the same way DEFAULTS above stands in for defaults: irrelevant to a
    # given test -- a test that IS about field_providers overrides this by
    # setting its own key in the layout dict it passes in.
    validate_layout(
        {"field_providers": [], **layout},
        layout_id="cba_standard",
        layout_path="config/layouts/bank_statements.yml",
        known_fields=FIELDS,
    )


def test_column_budget_matching_its_geometry_is_accepted():
    # Column spans x=200 to the next column's left edge at 1600-420=1180, so 980px
    # is available; the declared 760 fits within it.
    _validate_layout(BUDGETED_LAYOUT)


def test_column_budget_wider_than_its_geometry_is_rejected():
    layout = deepcopy(BUDGETED_LAYOUT)
    layout["field_budgets"]["DESC"]["width"] = 1400
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "1400" in message and "980" in message
    assert_diagnostic_error(message)


def test_column_naming_a_missing_budget_is_rejected():
    layout = deepcopy(BUDGETED_LAYOUT)
    layout["field_budgets"] = {}
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert "DESC" in str(exc_info.value)


def test_panel_padding_wider_than_the_page_is_rejected():
    layout = {
        "content_width": 100,
        "defaults": DEFAULTS,
        "field_budgets": {},
        "body": [{"type": "panel", "padding": 80, "children": [{"type": "rule"}]}],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert_diagnostic_error(str(exc_info.value))


def test_split_with_too_large_a_gap_is_rejected():
    layout = {
        "content_width": 100,
        "defaults": DEFAULTS,
        "field_budgets": {},
        "body": [{"type": "split", "gap": 200, "children": [[{"type": "rule"}], [{"type": "rule"}]]}],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert_diagnostic_error(str(exc_info.value))


def test_split_widths_summing_over_the_region_is_rejected():
    """Geometry-level check, distinct from the body-level widths/children count
    check: the widths themselves are shaped correctly but overflow the page."""
    layout = {
        "content_width": 100,
        "defaults": DEFAULTS,
        "field_budgets": {},
        "body": [
            {
                "type": "split",
                "widths": [80, 80],
                "children": [[{"type": "rule"}], [{"type": "rule"}]],
            }
        ],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "80" in message and "100" in message
    assert_diagnostic_error(message)


def test_split_widths_exactly_filling_the_region_is_accepted():
    layout = {
        "content_width": 100,
        "defaults": DEFAULTS,
        "field_budgets": {},
        "body": [
            {
                "type": "split",
                "widths": [60, 40],
                "children": [[{"type": "rule"}], [{"type": "rule"}]],
            }
        ],
    }
    _validate_layout(layout)  # must not raise


def test_split_gap_comes_from_the_layout_default_when_the_block_omits_it():
    """draw_split resolves `gap:` against `defaults.split_gap`; so must
    validation. Checking a gap-less split at 0 would pass widths the renderer
    then cannot fit, and the overflow would surface as a wrong-looking page
    rather than a validate-time error naming the block."""
    layout = {
        "content_width": 100,
        "defaults": {**DEFAULTS, "split_gap": 30},
        "field_budgets": {},
        "body": [
            {
                "type": "split",
                "widths": [60, 40],  # exactly 100 at gap 0; 130 at the layout's gap 30
                "children": [[{"type": "rule"}], [{"type": "rule"}]],
            }
        ],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "30" in message and "130" in message
    assert_diagnostic_error(message)


def test_panel_padding_comes_from_the_layout_default_when_the_block_omits_it():
    """The panel counterpart: draw_panel resolves `padding:` against
    `defaults.panel_padding`, so a padding-less panel in a layout declaring a
    large one must be checked at that padding, not at 0."""
    layout = {
        "content_width": 100,
        "defaults": {**DEFAULTS, "panel_padding": 60},
        "field_budgets": {},
        "body": [{"type": "panel", "children": [{"type": "rule"}]}],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "60" in message
    assert_diagnostic_error(message)


def test_budgeted_table_nested_in_a_split_with_widths_uses_the_explicit_column_width():
    """A budget that fits equal division (800px columns) but not the invoice's
    real fixed-width totals column (400px) must be rejected, not silently
    validated against the wrong (equal-division) width."""
    layout = {
        "content_width": 1600,
        "defaults": DEFAULTS,
        "field_budgets": {"DESC": {"width": 700, "fit": "wrap", "min_font": 10, "max_lines": 2}},
        "body": [
            {
                "type": "split",
                "widths": [1200, 400],
                "children": [
                    [{"type": "rule"}],
                    [
                        {
                            "type": "table",
                            "rows": "pipe_fields",
                            "frame": "plain",
                            "grouping": "none",
                            "columns": [
                                {"key": "label", "label": "L", "align": "left", "x": 0, "budget": "DESC"},
                            ],
                        }
                    ],
                ],
            }
        ],
    }
    # 700px budget does not fit the explicit 400px second column, even though
    # it would fit an equally-divided 800px column.
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "700" in message and "400" in message
    assert_diagnostic_error(message)


def test_validate_layout_rejects_a_layout_with_no_body_key():
    layout = {"content_width": 1600, "defaults": DEFAULTS, "field_budgets": {}}
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "body" in message
    assert_diagnostic_error(message)


def test_validate_layout_rejects_a_layout_with_no_content_width_key():
    layout = {"body": [{"type": "rule"}], "defaults": DEFAULTS, "field_budgets": {}}
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "content_width" in message
    assert_diagnostic_error(message)


def test_budgeted_table_nested_in_a_panel_uses_the_narrowed_width():
    # Panel padding 100 each side narrows 1600 -> 1400. Description column at x=0 with a
    # following column anchored at x_right=-400 (i.e. 1000) leaves 1000px available.
    layout = {
        "content_width": 1600,
        "defaults": DEFAULTS,
        "field_budgets": {"DESC": {"width": 1200, "fit": "wrap", "min_font": 10, "max_lines": 2}},
        "body": [
            {
                "type": "panel",
                "padding": 100,
                "children": [
                    {
                        "type": "table",
                        "rows": "pipe_fields",
                        "frame": "plain",
                        "grouping": "none",
                        "columns": [
                            {"key": "d", "label": "D", "align": "left", "x": 0, "budget": "DESC"},
                            {"key": "x", "label": "X", "align": "right", "x_right": -400},
                        ],
                    }
                ],
            }
        ],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "1200" in message and "1000" in message
    assert_diagnostic_error(message)


# -- text/pair fit budgets ----------------------------------------------------

TEXT_BUDGETED_LAYOUT = {
    "content_width": 1600,
    "defaults": DEFAULTS,
    "field_budgets": {"SUPPLIER_NAME": {"width": 800, "fit": "wrap", "min_font": 10, "max_lines": 2}},
    "body": [{"type": "text", "content": "{SUPPLIER_NAME}", "budget": "SUPPLIER_NAME"}],
}


def test_text_budget_matching_its_region_is_accepted():
    _validate_layout(TEXT_BUDGETED_LAYOUT)


def test_text_budget_wider_than_its_region_is_rejected():
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["field_budgets"]["SUPPLIER_NAME"]["width"] = 2000
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "2000" in message and "1600" in message
    assert_diagnostic_error(message)


def test_text_budget_naming_a_missing_budget_is_rejected():
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["field_budgets"] = {}
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert "SUPPLIER_NAME" in str(exc_info.value)


def test_pair_budget_matching_its_region_is_accepted():
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["body"] = [
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "budget": "SUPPLIER_NAME"}
    ]
    _validate_layout(layout)


def test_pair_budget_wider_than_its_region_is_rejected():
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["body"] = [
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "budget": "SUPPLIER_NAME"}
    ]
    layout["field_budgets"]["SUPPLIER_NAME"]["width"] = 2000
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "2000" in message and "1600" in message
    assert_diagnostic_error(message)


# -- pair.value_align / pair.min_gap / rule.fill_char ------------------------


def test_accepts_pair_value_align_and_min_gap_keys():
    _validate([{"type": "pair", "label": "TOTAL", "value": "{PAYER_NAME}", "value_align": "right"}])
    _validate(
        [{"type": "pair", "label": "TOTAL", "value": "{PAYER_NAME}", "value_align": "right", "min_gap": 24}]
    )


def test_rejects_unknown_pair_value_align():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "pair", "label": "TOTAL", "value": "{PAYER_NAME}", "value_align": "centre"}])
    message = str(exc_info.value)
    assert "centre" in message
    assert "left" in message and "right" in message
    assert_diagnostic_error(message)


def test_accepts_rule_fill_char_key():
    _validate([{"type": "rule", "fill_char": "-"}])


def test_budgeted_right_aligned_pair_with_a_min_gap_is_rejected():
    """draw_pair's budgeted path draws the label first and fits the value into
    what is left; it never repositions the label, so a declared min_gap is
    dropped with nothing on the page to show it. The combination was a written
    constraint while the primitive was built; this is that constraint made
    enforceable."""
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["defaults"] = {**DEFAULTS, "pair_value_align": "right", "pair_min_gap": 200}
    layout["body"] = [
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "budget": "SUPPLIER_NAME"}
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "min_gap" in message and "200" in message
    assert "budget" in message and "value_align" in message
    assert_diagnostic_error(message)


def test_budgeted_right_aligned_pair_with_a_zero_min_gap_is_accepted():
    """Zero is the resolved value every shipped layout carries, and it asks
    for nothing the budgeted path cannot deliver."""
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["defaults"] = {**DEFAULTS, "pair_value_align": "right", "pair_min_gap": 0}
    layout["body"] = [
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "budget": "SUPPLIER_NAME"}
    ]
    layout["field_budgets"]["SUPPLIER_NAME"]["width"] = 1600
    _validate_layout(layout)  # must not raise


def test_budgeted_right_aligned_pair_rejects_a_block_level_min_gap_too():
    """A block's own min_gap is as unhonoured as a layout-level one."""
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["defaults"] = {**DEFAULTS, "pair_value_align": "right", "pair_min_gap": 0}
    layout["body"] = [
        {
            "type": "pair",
            "label": "Account Holder",
            "value": "{PAYER_NAME}",
            "budget": "SUPPLIER_NAME",
            "min_gap": 200,
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "min_gap" in message and "200" in message
    assert_diagnostic_error(message)


def test_unbudgeted_right_aligned_pair_may_still_carry_a_min_gap():
    """The live invoice case: no budget, so min_gap does reposition the label
    at render time and must stay legal."""
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["defaults"] = {**DEFAULTS, "pair_value_align": "right", "pair_min_gap": 0}
    layout["body"] = [
        {"type": "pair", "label": "GST included (10%)", "value": "{PAYER_NAME}", "min_gap": 24}
    ]
    _validate_layout(layout)  # must not raise


def test_left_aligned_pair_budget_is_still_checked_against_the_full_width():
    """pair_value_align: left (the default) must reproduce the pre-existing,
    unnarrowed check -- min_gap plays no part in it."""
    layout = deepcopy(TEXT_BUDGETED_LAYOUT)
    layout["defaults"] = {**DEFAULTS, "pair_value_align": "left", "pair_min_gap": 200}
    layout["body"] = [
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "budget": "SUPPLIER_NAME"}
    ]
    layout["field_budgets"]["SUPPLIER_NAME"]["width"] = 1600
    _validate_layout(layout)  # must not raise -- unnarrowed by the 200px min_gap


def test_text_budget_nested_in_a_panel_uses_the_narrowed_width():
    # Panel padding 100 each side narrows 1600 -> 1400; the declared 1500 no longer fits.
    layout = {
        "content_width": 1600,
        "defaults": DEFAULTS,
        "field_budgets": {"SUPPLIER_NAME": {"width": 1500, "fit": "wrap", "min_font": 10, "max_lines": 2}},
        "body": [
            {
                "type": "panel",
                "padding": 100,
                "children": [{"type": "text", "content": "{SUPPLIER_NAME}", "budget": "SUPPLIER_NAME"}],
            }
        ],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "1500" in message and "1400" in message
    assert_diagnostic_error(message)


def test_text_without_budget_is_unaffected_by_budget_validation():
    _validate([{"type": "text", "content": "{SUPPLIER_NAME}"}])


# -- ANZ additions: banner primitive, header_rule_top/header_rule_gap --------


def test_accepts_a_minimal_banner_block():
    _validate([{"type": "banner", "content": "ANZ", "height": 120, "color": "#0061B5"}])


def test_banner_requires_content_height_and_color():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "banner"}])
    message = str(exc_info.value)
    assert "content" in message and "height" in message and "color" in message
    assert_diagnostic_error(message)


def test_banner_rejects_unknown_field_reference():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "banner", "content": "{NOT_A_FIELD}", "height": 120, "color": "#0061B5"}])
    assert "NOT_A_FIELD" in str(exc_info.value)


def test_banner_accepts_its_optional_keys():
    _validate(
        [
            {
                "type": "banner",
                "content": "ANZ",
                "height": 120,
                "color": "#0061B5",
                "text_color": "white",
                "role": "header",
                "text_y": 30,
                "bold": True,
            }
        ]
    )


def test_accepts_header_rule_top_and_header_rule_gap_with_ruled_frame():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "ruled",
            "grouping": "none",
            "header_rule_top": False,
            "header_rule_gap": 14,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    _validate(body)  # must not raise


def test_rejects_header_rule_top_on_a_non_ruled_frame():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "header_rule_top": False,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "header_rule_top" in message and "ruled" in message
    assert_diagnostic_error(message)


def test_rejects_header_rule_gap_on_a_non_ruled_frame():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "bordered",
            "grouping": "none",
            "header_rule_gap": 14,
            "columns": [{"key": "a", "label": "A", "x": 0}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "header_rule_gap" in message and "ruled" in message
    assert_diagnostic_error(message)


# -- line_advance: shape (role -> pixels mapping, not one flat number) and
# role-coverage (every role the body actually resolves through it) checks. --


def test_line_advance_as_a_single_number_is_rejected():
    """A layout author's most natural mistake for a mostly-one-font-size
    document (receipts) -- `line_advance: 20` -- must fail at validate time,
    not silently give every role the same flat advance at render time."""
    layout = {
        "content_width": 1600,
        "defaults": {**DEFAULTS, "line_advance": 25},
        "field_budgets": {},
        "body": [{"type": "rule"}],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "25" in message
    assert "line_advance" in message
    assert_diagnostic_error(message)


def test_line_advance_missing_a_used_role_is_rejected():
    layout = {
        "content_width": 1600,
        "defaults": {**DEFAULTS, "line_advance": {"unused": 0}},
        "field_budgets": {},
        "body": [{"type": "text", "content": "hi", "role": "header"}],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "header" in message
    assert "line_advance" in message
    assert_diagnostic_error(message)


def test_line_advance_missing_role_inside_a_sub_line_is_rejected():
    """A role buried inside a table column's `sub_line` (bank_statements.yml's
    real `sub_line: {role: sub_description}`) must not be invisible to a
    naive top-level-only role scan."""
    layout = {
        "content_width": 1600,
        "defaults": {**DEFAULTS, "line_advance": {"unused": 0}},
        "field_budgets": {},
        "body": [
            {
                "type": "table",
                "rows": "pipe_fields",
                "frame": "plain",
                "grouping": "none",
                "columns": [
                    {
                        "key": "a",
                        "label": "A",
                        "x": 0,
                        "sub_line": {"key": "reference", "role": "sub_description"},
                    }
                ],
            }
        ],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "sub_description" in message
    assert "line_advance" in message
    assert_diagnostic_error(message)


def test_line_advance_role_inside_a_container_is_reached():
    """A role nested inside a panel/split (not just a top-level block) must
    still be caught -- the same reach `_validate_blocks`/`_validate_children`
    give every other structural check."""
    layout = {
        "content_width": 1600,
        "defaults": {**DEFAULTS, "line_advance": {"unused": 0}},
        "field_budgets": {},
        "body": [
            {
                "type": "split",
                "children": [
                    [{"type": "text", "content": "hi", "role": "footer"}],
                    [{"type": "rule"}],
                ],
            }
        ],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert "footer" in str(exc_info.value)


def test_line_advance_block_override_exempts_that_role_from_coverage():
    """A block's own bare-integer line_advance: override means its role is
    never actually looked up in the layout's mapping at render time
    (line_advance()'s block-key-wins resolution) -- so validate_layout must
    not demand the layout cover it either."""
    layout = {
        "content_width": 1600,
        "defaults": {**DEFAULTS, "line_advance": {"unused": 0}},
        "field_budgets": {},
        "body": [{"type": "text", "content": "hi", "role": "header", "line_advance": 61}],
    }
    _validate_layout(layout)  # must not raise


def test_bank_layouts_pass_the_line_advance_checks():
    """The 8 shipped bank layouts must still validate clean under both new
    checks -- see test_every_bank_layout_validates in
    tests/test_bank_dsl_validation.py for the full end-to-end version; this
    one pins it to line_advance specifically."""
    from pathlib import Path

    from generators.loader import load_layout_registry
    from generators.schema import field_names_for

    layout_path = Path("config/layouts/bank_statements.yml")
    known_fields = field_names_for("bank_statements")
    for layout_id, layout in load_layout_registry(layout_path).items():
        assert isinstance(layout["defaults"]["line_advance"], dict), layout_id
        validate_layout(
            layout, layout_id=layout_id, layout_path=str(layout_path), known_fields=known_fields
        )


# -- field_providers: validate_layout checks (Task 9) ------------------------
#
# Throwaway probe registered here, not in generators/layout_dsl/field_providers.py --
# the shipped module carries only the real providers Tasks 10/11 add. Named
# distinctly from tests/layout_dsl/test_field_providers.py's probes since the
# registry is a single process-wide dict shared by the whole `pytest tests/` run.

from generators.layout_dsl.field_providers import field_provider  # noqa: E402


@field_provider("schema_probe", params=frozenset({"suffix"}), emits=("PROBE_A", "PROBE_B"))
def _schema_probe(entry: dict, params: dict) -> dict:
    return {"PROBE_A": "a", "PROBE_B": "b"}


# Deliberately declares the same emit (PROBE_A) as schema_probe -- exists only
# to exercise the provider-versus-provider collision check below.
@field_provider("schema_probe_dup", params=frozenset(), emits=("PROBE_A",))
def _schema_probe_dup(entry: dict, params: dict) -> dict:
    return {"PROBE_A": "dup"}


def _providers_layout(field_providers: list, body: list) -> dict:
    return {
        "content_width": 1600,
        "defaults": DEFAULTS,
        "field_budgets": {},
        "field_providers": field_providers,
        "body": body,
    }


def test_validate_layout_rejects_a_layout_with_no_field_providers_key():
    """field_providers is required -- see engine.py's apply_field_providers and
    the 8 bank layouts, which all set field_providers: [] explicitly. Calls
    validate_layout directly (bypassing _validate_layout's auto-default) on
    BUDGETED_LAYOUT, which has content_width/defaults/field_budgets/body but
    deliberately no field_providers key."""
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            BUDGETED_LAYOUT,
            layout_id="cba_standard",
            layout_path="config/layouts/bank_statements.yml",
            known_fields=FIELDS,
        )
    message = str(exc_info.value)
    assert "field_providers" in message
    assert_diagnostic_error(message)


def test_field_providers_entry_naming_an_unregistered_provider_is_rejected():
    layout = _providers_layout([{"name": "no_such_provider", "params": {}}], [{"type": "rule"}])
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            layout, layout_id="probe", layout_path="config/layouts/receipts.yml", known_fields=FIELDS
        )
    message = str(exc_info.value)
    assert "no_such_provider" in message and "schema_probe" in message
    assert_diagnostic_error(message)


def test_field_providers_entry_with_an_unknown_param_key_is_rejected():
    layout = _providers_layout([{"name": "schema_probe", "params": {"typo_param": 1}}], [{"type": "rule"}])
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            layout, layout_id="probe", layout_path="config/layouts/receipts.yml", known_fields=FIELDS
        )
    message = str(exc_info.value)
    assert "typo_param" in message and "suffix" in message
    assert_diagnostic_error(message)


def test_field_providers_entry_accepts_its_declared_param():
    layout = _providers_layout([{"name": "schema_probe", "params": {"suffix": "!"}}], [{"type": "rule"}])
    validate_layout(
        layout, layout_id="probe", layout_path="config/layouts/receipts.yml", known_fields=FIELDS
    )  # must not raise


def test_a_referenced_providers_emits_resolve_as_known_fields():
    """A {FIELD} naming a value this layout's own field_providers: derives
    must resolve -- known_fields is widened by the provider's emits."""
    layout = _providers_layout(
        [{"name": "schema_probe", "params": {}}],
        [{"type": "text", "content": "{PROBE_A}"}],
    )
    validate_layout(
        layout, layout_id="probe", layout_path="config/layouts/receipts.yml", known_fields=FIELDS
    )  # must not raise


def test_field_providers_declaring_overlapping_emits_is_rejected_at_validate_time():
    """Two providers on one layout declaring the same emits name must fail
    here, from the emits= declarations alone -- statically, before any
    provider is ever called -- so a receipt layout combining receipt_pos,
    receipt_payment, and computed_totals (Tasks 10/11) cannot silently ship
    a page where one provider's value overwrites another's with no error.
    apply_field_providers in field_providers.py keeps a second, defensive
    check at merge time for a caller that bypasses validate_layout (see
    test_apply_field_providers_rejects_two_providers_emitting_the_same_key
    in tests/layout_dsl/test_field_providers.py)."""
    layout = _providers_layout(
        [
            {"name": "schema_probe", "params": {}},
            {"name": "schema_probe_dup", "params": {}},
        ],
        [{"type": "rule"}],
    )
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            layout, layout_id="probe", layout_path="config/layouts/receipts.yml", known_fields=FIELDS
        )
    message = str(exc_info.value)
    assert "PROBE_A" in message
    assert "schema_probe" in message and "schema_probe_dup" in message
    assert_diagnostic_error(message)


def test_an_unreferenced_providers_emits_do_not_resolve_as_known_fields():
    """The permissive-direction trap this check exists to avoid: a provider's
    emits must only widen known_fields for a layout that actually declares
    that provider in field_providers -- never globally for every layout,
    which would let a typo coincidentally matching another layout's derived
    field name silently pass."""
    layout = _providers_layout(
        [],  # schema_probe is registered process-wide but NOT declared here
        [{"type": "text", "content": "{PROBE_A}"}],
    )
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            layout, layout_id="probe", layout_path="config/layouts/receipts.yml", known_fields=FIELDS
        )
    message = str(exc_info.value)
    assert "PROBE_A" in message
    assert_diagnostic_error(message)


# --- pair currency and column prefix keys (Task 14) --------------------------


def test_pair_accepts_the_two_currency_styles():
    for style in ("symbol", "plain"):
        _validate([{"type": "pair", "label": "TOTAL", "value": "{PAYER_NAME}", "currency": style}])


def test_pair_rejects_an_unknown_currency_style():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "pair", "label": "TOTAL", "value": "{PAYER_NAME}", "currency": "dollars"}])
    message = str(exc_info.value)
    assert "dollars" in message
    assert "symbol" in message and "plain" in message
    assert_diagnostic_error(message)


def _prefix_table(**column_overrides) -> list:
    column = {
        "key": "description",
        "label": "Description",
        "align": "left",
        "x": 0,
        "budget": "DESC",
        "field": "SUPPLIER_NAME",
        "prefix_key": "quantity_prefix",
        "prefix_field": "PAYER_NAME",
    }
    column.update(column_overrides)
    for key, value in list(column.items()):
        if value is None:
            del column[key]
    return [
        {
            "type": "table",
            "rows": "pipe_fields",
            "frame": "plain",
            "grouping": "none",
            "columns": [column],
        }
    ]


def test_prefix_keys_are_accepted_on_a_left_budgeted_column():
    _validate(_prefix_table())


def test_prefix_key_without_prefix_field_is_rejected():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(_prefix_table(prefix_field=None))
    message = str(exc_info.value)
    assert "prefix_field" in message
    assert_diagnostic_error(message)


def test_prefix_field_without_prefix_key_is_rejected():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(_prefix_table(prefix_key=None))
    message = str(exc_info.value)
    assert "prefix_key" in message
    assert_diagnostic_error(message)


def test_prefix_keys_are_rejected_on_an_unbudgeted_column():
    """Only `draw_fitted_left` measures a prefix sub-box; an unbudgeted cell
    draws through `draw_text_left`, which would silently record nothing."""
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(_prefix_table(budget=None))
    assert_diagnostic_error(str(exc_info.value))


def test_prefix_keys_are_rejected_on_a_right_aligned_column():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(_prefix_table(align="right", x=None, x_right=0))
    assert "right-aligned" in str(exc_info.value)
    assert_diagnostic_error(str(exc_info.value))


def test_prefix_field_must_name_a_known_field():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(_prefix_table(prefix_field="LINE_ITEM_QUANTITEIS"))
    message = str(exc_info.value)
    assert "LINE_ITEM_QUANTITEIS" in message
    assert_diagnostic_error(message)


# --- known_layout_keys / the dead-key sweep ---------------------------------

_DSL_LAYOUT_FILES = ("bank_statements", "receipts", "invoices")


def _shipped_registry(name: str) -> dict:
    from generators.loader import load_layout_registry

    return load_layout_registry(Path(f"config/layouts/{name}.yml"))


def test_layout_carries_no_key_the_engine_never_reads():
    """The invoice YAML shipped six-column table specs, table_start_y, and per-
    section font sizes that no code path read. A layout key that does nothing is
    worse than no key: it tells an operator the document is configured a way it
    is not."""
    for name in _DSL_LAYOUT_FILES:
        for layout_id, layout in _shipped_registry(name).items():
            unknown = set(layout) - known_layout_keys(layout)
            assert not unknown, f"{name}.yml -> {layout_id} carries unread keys: {sorted(unknown)}"


def test_known_layout_keys_admits_a_from_layout_target():
    """`from_layout:` names an arbitrary layout key, so the permitted set has
    to grow with the body rather than being hand-listed."""
    layout = {"body": [{"type": "text", "from_layout": "footer_text"}]}
    assert "footer_text" in known_layout_keys(layout)
    assert "footer_text" not in known_layout_keys({"body": []})


def test_known_layout_keys_admits_a_suppress_if_equals_target():
    layout = {"body": [{"type": "text", "content": "{PAYER_NAME}", "suppress_if_equals": "logo_text"}]}
    assert "logo_text" in known_layout_keys(layout)


def test_known_layout_keys_reaches_into_panel_and_split_children():
    layout = {
        "body": [
            {
                "type": "panel",
                "children": [
                    {
                        "type": "split",
                        "children": [
                            [{"type": "banner", "from_layout": "nested_banner", "height": 1, "color": "x"}],
                            [{"type": "text", "from_layout": "nested_text"}],
                        ],
                    }
                ],
            }
        ]
    }
    keys = known_layout_keys(layout)
    assert "nested_banner" in keys and "nested_text" in keys


def test_validate_layout_rejects_a_key_nothing_reads():
    layout = {
        "defaults": DEFAULTS,
        "content_width": 100,
        "field_providers": [],
        "body": [{"type": "rule"}],
        "mixed_tax_mode": True,
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            layout,
            layout_id="tax_invoice_mixed",
            layout_path="config/layouts/invoices.yml",
            known_fields=FIELDS,
        )
    message = str(exc_info.value)
    assert "mixed_tax_mode" in message
    assert "config/layouts/invoices.yml" in message
    assert_diagnostic_error(message)


def test_validate_layout_accepts_a_key_the_body_names_via_from_layout():
    layout = {
        "defaults": DEFAULTS,
        "content_width": 100,
        "field_providers": [],
        "footer_text": "Thank you",
        "body": [{"type": "text", "from_layout": "footer_text", "line_advance": 10}],
    }
    validate_layout(
        layout,
        layout_id="receipt_thermal_80mm",
        layout_path="config/layouts/receipts.yml",
        known_fields=FIELDS,
    )
