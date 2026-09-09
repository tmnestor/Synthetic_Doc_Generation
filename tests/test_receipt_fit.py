"""Receipt fit-safety: budgets present, no field clips, and unchanged docs stay
byte-identical while pre-existing overflows are fixed (wrapped/shrunk)."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from generators.common import fit_text, load_font
from generators.layout_budgets import field_budget
from generators.layout_dsl.field_providers import receipt_pos
from generators.layout_dsl.providers import get_provider
from generators.loader import load_ground_truth, load_layout_registry
from generators.payment_block import derive_payment
from generators.receipt import render_receipt

# The row/field providers the receipt layouts declare — the same code path the
# `body:` tree renders through, so this measures what the page actually draws
# rather than a second, drifting copy of the line-item and POS derivations.
_LINE_ITEM_PARAMS = {
    "fields": {
        "description": "LINE_ITEM_DESCRIPTIONS",
        "quantity": "LINE_ITEM_QUANTITIES",
        "price": "LINE_ITEM_PRICES",
        "total": "LINE_ITEM_TOTAL_PRICES",
    },
    "quantity_prefix_format": "{quantity}x ",
}

_LP = "config/layouts/receipts.yml"
# No PHONE: the merchant "Ph:" line was dropped when the body went declarative,
# because BUSINESS_PHONE is not a field of field_definitions.yml's
# document_fields.receipt, so no receipt entry can carry one.
_FIELDS = (
    "SUPPLIER_NAME",
    "BUSINESS_ADDRESS",
    "ABN_LINE",
    "LINE_ITEM_DESC",
    "LINE_ITEM_AMOUNT",
    "PAYMENT_ACQUIRER",
    "PAYMENT_LINE",
)


def _layouts() -> dict:
    return load_layout_registry(Path(_LP))


def _entries() -> dict:
    return load_ground_truth(Path("ground_truth/receipts.yml"))


def _baseline() -> dict:
    return json.loads(Path("tests/fixtures/receipt_baseline_hashes.json").read_text())


def _family(layout: dict) -> str:
    """The face this layout renders in — read from the layout, never hardcoded.

    All six receipt layouts are liberation_mono today, but reading it keeps
    this test honest if one ever moves to a proportional face (see the
    follow-up note in config/layouts/receipts.yml).
    """
    return str(layout["defaults"]["family"])


def _measure(text: str, size: int, family: str, *, bold: bool) -> int:
    bbox = load_font(size, family=family, bold=bold).getbbox(text)
    return int(bbox[2] - bbox[0])


def _fixed_slip_strings(layout: dict) -> list[tuple[str, str, bool]]:
    """(budget_field, literal, bold) for every slip block drawing constant text.

    Read out of the layout body rather than restated here: these strings are
    the page's own fixed wording, so a test carrying its own copy of them
    could pass while the page itself overflowed. A slip block is one guarded
    on a PAYMENT_* key; a block whose content carries a `{PLACEHOLDER}` is not
    constant and is handled by the caller instead.
    """
    out: list[tuple[str, str, bool]] = []
    for block in layout["body"]:
        if not str(block.get("when", "")).startswith("PAYMENT_"):
            continue
        content = block.get("content")
        if not isinstance(content, str) or "{" in content:
            continue
        out.append((block["budget"], content, bool(block.get("bold", False))))
    return out


def _variable_strings(case_id: str, fields: dict, layout: dict) -> list[tuple[str, str, bool]]:
    """(budget_field, rendered_string, bold) for each variable field of an entry.

    Includes the EFTPOS payment block's lines, derived exactly as the renderer
    derives them, so a terminal line that cannot fit its layout fails here.
    """
    out: list[tuple[str, str, bool]] = [("SUPPLIER_NAME", fields.get("SUPPLIER_NAME", ""), True)]
    if fields.get("BUSINESS_ADDRESS"):
        out.append(("BUSINESS_ADDRESS", fields["BUSINESS_ADDRESS"], False))
    if fields.get("BUSINESS_ABN"):
        out.append(("ABN_LINE", f"ABN: {fields['BUSINESS_ABN']}", False))
    # The provider already applies the quantity prefix and coerces the amount
    # columns to Decimal, exactly as the table draws them.
    for item in get_provider("receipt_line_items")({"fields": fields}, _LINE_ITEM_PARAMS):
        out.append(("LINE_ITEM_DESC", item["description"], False))
        if item["total"] != "":
            out.append(("LINE_ITEM_AMOUNT", f"{Decimal(item['total']):,.2f}", False))

    pos_time = receipt_pos({"case_id": case_id, "fields": fields}, {})["POS_TIME"]
    d = derive_payment(
        case_id,
        fields.get("INVOICE_DATE", ""),
        fields.get("TOTAL_AMOUNT", "0"),
        pos_time,
    )
    if d.kind == "cash":
        return out
    out.append(("PAYMENT_ACQUIRER", d.acquirer, False))
    out.extend(_fixed_slip_strings(layout))
    if d.kind == "wallet":
        # The one slip line that is neither fully fixed nor fully derived. Its
        # literal half is pinned against the body by
        # test_payment_block.py::test_the_receipt_body_prints_the_expected_slip_wording.
        out.append(("PAYMENT_LINE", f"CONTACTLESS - {d.wallet_label}", False))
    for text in (
        f"{d.scheme_display} {d.account_type}",
        f"AID: {d.aid}",
        f"Card: {d.masked_pan} {d.entry_mode}",
        f"PSN: {d.psn}, ATC: {d.atc}",
        f"Terminal ID: {d.terminal_id}",
        f"Transaction Ref: {d.transaction_ref}",
        d.timestamp,
    ):
        out.append(("PAYMENT_LINE", text, False))
    return out


def test_every_receipt_layout_has_budgets_for_variable_fields():
    layouts = _layouts()
    for lid, layout in layouts.items():
        for field in _FIELDS:
            field_budget(layout, lid, field, layout_path=_LP)  # raises if missing/invalid


def test_no_variable_field_overflows_after_fitting():
    """Every current string fits its budget losslessly (fit_text never raises)."""
    layouts = _layouts()
    for case_id, entry in _entries().items():
        layout = layouts[entry["layout"]]
        size = layout["font_sizes"]["body"]
        for field, text, bold in _variable_strings(str(case_id), entry["fields"], layout):
            if not text:
                continue
            b = field_budget(layout, entry["layout"], field, layout_path=_LP)
            fit_text(
                text,
                width=b["width"],
                fit=b["fit"],
                min_font=b["min_font"],
                max_lines=b["max_lines"],
                nominal_size=size,
                family=_family(layout),
                bold=bold,
            )  # must not raise FitError


def test_unchanged_docs_byte_identical():
    # Baselines re-captured after the bank-consistency change: each receipt's card
    # scheme now comes from its linked bank row, so the post-EFTPOS-block hashes no
    # longer apply either. From this point they pin renders in which every linked
    # receipt agrees with its bank statement; any further renderer change must be
    # deliberate and re-captured the same way.
    layouts = _layouts()
    baseline = _baseline()
    for case_id, entry in _entries().items():
        entry["case_id"] = str(case_id)
        layout = layouts[entry["layout"]]
        digest = hashlib.sha256(render_receipt(entry, layout).tobytes()).hexdigest()
        key = f"{case_id}_{entry['layout']}"
        assert digest == baseline[key], f"{key} should be byte-identical but changed"
