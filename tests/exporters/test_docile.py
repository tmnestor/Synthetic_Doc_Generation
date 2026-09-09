"""Tests for the DocILE KILE/LIR mapper (spec Mapping B).

DocILE is restricted to invoices (see generators/exporters/docile.py module
docstring), so every fixture here is an invoice with complete geometry —
every DocILE field renders on an invoice, so a missing box is always a real
capture bug, never a structural absence.
"""

import pytest

from conftest import assert_diagnostic_error
from generators.exporters.docile import to_docile

FIELDTYPES = {
    "SUPPLIER_NAME": "vendor_name",
    "BUSINESS_ADDRESS": "vendor_address",
    "BUSINESS_ABN": "vendor_registration_id",
    "INVOICE_DATE": "date_issue",
    "PAYMENT_DUE_DATE": "date_due",
    "GST_AMOUNT": "amount_total_tax",
    "TOTAL_AMOUNT_GROSS": "amount_total_gross",
    "TOTAL_AMOUNT_NET": "amount_total_net",
    "PAYER_NAME": "customer_billing_name",
    "PAYER_ADDRESS": "customer_billing_address",
    "LINE_ITEM_DESCRIPTIONS": "line_item_description",
    "LINE_ITEM_QUANTITIES": "line_item_quantity",
    "LINE_ITEM_PRICES": "line_item_unit_price_gross",
    "LINE_ITEM_TOTAL_PRICES": "line_item_amount_gross",
}

# All 8 KILE columns plus both line items present, matching the "every DocILE
# field renders on an invoice" guarantee behind the invoice-only scope decision.
FIELDS = {
    "DOCUMENT_TYPE": "INVOICE",
    "SUPPLIER_NAME": "Ravensdale Health Store",
    "BUSINESS_ADDRESS": "400 Stewart Rd, South Yarra VIC 3141",
    "BUSINESS_ABN": "79 104 332 181",
    "INVOICE_DATE": "02/03/2023",
    "PAYMENT_DUE_DATE": "16/03/2023",
    "IS_GST_INCLUDED": "true",
    "GST_AMOUNT": "1.24",
    "TOTAL_AMOUNT": "13.60",
    "PAYER_NAME": "Prime Consulting Partners",
    "PAYER_ADDRESS": "13 Mendoza Cl, Glenelg SA 5045",
    "LINE_ITEM_DESCRIPTIONS": "Dishwashing Liquid|Bandaids 40pk",
    "LINE_ITEM_QUANTITIES": "1|1",
    "LINE_ITEM_PRICES": "4.73|8.87",
    "LINE_ITEM_TOTAL_PRICES": "4.73|8.87",
}

BOXES = {
    "SUPPLIER_NAME": [0.08, 0.04, 0.62, 0.09],
    "BUSINESS_ADDRESS": [0.08, 0.16, 0.55, 0.20],
    "BUSINESS_ABN": [0.08, 0.10, 0.55, 0.14],
    "INVOICE_DATE": [0.70, 0.10, 0.95, 0.14],
    "PAYMENT_DUE_DATE": [0.70, 0.16, 0.95, 0.20],
    "GST_AMOUNT": [0.72, 0.80, 0.95, 0.84],
    "TOTAL_AMOUNT": [0.72, 0.86, 0.95, 0.90],
    "PAYER_NAME": [0.08, 0.22, 0.55, 0.26],
    "PAYER_ADDRESS": [0.08, 0.28, 0.55, 0.32],
    "LINE_ITEM_DESCRIPTIONS[0]": [0.06, 0.40, 0.55, 0.44],
    "LINE_ITEM_QUANTITIES[0]": [0.56, 0.40, 0.62, 0.44],
    "LINE_ITEM_PRICES[0]": [0.63, 0.40, 0.80, 0.44],
    "LINE_ITEM_TOTAL_PRICES[0]": [0.81, 0.40, 0.95, 0.44],
    "LINE_ITEM_DESCRIPTIONS[1]": [0.06, 0.45, 0.55, 0.49],
    "LINE_ITEM_QUANTITIES[1]": [0.56, 0.45, 0.62, 0.49],
    "LINE_ITEM_PRICES[1]": [0.63, 0.45, 0.80, 0.49],
    "LINE_ITEM_TOTAL_PRICES[1]": [0.81, 0.45, 0.95, 0.49],
}


def test_kile_emits_one_entry_per_present_field() -> None:
    """Structural: exactly 9 kile entries (8 KILE_COLUMNS + 1 total variant).

    Content: the fieldtype set matches every configured DocILE fieldtype.
    """
    result = to_docile(FIELDS, BOXES, FIELDTYPES)
    assert len(result["kile"]) == 9
    types = {entry["fieldtype"] for entry in result["kile"]}
    assert types == {
        "vendor_name",
        "vendor_address",
        "vendor_registration_id",
        "date_issue",
        "date_due",
        "amount_total_tax",
        "amount_total_gross",
        "customer_billing_name",
        "customer_billing_address",
    }


