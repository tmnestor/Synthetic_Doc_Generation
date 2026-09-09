from decimal import Decimal

import pytest
from PIL import Image, ImageDraw

from generators.common import load_font
from generators.exporters.geometry import BoxRecorder
from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.defaults import PARAMETER_DEFAULTS
from generators.layout_dsl.primitives_table import TableError, _draw_row, column_x, draw_table
from conftest import assert_diagnostic_error

# A complete, literal-transcribed defaults: mapping (matching bank_statements.yml's
# shared _dsl_defaults_values anchor), so a block that omits a parameter still
# resolves through the layout rather than raising DefaultsError.
DEFAULTS = {
    "role": "body",
    "color": "black",
    "align": "left",
    "bold": False,
    "family": "carlito",
    # Per-role mapping (matching bank_statements.yml's shape): int(size * 1.4)
    # for LAYOUT's font_sizes (body 32, footer 18).
    "line_advance": {"body": 44, "footer": 25},
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

LAYOUT = {
    "font_sizes": {"body": 32, "footer": 18},
    "row_height": 72,
    "field_budgets": {
        "TRANSACTION_DESC": {"width": 760, "fit": "wrap", "min_font": 10, "max_lines": 2},
    },
    "defaults": DEFAULTS,
}

ENTRY = {
    "fields": {
        "TRANSACTION_DATES": "01/07/2024|02/07/2024",
        "TRANSACTION_DESCRIPTIONS": "ATM WITHDRAWAL|SALARY",
        "TRANSACTION_AMOUNTS_PAID": "100.00|NOT_FOUND",
        "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|500.00",
        "ACCOUNT_BALANCE": "1400.00",
    }
}

COLUMNS = [
    {"key": "date", "label": "Date", "align": "left", "x": 0},
    {
        "key": "description",
        "label": "Description",
        "align": "left",
        "x": 200,
        "budget": "TRANSACTION_DESC",
        "field": "TRANSACTION_DESCRIPTIONS",
    },
    {"key": "debit", "label": "Withdrawal", "align": "right", "x_right": -420},
    {"key": "balance", "label": "Balance", "align": "right", "x_right": 0},
]

# Mirrors a real bank layout: right-aligned amount columns carry their own
# `field`, and the balance column additionally carries `last_row_field` for
# the once-only closing-balance record legacy renderers emit.
COLUMNS_WITH_AMOUNT_FIELDS = [
    {"key": "date", "label": "Date", "align": "left", "x": 0},
    {
        "key": "description",
        "label": "Description",
        "align": "left",
        "x": 200,
        "budget": "TRANSACTION_DESC",
        "field": "TRANSACTION_DESCRIPTIONS",
    },
    {
        "key": "debit",
        "label": "Withdrawal",
        "align": "right",
        "x_right": -620,
        "field": "TRANSACTION_AMOUNTS_PAID",
    },
    {
        "key": "credit",
        "label": "Deposit",
        "align": "right",
        "x_right": -420,
        "field": "TRANSACTION_AMOUNTS_RECEIVED",
    },
    {
        "key": "balance",
        "label": "Balance",
        "align": "right",
        "x_right": 0,
        "last_row_field": "ACCOUNT_BALANCE",
    },
]


def _ctx(recorder: BoxRecorder | None = None, layout: dict = LAYOUT) -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry=ENTRY,
        layout=layout,
        layout_id="cba_standard",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        recorder=recorder,
    )


def test_column_x_resolves_left_offset():
    assert column_x({"x": 200}, _ctx()) == 300


def test_column_x_resolves_right_offset():
    assert column_x({"x_right": -420}, _ctx()) == 1280


def test_table_advances_by_header_plus_rows():
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS,
    }
    end = draw_table(block, _ctx(), 500)
    assert end > 500 + 2 * LAYOUT["row_height"]


def test_table_records_each_row_description():
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    assert "TRANSACTION_DESCRIPTIONS[0]" in boxes
    assert "TRANSACTION_DESCRIPTIONS[1]" in boxes


def test_synthetic_opening_row_is_not_recorded():
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "params": {"opening_balance": True, "opening_balance_label": "Opening Balance"},
        "columns": COLUMNS,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    # Two real transactions only; the synthetic row has no ground-truth identity.
    assert sorted(k for k in boxes if k.startswith("TRANSACTION_DESCRIPTIONS")) == [
        "TRANSACTION_DESCRIPTIONS[0]",
        "TRANSACTION_DESCRIPTIONS[1]",
    ]


def test_synthetic_opening_row_does_not_shift_real_row_indices():
    """Inserting the synthetic opening row must not renumber the real rows beneath it."""
    without_opening = BoxRecorder(1800, 3508)
    with_opening = BoxRecorder(1800, 3508)
    base_block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS,
    }
    opening_block = {
        **base_block,
        "params": {"opening_balance": True, "opening_balance_label": "Opening Balance"},
    }

    draw_table(base_block, _ctx(without_opening), 500)
    draw_table(opening_block, _ctx(with_opening), 500)

    plain_keys = sorted(k for k in without_opening.as_dict() if k.startswith("TRANSACTION_DESCRIPTIONS"))
    opening_keys = sorted(k for k in with_opening.as_dict() if k.startswith("TRANSACTION_DESCRIPTIONS"))
    assert plain_keys == opening_keys == ["TRANSACTION_DESCRIPTIONS[0]", "TRANSACTION_DESCRIPTIONS[1]"]


def test_decimal_cells_format_as_amounts():
    from generators.common import fmt_amount

    assert fmt_amount(Decimal("1400.00")) == fmt_amount(Decimal("1400.0"))


@pytest.mark.parametrize(
    ("frame", "grouping"),
    [
        ("ruled", "none"),
        ("bordered", "none"),
        ("bordered", "inline"),
        ("plain", "dedicated_row"),
        ("plain", "none"),
    ],
)
def test_every_frame_and_grouping_combination_renders(frame: str, grouping: str):
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": frame,
        "grouping": grouping,
        "columns": COLUMNS,
    }
    assert draw_table(block, _ctx(), 500) > 500


def test_missing_row_height_raises_diagnostic_with_four_elements():
    layout_without_row_height = {
        "font_sizes": {"body": 32, "footer": 18},
        "field_budgets": LAYOUT["field_budgets"],
        "defaults": DEFAULTS,
    }
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS,
    }
    with pytest.raises(TableError) as exc_info:
        draw_table(block, _ctx(layout=layout_without_row_height), 500)

    message = str(exc_info.value)
    assert "What:" in message
    assert "Where:" in message
    assert "Expected:" in message
    assert "Recover:" in message


def _grouped_inset_block(**extra) -> dict:
    return {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "dedicated_row",
        "columns": COLUMNS,
        **extra,
    }


def test_dedicated_row_grouping_with_a_row_inset_is_rejected():
    """An inset moves the cells but not the bold date sub-header row grouping
    inserts, so the two together have no defined meaning."""
    with pytest.raises(TableError) as exc_info:
        draw_table(_grouped_inset_block(row_inset_y=12), _ctx(), 500)
    message = str(exc_info.value)
    assert "dedicated_row" in message and "row_inset_y" in message
    assert_diagnostic_error(message)


def test_dedicated_row_grouping_rejects_an_inset_inherited_from_the_layout():
    """The block need not carry the inset itself: `defaults.table_row_inset_y`
    reaches the same code, which is why this cannot live in schema.py's
    `_validate_table` (it never sees the layout's defaults)."""
    layout = {**LAYOUT, "defaults": {**DEFAULTS, "table_row_inset_y": 12}}
    with pytest.raises(TableError) as exc_info:
        draw_table(_grouped_inset_block(), _ctx(layout=layout), 500)
    assert_diagnostic_error(str(exc_info.value))


