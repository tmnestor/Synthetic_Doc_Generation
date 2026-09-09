import pytest
from PIL import Image, ImageDraw

from generators.common import fit_text, load_font
from generators.exporters.geometry import BoxRecorder
from generators.layout_budgets import LayoutBudgetError
from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.defaults import DefaultsError, PARAMETER_DEFAULTS
from generators.layout_dsl.primitives_text import (
    CurrencyError,
    RoleError,
    draw_banner,
    draw_block,
    draw_pair,
    draw_rule,
    draw_spacer,
    draw_text_block,
    font_for,
    format_currency,
    line_advance,
    resolve_role,
)
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
    # for LAYOUT's font_sizes (header 48, body 32, footer 18).
    "line_advance": {"header": 67, "body": 44, "footer": 25},
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

# Named so `_shrunk_width` can use it as a typed int: LAYOUT is heterogeneous,
# so mypy sees LAYOUT["font_sizes"]["body"] as an unindexable `object`.
_BODY_SIZE = 32

LAYOUT = {
    "font_sizes": {"header": 48, "body": _BODY_SIZE, "footer": 18},
    "margin": 100,
    "page_dimensions": {"width": 1800, "height": 3508},
    "defaults": DEFAULTS,
}


def _ctx(recorder: BoxRecorder | None = None, layout: dict = LAYOUT) -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry={"fields": {"PAYER_NAME": "Robin Wood", "STATEMENT_DATE_RANGE": "01/07/2024 - 29/07/2024"}},
        layout=layout,
        layout_id="cba_standard",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        recorder=recorder,
    )


def test_resolve_role_returns_font_size():
    assert resolve_role(LAYOUT, "body") == 32


def test_resolve_role_fails_fast_on_unknown_role():
    with pytest.raises(RoleError) as exc_info:
        resolve_role(LAYOUT, "mystery")
    message = str(exc_info.value)
    assert "mystery" in message and "header" in message
    assert_diagnostic_error(message)


def test_text_advances_y():
    end = draw_text_block({"type": "text", "content": "{PAYER_NAME}", "role": "body"}, _ctx(), 200)
    assert end > 200


def test_line_advance_resolves_by_the_blocks_own_role():
    """A layout's line_advance is a role -> pixels mapping, not one flat
    number: a header-role block and a footer-role block need different
    advances, since each was historically int(that role's own font size *
    1.4) -- a flat per-layout number cannot express both at once."""
    layout = {"defaults": {"line_advance": {"header": 61, "body": 44, "footer": 25}}}
    assert line_advance(layout, {"role": "header"}, layout_id="x", layout_path="y") == 61
    assert line_advance(layout, {"role": "footer"}, layout_id="x", layout_path="y") == 25


def test_line_advance_missing_role_raises_a_four_element_diagnostic():
    """A role present in font_sizes but absent from defaults.line_advance
    must fail fast, not silently fall back to some other role's advance."""
    layout = {"defaults": {"role": "body", "line_advance": {"body": 44}}}
    with pytest.raises(DefaultsError) as exc_info:
        line_advance(layout, {"role": "sub_description"}, layout_id="cba_standard", layout_path="z.yml")
    message = str(exc_info.value)
    assert "sub_description" in message
    assert "line_advance" in message
    assert_diagnostic_error(message)


def test_line_advance_block_override_wins_over_the_layout_default():
    """A block's own bare-integer line_advance wins outright, without any
    role lookup -- the escape hatch for the rare line that is not simply
    'this role's usual advance'."""
    layout = {"defaults": {"role": "body", "line_advance": {"body": 44}}}
    assert line_advance(layout, {"role": "body", "line_advance": 10}, layout_id="x", layout_path="y") == 10


def test_line_advance_comes_from_the_layout_not_a_1_4_ratio():
    """Receipts declare `line_advance: {body: 20}` against an 18pt body
    font -- a ratio of 1.11, not the 1.4 the old `line_height(size)`
    hardcoded. If draw_text_block silently reverted to that ratio, this
    would advance to 100 + int(18 * 1.4) == 125, not the declared 120.
    """
    layout = {
        **LAYOUT,
        "font_sizes": {"body": 18},
        "defaults": {**DEFAULTS, "line_advance": {"body": 20}},
    }
    end = draw_text_block(
        {"type": "text", "content": "{PAYER_NAME}", "role": "body"}, _ctx(layout=layout), 100
    )
    assert end == 120


def test_font_for_resolves_mono_from_the_layout_default():
    mono_font = font_for({"defaults": {"family": "liberation_mono"}}, {}, 32, layout_id="x", layout_path="y")
    sans_font = font_for({"defaults": {"family": "carlito"}}, {}, 32, layout_id="x", layout_path="y")
    assert mono_font is not sans_font  # load_font caches by (size, family, bold)


