"""Tests for the CORD JSONL derivation."""

import json
from pathlib import Path

import yaml

from conftest import assert_diagnostic_error
from generators.derive_outputs import derive_cord

CONFIG = {"abn_tfn_canonical_form": "spaced"}

FIXTURE = {
    "CASE001": {
        "layout": "receipt_fuel",
        "degradation_seed": 8967,
        "fields": {
            "DOCUMENT_TYPE": "RECEIPT",
            "SUPPLIER_NAME": "Ravensdale Health Store",
            "GST_AMOUNT": "1.24",
            "TOTAL_AMOUNT": "13.60",
            "LINE_ITEM_DESCRIPTIONS": "Dishwashing Liquid|Bandaids 40pk",
            "LINE_ITEM_QUANTITIES": "1|1",
            "LINE_ITEM_PRICES": "4.73|8.87",
            "LINE_ITEM_TOTAL_PRICES": "4.73|8.87",
        },
    }
}


def test_derive_cord_writes_one_line_per_document(tmp_path: Path) -> None:
    gt = tmp_path / "receipts.yml"
    gt.write_text(yaml.safe_dump(FIXTURE))
    out = tmp_path / "cord.jsonl"

    result = derive_cord([gt], CONFIG, out)

    assert result == out
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["case_id"] == "CASE001"
    assert record["image_file"] == "CASE001_receipt_fuel.png"
    assert record["gt_parse"]["total"]["total_price"] == "13.60"
    # Structural assertions: exact record shape, not just presence of one field.
    assert set(record.keys()) == {"case_id", "image_file", "gt_parse"}
    assert record["gt_parse"]["menu"] == [
        {"nm": "Dishwashing Liquid", "cnt": "1", "unitprice": "4.73", "price": "4.73"},
        {"nm": "Bandaids 40pk", "cnt": "1", "unitprice": "8.87", "price": "8.87"},
    ]
    assert record["gt_parse"]["sub_total"] == {"tax_price": "1.24"}


def test_derive_cord_maps_unit_price_and_total_price_distinctly(tmp_path: Path) -> None:
    """The independent oracle for the unitprice/price mapping.

    Every other CORD test uses quantity-1 line items, where LINE_ITEM_PRICES
    equals LINE_ITEM_TOTAL_PRICES and a swap of the two is invisible. The
    corpus self-score cannot catch such a swap either, since both sides of a
    self-comparison come from the same to_cord call. This fixture uses
    quantity 3 so unit price and line total genuinely differ, pinning
    LINE_ITEM_PRICES -> menu.unitprice and LINE_ITEM_TOTAL_PRICES ->
    menu.price against literal expected values.
    """
    fixture = {
        "CASE001": {
            "layout": "receipt_retail_tax",
            "fields": {
                "DOCUMENT_TYPE": "RECEIPT",
                "SUPPLIER_NAME": "Ravensdale Health Store",
                "TOTAL_AMOUNT": "30.00",
                "LINE_ITEM_DESCRIPTIONS": "Yoghurt Tub 1kg",
                "LINE_ITEM_QUANTITIES": "3",
                "LINE_ITEM_PRICES": "10.00",
                "LINE_ITEM_TOTAL_PRICES": "30.00",
            },
        }
    }
    gt = tmp_path / "receipts.yml"
    gt.write_text(yaml.safe_dump(fixture))
    out = tmp_path / "cord.jsonl"

    derive_cord([gt], CONFIG, out)

    record = json.loads(out.read_text().strip())
    item = record["gt_parse"]["menu"][0]
    assert item == {"nm": "Yoghurt Tub 1kg", "cnt": "3", "unitprice": "10.00", "price": "30.00"}
    # Stated separately so a swap names itself in the failure output.
    assert item["unitprice"] == "10.00", "menu.unitprice must come from LINE_ITEM_PRICES"
    assert item["price"] == "30.00", "menu.price must come from LINE_ITEM_TOTAL_PRICES"
    assert item["unitprice"] != item["price"], "Fixture is degenerate: a swap would be invisible."


def test_derive_cord_skips_non_receipt_document_types(tmp_path: Path) -> None:
    """Bank statements have no CORD equivalent (spec section 7)."""
    fixture = {
        "CASE001": {
            "layout": "cba_standard",
            "fields": {"DOCUMENT_TYPE": "BANK_STATEMENT", "SUPPLIER_NAME": "CBA"},
        }
    }
    gt = tmp_path / "bank_statements.yml"
    gt.write_text(yaml.safe_dump(fixture))
    out = tmp_path / "cord.jsonl"

    result = derive_cord([gt], CONFIG, out)

    assert result == out
    assert out.read_text().strip() == ""