def test_dedicated_row_grouping_accepts_a_zero_inset():
    assert draw_table(_grouped_inset_block(row_inset_y=0), _ctx(), 500) > 500


def test_a_row_inset_is_still_allowed_without_dedicated_row_grouping():
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "row_inset_y": 12,
        "columns": COLUMNS,
    }
    assert draw_table(block, _ctx(), 500) > 500


def test_block_row_height_used_when_layout_omits_it():
    layout_without_row_height = {
        "font_sizes": {"body": 32, "footer": 18},
        "field_budgets": LAYOUT["field_budgets"],
        "defaults": DEFAULTS,
    }
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "row_height": 60,
        "columns": COLUMNS,
    }
    end = draw_table(block, _ctx(layout=layout_without_row_height), 500)
    assert end > 500 + 2 * 60


def test_debit_cell_renders_with_currency_formatting():
    """A debit cell must be drawn with the same glyphs as fmt_amount, not the raw string.

    The bank_transactions provider coerces real (non-sentinel) debit/credit
    amounts to Decimal so _cell_text formats them through fmt_amount, matching
    the legacy renderer's `$100.00` rather than a bare `100.00`.
    """
    from generators.common import fmt_amount

    drawn: list[str] = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append(text)
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    assert fmt_amount(Decimal("100.00")) in drawn
    assert "100.00" not in drawn


def test_right_aligned_column_with_field_records_geometry():
    """Right-aligned amount columns must record geometry, same as the description column."""
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    # Row 0 has a debit (100.00) and NOT_FOUND credit; row 1 the reverse.
    assert "TRANSACTION_AMOUNTS_PAID[0]" in boxes
    assert "TRANSACTION_AMOUNTS_RECEIVED[1]" in boxes


def test_synthetic_row_records_no_amount_geometry():
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "params": {"opening_balance": True, "opening_balance_label": "Opening Balance"},
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    assert sorted(k for k in boxes if k.startswith("TRANSACTION_AMOUNTS_PAID")) == [
        "TRANSACTION_AMOUNTS_PAID[0]",
    ]
    assert sorted(k for k in boxes if k.startswith("TRANSACTION_AMOUNTS_RECEIVED")) == [
        "TRANSACTION_AMOUNTS_RECEIVED[1]",
    ]


def test_amount_field_index_stability_with_and_without_synthetic_row():
    """Real rows must keep identical FIELD[i] keys whether or not a synthetic row precedes them."""
    without_opening = BoxRecorder(1800, 3508)
    with_opening = BoxRecorder(1800, 3508)
    base_block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    opening_block = {
        **base_block,
        "params": {"opening_balance": True, "opening_balance_label": "Opening Balance"},
    }

    draw_table(base_block, _ctx(without_opening), 500)
    draw_table(opening_block, _ctx(with_opening), 500)

    plain_keys = sorted(without_opening.as_dict())
    opening_keys = sorted(with_opening.as_dict())
    assert plain_keys == opening_keys


def test_right_aligned_budgeted_column_is_not_silently_ignored():
    """A `budget` on a right-aligned column must actually fit/record, not go inert."""
    recorder = BoxRecorder(1800, 3508)
    columns = [
        {"key": "date", "label": "Date", "align": "left", "x": 0},
        {
            "key": "description",
            "label": "Description",
            "align": "left",
            "x": 200,
            "budget": "TRANSACTION_DESC",
            "field": "TRANSACTION_DESCRIPTIONS",
        },
        {
            "key": "balance",
            "label": "Balance",
            "align": "right",
            "x_right": 0,
            "budget": "TRANSACTION_DESC",
            "field": "ACCOUNT_BALANCE",
        },
    ]
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": columns,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    assert "ACCOUNT_BALANCE[0]" in boxes
    assert "ACCOUNT_BALANCE[1]" in boxes


def test_last_row_field_records_once_unindexed_on_final_real_row():
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    assert "ACCOUNT_BALANCE" in boxes
    # Unindexed — not a per-row record.
    assert "ACCOUNT_BALANCE[0]" not in boxes
    assert "ACCOUNT_BALANCE[1]" not in boxes


def test_last_row_field_still_targets_the_final_real_row_with_synthetic_prepended():
    """A prepended synthetic row must not shift which row counts as 'last'.

    Absolute pixel position legitimately shifts down by one row height (the
    synthetic row occupies space above it) -- the invariant under test is
    that the closing balance is still recorded exactly once, unindexed, and
    that its horizontal extent (unaffected by the vertical shift) matches.
    """
    without_opening = BoxRecorder(1800, 3508)
    with_opening = BoxRecorder(1800, 3508)
    base_block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    opening_block = {
        **base_block,
        "params": {"opening_balance": True, "opening_balance_label": "Opening Balance"},
    }

    draw_table(base_block, _ctx(without_opening), 500)
    draw_table(opening_block, _ctx(with_opening), 500)

    plain_box = without_opening.as_dict()["ACCOUNT_BALANCE"]
    opening_box = with_opening.as_dict()["ACCOUNT_BALANCE"]
    assert (plain_box[0], plain_box[2]) == (opening_box[0], opening_box[2])  # left, right unchanged
    assert opening_box[1] > plain_box[1]  # top shifted down by exactly the synthetic row


def test_frame_and_grouping_axes_compose_into_distinct_output():
    """Neither axis may be a no-op, and combinations must not collapse onto each other.

    This replaces the old single-enum "every style draws differently" check:
    with two independent axes, distinctness has to be demonstrated across
    combinations, not just across a flat list of named styles.
    """

    def _draw_calls(block):
        counts = {"rectangle": 0, "line": 0}
        ctx = _ctx()
        ctx.draw.rectangle = lambda *a, **k: counts.__setitem__("rectangle", counts["rectangle"] + 1)
        ctx.draw.line = lambda *a, **k: counts.__setitem__("line", counts["line"] + 1)
        draw_table(block, ctx, 500)
        return counts

    def _block(frame, grouping, **extra):
        return {
            "type": "table",
            "rows": "bank_transactions",
            "frame": frame,
            "grouping": grouping,
            "columns": COLUMNS,
            **extra,
        }

    plain_none = _draw_calls(_block("plain", "none"))
    bordered_none = _draw_calls(_block("bordered", "none"))
    ruled_none = _draw_calls(_block("ruled", "none"))
    filled_dedicated = _draw_calls(_block("filled", "dedicated_row", fill_color="#E8F0FE"))

    # The frame axis: plain draws no rectangles; bordered and filled both do,
    # by different means (outline vs. fill), and ruled draws more lines than plain.
    assert plain_none["rectangle"] == 0
    assert bordered_none["rectangle"] > 0
    assert filled_dedicated["rectangle"] > 0
    assert ruled_none["line"] > plain_none["line"]

    # The grouping axis, independent of frame: on data where every row's date
    # changes, dedicated_row inserts a date sub-header row that none/inline
    # do not, so it must advance further for the same frame.
    plain_dedicated_end = draw_table(_block("plain", "dedicated_row"), _ctx(), 500)
    plain_none_end = draw_table(_block("plain", "none"), _ctx(), 500)
    assert plain_dedicated_end > plain_none_end

    bordered_inline_end = draw_table(_block("bordered", "inline"), _ctx(), 500)
    assert bordered_inline_end != plain_dedicated_end  # frame changes geometry too


# -- Westpac additions: bordered_grouped, dividers, plain-currency cells -----