def test_font_for_block_override_wins_over_the_layout_default():
    from generators.common import load_font

    mono_font = font_for({"defaults": {"family": "carlito"}}, {"family": "liberation_mono"}, 32, layout_id="x", layout_path="y")
    assert mono_font is load_font(32, family="liberation_mono")


def test_monospace_is_honoured_end_to_end():
    """Every load_font call in this module used to omit mono=, so a layout
    declaring `mono: true` (as all six receipt layouts do, via
    `font_family: monospace`) still silently rendered the sans face. Proven
    by an actual pixel difference, not just that a flag was threaded."""
    mono_layout = {**LAYOUT, "defaults": {**DEFAULTS, "family": "liberation_mono"}}
    sans_layout = {**LAYOUT, "defaults": {**DEFAULTS, "family": "carlito"}}
    mono_ctx = _ctx(layout=mono_layout)
    sans_ctx = _ctx(layout=sans_layout)
    draw_text_block({"type": "text", "content": "{PAYER_NAME}", "role": "body"}, mono_ctx, 200)
    draw_text_block({"type": "text", "content": "{PAYER_NAME}", "role": "body"}, sans_ctx, 200)
    assert list(mono_ctx.draw._image.getdata()) != list(sans_ctx.draw._image.getdata())


def test_text_records_geometry_when_field_given():
    recorder = BoxRecorder(1800, 3508)
    draw_text_block(
        {"type": "text", "content": "{PAYER_NAME}", "role": "body", "field": "PAYER_NAME"},
        _ctx(recorder),
        200,
    )
    assert "PAYER_NAME" in recorder.as_dict()


def test_text_without_field_records_nothing():
    recorder = BoxRecorder(1800, 3508)
    draw_text_block({"type": "text", "content": "{PAYER_NAME}", "role": "body"}, _ctx(recorder), 200)
    assert recorder.as_dict() == {}


def test_text_bold_uses_the_bold_font():
    """Westpac's brand header and section titles are bold in the legacy renderer.

    `bold` is opt-in and defaults to false, so it must not change advance or
    plain-text rendering for every other consumer of `text`.
    """
    from generators.common import load_font

    ctx = _ctx()
    fonts_used: list = []
    original_text = ctx.draw.text

    def spy_text(xy, text, *, font, **kwargs):
        fonts_used.append(font)
        return original_text(xy, text, font=font, **kwargs)

    ctx.draw.text = spy_text
    draw_text_block({"type": "text", "content": "Westpac", "role": "header", "bold": True}, ctx, 200)

    assert fonts_used == [load_font(48, family=DEFAULTS["family"], bold=True)]


def test_budgeted_text_wraps_and_advances_by_the_wrapped_height():
    """shrink_then_wrap with max_lines 2 puts a long supplier name on two lines.
    The cursor must advance by both, or every block below it overlaps."""
    layout = {
        "font_sizes": {"body": 18},
        "defaults": {
            "role": "body",
            "color": "black",
            "align": "center",
            "bold": False,
            "family": "liberation_mono",
            "line_advance": 20,
        },
        "field_budgets": {
            "SUPPLIER_NAME": {"width": 396, "fit": "shrink_then_wrap", "min_font": 10, "max_lines": 2}
        },
    }
    ctx = _ctx(layout=layout)
    ctx.entry["fields"]["SUPPLIER_NAME"] = "Woolworths Group Limited Southbank Trading"
    end = draw_text_block(
        {"type": "text", "content": "{SUPPLIER_NAME}", "budget": "SUPPLIER_NAME"}, ctx, 100
    )
    assert end == 140


def test_budget_names_an_undeclared_field_budget():
    layout = {
        "font_sizes": {"body": 18},
        "defaults": {
            "role": "body",
            "color": "black",
            "align": "left",
            "bold": False,
            "family": "liberation_mono",
            "line_advance": 20,
        },
        "field_budgets": {},
    }
    with pytest.raises(LayoutBudgetError) as exc_info:
        draw_text_block({"type": "text", "content": "x", "budget": "SUPPLIER_NAME"}, _ctx(layout=layout), 0)
    assert_diagnostic_error(exc_info.value)


# A budget narrow enough to force a real shrink of "Robin Wood" from its
# nominal 32pt -- wide enough that an *unbudgeted* draw (nominal size, ignoring
# the budget) would land at a visibly different x than a correctly budgeted
# one. A budget too generous to ever shrink would let these tests pass
# vacuously even with `budget:` silently ignored, so `_shrunk_width` below
# asserts the shrink actually happened rather than trusting it.
# Spelled out as typed scalars, not read back out of the budget dict: the dict
# is heterogeneous (str and int values), so every value read from it is `object`
# to mypy and cannot be passed to fit_text's typed parameters.
_SHRINK_WIDTH = 150
_SHRINK_MIN_FONT = 10
_SHRINK_MAX_LINES = 1
_SHRINK_BUDGET = {
    "width": _SHRINK_WIDTH,
    "fit": "shrink",
    "min_font": _SHRINK_MIN_FONT,
    "max_lines": _SHRINK_MAX_LINES,
}


