"""Invoice fit-safety: budgets present, no field clips, unchanged docs byte-identical."""

import hashlib
import json
from pathlib import Path

from generators.common import fit_text, load_font
from generators.invoice import render_invoice
from generators.layout_budgets import field_budget
from generators.layout_dsl.providers import get_provider
from generators.loader import load_ground_truth, load_layout_registry

_LP = "config/layouts/invoices.yml"
_FIELDS = ("SUPPLIER_NAME", "BUSINESS_ADDRESS", "ABN_LINE", "PAYER_NAME", "PAYER_ADDRESS", "LINE_ITEM_DESC")

# The row provider and params the invoice layouts' own line-item table declares,
# so this measures the descriptions the page actually draws rather than a second,
# drifting copy of the parsing (this used to import invoice.py's _parse_line_items,
# which the declarative migration deleted).
_LINE_ITEM_PARAMS = {
    "fields": {
        "description": "LINE_ITEM_DESCRIPTIONS",
        "quantity": "LINE_ITEM_QUANTITIES",
        "price": "LINE_ITEM_PRICES",
        "total": "LINE_ITEM_TOTAL_PRICES",
    },
    "decimal_keys": ["price", "total"],
}


def _layouts() -> dict:
    return load_layout_registry(Path(_LP))


def _entries() -> dict:
    return load_ground_truth(Path("ground_truth/invoices.yml"))


def _baseline() -> dict:
    return json.loads(Path("tests/fixtures/invoice_baseline_hashes.json").read_text())


def _family(layout: dict) -> str:
    """The face this layout renders in — read from the layout, never hardcoded.

    The four invoice layouts no longer share one face (two are carlito, two are
    liberation_sans), so a hardcoded family would measure a different face than
    the renderer draws and quietly invalidate the fit assertions.
    """
    return str(layout["defaults"]["family"])


def _measure(text: str, size: int, family: str) -> int:
    bbox = load_font(size, family=family).getbbox(text)
    return int(bbox[2] - bbox[0])


def _variable_strings(fields: dict, layout: dict) -> list[tuple[str, str, int]]:
    """(budget_field, rendered_string, nominal_size) for each variable field."""
    sizes = layout["font_sizes"]
    sb = sizes["body"]  # the supplier/payer *name* size
    ss = sizes["subheader"]  # the invoice's workhorse size, everything else
    out: list[tuple[str, str, int]] = [
        ("SUPPLIER_NAME", fields.get("SUPPLIER_NAME", ""), sb),
        ("BUSINESS_ADDRESS", fields.get("BUSINESS_ADDRESS", ""), ss),
        ("ABN_LINE", f"ABN: {fields.get('BUSINESS_ABN', '')}", ss),
    ]
    if fields.get("PAYER_NAME"):
        out.append(("PAYER_NAME", fields["PAYER_NAME"], sb))
        if fields.get("PAYER_ADDRESS"):
            out.append(("PAYER_ADDRESS", fields["PAYER_ADDRESS"], ss))
    for row in get_provider("pipe_fields")({"fields": fields}, _LINE_ITEM_PARAMS):
        if row["description"]:
            out.append(("LINE_ITEM_DESC", row["description"], ss))
    return out


def test_every_invoice_layout_has_budgets():
    layouts = _layouts()
    for lid, layout in layouts.items():
        for field in _FIELDS:
            field_budget(layout, lid, field, layout_path=_LP)


def test_no_invoice_field_overflows_after_fitting():
    layouts = _layouts()
    for entry in _entries().values():
        layout = layouts[entry["layout"]]
        for field, text, size in _variable_strings(entry["fields"], layout):
            if not text:
                continue
            b = field_budget(layout, entry["layout"], field, layout_path=_LP)
            fit_text(
                text, width=b["width"], fit=b["fit"], min_font=b["min_font"],
                max_lines=b["max_lines"], nominal_size=size, family=_family(layout),
            )  # must not raise


def test_unchanged_invoices_byte_identical():
    layouts = _layouts()
    baseline = _baseline()
    for case_id, entry in _entries().items():
        entry["case_id"] = str(case_id)
        layout = layouts[entry["layout"]]
        fits_as_is = all(
            _measure(text, size, _family(layout))
            <= field_budget(layout, entry["layout"], field, layout_path=_LP)["width"]
            for field, text, size in _variable_strings(entry["fields"], layout)
            if text
        )
        digest = hashlib.sha256(render_invoice(entry, layout).tobytes()).hexdigest()
        key = f"{case_id}_{entry['layout']}"
        if fits_as_is:
            assert digest == baseline[key], f"{key} should be byte-identical but changed"
