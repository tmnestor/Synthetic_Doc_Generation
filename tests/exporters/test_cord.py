"""Tests for the CORD gt_parse mapper (spec Mapping A)."""

from generators.exporters.cord import to_cord

CASE001_RECEIPT = {
    "DOCUMENT_TYPE": "RECEIPT",
    "SUPPLIER_NAME": "Ravensdale Health Store",
    "BUSINESS_ABN": "79 104 332 181",
    "BUSINESS_ADDRESS": "400 Stewart Rd, South Yarra VIC 3141",
    "INVOICE_DATE": "02/03/2023",
    "IS_GST_INCLUDED": "true",
    "GST_AMOUNT": "1.24",
    "TOTAL_AMOUNT": "13.60",
    "LINE_ITEM_DESCRIPTIONS": "Dishwashing Liquid|Bandaids 40pk",
    "LINE_ITEM_QUANTITIES": "1|1",
    "LINE_ITEM_PRICES": "4.73|8.87",
    "LINE_ITEM_TOTAL_PRICES": "4.73|8.87",
}

EXPECTED = {
    "menu": [
        {"nm": "Dishwashing Liquid", "cnt": "1", "unitprice": "4.73", "price": "4.73"},
        {"nm": "Bandaids 40pk", "cnt": "1", "unitprice": "8.87", "price": "8.87"},
    ],
    "sub_total": {"tax_price": "1.24"},
    "total": {"total_price": "13.60"},
    "extension": {
        "supplier_name": "Ravensdale Health Store",
        "business_abn": "79 104 332 181",
        "business_address": "400 Stewart Rd, South Yarra VIC 3141",
        "invoice_date": "02/03/2023",
    },
}


def _leaf_values(node: object) -> list[object]:
    """Recursively collect every leaf (non-container) value in a gt_parse tree.

    Args:
        node: A gt_parse tree, or any nested dict/list/scalar within one.

    Returns:
        A flat list of every scalar value found at the leaves of the tree,
        so tests can assert on actual emitted *values* rather than relying
        on substring checks against ``str(tree)``.
    """
    if isinstance(node, dict):
        values: list[object] = []
        for value in node.values():
            values.extend(_leaf_values(value))
        return values
    if isinstance(node, list):
        values = []
        for item in node:
            values.extend(_leaf_values(item))
        return values
    return [node]


def test_case001_matches_the_spec_worked_example() -> None:
    assert to_cord(CASE001_RECEIPT, "spaced") == EXPECTED


def test_is_gst_included_is_not_emitted() -> None:
    """Spec section 3 rule 6: the boolean is generator metadata, not tree content.

    Strengthened beyond the field-name check: given cord.py's allowlist
    architecture, "IS_GST_INCLUDED" not in str(tree) can only fail if the
    whole fields dict leaked wholesale. The requirement actually means the
    *value* "true" must never appear anywhere in the emitted tree either.
    """
    tree = to_cord(CASE001_RECEIPT, "spaced")
    assert "IS_GST_INCLUDED" not in str(tree)
    assert "true" not in _leaf_values(tree)


def test_document_type_is_not_emitted() -> None:
    """As above: also assert the value "RECEIPT" is absent, not just the key."""
    tree = to_cord(CASE001_RECEIPT, "spaced")
    assert "RECEIPT" not in str(tree)
    assert "RECEIPT" not in _leaf_values(tree)


def test_not_found_fields_are_absent() -> None:
    """Spec section 3 rule 5: NOT_FOUND is never emitted."""
    fields = {**CASE001_RECEIPT, "BUSINESS_ADDRESS": "NOT_FOUND"}
    tree = to_cord(fields, "spaced")
    assert "business_address" not in tree["extension"]


def test_invoice_adds_payer_to_extension() -> None:
    fields = {
        **CASE001_RECEIPT,
        "DOCUMENT_TYPE": "INVOICE",
        "PAYER_NAME": "Prime Consulting Partners",
        "PAYER_ADDRESS": "13 Mendoza Cl, Glenelg SA 5045",
    }
    extension = to_cord(fields, "spaced")["extension"]
    assert extension["payer_name"] == "Prime Consulting Partners"
    assert extension["payer_address"] == "13 Mendoza Cl, Glenelg SA 5045"


def test_digits_only_form_applies_to_abn() -> None:
    tree = to_cord(CASE001_RECEIPT, "digits_only")
    assert tree["extension"]["business_abn"] == "79104332181"


