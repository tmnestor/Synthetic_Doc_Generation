"""Pixel-level anchor test for draw-time bounding boxes (Task 12b).

Task 12's DocILE self-score is structurally blind to systematic bbox bugs:
the gold annotations, synthesized OCR, and predictions all derive from the
same `to_docile` output, so a transposed axis or a wrong offset moves all
three in lockstep and still scores 1.0. Nothing before this file verified
that a captured bounding box actually lands on the *rendered pixels* of its
field's text.

For most fields the recorded box is exactly the renderer's own draw
coordinate, so it cannot drift from the glyphs. INVOICE_DATE is the
exception: `capture_label_prefixed_value` (generators/common.py) computes the
box by measuring the pixel width of the literal "Date: " label and shifting
the box right by that amount, so the recorded box covers the value, not the
label. That arithmetic (added in commit 434bc82) is exactly the kind of bug
that could be subtly wrong while every existing (geometry-only,
label-vs-margin) test still passes, because none of them look at pixels.

This file renders real documents with a BoxRecorder, converts each
normalised box back to pixel coordinates, crops that region out of the
actual rendered PIL image, and asserts the crop contains dark ink -- not
blank paper. A negative control (a page region known to be empty) proves the
check can actually fail, rather than trivially passing on any crop.
"""

from pathlib import Path

import numpy as np
from PIL import Image

from generators.invoice import render_invoice
from generators.loader import load_ground_truth, load_layout_registry
from generators.receipt import render_receipt

_INVOICE_GT = Path("ground_truth/invoices.yml")
_INVOICE_LAYOUTS = Path("config/layouts/invoices.yml")
_RECEIPT_GT = Path("ground_truth/receipts.yml")
_RECEIPT_LAYOUTS = Path("config/layouts/receipts.yml")

# Grayscale intensity below which a pixel counts as "ink". Body text on these
# layouts is rendered as near-black glyphs (fill="black") on a pure white
# background, so real text pixels fall well under 100 while every untouched
# background pixel is exactly 255; 180 sits far from both, tolerant of
# anti-aliased glyph edges without drifting into false positives.
_DARK_THRESHOLD = 180

# Minimum fraction of "dark" pixels a box must contain to count as covering
# drawn text. Chosen well below every positive-control measurement observed
# on these fixtures (roughly 0.10-0.35 -- see the module docstring in the
# accompanying report) and well above the negative control (0.0 on an
# untouched page margin), so it discriminates cleanly rather than being
# tuned to make any one field pass.
_MIN_DARK_FRACTION = 0.03


def _entry_and_layout(gt_path: Path, layouts_path: Path, case_id: str) -> tuple[dict, dict]:
    """Load one ground-truth entry and its resolved layout dict."""
    gt = load_ground_truth(gt_path)
    layouts = load_layout_registry(layouts_path)
    entry = dict(gt[case_id])
    entry["case_id"] = case_id
    layout = layouts[entry["layout"]]
    return entry, layout