ENTRY_SAME_DATE_GROUP = {
    "fields": {
        "TRANSACTION_DATES": "01/07/2024|01/07/2024|02/07/2024",
        "TRANSACTION_DESCRIPTIONS": "ATM WITHDRAWAL|COFFEE|SALARY",
        "TRANSACTION_AMOUNTS_PAID": "100.00|5.00|NOT_FOUND",
        "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|NOT_FOUND|500.00",
        "ACCOUNT_BALANCE": "1400.00",
    }
}

WESTPAC_COLUMNS = [
    {"key": "date", "label": "Date of\nTransaction", "align": "left", "x": 8},
    {
        "key": "description",
        "label": "Description",
        "align": "left",
        "x": 208,
        "budget": "TRANSACTION_DESC",
        "field": "TRANSACTION_DESCRIPTIONS",
    },
    {
        "key": "debit",
        "label": "Debits",
        "align": "right",
        "x_right": -168,
        "field": "TRANSACTION_AMOUNTS_PAID",
        "currency": "plain",
    },
    {
        "key": "credit",
        "label": "Credits (-)",
        "align": "right",
        "x_right": -8,
        "field": "TRANSACTION_AMOUNTS_RECEIVED",
        "currency": "plain",
    },
]

WESTPAC_DIVIDERS = [{"x": 200}, {"x_right": -320}, {"x_right": -160}]


def _westpac_ctx(recorder: BoxRecorder | None = None, entry: dict = ENTRY_SAME_DATE_GROUP):
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry=entry,
        layout={
            **LAYOUT,
            "font_sizes": {"body": 28, "footer": 16, "header": 44},
            "row_height": 62,
            # Real westpac_standard's own line_advance mapping (config/layouts/
            # bank_statements.yml): int(28 * 1.4) = 39 for body, distinct from
            # LAYOUT's body-32-derived 44.
            "defaults": {**DEFAULTS, "line_advance": {"body": 39, "footer": 22, "header": 61}},
        },
        layout_id="westpac_standard",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=80, width=1600),
        recorder=recorder,
    )


def test_currency_plain_strips_dollar_sign():
    """A `currency: plain` column must drop the $ prefix fmt_amount otherwise adds."""
    drawn: list[str] = []
    ctx = _westpac_ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append(text)
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "bordered",
        "grouping": "none",
        "columns": WESTPAC_COLUMNS,
    }
    draw_table(block, ctx, 500)

    assert "100.00" in drawn
    assert "$100.00" not in drawn


def test_inline_grouping_blanks_repeated_date_and_skips_its_divider():
    """Two same-date rows: the second must draw no date text and no divider above it."""
    date_calls: list[str] = []
    line_calls = 0
    ctx = _westpac_ctx()
    original_text = ctx.draw.text
    original_line = ctx.draw.line

    def spy_text(xy, text, **kwargs):
        date_calls.append(text)
        return original_text(xy, text, **kwargs)

    def spy_line(*a, **k):
        nonlocal line_calls
        line_calls += 1
        return original_line(*a, **k)

    ctx.draw.text = spy_text
    ctx.draw.line = spy_line
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "bordered",
        "grouping": "inline",
        "columns": WESTPAC_COLUMNS,
    }
    draw_table(block, ctx, 500)

    assert date_calls.count("01/07/2024") == 1  # only the first of the two same-date rows
    assert date_calls.count("02/07/2024") == 1


def test_inline_grouping_does_not_insert_a_dedicated_date_row():
    """Unlike `dedicated_row`, `inline` grouping must draw exactly one row per transaction."""
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "bordered",
        "grouping": "inline",
        "columns": WESTPAC_COLUMNS,
    }
    end = draw_table(block, _westpac_ctx(), 500)
    # header (default line_advance=39, westpac_standard's own value) + 3
    # transactions * row_height(62) each -- no extra date-only row, no gap,
    # unlike `dedicated_row` grouping.
    assert end == 500 + 39 + 3 * 62


def test_dividers_are_drawn_across_header_and_body():
    """Divider x-positions must appear as vertical line calls spanning the table."""
    xs_drawn: list[int] = []
    ctx = _westpac_ctx()
    original_line = ctx.draw.line

    def spy_line(points, **kwargs):
        (x1, _y1), (x2, _y2) = points
        if x1 == x2:
            xs_drawn.append(x1)
        return original_line(points, **kwargs)

    ctx.draw.line = spy_line
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "bordered",
        "grouping": "none",
        "header_height": 72,
        "dividers": WESTPAC_DIVIDERS,
        "columns": WESTPAC_COLUMNS,
    }
    draw_table(block, ctx, 500)

    # Divider absolute x positions: region.x=80, region.right=1680.
    assert 280 in xs_drawn  # {x: 200}
    assert 1360 in xs_drawn  # {x_right: -320}
    assert 1520 in xs_drawn  # {x_right: -160}


def test_multiline_header_label_draws_each_line():
    drawn: list[str] = []
    ctx = _westpac_ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append(text)
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "bordered",
        "grouping": "none",
        "header_height": 72,
        "columns": WESTPAC_COLUMNS,
    }
    draw_table(block, ctx, 500)

    assert "Date of" in drawn
    assert "Transaction" in drawn


# -- NAB-style additions: the `filled` frame -----------------------------


def test_filled_frame_fills_the_header_bar_with_fill_color():
    """The header bar itself must be filled with fill_color, not merely outlined."""
    fills: list[str] = []
    ctx = _ctx()
    original_rectangle = ctx.draw.rectangle

    def spy_rectangle(xy, **kwargs):
        if "fill" in kwargs:
            fills.append(kwargs["fill"])
        return original_rectangle(xy, **kwargs)

    ctx.draw.rectangle = spy_rectangle
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "dedicated_row",
        "fill_color": "#E8F0FE",
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    assert "#E8F0FE" in fills


def test_filled_frame_fills_each_dedicated_group_row_not_only_the_header():
    """NAB fills the header bar AND each date sub-header row it inserts.

    ENTRY has two distinct dates, so dedicated_row grouping inserts two date
    sub-header rows; each must be filled in addition to the header bar.
    """
    fill_rectangle_count = 0
    ctx = _ctx()
    original_rectangle = ctx.draw.rectangle

    def spy_rectangle(xy, **kwargs):
        nonlocal fill_rectangle_count
        if kwargs.get("fill") == "#E8F0FE":
            fill_rectangle_count += 1
        return original_rectangle(xy, **kwargs)

    ctx.draw.rectangle = spy_rectangle
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "dedicated_row",
        "fill_color": "#E8F0FE",
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    # One fill for the header bar, plus one per distinct date (two, in ENTRY).
    assert fill_rectangle_count == 3


def test_filled_frame_with_none_grouping_only_fills_the_header():
    """No dedicated row exists without dedicated_row grouping, so nothing else fills."""
    fill_rectangle_count = 0
    ctx = _ctx()
    original_rectangle = ctx.draw.rectangle

    def spy_rectangle(xy, **kwargs):
        nonlocal fill_rectangle_count
        if kwargs.get("fill") == "#E8F0FE":
            fill_rectangle_count += 1
        return original_rectangle(xy, **kwargs)

    ctx.draw.rectangle = spy_rectangle
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "none",
        "fill_color": "#E8F0FE",
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    assert fill_rectangle_count == 1


def test_filled_frame_draws_no_dividers():
    """NAB's header bar has no interior column dividers, unlike `bordered`."""
    line_calls = 0
    ctx = _ctx()
    original_line = ctx.draw.line

    def spy_line(*a, **k):
        nonlocal line_calls
        line_calls += 1
        return original_line(*a, **k)

    ctx.draw.line = spy_line
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "none",
        "fill_color": "#E8F0FE",
        "dividers": [{"x": 200}],
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    assert line_calls == 0