def test_digits_only_form_does_not_strip_other_extension_fields() -> None:
    """Identifier-form scoping must be limited to BUSINESS_ABN alone.

    A regression that ran canonical_identifier over every extension value
    (instead of only the IDENTIFIER_COLUMNS-listed ones) would strip spaces
    out of business_address, invoice_date and payer_name/payer_address too.
    The only pre-existing digits_only test checks business_abn in isolation,
    so it would not catch that. INVOICE_DATE is overridden here to a value
    that itself contains a space ("02 03 2023" rather than "02/03/2023") so
    that a blanket space-stripping regression has something to strip in
    every field under test, not just business_address and the payer name.
    """
    fields = {
        **CASE001_RECEIPT,
        "DOCUMENT_TYPE": "INVOICE",
        "INVOICE_DATE": "02 03 2023",
        "PAYER_NAME": "Prime Consulting Partners",
        "PAYER_ADDRESS": "13 Mendoza Cl, Glenelg SA 5045",
    }
    extension = to_cord(fields, "digits_only")["extension"]
    assert extension["business_abn"] == "79104332181"
    assert extension["business_address"] == "400 Stewart Rd, South Yarra VIC 3141"
    assert extension["invoice_date"] == "02 03 2023"
    assert extension["payer_name"] == "Prime Consulting Partners"
    assert extension["payer_address"] == "13 Mendoza Cl, Glenelg SA 5045"


def test_line_item_totals_sum_to_the_document_total() -> None:
    """Arithmetic sanity: 4.73 + 8.87 == 13.60."""
    tree = to_cord(CASE001_RECEIPT, "spaced")
    line_total = sum(float(item["price"]) for item in tree["menu"])
    assert round(line_total, 2) == float(tree["total"]["total_price"])


def test_line_item_unit_price_and_total_price_map_to_distinct_columns() -> None:
    """CASE001's rows all have unit_price == total_price (4.73/4.73, 8.87/8.87),
    so a bug that swapped the LINE_ITEM_PRICES -> unitprice and
    LINE_ITEM_TOTAL_PRICES -> price mappings would pass every existing
    assertion. This fixture's quantity of 2 makes the two genuinely differ
    (12.50 unit price vs 25.00 line total), so a swap is caught either by
    the direct field checks below or by the sum-to-total check.
    """
    fields = {
        "DOCUMENT_TYPE": "RECEIPT",
        "SUPPLIER_NAME": "Example Wholesale Co",
        "GST_AMOUNT": "2.27",
        "TOTAL_AMOUNT": "25.00",
        "LINE_ITEM_DESCRIPTIONS": "Widget",
        "LINE_ITEM_QUANTITIES": "2",
        "LINE_ITEM_PRICES": "12.50",
        "LINE_ITEM_TOTAL_PRICES": "25.00",
    }
    tree = to_cord(fields, "spaced")
    item = tree["menu"][0]
    assert item["cnt"] == "2"
    assert item["unitprice"] == "12.50"
    assert item["price"] == "25.00"
    line_total = sum(float(menu_item["price"]) for menu_item in tree["menu"])
    assert round(line_total, 2) == float(tree["total"]["total_price"])


def test_no_line_items_omits_menu_key() -> None:
    """A record with no LINE_ITEM_* columns at all must omit "menu" entirely
    rather than emit an empty list. Absence here is via omitted keys.
    """
    fields = {
        "DOCUMENT_TYPE": "RECEIPT",
        "SUPPLIER_NAME": "Ravensdale Health Store",
        "TOTAL_AMOUNT": "13.60",
    }
    tree = to_cord(fields, "spaced")
    assert "menu" not in tree


def test_gst_amount_absent_omits_sub_total_key() -> None:
    """GST_AMOUNT absent (via the NOT_FOUND sentinel) must omit "sub_total"
    entirely rather than emit an empty container.
    """
    fields = {**CASE001_RECEIPT, "GST_AMOUNT": "NOT_FOUND"}
    tree = to_cord(fields, "spaced")
    assert "sub_total" not in tree


def test_total_amount_absent_omits_total_key() -> None:
    """TOTAL_AMOUNT absent (via an omitted key) must omit "total" entirely
    rather than emit an empty container.
    """
    fields = {key: value for key, value in CASE001_RECEIPT.items() if key != "TOTAL_AMOUNT"}
    tree = to_cord(fields, "spaced")
    assert "total" not in tree


def test_all_extension_sources_absent_omits_extension_key() -> None:
    """When every EXTENSION_COLUMNS source is absent, "extension" must be
    omitted entirely rather than emitted as an empty dict. Mixes both real
    forms absence takes: NOT_FOUND sentinels for the columns present in the
    fields dict, and simply omitted keys for the rest.
    """
    fields = {
        "DOCUMENT_TYPE": "RECEIPT",
        "GST_AMOUNT": "1.24",
        "TOTAL_AMOUNT": "13.60",
        "SUPPLIER_NAME": "NOT_FOUND",
        "BUSINESS_ABN": "NOT_FOUND",
    }
    tree = to_cord(fields, "spaced")
    assert "extension" not in tree