def _pixel_box(box: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    """Convert a normalised [0, 1] box back to pixel coordinates on the page."""
    left, top, right, bottom = box
    return int(left * width), int(top * height), int(right * width), int(bottom * height)


def _dark_fraction(img: Image.Image, px_box: tuple[int, int, int, int]) -> float:
    """Fraction of pixels in `px_box` darker than `_DARK_THRESHOLD` (grayscale)."""
    left, top, right, bottom = px_box
    assert right > left and bottom > top, f"degenerate/empty crop region {px_box}"
    crop = img.crop((left, top, right, bottom)).convert("L")
    arr = np.array(crop)
    return float((arr < _DARK_THRESHOLD).mean())


def _assert_covers_text(img: Image.Image, box: list[float], width: int, height: int, field: str) -> float:
    """Assert a normalised box lands on drawn ink; returns the measured fraction."""
    px_box = _pixel_box(box, width, height)
    fraction = _dark_fraction(img, px_box)
    assert fraction >= _MIN_DARK_FRACTION, (
        f"{field}'s captured box {px_box} (normalised {box}) has only "
        f"{fraction:.4f} of its pixels darker than {_DARK_THRESHOLD} -- expected "
        f">= {_MIN_DARK_FRACTION}. This box lands on blank paper, not on drawn "
        f"text: the Task 10b offset arithmetic for this field is wrong."
    )
    return fraction


# --- negative control: proves the check can actually fail -------------------


def test_blank_margin_region_fails_the_text_check_on_invoice() -> None:
    """A known-empty strip of page must NOT pass `_assert_covers_text`.

    This is the negative control: without it, a test that simply measures
    "some darkness" could pass on any crop, including one on blank paper,
    which is exactly the failure mode this file exists to catch.
    """
    entry, layout = _entry_and_layout(_INVOICE_GT, _INVOICE_LAYOUTS, "CASE001")
    geometry_out: dict = {}
    img = render_invoice(entry, layout, geometry_out=geometry_out)
    width, height = geometry_out["width"], geometry_out["height"]

    # Top-right corner strip: above the title baseline and inside the right
    # margin gutter, where nothing is ever drawn.
    blank_px_box = (width - 50, 0, width, 30)
    fraction = _dark_fraction(img, blank_px_box)
    assert fraction < _MIN_DARK_FRACTION, (
        f"expected the blank margin region {blank_px_box} to be free of ink, "
        f"but measured dark fraction {fraction:.4f} -- fixture assumption broken, "
        f"this region no longer proves the check can distinguish text from paper."
    )


def test_blank_margin_region_fails_the_text_check_on_receipt() -> None:
    """Same negative control on a receipt page (different aspect ratio/DPI)."""
    entry, layout = _entry_and_layout(_RECEIPT_GT, _RECEIPT_LAYOUTS, "CASE001")
    geometry_out: dict = {}
    img = render_receipt(entry, layout, geometry_out=geometry_out)
    width, height = geometry_out["width"], geometry_out["height"]

    blank_px_box = (width - 50, 0, width, 30)
    fraction = _dark_fraction(img, blank_px_box)
    assert fraction < _MIN_DARK_FRACTION, (
        f"expected the blank margin region {blank_px_box} to be free of ink, "
        f"but measured dark fraction {fraction:.4f}."
    )


# --- INVOICE_DATE: the primary target (label-offset arithmetic) -------------


def test_invoice_date_box_lands_on_the_value_pixels() -> None:
    """The INVOICE_DATE box (offset past 'Date: ' by Task 10b) must cover ink."""
    entry, layout = _entry_and_layout(_INVOICE_GT, _INVOICE_LAYOUTS, "CASE001")
    geometry_out: dict = {}
    img = render_invoice(entry, layout, geometry_out=geometry_out)
    width, height = geometry_out["width"], geometry_out["height"]
    box = geometry_out["boxes"]["INVOICE_DATE"]

    _assert_covers_text(img, box, width, height, "INVOICE_DATE")


def test_invoice_date_box_excludes_the_label_to_its_left() -> None:
    """The region immediately LEFT of the captured box must ALSO contain ink.

    That region is where the "Date: " label itself sits. If the offset
    arithmetic were wrong and the box's left edge started at the line origin
    (i.e. included the label), there would be nothing left of the box to
    inspect -- this test would degenerate or find blank space. Finding ink
    here, with the value box starting to its right, is the positive proof
    that the box begins after the label rather than at the label's start.
    """
    entry, layout = _entry_and_layout(_INVOICE_GT, _INVOICE_LAYOUTS, "CASE001")
    margin = layout.get("margin", 100)
    geometry_out: dict = {}
    img = render_invoice(entry, layout, geometry_out=geometry_out)
    width, height = geometry_out["width"], geometry_out["height"]
    box = geometry_out["boxes"]["INVOICE_DATE"]

    left_px, top_px, _right_px, bottom_px = _pixel_box(box, width, height)
    label_px_box = (margin, top_px, left_px, bottom_px)
    fraction = _dark_fraction(img, label_px_box)
    assert fraction >= _MIN_DARK_FRACTION, (
        f"region left of the INVOICE_DATE box {label_px_box} (between the page "
        f"margin {margin}px and the box's left edge {left_px}px) has only "
        f"{fraction:.4f} dark-pixel fraction -- expected to find the 'Date: ' "
        f"label's ink there. If this is blank, the box's left edge did not "
        f"actually move past the label."
    )


def test_receipt_date_box_lands_on_value_and_excludes_label() -> None:
    """Same label-offset anchor on the receipt renderer.

    generators/receipt.py draws INVOICE_DATE via the same
    `capture_label_prefixed_value("Date: ", ...)` helper as invoices (see the
    receipt_meta/title/metadata section branches), so it carries the same
    Task 10b offset-arithmetic risk and gets the same two-sided check.
    """
    entry, layout = _entry_and_layout(_RECEIPT_GT, _RECEIPT_LAYOUTS, "CASE001")
    margin = layout.get("margin", 40)
    geometry_out: dict = {}
    img = render_receipt(entry, layout, geometry_out=geometry_out)
    width, height = geometry_out["width"], geometry_out["height"]
    box = geometry_out["boxes"]["INVOICE_DATE"]

    _assert_covers_text(img, box, width, height, "INVOICE_DATE")

    left_px, top_px, _right_px, bottom_px = _pixel_box(box, width, height)
    label_px_box = (margin, top_px, left_px, bottom_px)
    fraction = _dark_fraction(img, label_px_box)
    assert fraction >= _MIN_DARK_FRACTION, (
        f"region left of the receipt INVOICE_DATE box {label_px_box} has only "
        f"{fraction:.4f} dark-pixel fraction -- expected the 'Date: ' label's "
        f"ink there."
    )


# --- positive controls: fields captured via the normal (non-offset) helpers -


def test_invoice_supplier_name_box_lands_on_text() -> None:
    """SUPPLIER_NAME's box is the renderer's own draw_fitted_left extent --
    a sanity check that the anchoring method itself is sound, independent of
    any Task 10b offset arithmetic."""
    entry, layout = _entry_and_layout(_INVOICE_GT, _INVOICE_LAYOUTS, "CASE001")
    geometry_out: dict = {}
    img = render_invoice(entry, layout, geometry_out=geometry_out)
    width, height = geometry_out["width"], geometry_out["height"]
    box = geometry_out["boxes"]["SUPPLIER_NAME"]

    _assert_covers_text(img, box, width, height, "SUPPLIER_NAME")


def test_invoice_total_amount_box_lands_on_text() -> None:
    """TOTAL_AMOUNT is captured via draw_text_right's own extent."""
    entry, layout = _entry_and_layout(_INVOICE_GT, _INVOICE_LAYOUTS, "CASE001")
    geometry_out: dict = {}
    img = render_invoice(entry, layout, geometry_out=geometry_out)
    width, height = geometry_out["width"], geometry_out["height"]
    box = geometry_out["boxes"]["TOTAL_AMOUNT"]

    _assert_covers_text(img, box, width, height, "TOTAL_AMOUNT")


def test_invoice_line_item_description_box_lands_on_text() -> None:
    """LINE_ITEM_DESCRIPTIONS[0] is captured via draw_fitted_left's own extent."""
    entry, layout = _entry_and_layout(_INVOICE_GT, _INVOICE_LAYOUTS, "CASE001")
    geometry_out: dict = {}
    img = render_invoice(entry, layout, geometry_out=geometry_out)
    width, height = geometry_out["width"], geometry_out["height"]
    box = geometry_out["boxes"]["LINE_ITEM_DESCRIPTIONS[0]"]

    _assert_covers_text(img, box, width, height, "LINE_ITEM_DESCRIPTIONS[0]")