def test_gst_inclusive_selects_the_gross_total_fieldtype() -> None:
    """Spec section 5.1: IS_GST_INCLUDED chooses between gross and net."""
    result = to_docile(FIELDS, BOXES, FIELDTYPES)
    total = next(e for e in result["kile"] if e["text"] == "13.60")
    assert total["fieldtype"] == "amount_total_gross"


def test_gst_exclusive_selects_the_net_total_fieldtype() -> None:
    result = to_docile({**FIELDS, "IS_GST_INCLUDED": "false"}, BOXES, FIELDTYPES)
    total = next(e for e in result["kile"] if e["text"] == "13.60")
    assert total["fieldtype"] == "amount_total_net"


def test_lir_groups_by_line_item_id() -> None:
    """Structural: 8 lir entries total, 4 per row.

    Content: row 0's texts are the description, quantity and price/total
    (a quantity-one item collapses unit price and line total to one value),
    and indices align — description[0] and quantity[0] both carry
    line_item_id 0, description[1] and quantity[1] both carry line_item_id 1.
    """
    result = to_docile(FIELDS, BOXES, FIELDTYPES)
    assert len(result["lir"]) == 8

    row_zero = [e for e in result["lir"] if e["line_item_id"] == 0]
    row_one = [e for e in result["lir"] if e["line_item_id"] == 1]
    assert len(row_zero) == 4
    assert len(row_one) == 4
    assert {e["text"] for e in row_zero} == {"Dishwashing Liquid", "1", "4.73"}
    assert {e["text"] for e in row_one} == {"Bandaids 40pk", "1", "8.87"}

    description_zero = next(
        e for e in result["lir"] if e["fieldtype"] == "line_item_description" and e["text"] == "Dishwashing Liquid"
    )
    quantity_zero = next(
        e
        for e in result["lir"]
        if e["fieldtype"] == "line_item_quantity" and e["bbox"] == BOXES["LINE_ITEM_QUANTITIES[0]"]
    )
    assert description_zero["line_item_id"] == 0
    assert quantity_zero["line_item_id"] == 0


def test_every_entry_carries_a_page_and_bbox() -> None:
    result = to_docile(FIELDS, BOXES, FIELDTYPES)
    assert result["kile"] + result["lir"]
    for entry in result["kile"] + result["lir"]:
        assert entry["page"] == 0
        assert len(entry["bbox"]) == 4
        assert all(0.0 <= c <= 1.0 for c in entry["bbox"])


def test_missing_geometry_is_a_hard_error() -> None:
    """A silently dropped field is absent from both predictions and truth,
    which inflates precision instead of failing. Every DocILE field on an
    invoice has geometry, so a missing box always signals a real capture bug.
    """
    boxes = {k: v for k, v in BOXES.items() if k != "SUPPLIER_NAME"}
    with pytest.raises(KeyError) as exc:
        to_docile(FIELDS, boxes, FIELDTYPES)
    assert "SUPPLIER_NAME" in str(exc.value)
    assert_diagnostic_error(exc.value)


def test_unknown_fieldtype_is_rejected_at_export_time() -> None:
    fieldtypes = {k: v for k, v in FIELDTYPES.items() if k != "SUPPLIER_NAME"}
    with pytest.raises(KeyError) as exc:
        to_docile(FIELDS, BOXES, fieldtypes)
    assert "SUPPLIER_NAME" in str(exc.value)
    assert "docile_fieldtypes" in str(exc.value)
    assert_diagnostic_error(exc.value)


def test_missing_geometry_for_a_line_item_is_a_hard_error() -> None:
    """The hard-error rule applies to LIR fields too, not just KILE fields."""
    boxes = {k: v for k, v in BOXES.items() if k != "LINE_ITEM_QUANTITIES[1]"}
    with pytest.raises(KeyError) as exc:
        to_docile(FIELDS, boxes, FIELDTYPES)
    assert "LINE_ITEM_QUANTITIES[1]" in str(exc.value)
    assert_diagnostic_error(exc.value)


def test_absent_field_is_omitted_without_requiring_its_box() -> None:
    """A field absent from ground truth (e.g. NOT_FOUND) must not be emitted,
    and must not require geometry either — only *present* fields are hard
    errors when their box is missing.
    """
    fields = {**FIELDS, "PAYMENT_DUE_DATE": "NOT_FOUND"}
    boxes = {k: v for k, v in BOXES.items() if k != "PAYMENT_DUE_DATE"}
    result = to_docile(fields, boxes, FIELDTYPES)
    assert "date_due" not in {e["fieldtype"] for e in result["kile"]}