# -- Fix round 1: fill_inset, fill_height, label_inset_y ------------------
#
# All three default to exactly today's behaviour when absent -- these tests
# pair each key's absent case (unchanged geometry) with its present case
# (the declared override actually takes effect), per NAB's real header bar
# (44px fill, 50px advance, labels at y+10) and date-group rows (row_height
# - 2px fill), which the primitive could not express before this round.


def _rectangle_fills(ctx, *, color="#E8F0FE"):
    """Spy on ctx.draw.rectangle, returning (top_left, bottom_right) for
    every call whose `fill` matches `color`, in draw order."""
    fills = []
    original_rectangle = ctx.draw.rectangle

    def spy_rectangle(xy, **kwargs):
        if kwargs.get("fill") == color:
            fills.append(xy)
        return original_rectangle(xy, **kwargs)

    ctx.draw.rectangle = spy_rectangle
    return fills


def test_fill_inset_absent_leaves_the_group_row_fill_at_full_row_height():
    ctx = _ctx()
    fills = _rectangle_fills(ctx)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "dedicated_row",
        "fill_color": "#E8F0FE",
        "header": False,
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    (top_left, bottom_right) = fills[0]
    assert bottom_right[1] - top_left[1] == LAYOUT["row_height"]


def test_fill_inset_shrinks_the_group_row_fill_by_the_given_pixels():
    ctx = _ctx()
    fills = _rectangle_fills(ctx)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "dedicated_row",
        "fill_color": "#E8F0FE",
        "fill_inset": 2,
        "header": False,
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    (top_left, bottom_right) = fills[0]
    assert bottom_right[1] - top_left[1] == LAYOUT["row_height"] - 2


def test_fill_height_absent_fills_the_full_header_height():
    ctx = _ctx()
    fills = _rectangle_fills(ctx)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "none",
        "fill_color": "#E8F0FE",
        "header_height": 50,
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    (top_left, bottom_right) = fills[0]
    assert bottom_right[1] - top_left[1] == 50


def test_fill_height_overrides_the_fill_without_changing_the_row_advance():
    """NAB fills a 44px bar but advances 50px -- header_height alone cannot express that gap."""
    drawn_y: list[int] = []
    ctx = _ctx()
    fills = _rectangle_fills(ctx)
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn_y.append(xy[1])
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "none",
        "fill_color": "#E8F0FE",
        "header_height": 50,
        "fill_height": 44,
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    (top_left, bottom_right) = fills[0]
    assert bottom_right[1] - top_left[1] == 44  # the bar itself is 44px, not 50px
    # The first data-row text (drawn right after the header labels) still
    # starts at 500 + 50, not 500 + 44 -- the advance is untouched.
    header_label_count = len(COLUMNS)
    assert drawn_y[header_label_count] == 500 + 50


def test_label_inset_y_absent_uses_computed_centring():
    """Unchanged default: filled/bordered headers centre the label block."""
    drawn_y: list[int] = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn_y.append(xy[1])
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "none",
        "fill_color": "#E8F0FE",
        "header_height": 44,
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    advance = LAYOUT["defaults"]["line_advance"]["body"]
    expected = 500 + max(0, (44 - advance) // 2)
    assert drawn_y[0] == expected


# -- NAB-style additions round 2: group_gap, synthetic_row_placement,
# sub_line, currency_suffix, and positional (not "last real row") is_last. --

ENTRY_TWO_GROUPS = {
    "fields": {
        "TRANSACTION_DATES": "01/07/2024|01/07/2024|02/07/2024",
        "TRANSACTION_DESCRIPTIONS": "ATM WITHDRAWAL|COFFEE|SALARY",
        "TRANSACTION_AMOUNTS_PAID": "100.00|5.00|NOT_FOUND",
        "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|NOT_FOUND|500.00",
        "ACCOUNT_BALANCE": "1400.00",
    }
}


def _ctx_two_groups(recorder: BoxRecorder | None = None) -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry=ENTRY_TWO_GROUPS,
        layout=LAYOUT,
        layout_id="nab_classic",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        recorder=recorder,
    )


def test_group_gap_default_matches_the_old_hardcoded_ten_pixels():
    """Absent group_gap must reproduce today's CBA behaviour exactly (10px)."""
    block_with_gap = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "dedicated_row",
        "columns": COLUMNS,
    }
    block_zero_gap = {**block_with_gap, "group_gap": 0}

    end_default = draw_table(block_with_gap, _ctx_two_groups(), 500)
    end_zero = draw_table(block_zero_gap, _ctx_two_groups(), 500)
    assert end_default - end_zero == 10


def test_group_gap_zero_matches_nabs_real_behaviour():
    """NAB's legacy renderer inserts no gap between consecutive date groups."""
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "dedicated_row",
        "group_gap": 0,
        "columns": COLUMNS,
    }
    end = draw_table(block, _ctx_two_groups(), 500)
    header = LAYOUT["defaults"]["line_advance"]["body"]
    row_height = LAYOUT["row_height"]
    # header + 2 group headers + 3 transaction rows, no gap between groups.
    assert end == 500 + header + 2 * row_height + 3 * row_height


def test_synthetic_row_placement_defaults_to_leading():
    """Absent synthetic_row_placement: the synthetic row renders before any group header."""
    drawn: list[str] = []
    ctx = _ctx_two_groups()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append(text)
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "dedicated_row",
        "params": {"opening_balance": True, "opening_balance_label": "Opening Balance"},
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)
    # The synthetic row's own description comes before the first date group header.
    assert drawn.index("Opening Balance") < drawn.index("01/07/2024")


def test_synthetic_row_placement_after_first_group_header():
    """NAB's real order: the group header for the first date, then Brought forward."""
    drawn: list[str] = []
    ctx = _ctx_two_groups()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append(text)
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "dedicated_row",
        "synthetic_row_placement": "after_first_group_header",
        "params": {"brought_forward": True, "brought_forward_label": "Balance Brought Forward"},
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)
    assert drawn.index("01/07/2024") < drawn.index("Balance Brought Forward")


def test_synthetic_row_placement_after_first_group_header_is_not_recorded():
    """The deferred synthetic row still carries no ground-truth identity."""
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "dedicated_row",
        "synthetic_row_placement": "after_first_group_header",
        "params": {"brought_forward": True, "brought_forward_label": "Balance Brought Forward"},
        "columns": COLUMNS,
    }
    draw_table(block, _ctx_two_groups(recorder), 500)
    boxes = recorder.as_dict()
    assert sorted(k for k in boxes if k.startswith("TRANSACTION_DESCRIPTIONS")) == [
        "TRANSACTION_DESCRIPTIONS[0]",
        "TRANSACTION_DESCRIPTIONS[1]",
        "TRANSACTION_DESCRIPTIONS[2]",
    ]


def test_currency_suffix_appends_after_the_formatted_amount():
    drawn: list[str] = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append(text)
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    columns = [
        {"key": "date", "label": "Date", "align": "left", "x": 0},
        {"key": "balance", "label": "Balance", "align": "right", "x_right": 0, "currency_suffix": "Cr"},
    ]
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": columns,
    }
    draw_table(block, ctx, 500)

    from generators.common import fmt_amount

    assert f"{fmt_amount(Decimal('1400.00'))} Cr" in drawn