def test_derive_cord_mixes_and_filters_multiple_document_types(tmp_path: Path) -> None:
    """A single gt_files list mixing eligible and ineligible types emits only
    the eligible ones, and multiple gt_files are concatenated in file order.
    """
    receipts = {
        "CASE001": {
            "layout": "receipt_fuel",
            "fields": {
                "DOCUMENT_TYPE": "RECEIPT",
                "SUPPLIER_NAME": "Ravensdale Health Store",
                "TOTAL_AMOUNT": "13.60",
            },
        },
        "CASE002": {
            "layout": "cba_standard",
            "fields": {"DOCUMENT_TYPE": "BANK_STATEMENT", "SUPPLIER_NAME": "CBA"},
        },
    }
    invoices = {
        "CASE003": {
            "layout": "invoice_standard",
            "fields": {
                "DOCUMENT_TYPE": "INVOICE",
                "SUPPLIER_NAME": "Example Co",
                "TOTAL_AMOUNT": "25.00",
            },
        }
    }
    gt1 = tmp_path / "receipts.yml"
    gt1.write_text(yaml.safe_dump(receipts))
    gt2 = tmp_path / "invoices.yml"
    gt2.write_text(yaml.safe_dump(invoices))
    out = tmp_path / "cord.jsonl"

    derive_cord([gt1, gt2], CONFIG, out)

    lines = out.read_text().strip().split("\n")
    records = [json.loads(line) for line in lines]
    assert [r["case_id"] for r in records] == ["CASE001", "CASE003"]


def test_derive_cord_creates_parent_directories(tmp_path: Path) -> None:
    """Mirrors derive_csv/derive_jsonl's mkdir(parents=True) behaviour."""
    gt = tmp_path / "receipts.yml"
    gt.write_text(yaml.safe_dump(FIXTURE))
    out = tmp_path / "nested" / "deeper" / "cord.jsonl"

    derive_cord([gt], CONFIG, out)

    assert out.exists()


def test_derive_cord_applies_identifier_form_from_export_config(tmp_path: Path) -> None:
    """The export_config's abn_tfn_canonical_form must actually flow through
    to to_cord's identifier_form argument (not just be accepted and ignored).
    """
    fixture = {
        "CASE001": {
            "layout": "receipt_fuel",
            "fields": {
                "DOCUMENT_TYPE": "RECEIPT",
                "SUPPLIER_NAME": "Ravensdale Health Store",
                "BUSINESS_ABN": "79 104 332 181",
                "TOTAL_AMOUNT": "13.60",
            },
        }
    }
    gt = tmp_path / "receipts.yml"
    gt.write_text(yaml.safe_dump(fixture))
    out = tmp_path / "cord.jsonl"

    derive_cord([gt], {"abn_tfn_canonical_form": "digits_only"}, out)

    record = json.loads(out.read_text().strip())
    assert record["gt_parse"]["extension"]["business_abn"] == "79104332181"


def test_derive_cord_propagates_line_item_mismatch_diagnostic(tmp_path: Path) -> None:
    """A malformed ground-truth entry (mismatched LINE_ITEM_* list lengths)
    must surface zip_line_items' four-element diagnostic, not a bare
    traceback or a silently truncated/wrong tree.
    """
    fixture = {
        "CASE001": {
            "layout": "receipt_fuel",
            "fields": {
                "DOCUMENT_TYPE": "RECEIPT",
                "SUPPLIER_NAME": "Ravensdale Health Store",
                "TOTAL_AMOUNT": "13.60",
                "LINE_ITEM_DESCRIPTIONS": "Dishwashing Liquid|Bandaids 40pk",
                "LINE_ITEM_QUANTITIES": "1",
                "LINE_ITEM_PRICES": "4.73|8.87",
                "LINE_ITEM_TOTAL_PRICES": "4.73|8.87",
            },
        }
    }
    gt = tmp_path / "receipts.yml"
    gt.write_text(yaml.safe_dump(fixture))
    out = tmp_path / "cord.jsonl"

    try:
        derive_cord([gt], CONFIG, out)
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None, "expected a ValueError from mismatched LINE_ITEM_* lengths"
    assert_diagnostic_error(raised)
