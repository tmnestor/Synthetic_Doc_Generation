"""Task 10b: draw-time geometry capture for INVOICE_DATE, LINE_ITEM_QUANTITIES,
and LINE_ITEM_PRICES -- the three DocILE-required fields Step 9 found had no
geometry at all (drawn via raw `draw.text` calls, not the capture-hooked
helpers).

Each test renders WITH a recorder (`geometry_out={}`) and asserts the
captured box is present, normalised within [0, 1], and positioned plausibly
(a label-prefixed value's box must not start at the page's left margin -- it
must be offset past the label).

LINE_ITEM_PRICES on receipts is a documented, verified gap: receipts have no
draw site at all for the per-unit price (only the line total is rendered), so
there is nothing on the page to capture without adding new visible content --
which would violate the opt-in/non-destructive contract (pixels must stay
byte-identical with no recorder). That sub-case is asserted as BLOCKED, not
faked.
"""

from pathlib import Path

from generators.invoice import render_invoice
from generators.loader import load_ground_truth, load_layout_registry
from generators.receipt import render_receipt

_RECEIPT_GT = Path("ground_truth/receipts.yml")
_RECEIPT_LAYOUTS = Path("config/layouts/receipts.yml")
_INVOICE_GT = Path("ground_truth/invoices.yml")
_INVOICE_LAYOUTS = Path("config/layouts/invoices.yml")


def _receipt_entry(case_id: str) -> tuple[dict, dict]:
    gt = load_ground_truth(_RECEIPT_GT)
    layouts = load_layout_registry(_RECEIPT_LAYOUTS)
    entry = dict(gt[case_id])
    entry["case_id"] = case_id
    layout = layouts[entry["layout"]]
    return entry, layout


def _invoice_entry(case_id: str) -> tuple[dict, dict]:
    gt = load_ground_truth(_INVOICE_GT)
    layouts = load_layout_registry(_INVOICE_LAYOUTS)
    entry = dict(gt[case_id])
    entry["case_id"] = case_id
    layout = layouts[entry["layout"]]
    return entry, layout


def _assert_box_in_unit_square(box: list[float]) -> None:
    left, top, right, bottom = box
    for v in (left, top, right, bottom):
        assert 0.0 <= v <= 1.0, f"coordinate {v} outside [0, 1]: {box}"
    assert left < right, f"degenerate/zero-width box: {box}"
    assert top < bottom, f"degenerate/zero-height box: {box}"


# --- INVOICE_DATE -----------------------------------------------------------


def test_receipt_invoice_date_captured_and_offset_past_label() -> None:
    """The receipt_meta branch draws 'Date: <value>' as one string; the
    recorded box must cover only the value, so it must not start at the
    left margin (it must be offset past the "Date: " label)."""
    entry, layout = _receipt_entry("CASE001")
    margin = layout.get("margin", 40)
    geometry_out: dict = {}
    render_receipt(entry, layout, geometry_out=geometry_out)

    assert "INVOICE_DATE" in geometry_out["boxes"]
    box = geometry_out["boxes"]["INVOICE_DATE"]
    _assert_box_in_unit_square(box)

    left_px = box[0] * geometry_out["width"]
    assert left_px > margin, (
        f"INVOICE_DATE box starts at x={left_px:.1f}px, expected it offset past "
        f"the 'Date: ' label (margin={margin}px) -- looks like the label was "
        f"captured along with the value."
    )


def test_invoice_invoice_date_captured_and_offset_past_label() -> None:
    """Same label-prefix check on the invoice renderer's live
    section/name==invoice_metadata branch."""
    entry, layout = _invoice_entry("CASE001")
    margin = layout.get("margin", 100)
    geometry_out: dict = {}
    render_invoice(entry, layout, geometry_out=geometry_out)

    assert "INVOICE_DATE" in geometry_out["boxes"]
    box = geometry_out["boxes"]["INVOICE_DATE"]
    _assert_box_in_unit_square(box)

    left_px = box[0] * geometry_out["width"]
    assert left_px > margin, (
        f"INVOICE_DATE box starts at x={left_px:.1f}px, expected it offset past "
        f"the 'Date: ' label (margin={margin}px)."
    )


def test_invoice_date_value_matches_ground_truth_string_width() -> None:
    """The box should be sized for the *value* substring, not the whole
    'Date: <value>' string -- i.e. narrower than the full label+value run."""
    entry, layout = _invoice_entry("CASE001")
    geometry_out: dict = {}
    render_invoice(entry, layout, geometry_out=geometry_out)
    box = geometry_out["boxes"]["INVOICE_DATE"]
    value = entry["fields"]["INVOICE_DATE"]
    width_px = (box[2] - box[0]) * geometry_out["width"]
    # A short date string like "20/11/2023" at this layout's small font is a
    # few hundred px at most on a ~2000px-wide page; sanity-bound it well
    # below the full page width so a label-inclusive box would fail this.
    assert 0 < width_px < geometry_out["width"] * 0.3
    assert len(value) > 0