def test_bold_row_uses_bold_font_for_unbudgeted_cells():
    """A row provider marks with `bold: True` (e.g. carried_forward) draws in bold,
    unlike ordinary rows -- traced against legacy's font_body_bold Carried-forward row."""
    from generators.common import load_font

    fonts_used: list = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        fonts_used.append(kwargs.get("font"))
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    columns = [
        {"key": "date", "label": "Date", "align": "left", "x": 0},
        {"key": "balance", "label": "Balance", "align": "right", "x_right": 0, "currency_suffix": "Cr"},
    ]
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "header": False,
        "params": {"carried_forward": True, "carried_forward_label": "Carried forward"},
        "columns": columns,
    }
    draw_table(block, ctx, 500)

    bold_font = load_font(LAYOUT["font_sizes"]["body"], family=DEFAULTS["family"], bold=True)
    regular_font = load_font(LAYOUT["font_sizes"]["body"], family=DEFAULTS["family"], bold=False)

    # ENTRY has 2 real transactions (date+balance each = 4 calls), then the
    # trailing Carried-forward row draws only its balance (date is blank).
    assert len(fonts_used) == 5
    assert fonts_used[0] is regular_font  # txn 0's date
    assert fonts_used[3] is regular_font  # txn 1's balance
    assert fonts_used[-1] is bold_font  # Carried forward's balance


def test_bold_row_threads_through_the_budgeted_path_too():
    """A budgeted (fitted) cell must also honour the row's bold flag, not just plain cells."""
    from generators.common import load_font

    fonts_used: list = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        fonts_used.append((text, kwargs.get("font")))
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    columns = [
        {
            "key": "description",
            "label": "Particulars",
            "align": "left",
            "x": 0,
            "budget": "TRANSACTION_DESC",
        },
    ]
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "header": False,
        "params": {"carried_forward": True, "carried_forward_label": "Carried forward"},
        "columns": columns,
    }
    draw_table(block, ctx, 500)

    bold_font = load_font(LAYOUT["font_sizes"]["body"], family=DEFAULTS["family"], bold=True)
    carried_forward_calls = [font for text, font in fonts_used if text == "Carried forward"]
    assert carried_forward_calls == [bold_font]


def test_rows_without_a_bold_key_render_regular_as_before():
    """Absent `bold` on a row (every row type except carried_forward): unchanged behaviour."""
    from generators.common import load_font

    fonts_used: list = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        fonts_used.append(kwargs.get("font"))
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "header": False,
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    regular_font = load_font(LAYOUT["font_sizes"]["body"], family=DEFAULTS["family"], bold=False)
    assert all(font is regular_font for font in fonts_used)


def test_currency_suffix_absent_by_default():
    """COLUMNS' balance column has no currency_suffix -- must render unchanged."""
    drawn: list[str] = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append(text)
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    from generators.common import fmt_amount

    assert fmt_amount(Decimal("1400.00")) in drawn
    assert f"{fmt_amount(Decimal('1400.00'))} Cr" not in drawn


def test_is_last_targets_a_trailing_synthetic_row_over_the_last_real_row():
    """carried_forward's trailing row -- not the last transaction -- gets last_row_field."""
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "params": {"carried_forward": True, "carried_forward_label": "Carried forward"},
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    assert "ACCOUNT_BALANCE" in boxes
    # Still exactly one record, unindexed -- not on the real rows.
    assert "ACCOUNT_BALANCE[0]" not in boxes
    assert "ACCOUNT_BALANCE[1]" not in boxes


def test_is_last_without_carried_forward_still_targets_the_last_real_row():
    """No trailing synthetic row: unchanged behaviour, same as before this round."""
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    draw_table(block, _ctx(recorder), 500)
    assert "ACCOUNT_BALANCE" in recorder.as_dict()


def test_sub_line_draws_beneath_the_main_cell_and_extends_row_height():
    """A column's sub_line renders its own text and adds its declared height once."""
    entry = {
        "fields": {
            "TRANSACTION_DATES": "01/07/2024",
            "TRANSACTION_DESCRIPTIONS": "ATM WITHDRAWAL",
            "TRANSACTION_AMOUNTS_PAID": "100.00",
            "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND",
            "ACCOUNT_BALANCE": "900.00",
        }
    }
    image = Image.new("RGB", (1800, 3508), "white")
    ctx = RenderContext(
        draw=ImageDraw.Draw(image),
        entry=entry,
        layout=LAYOUT,
        layout_id="nab_classic",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
    )
    drawn: list[tuple] = []
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append((xy, text, kwargs.get("fill")))
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    columns = [
        {"key": "date", "label": "Date", "align": "left", "x": 0},
        {
            "key": "description",
            "label": "Particulars",
            "align": "left",
            "x": 180,
            "sub_line": {
                "key": "reference",
                "role": "footer",
                "color": "#999999",
                "offset_y": 34,
                "height": 32,
            },
        },
    ]
    params = {
        "references": True,
        "reference_prefix": "Ref: ",
        "reference_pad_char": ".",
        "reference_pad_width": 40,
    }
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "header": False,
        "params": params,
        "columns": columns,
    }
    end = draw_table(block, ctx, 500)

    ref_calls = [(xy, text) for xy, text, fill in drawn if text.startswith("Ref: ")]
    assert len(ref_calls) == 1
    (x, y), text = ref_calls[0]
    assert x == 100 + 180  # same column anchor as the description cell.
    assert y == 500 + 34  # row's own start y (header:False, so the row starts at 500) + offset_y.
    assert end == 500 + LAYOUT["row_height"] + 32  # row_height floor + the sub_line's declared height.


def test_sub_line_absent_when_row_has_no_data_for_its_key():
    """Without `references: true`, no row carries a `reference` key -- no sub_line, no extra height."""
    columns = [
        {"key": "date", "label": "Date", "align": "left", "x": 0},
        {
            "key": "description",
            "label": "Particulars",
            "align": "left",
            "x": 180,
            "sub_line": {"key": "reference", "height": 32},
        },
    ]
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "header": False,
        "columns": columns,
    }
    end = draw_table(block, _ctx(), 500)
    assert end == 500 + 2 * LAYOUT["row_height"]  # no +32 anywhere -- two ordinary rows.


def test_label_inset_y_overrides_computed_centring():
    """NAB's real offset (y+10 inside a 44px bar) the centring formula cannot reproduce."""
    drawn_y: list[int] = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn_y.append(xy[1])
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "filled",
        "grouping": "none",
        "fill_color": "#E8F0FE",
        "header_height": 44,
        "label_inset_y": 10,
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)

    assert drawn_y[0] == 510
    assert drawn_y[: len(COLUMNS)] == [510] * len(COLUMNS)


# -- ANZ additions: header_rule_top/gap, rule_above, no more per-row ruled line --


def test_ruled_frame_draws_no_line_under_each_row():
    """Legacy CBA and ANZ both draw zero per-row rules; only NAB/Westpac's own
    frames (filled/bordered) decorate individual rows."""
    lines: list[tuple] = []
    ctx = _ctx()
    original_line = ctx.draw.line

    def spy_line(xy, **kwargs):
        lines.append(kwargs.get("fill"))
        return original_line(xy, **kwargs)

    ctx.draw.line = spy_line
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "ruled",
        "grouping": "none",
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)
    # Exactly the header's own pre/post rules (both black) -- never the old
    # #CCCCCC per-row line, which no legacy renderer using `ruled` draws.
    assert lines == ["black", "black"]