def _shrunk_width(text: str = "Robin Wood") -> int:
    """Width `text` is actually drawn at under `_SHRINK_BUDGET`.

    Derived, not hardcoded: the chosen size and resulting width are functions
    of the face's metrics, so pinning them (this file once pinned 25pt/150px
    against DejaVu) breaks on any typeface change while telling you nothing
    about the behaviour under test. Asserting the shrink *fired* is the part
    that actually matters.
    """
    nominal = _BODY_SIZE
    family = str(DEFAULTS["family"])
    result = fit_text(
        text,
        width=_SHRINK_WIDTH,
        fit="shrink",
        min_font=_SHRINK_MIN_FONT,
        max_lines=_SHRINK_MAX_LINES,
        nominal_size=nominal,
        family=family,
    )
    assert result.size < nominal, (
        f"sanity: budget must bind — {text!r} already fits at {nominal}pt, "
        "so this test would pass even if `budget:` were ignored"
    )
    bbox = load_font(result.size, family=family, bold=False).getbbox(text)
    width = int(bbox[2] - bbox[0])
    assert width <= _SHRINK_WIDTH
    return width


def test_budgeted_text_centers_within_the_full_page_width_not_the_region():
    """draw_fitted_center centres in a canvas width, not a region -- receipts
    centre within the full page width (receipt.py:161's `width` argument),
    not the margin-inset region. LAYOUT's region is x=100, width=1600 inside
    an 1800px page (page_dimensions.width) -- a symmetric 100px margin each
    side. `region.x * 2 + region.width` reconstructs that 1800px page width;
    if draw_text_block instead centred within the 1600px region alone, this
    x would differ (100 + (1600-150)//2 == 825 too, by coincidence of the
    symmetric margin -- see the left/right tests below for the case that
    actually discriminates budgeted from unbudgeted rendering)."""
    layout = {**LAYOUT, "field_budgets": {"SHORT": _SHRINK_BUDGET}}
    ctx = _ctx(layout=layout)  # PAYER_NAME defaults to "Robin Wood"
    drawn: list[tuple] = []
    original_text = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (drawn.append(xy), original_text(xy, text, **kwargs))[1]

    draw_text_block(
        {"type": "text", "content": "{PAYER_NAME}", "role": "body", "align": "center", "budget": "SHORT"},
        ctx,
        200,
    )

    text_width = _shrunk_width()  # asserts the budget really is binding, not a no-op
    expected_x = (1800 - text_width) // 2  # the full page width, not the 1600px region
    assert drawn == [(expected_x, 200)]


def test_budgeted_text_left_shrinks_to_fit_and_stays_anchored_at_region_x():
    """Left alignment always anchors at region.x regardless of font size, so
    position alone cannot prove the budget was honoured -- the drawn extent
    must actually have shrunk to fit, not stayed at the too-wide nominal
    193px ("Robin Wood" at 32pt)."""
    recorder = BoxRecorder(1800, 3508)
    layout = {**LAYOUT, "field_budgets": {"SHORT": _SHRINK_BUDGET}}
    ctx = _ctx(recorder, layout=layout)

    draw_text_block(
        {
            "type": "text",
            "content": "{PAYER_NAME}",
            "role": "body",
            "align": "left",
            "budget": "SHORT",
            "field": "PAYER_NAME",
        },
        ctx,
        200,
    )
    box = recorder.as_dict()["PAYER_NAME"]  # normalised to [0, 1] by the 1800x3508 page
    assert round(box[0] * 1800) == ctx.region.x  # anchored left, as always
    width_px = (box[2] - box[0]) * 1800
    assert width_px <= 150  # but shrunk to fit the budget, not left at the 193px nominal


def test_budgeted_text_right_shrinks_to_fit_and_anchors_at_region_right():
    layout = {**LAYOUT, "field_budgets": {"SHORT": _SHRINK_BUDGET}}
    ctx = _ctx(layout=layout)
    drawn: list[tuple] = []
    original_text = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (drawn.append(xy), original_text(xy, text, **kwargs))[1]

    draw_text_block(
        {"type": "text", "content": "{PAYER_NAME}", "role": "body", "align": "right", "budget": "SHORT"},
        ctx,
        200,
    )
    text_width = _shrunk_width()  # asserts the budget really is binding, not a no-op
    assert drawn[0][0] == 1700 - text_width  # region.right (100 + 1600) minus the shrunk width