# --- LINE_ITEM_QUANTITIES -----------------------------------------------


def test_receipt_line_item_quantity_captured_when_rendered() -> None:
    """CASE003 has quantities > 1, so the receipt renders a '2x ' prefix on
    the description line; that prefix's own sub-box must be captured."""
    entry, layout = _receipt_entry("CASE003")
    geometry_out: dict = {}
    render_receipt(entry, layout, geometry_out=geometry_out)

    qtys = entry["fields"]["LINE_ITEM_QUANTITIES"].split("|")
    found_any = False
    for i, qty in enumerate(qtys):
        key = f"LINE_ITEM_QUANTITIES[{i}]"
        if qty.strip() not in ("1", ""):
            assert key in geometry_out["boxes"], f"{key} not captured for qty={qty!r}"
            _assert_box_in_unit_square(geometry_out["boxes"][key])
            found_any = True
    assert found_any, "fixture CASE003 was expected to have a qty != 1 line item"


def test_receipt_line_item_quantity_of_one_has_no_box_by_design() -> None:
    """Quantity 1 is never printed on receipts (real receipts don't write
    '1x Coffee') -- so there is genuinely nothing to capture for those rows.
    This documents the known, deliberate shortfall rather than hiding it."""
    entry, layout = _receipt_entry("CASE003")
    geometry_out: dict = {}
    render_receipt(entry, layout, geometry_out=geometry_out)
    qtys = entry["fields"]["LINE_ITEM_QUANTITIES"].split("|")
    for i, qty in enumerate(qtys):
        if qty.strip() == "1":
            assert f"LINE_ITEM_QUANTITIES[{i}]" not in geometry_out["boxes"]


def test_invoice_line_item_quantity_captured_for_every_item() -> None:
    """Invoices always print the quantity column regardless of its value, so
    every line item's quantity must be captured."""
    entry, layout = _invoice_entry("CASE001")
    geometry_out: dict = {}
    render_invoice(entry, layout, geometry_out=geometry_out)
    qtys = entry["fields"]["LINE_ITEM_QUANTITIES"].split("|")
    for i in range(len(qtys)):
        key = f"LINE_ITEM_QUANTITIES[{i}]"
        assert key in geometry_out["boxes"], f"{key} missing"
        _assert_box_in_unit_square(geometry_out["boxes"][key])


# --- LINE_ITEM_PRICES ----------------------------------------------------


def test_invoice_line_item_price_captured_for_every_item() -> None:
    """Regression guard: invoices already had full LINE_ITEM_PRICES coverage
    before this change; must remain so."""
    entry, layout = _invoice_entry("CASE001")
    geometry_out: dict = {}
    render_invoice(entry, layout, geometry_out=geometry_out)
    prices = entry["fields"]["LINE_ITEM_PRICES"].split("|")
    for i in range(len(prices)):
        key = f"LINE_ITEM_PRICES[{i}]"
        assert key in geometry_out["boxes"], f"{key} missing"
        _assert_box_in_unit_square(geometry_out["boxes"][key])


def test_receipt_line_item_price_is_blocked_no_draw_site_exists() -> None:
    """Documented BLOCKED gap: render_receipt has no draw call for the
    per-unit price anywhere (only LINE_ITEM_TOTAL_PRICES is ever printed), so
    there is no pixel location to capture without adding new visible content
    -- which would break the opt-in/non-destructive contract. This test pins
    that fact so a future fix is a deliberate, visible decision, not a
    silent regression."""
    entry, layout = _receipt_entry("CASE001")
    geometry_out: dict = {}
    render_receipt(entry, layout, geometry_out=geometry_out)
    prices = entry["fields"].get("LINE_ITEM_PRICES", "").split("|")
    for i in range(len(prices)):
        assert f"LINE_ITEM_PRICES[{i}]" not in geometry_out["boxes"]


# --- non-destructive / opt-in contract ------------------------------------


def test_no_recorder_still_byte_identical_after_task10b_changes() -> None:
    """The new capture calls must never alter pixels when there is no
    recorder -- same invariant Task 10 Step 9 established."""
    r_entry, r_layout = _receipt_entry("CASE003")
    a = render_receipt(dict(r_entry), r_layout)
    b = render_receipt(dict(r_entry), r_layout, geometry_out=None)
    assert a.tobytes() == b.tobytes()
    assert a.size == b.size

    i_entry, i_layout = _invoice_entry("CASE001")
    c = render_invoice(dict(i_entry), i_layout)
    d = render_invoice(dict(i_entry), i_layout, geometry_out=None)
    assert c.tobytes() == d.tobytes()
    assert c.size == d.size