def test_header_rule_top_false_skips_the_rule_above_the_labels():
    lines: list[tuple] = []
    ctx = _ctx()
    original_line = ctx.draw.line

    def spy_line(xy, **kwargs):
        lines.append(xy)
        return original_line(xy, **kwargs)

    ctx.draw.line = spy_line
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "ruled",
        "grouping": "none",
        "header_rule_top": False,
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)
    # Only the below-header rule remains; it must still sit at the same y a
    # default (both-rules) header's post-rule would, i.e. 500 + header_height.
    assert len(lines) == 1
    assert lines[0][0][1] == 500 + LAYOUT["defaults"]["line_advance"]["body"]


def test_header_rule_top_defaults_true_and_draws_both_rules():
    lines: list[tuple] = []
    ctx = _ctx()
    original_line = ctx.draw.line

    def spy_line(xy, **kwargs):
        lines.append(xy)
        return original_line(xy, **kwargs)

    ctx.draw.line = spy_line
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "ruled",
        "grouping": "none",
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)
    assert len(lines) == 2
    assert lines[0][0][1] == 500  # pre-header rule, at the untouched y


def test_header_rule_gap_overrides_the_default_16px_advance():
    block_default = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "ruled",
        "grouping": "none",
        "header_rule_top": False,
        "columns": COLUMNS,
    }
    block_custom = {**block_default, "header_rule_gap": 14}
    default_end = draw_table(block_default, _ctx(), 500)
    custom_end = draw_table(block_custom, _ctx(), 500)
    assert default_end - custom_end == 2  # 16 - 14


def test_rule_above_draws_a_black_rule_before_the_row_with_a_12px_gap():
    lines: list[tuple] = []
    ctx = _ctx()
    original_line = ctx.draw.line

    def spy_line(xy, **kwargs):
        lines.append((xy, kwargs.get("fill")))
        return original_line(xy, **kwargs)

    ctx.draw.line = spy_line
    block = {
        "type": "table",
        "rows": "bank_transaction_totals",
        "frame": "plain",
        "grouping": "none",
        "header": False,
        "params": {"label": "Totals at end of period"},
        "columns": COLUMNS,
    }
    end = draw_table(block, ctx, 500)
    assert len(lines) == 1
    (x0, y0), (x1, y1) = lines[0][0]
    assert y0 == y1 == 500
    assert lines[0][1] == "black"
    assert end == 500 + 12 + LAYOUT["row_height"]


def test_rule_above_absent_by_default_draws_no_rule():
    lines: list = []
    ctx = _ctx()
    original_line = ctx.draw.line
    ctx.draw.line = lambda *a, **k: (lines.append(1), original_line(*a, **k))[1]
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS,
    }
    draw_table(block, ctx, 500)
    assert lines == []


# -- Invoice addition: `capture: false` -------------------------------------
#
# `tax_invoice_mixed` renders the same LINE_ITEM_* list into two tables (a
# taxable/GST-free split display). Recording the second table's boxes would
# collide with the first, since one ground-truth value has exactly one
# bounding box -- capture: false suppresses geometry recording entirely for
# a table block, replacing the legacy renderer's line_item_tables_seen
# counter (invoice.py).


def test_capture_false_records_no_field_boxes():
    """tax_invoice_mixed renders the same line items twice. The second table
    must not record boxes -- one ground-truth value has one box."""
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "capture": False,
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    draw_table(block, _ctx(recorder), 500)
    assert recorder.as_dict() == {}


def test_capture_default_true_still_records_field_boxes():
    """Default (capture omitted) must keep recording -- capture: false is opt-in,
    not a silent behaviour change for every other table."""
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    assert "TRANSACTION_AMOUNTS_PAID[0]" in boxes
    assert "ACCOUNT_BALANCE" in boxes  # last_row_field path too


def test_capture_false_still_renders_the_table_geometry():
    """capture: false suppresses recording only -- the table itself still draws
    (same y-advance as the default), so it is not a silent no-op render."""
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "frame": "plain",
        "grouping": "none",
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    end_captured = draw_table(block, _ctx(BoxRecorder(1800, 3508)), 500)
    end_uncaptured = draw_table({**block, "capture": False}, _ctx(BoxRecorder(1800, 3508)), 500)
    assert end_captured == end_uncaptured


def test_bank_transaction_totals_row_renders_through_the_table():
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transaction_totals",
        "frame": "plain",
        "grouping": "none",
        "header": False,
        "params": {"label": "Totals at end of period"},
        "columns": COLUMNS_WITH_AMOUNT_FIELDS,
    }
    end = draw_table(block, _ctx(recorder), 500)
    assert end > 500
    # The totals row is synthetic -- it must record nothing, including on the
    # balance column's last_row_field, which this row never populates.
    assert recorder.as_dict() == {}


# -- Cell-level bold (`row["bold"]` as a column-key collection) --------------

_MIXED_BOLD_COLUMNS = [
    {"key": "date", "label": "Date", "align": "left", "x": 0},
    {"key": "description", "label": "Description", "align": "left", "x": 200},
    {"key": "balance", "label": "Balance", "align": "right", "x_right": 0},
]


def _spy_on_text(ctx):
    """Capture every (text, font) pair drawn via ctx.draw.text, in order.

    Left untyped on purpose, matching every other draw-call spy in this file
    (all defined inline inside untyped `def test_...():` functions, whose
    bodies mypy does not check by default): a typed signature here would put
    mypy's strict method-assignment/return-value checks on the monkeypatch
    trick itself, which is test-only plumbing, not production code.
    """
    drawn = []
    original_text = ctx.draw.text

    def spy(xy, text, **kwargs):
        drawn.append((text, kwargs.get("font")))
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy
    return drawn


def test_cell_bold_collection_bolds_only_the_named_column():
    """ANZ's 'BALANCE BROUGHT FORWARD' row: label bold, balance value not --
    a single row with two different font weights, which only a per-column
    (not per-row) bold spec can express."""
    ctx = _ctx()
    drawn = _spy_on_text(ctx)
    row = {
        "date": "",
        "description": "BALANCE BROUGHT FORWARD",
        "balance": Decimal("100.00"),
        "synthetic": True,
        "bold": {"description"},
    }
    _draw_row(
        row,
        _MIXED_BOLD_COLUMNS,
        ctx,
        500,
        size=LAYOUT["font_sizes"]["body"],
        frame="plain",
        grouping="none",
        row_height=LAYOUT["row_height"],
        index=None,
        is_last=False,
        family="carlito",
        inset_y=0,
        cell_line_spacing="row_height",
    )

    size = LAYOUT["font_sizes"]["body"]
    bold_font = load_font(size, family=DEFAULTS["family"], bold=True)
    regular_font = load_font(size, family=DEFAULTS["family"], bold=False)
    by_text = dict(drawn)
    # load_font caches by (size, bold): same weight -> same object, so identity
    # is a reliable, simple way to tell which font a given draw call used.
    assert by_text["BALANCE BROUGHT FORWARD"] is bold_font
    assert by_text["$100.00"] is regular_font


def test_cell_bold_true_still_bolds_every_cell():
    """The whole-row form (NAB's Carried forward, ANZ's totals row) is unchanged."""
    ctx = _ctx()
    drawn = _spy_on_text(ctx)
    row = {
        "date": "01/07/2024",
        "description": "Carried forward",
        "balance": Decimal("100.00"),
        "bold": True,
    }
    _draw_row(
        row,
        _MIXED_BOLD_COLUMNS,
        ctx,
        500,
        size=LAYOUT["font_sizes"]["body"],
        frame="plain",
        grouping="none",
        row_height=LAYOUT["row_height"],
        index=None,
        is_last=False,
        family="carlito",
        inset_y=0,
        cell_line_spacing="row_height",
    )
    bold_font = load_font(LAYOUT["font_sizes"]["body"], family=DEFAULTS["family"], bold=True)
    assert all(font is bold_font for _text, font in drawn)