def test_budgeted_text_records_the_full_wrapped_extent():
    recorder = BoxRecorder(1800, 3508)
    layout = {
        "font_sizes": {"body": 18},
        "defaults": {
            "role": "body",
            "color": "black",
            "align": "center",
            "bold": False,
            "family": "liberation_mono",
            "line_advance": 20,
        },
        "field_budgets": {
            "SUPPLIER_NAME": {"width": 396, "fit": "shrink_then_wrap", "min_font": 10, "max_lines": 2}
        },
    }
    ctx = _ctx(recorder, layout=layout)
    ctx.entry["fields"]["SUPPLIER_NAME"] = "Woolworths Group Limited Southbank Trading"
    draw_text_block(
        {
            "type": "text",
            "content": "{SUPPLIER_NAME}",
            "budget": "SUPPLIER_NAME",
            "field": "SUPPLIER_NAME",
        },
        ctx,
        100,
    )
    box = recorder.as_dict()["SUPPLIER_NAME"]  # normalised to [0, 1] by the 1800x3508 page
    assert round(box[1] * 3508) == 100  # top: the wrap's first line
    assert round(box[3] * 3508) == 140  # bottom: below the wrapped second line, not a single line_advance


def test_unbudgeted_text_is_unaffected_by_budget_support():
    """A block without `budget:` must render byte-identical to before -- the
    engine gap this task closes must be inert unless a layout opts in."""
    end = draw_text_block({"type": "text", "content": "{PAYER_NAME}", "role": "body"}, _ctx(), 200)
    assert end == 200 + 44  # LAYOUT's own defaults.line_advance.body, unrelated to any budget


def test_pair_renders_label_and_value():
    end = draw_pair(
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "role": "body"},
        _ctx(),
        200,
    )
    assert end > 200


def test_pair_records_only_the_value_not_the_label():
    recorder_text = BoxRecorder(1800, 3508)
    draw_text_block(
        {"type": "text", "content": "{PAYER_NAME}", "role": "body", "field": "PAYER_NAME"},
        _ctx(recorder_text),
        200,
    )
    text_box = recorder_text.as_dict()["PAYER_NAME"]

    recorder_pair = BoxRecorder(1800, 3508)
    draw_pair(
        {
            "type": "pair",
            "label": "Account Holder",
            "value": "{PAYER_NAME}",
            "role": "body",
            "field": "PAYER_NAME",
        },
        _ctx(recorder_pair),
        200,
    )
    pair_box = recorder_pair.as_dict()["PAYER_NAME"]

    # The pair's recorded box must start after the label, not at the region's left edge.
    assert pair_box[0] > text_box[0]
    # The pair's box must have the same width as the text box (same value, same font).
    text_width = text_box[2] - text_box[0]
    pair_width = pair_box[2] - pair_box[0]
    assert abs(pair_width - text_width) < 0.001  # Allow 0.1% tolerance for rounding
    # Top must match.
    assert pair_box[1] == text_box[1]


def test_pair_records_nothing_without_a_field():
    recorder = BoxRecorder(1800, 3508)
    draw_pair(
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "role": "body"},
        _ctx(recorder),
        200,
    )
    assert recorder.as_dict() == {}


def test_pair_budget_wraps_only_the_value_and_advances_by_the_wrapped_height():
    """Apply the fit budget to the pair's value only -- the label always
    draws in full, unshrunk and unwrapped."""
    layout = {
        "font_sizes": {"body": 18},
        "defaults": {
            "role": "body",
            "color": "black",
            "align": "left",
            "bold": False,
            "family": "liberation_mono",
            "line_advance": 20,
            "pair_value_align": "left",
            "pair_separator": ": ",
        },
        "field_budgets": {
            "SUPPLIER_NAME": {"width": 300, "fit": "shrink_then_wrap", "min_font": 10, "max_lines": 2}
        },
    }
    ctx = _ctx(layout=layout)
    ctx.entry["fields"]["PAYER_NAME"] = "Woolworths Group Limited Southbank Trading"
    end = draw_pair(
        {
            "type": "pair",
            "label": "Account Holder",
            "value": "{PAYER_NAME}",
            "budget": "SUPPLIER_NAME",
        },
        ctx,
        100,
    )
    assert end == 140  # 100 + 2 wrapped lines * the declared 20px line_advance


