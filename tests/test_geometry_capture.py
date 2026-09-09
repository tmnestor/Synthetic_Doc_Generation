"""Draw-time geometry capture across all three renderers.

Verifies the opt-in contract end to end: passing `geometry_out=None` (the
default) must render pixel-identical to no signature change at all, and
passing `geometry_out={}` must never crash -- including the one document
type (tax_invoice_mixed) that draws the same LINE_ITEM_* list into two
separate table sections.
"""

from pathlib import Path

from generators.bank_statement import render_bank_statement
from generators.invoice import render_invoice
from generators.loader import load_ground_truth, load_layout_registry
from generators.receipt import render_receipt

_RENDERERS = {
    "bank_statements": (render_bank_statement, "config/layouts/bank_statements.yml"),
    "receipts": (render_receipt, "config/layouts/receipts.yml"),
    "invoices": (render_invoice, "config/layouts/invoices.yml"),
}


def _first_entry_per_layout(gt_path: str) -> dict:
    """Return {layout_id: (case_id, entry)} for the first entry seen per layout."""
    gt = load_ground_truth(Path(gt_path))
    seen: dict[str, tuple[str, dict]] = {}
    for case_id, entry in gt.items():
        layout_ref = entry.get("layout", "")
        if layout_ref not in seen:
            seen[layout_ref] = (str(case_id), entry)
    return seen


def test_default_call_has_no_geometry_out_and_returns_an_image() -> None:
    """The plain two-arg call (no geometry_out at all) must still work."""
    gt = load_ground_truth(Path("ground_truth/receipts.yml"))
    layouts = load_layout_registry(Path("config/layouts/receipts.yml"))
    case_id, entry = next(iter(gt.items()))
    entry["case_id"] = str(case_id)
    layout = layouts[entry.get("layout", "")]
    img = render_receipt(entry, layout)
    assert img.width > 0
    assert img.height > 0


def test_geometry_out_none_is_identical_to_omitting_it() -> None:
    """Explicit geometry_out=None must render exactly like the bare call."""
    gt = load_ground_truth(Path("ground_truth/receipts.yml"))
    layouts = load_layout_registry(Path("config/layouts/receipts.yml"))
    case_id, entry = next(iter(gt.items()))
    entry["case_id"] = str(case_id)
    layout = layouts[entry.get("layout", "")]
    a = render_receipt(dict(entry), layout)
    b = render_receipt(dict(entry), layout, geometry_out=None)
    assert a.tobytes() == b.tobytes()
    assert a.size == b.size


def test_every_layout_across_every_renderer_captures_geometry_without_crashing() -> None:
    """geometry_out={} must populate width/height/boxes for every layout id.

    This is Step 9's central check: it would have caught the tax_invoice_mixed
    duplicate-table crash (two "table" sections drawing the same
    LINE_ITEM_* list) before it ever reached `pipeline generate`.
    """
    for renderer, layout_path in _RENDERERS.values():
        layouts = load_layout_registry(Path(layout_path))
        gt_path = {
            "config/layouts/bank_statements.yml": "ground_truth/bank_statements.yml",
            "config/layouts/receipts.yml": "ground_truth/receipts.yml",
            "config/layouts/invoices.yml": "ground_truth/invoices.yml",
        }[layout_path]
        by_layout = _first_entry_per_layout(gt_path)

        for layout_id, layout in layouts.items():
            assert layout_id in by_layout, f"no ground-truth entry uses layout {layout_id!r}"
            case_id, entry = by_layout[layout_id]
            entry = dict(entry)
            entry["case_id"] = case_id
            geometry_out: dict = {}
            renderer(entry, layout, geometry_out=geometry_out)
            assert geometry_out["width"] > 0
            assert geometry_out["height"] > 0
            assert isinstance(geometry_out["boxes"], dict)


def test_invoice_mixed_layout_only_captures_the_first_table() -> None:
    """tax_invoice_mixed draws LINE_ITEM_DESCRIPTIONS twice (taxable + tax-free
    tables) -- only the first table's boxes may be recorded, or the second
    draw would collide with the first in the recorder."""
    gt = load_ground_truth(Path("ground_truth/invoices.yml"))
    layouts = load_layout_registry(Path("config/layouts/invoices.yml"))
    case_id, entry = next(
        (str(cid), e) for cid, e in gt.items() if e.get("layout") == "tax_invoice_mixed"
    )
    entry = dict(entry)
    entry["case_id"] = case_id
    layout = layouts["tax_invoice_mixed"]
    geometry_out: dict = {}
    render_invoice(entry, layout, geometry_out=geometry_out)
    assert "LINE_ITEM_DESCRIPTIONS[0]" in geometry_out["boxes"]