def test_cell_bold_empty_collection_bolds_nothing_and_does_not_crash():
    ctx = _ctx()
    drawn = _spy_on_text(ctx)
    row = {
        "date": "",
        "description": "BALANCE BROUGHT FORWARD",
        "balance": Decimal("100.00"),
        "bold": set(),
    }
    _draw_row(
        row,
        _MIXED_BOLD_COLUMNS,
        ctx,
        500,
        size=LAYOUT["font_sizes"]["body"],
        frame="plain",
        grouping="none",
        row_height=LAYOUT["row_height"],
        index=None,
        is_last=False,
        family="carlito",
        inset_y=0,
        cell_line_spacing="row_height",
    )
    regular_font = load_font(LAYOUT["font_sizes"]["body"], family=DEFAULTS["family"], bold=False)
    assert drawn  # sanity: the row actually drew something
    assert all(font is regular_font for _text, font in drawn)


def test_cell_bold_unknown_column_name_raises_four_element_diagnostic():
    """A misspelled *_bold entry (e.g. a params: typo) must fail loudly, not
    silently render the row entirely unbolded -- indistinguishable, at a
    glance, from the typo never having been caught at all."""
    from conftest import assert_diagnostic_error

    row = {
        "date": "",
        "description": "BALANCE BROUGHT FORWARD",
        "balance": Decimal("100.00"),
        "bold": {"descriptoin"},  # typo, on purpose
    }
    with pytest.raises(TableError) as exc_info:
        _draw_row(
            row,
            _MIXED_BOLD_COLUMNS,
            _ctx(),
            500,
            size=LAYOUT["font_sizes"]["body"],
            frame="plain",
            grouping="none",
            row_height=LAYOUT["row_height"],
            index=None,
            is_last=False,
            family="carlito",
            inset_y=0,
            cell_line_spacing="row_height",
        )
    message = str(exc_info.value)
    assert "descriptoin" in message
    assert "date" in message and "description" in message and "balance" in message
    assert_diagnostic_error(message)


def test_cell_bold_unknown_column_name_raises_before_drawing_any_cell():
    """The check happens before the row's cells draw -- a bad row is rejected
    outright, not partially rendered then rejected."""
    ctx = _ctx()
    drawn = _spy_on_text(ctx)
    row = {"date": "", "description": "X", "balance": Decimal("1.00"), "bold": {"nope"}}
    with pytest.raises(TableError):
        _draw_row(
            row,
            _MIXED_BOLD_COLUMNS,
            ctx,
            500,
            size=LAYOUT["font_sizes"]["body"],
            frame="plain",
            grouping="none",
            row_height=LAYOUT["row_height"],
            index=None,
            is_last=False,
            family="carlito",
            inset_y=0,
            cell_line_spacing="row_height",
        )
    assert drawn == []


def test_rule_above_does_not_draw_before_an_invalid_bold_spec_raises():
    """A row combining rule_above with an invalid bold collection must raise
    before marking the canvas, not draw the separator rule first."""
    lines: list = []
    ctx = _ctx()
    original_line = ctx.draw.line
    ctx.draw.line = lambda *a, **k: (lines.append(1), original_line(*a, **k))[1]
    row = {
        "date": "",
        "description": "X",
        "balance": Decimal("1.00"),
        "bold": {"nope"},
        "rule_above": True,
    }
    with pytest.raises(TableError):
        _draw_row(
            row,
            _MIXED_BOLD_COLUMNS,
            ctx,
            500,
            size=LAYOUT["font_sizes"]["body"],
            frame="plain",
            grouping="none",
            row_height=LAYOUT["row_height"],
            index=None,
            is_last=False,
            family="carlito",
            inset_y=0,
            cell_line_spacing="row_height",
        )
    assert lines == []


# --- mono threading and prefix capture (Task 14) ------------------------------

_PREFIX_COLUMNS = [
    {
        "key": "description",
        "label": "Description",
        "align": "left",
        "x": 0,
        "budget": "TRANSACTION_DESC",
        "field": "TRANSACTION_DESCRIPTIONS",
        "prefix_key": "quantity_prefix",
        "prefix_field": "TRANSACTION_AMOUNTS_PAID",
    },
]


def _draw_prefix_row(row, recorder, index=0, *, family="carlito"):
    return _draw_row(
        row,
        _PREFIX_COLUMNS,
        _ctx(recorder),
        500,
        size=LAYOUT["font_sizes"]["body"],
        frame="plain",
        grouping="none",
        row_height=LAYOUT["row_height"],
        index=index,
        is_last=False,
        family=family,
        inset_y=0,
        cell_line_spacing="row_height",
    )


def test_budgeted_cell_honours_the_layouts_monospace_face():
    """A budgeted cell used to omit mono= entirely, silently drawing every
    receipt line item in the sans face."""
    fonts: list = []
    for family in ("carlito", "liberation_mono"):
        ctx = _ctx()
        original = ctx.draw.text
        ctx.draw.text = lambda xy, text, **kwargs: (
            fonts.append(kwargs.get("font")),
            original(xy, text, **kwargs),
        )[1]
        _draw_row(
            {"description": "ATM WITHDRAWAL", "quantity_prefix": ""},
            _PREFIX_COLUMNS,
            ctx,
            500,
            size=LAYOUT["font_sizes"]["body"],
            frame="plain",
            grouping="none",
            row_height=LAYOUT["row_height"],
            index=0,
            is_last=False,
            family=family,
            inset_y=0,
            cell_line_spacing="row_height",
        )
    assert fonts[0].path == load_font(32, family="carlito").path
    assert fonts[1].path == load_font(32, family="liberation_mono").path
    assert fonts[0].path != fonts[1].path


def test_prefix_key_records_the_prefixs_own_box_inside_the_cell():
    recorder = BoxRecorder(1800, 3508)
    _draw_prefix_row({"description": "2x Coffee", "quantity_prefix": "2x "}, recorder)
    boxes = recorder.as_dict()
    assert "TRANSACTION_AMOUNTS_PAID[0]" in boxes
    prefix_box = boxes["TRANSACTION_AMOUNTS_PAID[0]"]
    desc_box = boxes["TRANSACTION_DESCRIPTIONS[0]"]
    # The prefix shares the cell's left edge and sits strictly inside its width.
    assert prefix_box[0] == desc_box[0]
    assert prefix_box[2] < desc_box[2]


def test_prefix_is_not_recorded_when_the_row_has_none():
    recorder = BoxRecorder(1800, 3508)
    _draw_prefix_row({"description": "Coffee", "quantity_prefix": ""}, recorder)
    boxes = recorder.as_dict()
    assert "TRANSACTION_DESCRIPTIONS[0]" in boxes
    assert "TRANSACTION_AMOUNTS_PAID[0]" not in boxes


def test_prefix_is_not_recorded_on_a_synthetic_row():
    """Synthetic rows carry no index and are never recorded — the prefix box
    must follow the same rule as the cell's own `field`."""
    recorder = BoxRecorder(1800, 3508)
    _draw_prefix_row({"description": "2x Coffee", "quantity_prefix": "2x "}, recorder, index=None)
    assert recorder.as_dict() == {}


# --- role, header weight, cell inset, label anchor, cell advance (Task 15) ----
#
# The legacy invoice renderer's line-item table breaks four assumptions the
# table primitive had baked into Python: it draws at a role other than "body",
# its column headings are regular weight, its cells' ink is inset 12px inside a
# 52px row, and its "Unit Price"/"Total" headings sit 200px left of the amounts
# beneath them. A fifth (a budgeted cell advancing by the fitted font's own line
# height, not the row pitch) decides how tall a box that cell records.