def test_pair_budget_positions_the_value_after_the_full_label():
    recorder = BoxRecorder(1800, 3508)
    layout = {
        "font_sizes": {"body": 18},
        "defaults": {
            "role": "body",
            "color": "black",
            "align": "left",
            "bold": False,
            "family": "liberation_mono",
            "line_advance": 20,
            "pair_value_align": "left",
            "pair_separator": ": ",
        },
        "field_budgets": {
            "SUPPLIER_NAME": {"width": 300, "fit": "shrink_then_wrap", "min_font": 10, "max_lines": 2}
        },
    }
    ctx = _ctx(recorder, layout=layout)
    ctx.entry["fields"]["PAYER_NAME"] = "Woolworths Group Limited Southbank Trading"
    draw_pair(
        {
            "type": "pair",
            "label": "Account Holder",
            "value": "{PAYER_NAME}",
            "budget": "SUPPLIER_NAME",
            "field": "SUPPLIER_NAME",
        },
        ctx,
        100,
    )
    box = recorder.as_dict()["SUPPLIER_NAME"]  # normalised to [0, 1] by the 1800x3508 page
    label_width = int(load_font(18, family="liberation_mono").getlength("Account Holder: "))
    # value starts right after the full label, not at region.x
    assert round(box[0] * 1800) == ctx.region.x + label_width
    assert round(box[1] * 3508) == 100
    assert round(box[3] * 3508) == 140  # wrapped bottom, not a single line_advance


def _spy_text(ctx):
    """Replace ctx.draw.text with a recording wrapper; still draws for real.

    Returns the list of (xy, text) pairs `draw.text` was actually called
    with -- the same coordinates PIL paints, not a value merely computed
    alongside the real call. Deliberately untyped (like every other spy
    assignment in this file): typing it would put mypy's --check-untyped-defs
    exemption out of reach and flag the lambda-onto-a-bound-method pattern
    every other test here already uses freely.
    """
    drawn = []
    original_text = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (
        drawn.append((xy, text)),
        original_text(xy, text, **kwargs),
    )[1]
    return drawn


def test_pair_right_aligns_its_value_to_the_region():
    """value_align: right must draw two separate strings -- label (plus its
    separator, here "") at region.x, value right-aligned at region.right --
    not the single joined string the default left style draws."""
    ctx = _ctx()
    drawn = _spy_text(ctx)

    draw_pair(
        {
            "type": "pair",
            "label": "TOTAL",
            "value": "137.73",
            "role": "body",
            "value_align": "right",
            "separator": "",
        },
        ctx,
        200,
    )

    font = font_for(LAYOUT, {}, 32, layout_id="x", layout_path="y")
    value_bbox = font.getbbox("137.73")
    value_width = value_bbox[2] - value_bbox[0]
    label_xy = next(xy for xy, text in drawn if text == "TOTAL")
    value_xy = next(xy for xy, text in drawn if text == "137.73")
    assert label_xy == (ctx.region.x, 200)
    assert value_xy == (ctx.region.right - value_width, 200)


def test_pair_separator_applies_on_the_right_aligned_path_too():
    """One label convention, not one per value_align.

    Before `pair_separator` existed the right-aligned path drew the label
    verbatim, so invoice layouts wrote their own colons into `label:` while
    left-aligned ones did not. The separator is now the layout's on both
    paths, and it is the drawn string that must carry it -- an assertion on
    the label alone would pass even if the separator were dropped.
    """
    ctx = _ctx()
    drawn = _spy_text(ctx)

    draw_pair(
        {
            "type": "pair",
            "label": "Total",
            "value": "137.73",
            "role": "body",
            "value_align": "right",
            "separator": ":",
        },
        ctx,
        200,
    )

    font = font_for(LAYOUT, {}, 32, layout_id="x", layout_path="y")
    assert [text for _, text in drawn] == ["Total:", "137.73"]
    # The label's x accounts for the separator's own width: min_gap is 0 here,
    # so it sits at region.x, and the value still right-aligns to region.right.
    value_width = font.getbbox("137.73")[2] - font.getbbox("137.73")[0]
    assert drawn[0][0] == (ctx.region.x, 200)
    assert drawn[1][0] == (ctx.region.right - value_width, 200)


def test_pair_separator_is_required_not_defaulted():
    """A layout that declares no pair_separator fails fast rather than
    printing whichever punctuation this module happens to prefer."""
    layout = {**LAYOUT, "defaults": {k: v for k, v in DEFAULTS.items() if k != "pair_separator"}}
    ctx = _ctx(layout=layout)
    with pytest.raises(DefaultsError) as exc_info:
        draw_pair({"type": "pair", "label": "Date", "value": "01/07/2024"}, ctx, 200)
    assert "pair_separator" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_pair_min_gap_pushes_a_long_label_left():
    """invoice.py:283-285 computes label_x so a long label never merges with
    a right-aligned amount into one OCR token. Region is deliberately
    narrower than label + value so the collision-avoidance actually fires --
    proven by a sanity assertion, not assumed.

    The region width is *derived* from the measured strings rather than
    hardcoded: a fixed width is only narrow enough for the face it was tuned
    against, and a narrower face (this corpus moved from DejaVu to Carlito)
    silently turns the collision into a comfortable fit, so the test stops
    exercising the branch it names."""
    ctx = _ctx()
    font = font_for(LAYOUT, {}, 32, layout_id="x", layout_path="y")
    label_span = font.getbbox("GST included (10%):")
    value_span = font.getbbox("1,234,567.89")
    # 10px of natural gap: positive (so nothing overlaps yet) but under the
    # 24px min_gap, so the label must still be pushed left.
    ctx.region = Region(
        x=0,
        width=(label_span[2] - label_span[0]) + (value_span[2] - value_span[0]) + 10,
    )
    drawn = _spy_text(ctx)

    draw_pair(
        {
            "type": "pair",
            "label": "GST included (10%):",
            "value": "1,234,567.89",
            "role": "body",
            "value_align": "right",
            "separator": "",
            "min_gap": 24,
        },
        ctx,
        200,
    )

    label_width = label_span[2] - label_span[0]
    value_width = value_span[2] - value_span[0]

    natural_gap = ctx.region.width - label_width - value_width
    assert natural_gap < 24, "sanity: label+value must not already fit with 24px to spare"

    label_xy = next(xy for xy, text in drawn if text == "GST included (10%):")
    value_xy = next(xy for xy, text in drawn if text == "1,234,567.89")
    expected_label_x = ctx.region.width - value_width - label_width - 24
    assert label_xy == (expected_label_x, 200)
    assert value_xy == (ctx.region.width - value_width, 200)
    assert value_xy[0] - (label_xy[0] + label_width) >= 24


def test_pair_min_gap_zero_never_moves_the_label():
    """`min_gap: 0` demands no gap and so never repositions the label, which is
    what both legacy renderers do: `draw_line_item` (receipts) and the invoice
    totals' "separate" branch each draw the label at a fixed x and let a long
    value run into it. Enforcing a zero gap instead would shift the label left
    of where legacy put it — real on 1 of the 55 corpus invoices, whose 48px
    "Total:" plus $19,176.69 needs 456px of a 400px totals column.

    As above, the region width is derived so the overlap this test depends on
    survives a change of typeface."""
    ctx = _ctx()
    font = font_for(LAYOUT, {}, 32, layout_id="x", layout_path="y")
    label_span = font.getbbox("Total:")
    value_span = font.getbbox("1,234,567.89")
    # 20px narrower than label + value, so they genuinely overlap.
    ctx.region = Region(
        x=0,
        width=(label_span[2] - label_span[0]) + (value_span[2] - value_span[0]) - 20,
    )
    drawn = _spy_text(ctx)

    draw_pair(
        {
            "type": "pair",
            "label": "Total:",
            "value": "1,234,567.89",
            "role": "body",
            "value_align": "right",
            "separator": "",
        },
        ctx,
        200,
    )

    label_width = label_span[2] - label_span[0]
    value_width = value_span[2] - value_span[0]
    assert ctx.region.width - label_width - value_width < 0, (
        "sanity: label and value must actually overlap, or this proves nothing"
    )

    label_xy = next(xy for xy, text in drawn if text == "Total:")
    assert label_xy == (ctx.region.x, 200)


def test_pair_value_align_right_records_the_values_own_box():
    """Both alignments must record the value's own extent, not the label's --
    the right-aligned counterpart to test_pair_records_only_the_value_not_the_label."""
    recorder = BoxRecorder(1800, 3508)
    draw_pair(
        {
            "type": "pair",
            "label": "TOTAL",
            "value": "137.73",
            "role": "body",
            "value_align": "right",
            "field": "TOTAL_AMOUNT",
        },
        _ctx(recorder),
        200,
    )
    font = font_for(LAYOUT, {}, 32, layout_id="x", layout_path="y")
    value_bbox = font.getbbox("137.73")
    value_width = value_bbox[2] - value_bbox[0]
    box = recorder.as_dict()["TOTAL_AMOUNT"]  # normalised to [0, 1] by the 1800x3508 page
    assert round(box[2] * 1800) == 1700  # region.right: value's own right edge, not the label's
    assert round(box[0] * 1800) == 1700 - value_width


def test_pair_unaligned_left_is_unaffected_by_value_align_support():
    """Default (left) rendering must stay byte-identical -- the engine gap
    this task closes must be inert unless a layout opts in."""
    end = draw_pair(
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "role": "body"}, _ctx(), 200
    )
    assert end == 200 + 44  # LAYOUT's own defaults.line_advance.body, unrelated to value_align


def test_block_advances_once_per_line():
    ctx = _ctx()
    one = draw_block({"type": "block", "lines": ["a"], "role": "footer"}, ctx, 0)
    three = draw_block({"type": "block", "lines": ["a", "b", "c"], "role": "footer"}, ctx, 0)
    assert three == one * 3


def test_spacer_advances_by_height():
    assert draw_spacer({"type": "spacer", "height": 40}, _ctx(), 200) == 240


def test_rule_advances_by_padding():
    end = draw_rule({"type": "rule", "pad_above": 10, "pad_below": 20}, _ctx(), 200)
    assert end == 231  # 10 above + 1px line + 20 below