_INVOICE_LAYOUT = {
    "font_sizes": {"header": 48, "subheader": 28, "body": 20},
    "row_height": 52,
    "field_budgets": {
        "LINE_ITEM_DESC": {"width": 870, "fit": "shrink", "min_font": 12, "max_lines": 1},
    },
    "defaults": {**DEFAULTS, "role": "subheader", "line_advance": {"subheader": 39, "body": 28}},
}

_INVOICE_ENTRY = {
    "fields": {
        "LINE_ITEM_DESCRIPTIONS": "Trademark registration",
        "LINE_ITEM_QUANTITIES": "4",
        "LINE_ITEM_PRICES": "716.52",
        "LINE_ITEM_TOTAL_PRICES": "2866.08",
    }
}

_INVOICE_COLUMNS = [
    {
        "key": "description",
        "label": "Description",
        "align": "left",
        "x": 0,
        "budget": "LINE_ITEM_DESC",
        "field": "LINE_ITEM_DESCRIPTIONS",
    },
    {"key": "quantity", "label": "Qty", "align": "left", "x": 900, "field": "LINE_ITEM_QUANTITIES"},
    {
        "key": "total",
        "label": "Total",
        "align": "right",
        "x": 1750,
        "label_x": 1550,
        "label_align": "left",
        "field": "LINE_ITEM_TOTAL_PRICES",
    },
]

_INVOICE_BLOCK = {
    "type": "table",
    "rows": "pipe_fields",
    "frame": "plain",
    "grouping": "none",
    "row_height": 52,
    "header_height": 52,
    "label_inset_y": 12,
    "row_inset_y": 12,
    "params": {
        "fields": {
            "description": "LINE_ITEM_DESCRIPTIONS",
            "quantity": "LINE_ITEM_QUANTITIES",
            "total": "LINE_ITEM_TOTAL_PRICES",
        },
        "decimal_keys": ["total"],
    },
    "columns": _INVOICE_COLUMNS,
}


def _invoice_ctx(recorder: BoxRecorder | None = None) -> RenderContext:
    image = Image.new("RGB", (1900, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry=_INVOICE_ENTRY,
        layout=_INVOICE_LAYOUT,
        layout_id="tax_invoice_standard",
        layout_path="config/layouts/invoices.yml",
        region=Region(x=100, width=1700),
        recorder=recorder,
    )


def _text_positions(ctx):
    """Capture every (text, xy, font) drawn via ctx.draw.text, in order."""
    drawn = []
    original_text = ctx.draw.text

    def spy(xy, text, **kwargs):
        drawn.append((text, xy, kwargs.get("font")))
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy
    return drawn


def test_table_draws_every_label_and_cell_at_its_own_role():
    """draw_table used to resolve `resolve_role(layout, "body")` — a hardcoded
    role name deciding a pixel outcome. An invoice table draws at `subheader`
    (28px) on a page whose `body` role is the 20px supplier-name line."""
    ctx = _invoice_ctx()
    drawn = _text_positions(ctx)
    draw_table(_INVOICE_BLOCK, ctx, 500)
    sizes = {font.size for _text, _xy, font in drawn}
    assert sizes == {28}


def test_table_role_block_key_wins_over_the_layout_default():
    """The test above covers the omitted case (defaults.role, which is what
    every bank and receipt table relies on); this covers the override."""
    ctx = _invoice_ctx()
    drawn = _text_positions(ctx)
    draw_table({**_INVOICE_BLOCK, "role": "body"}, ctx, 500)
    assert {font.size for _text, _xy, font in drawn} == {20}


def test_header_bold_false_draws_regular_weight_column_headings():
    ctx = _invoice_ctx()
    drawn = _text_positions(ctx)
    draw_table({**_INVOICE_BLOCK, "header_bold": False}, ctx, 500)
    headings = [font for text, _xy, font in drawn if text in ("Description", "Qty", "Total")]
    assert headings
    assert all(font.path == load_font(28, family=DEFAULTS["family"], bold=False).path for font in headings)


def test_header_bold_defaults_to_the_layout_default_which_is_bold():
    ctx = _invoice_ctx()
    drawn = _text_positions(ctx)
    draw_table(_INVOICE_BLOCK, ctx, 500)
    headings = [font for text, _xy, font in drawn if text in ("Description", "Qty", "Total")]
    assert headings
    assert all(font.path == load_font(28, family=DEFAULTS["family"], bold=True).path for font in headings)


def test_row_inset_y_shifts_cell_ink_without_changing_the_row_pitch():
    """Legacy draws each cell at `y + 12` inside a 52px row and still advances
    exactly 52 — the inset must not leak into the table's own flow."""
    inset_ctx = _invoice_ctx()
    inset_drawn = _text_positions(inset_ctx)
    inset_end = draw_table(_INVOICE_BLOCK, inset_ctx, 500)

    flush_ctx = _invoice_ctx()
    flush_drawn = _text_positions(flush_ctx)
    flush_end = draw_table({**_INVOICE_BLOCK, "row_inset_y": 0}, flush_ctx, 500)

    cell_y = {text: xy[1] for text, xy, _font in inset_drawn}["4"]
    flush_y = {text: xy[1] for text, xy, _font in flush_drawn}["4"]
    assert cell_y - flush_y == 12
    assert inset_end == flush_end == 500 + 52 + 52


def test_label_x_and_label_align_position_the_heading_apart_from_its_cells():
    """The legacy invoice header draws "Total" left-aligned at the column's own
    left edge while its amounts right-align 200px further along."""
    ctx = _invoice_ctx()
    drawn = _text_positions(ctx)
    draw_table(_INVOICE_BLOCK, ctx, 500)
    positions = {text: xy[0] for text, xy, _font in drawn}
    assert positions["Total"] == 100 + 1550  # label_x, left-aligned
    assert positions["$2,866.08"] < 100 + 1750  # cell right-aligned to x: 1750
    assert positions["Description"] == 100  # no label_x: the column's own anchor


def test_cell_line_spacing_font_records_the_fitted_fonts_own_height():
    """A budgeted cell in a 52px invoice row records a 28px-tall box, because
    legacy passed no line_spacing to draw_fitted_left at all."""
    recorder = BoxRecorder(1900, 3508)
    draw_table({**_INVOICE_BLOCK, "cell_line_spacing": "font"}, _invoice_ctx(recorder), 500)
    box = recorder.as_dict()["LINE_ITEM_DESCRIPTIONS[0]"]
    assert round((box[3] - box[1]) * 3508) == 28


def test_cell_line_spacing_row_height_records_the_row_pitch():
    """The default, and what every bank and receipt table's legacy renderer did."""
    recorder = BoxRecorder(1900, 3508)
    draw_table(_INVOICE_BLOCK, _invoice_ctx(recorder), 500)
    box = recorder.as_dict()["LINE_ITEM_DESCRIPTIONS[0]"]
    assert round((box[3] - box[1]) * 3508) == 52


def test_unknown_cell_line_spacing_raises_a_four_element_diagnostic():
    """Checked at render time as well as in schema.py, because the value may
    come from defaults.table_cell_line_spacing, which schema.py never reads."""
    from conftest import assert_diagnostic_error

    with pytest.raises(TableError) as exc_info:
        draw_table({**_INVOICE_BLOCK, "cell_line_spacing": "rowheight"}, _invoice_ctx(), 500)
    assert_diagnostic_error(exc_info.value)
    assert "rowheight" in str(exc_info.value)