def test_rule_advances_by_custom_thickness():
    end = draw_rule({"type": "rule", "pad_above": 5, "thickness": 3, "pad_below": 10}, _ctx(), 200)
    assert end == 218  # 5 above + 3px line + 10 below


def test_rule_default_fill_char_none_draws_a_line_not_glyphs():
    """LAYOUT's defaults.rule_fill_char is "none" (bank statements' own
    value) -- confirms the unaligned/undecorated path is unaffected."""
    ctx = _ctx()
    lines_drawn: list = []
    original_line = ctx.draw.line
    ctx.draw.line = lambda *a, **k: (lines_drawn.append((a, k)), original_line(*a, **k))[1]
    texts_drawn: list = []
    original_text = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (
        texts_drawn.append(text),
        original_text(xy, text, **kwargs),
    )[1]

    draw_rule({"type": "rule"}, ctx, 200)

    assert lines_drawn  # draw_separator_line was called
    assert texts_drawn == []  # no glyph row was drawn


def test_rule_fill_char_draws_glyphs_not_a_line():
    """fill_char must dispatch to a row of repeated glyphs (common.py's
    draw_separator), not the drawn `line` the default style uses -- and
    reuse its glyph-count arithmetic rather than reimplementing it."""
    ctx = _ctx()
    lines_drawn: list = []
    original_line = ctx.draw.line
    ctx.draw.line = lambda *a, **k: (lines_drawn.append((a, k)), original_line(*a, **k))[1]
    texts_drawn: list = []
    original_text = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (
        texts_drawn.append(text),
        original_text(xy, text, **kwargs),
    )[1]

    end = draw_rule({"type": "rule", "fill_char": "-"}, ctx, 200)

    assert lines_drawn == []  # draw_separator_line must NOT have been called
    assert len(texts_drawn) == 1
    assert set(texts_drawn[0]) == {"-"}  # a row of repeated glyphs

    font = font_for(LAYOUT, {}, 32, layout_id="x", layout_path="y")  # rule's role defaults to "body"
    dash_bbox = font.getbbox("-")
    dash_width = dash_bbox[2] - dash_bbox[0]
    assert len(texts_drawn[0]) == ctx.region.width // dash_width  # common.draw_separator's own arithmetic

    assert end == 200 + 44  # a full text-line advance (LAYOUT's body line_advance), not `thickness`


def test_rule_fill_char_advances_by_line_advance_not_thickness():
    """A character separator occupies a text line -- proven by a custom
    thickness making no difference to the advance when fill_char is set."""
    ctx = _ctx()
    end = draw_rule({"type": "rule", "fill_char": "=", "thickness": 9, "pad_below": 5}, ctx, 200)
    assert end == 200 + 44 + 5  # line_advance + pad_below; the thickness=9 override is ignored


def test_banner_leaves_the_y_cursor_untouched():
    """Legacy jumps to a hardcoded y after its header bar rather than flowing
    from the bar's own height; a spacer after the banner covers that jump."""
    end = draw_banner({"type": "banner", "content": "ANZ", "height": 120, "color": "#0061B5"}, _ctx(), 200)
    assert end == 200


def test_banner_paints_a_full_bleed_rectangle_at_the_page_top():
    rectangles: list[tuple] = []
    ctx = _ctx()
    original_rectangle = ctx.draw.rectangle

    def spy_rectangle(xy, **kwargs):
        rectangles.append((xy, kwargs.get("fill")))
        return original_rectangle(xy, **kwargs)

    ctx.draw.rectangle = spy_rectangle
    draw_banner({"type": "banner", "content": "ANZ", "height": 120, "color": "#0061B5"}, ctx, 200)
    assert rectangles == [([(0, 0), (1800, 120)], "#0061B5")]  # spans the page, not just the region


def test_banner_draws_text_at_the_declared_text_y_and_region_x():
    drawn: list[tuple] = []
    ctx = _ctx()
    original_text = ctx.draw.text

    def spy_text(xy, text, **kwargs):
        drawn.append((xy, text, kwargs.get("fill")))
        return original_text(xy, text, **kwargs)

    ctx.draw.text = spy_text
    draw_banner(
        {"type": "banner", "content": "ANZ", "height": 120, "color": "#0061B5", "text_y": 30}, ctx, 200
    )
    assert drawn == [((100, 30), "ANZ", "white")]  # region.x, not the page's own x=0


def test_banner_text_color_and_role_are_overridable():
    drawn: list[tuple] = []
    ctx = _ctx()
    original_text = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (
        drawn.append((xy, kwargs.get("fill"))),
        original_text(xy, text, **kwargs),
    )[1]
    draw_banner(
        {
            "type": "banner",
            "content": "ANZ",
            "height": 120,
            "color": "#0061B5",
            "text_color": "#F0F0F0",
            "role": "footer",
        },
        ctx,
        200,
    )
    assert drawn[0][1] == "#F0F0F0"


def test_banner_content_is_interpolated():
    ctx = _ctx()
    drawn: list[str] = []
    original_text = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (drawn.append(text), original_text(xy, text, **kwargs))[1]
    draw_banner({"type": "banner", "content": "{PAYER_NAME}", "height": 120, "color": "#0061B5"}, ctx, 200)
    assert drawn == ["Robin Wood"]


# --- pair: currency formatting and bold (Task 14) ----------------------------


def _amount_ctx(recorder: BoxRecorder | None = None) -> RenderContext:
    ctx = _ctx(recorder)
    ctx.entry = {"fields": {"TOTAL_AMOUNT": "1234.5", "GST_AMOUNT": "112.23", "NOTE": "n/a"}}
    return ctx


def _drawn_strings(ctx):
    """Capture every string drawn through `ctx`, in order.

    Deliberately unannotated, like the other draw-interception helpers in this
    file: mypy rejects assigning to a bound method, and the alternative (a
    stub ImageDraw subclass) buys nothing for a test-only probe.
    """
    drawn: list[str] = []
    original = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (drawn.append(text), original(xy, text, **kwargs))[1]
    return drawn


def test_format_currency_symbol_keeps_the_dollar_sign():
    assert format_currency("1234.5", "symbol", layout_id="x", layout_path="y") == "$1,234.50"


def test_format_currency_plain_drops_the_dollar_sign():
    assert format_currency("1234.5", "plain", layout_id="x", layout_path="y") == "1,234.50"


def test_pair_currency_formats_the_value_not_the_label():
    ctx = _amount_ctx()
    drawn = _drawn_strings(ctx)
    draw_pair(
        {
            "type": "pair",
            "label": "TOTAL",
            "value": "{TOTAL_AMOUNT}",
            "value_align": "right",
            "separator": "",
            "currency": "symbol",
        },
        ctx,
        200,
    )
    assert drawn == ["TOTAL", "$1,234.50"]


def test_pair_without_currency_draws_the_value_verbatim():
    """A provider-formatted value must not be re-formatted -- the receipt's
    cash lines bind an already-`fmt_amount`ed PAYMENT_TENDERED."""
    ctx = _amount_ctx()
    drawn = _drawn_strings(ctx)
    draw_pair(
        {
            "type": "pair",
            "label": "TOTAL",
            "value": "{TOTAL_AMOUNT}",
            "value_align": "right",
            "separator": "",
        },
        ctx,
        200,
    )
    assert drawn == ["TOTAL", "1234.5"]


def test_pair_currency_on_a_non_amount_is_a_four_element_diagnostic():
    ctx = _amount_ctx()
    with pytest.raises(CurrencyError) as exc_info:
        draw_pair({"type": "pair", "label": "Note", "value": "{NOTE}", "currency": "symbol"}, ctx, 200)
    message = str(exc_info.value)
    assert "n/a" in message
    assert_diagnostic_error(message)


def test_pair_currency_is_skipped_for_an_absent_value():
    """An empty interpolation (a NOT_FOUND field) must not raise: a `when:`
    guard, not the formatter, is what suppresses an absent value."""
    ctx = _ctx()
    ctx.entry = {"fields": {"TOTAL_AMOUNT": "NOT_FOUND"}}
    draw_pair({"type": "pair", "label": "TOTAL", "value": "{TOTAL_AMOUNT}", "currency": "symbol"}, ctx, 200)


def test_pair_bold_draws_both_label_and_value_in_the_bold_face():
    """Legacy drew the receipt's TOTAL line's label and amount in font_bold."""
    fonts: list = []
    ctx = _amount_ctx()
    original = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (
        fonts.append(kwargs.get("font")),
        original(xy, text, **kwargs),
    )[1]
    draw_pair(
        {
            "type": "pair",
            "label": "TOTAL",
            "value": "{TOTAL_AMOUNT}",
            "value_align": "right",
            "bold": True,
        },
        ctx,
        200,
    )
    assert len(fonts) == 2
    assert fonts[0] is fonts[1]
    assert fonts[0].path == load_font(32, family=DEFAULTS["family"], bold=True).path


def test_pair_defaults_to_regular_weight():
    fonts: list = []
    ctx = _amount_ctx()
    original = ctx.draw.text
    ctx.draw.text = lambda xy, text, **kwargs: (
        fonts.append(kwargs.get("font")),
        original(xy, text, **kwargs),
    )[1]
    draw_pair(
        {
            "type": "pair",
            "label": "TOTAL",
            "value": "{TOTAL_AMOUNT}",
            "value_align": "right",
            "separator": "",
        },
        ctx,
        200,
    )
    assert fonts[0].path == load_font(32, family=DEFAULTS["family"], bold=False).path
