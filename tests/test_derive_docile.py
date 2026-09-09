"""Tests for the DocILE JSONL derivation (invoice-only scope, spec section 8.3).

Mirrors tests/test_derive_cord.py's structure. DocILE is restricted to
invoices: receipts structurally never render unit price or quantity-when-1,
so DOCILE_DOCUMENT_TYPES = frozenset({"INVOICE"}) here, superseding any
receipt+invoice count implied elsewhere -- the real corpus emits exactly 55
records (one per invoice), not 110.
"""

import json
from pathlib import Path

import pytest
import yaml

from conftest import assert_diagnostic_error
from generators.derive_outputs import derive_docile

CONFIG = {
    "docile_fieldtypes": {
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
}

INVOICE_FIELDS = {
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

INVOICE_BOXES = {
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


def _write_geometry(path: Path, image_file: str, boxes: dict) -> None:
    path.write_text(
        json.dumps(
            {
                "case_id": "CASE001",
                "image_file": image_file,
                "width": 1000,
                "height": 1400,
                "boxes": boxes,
            }
        )
        + "\n"
    )


def test_derive_docile_writes_one_line_per_invoice(tmp_path: Path) -> None:
    gt = tmp_path / "invoices.yml"
    gt.write_text(yaml.safe_dump({"CASE001": {"layout": "invoice_standard", "fields": INVOICE_FIELDS}}))
    geometry = tmp_path / "geometry.jsonl"
    _write_geometry(geometry, "CASE001_invoice_standard.png", INVOICE_BOXES)
    out = tmp_path / "docile.jsonl"

    result = derive_docile([gt], geometry, CONFIG, out)

    assert result == out
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["case_id"] == "CASE001"
    assert record["image_file"] == "CASE001_invoice_standard.png"
    assert set(record.keys()) == {"case_id", "image_file", "kile", "lir"}
    assert record["kile"]
    assert record["lir"]
    # Structural: every entry carries page/bbox/fieldtype/text; lir also line_item_id.
    for entry in record["kile"]:
        assert entry["page"] == 0
        assert len(entry["bbox"]) == 4
        assert all(0.0 <= c <= 1.0 for c in entry["bbox"])
        assert isinstance(entry["fieldtype"], str)
        assert isinstance(entry["text"], str)
    for entry in record["lir"]:
        assert "line_item_id" in entry


def test_derive_docile_skips_non_invoice_document_types(tmp_path: Path) -> None:
    """Receipts have no DocILE equivalent -- structurally missing geometry
    for unit price / quantity-when-1 (spec section 8.3, invoice-only scope).
    """
    fixture = {
        "CASE001": {
            "layout": "receipt_fuel",
            "fields": {"DOCUMENT_TYPE": "RECEIPT", "SUPPLIER_NAME": "Ravensdale Health Store"},
        }
    }
    gt = tmp_path / "receipts.yml"
    gt.write_text(yaml.safe_dump(fixture))
    geometry = tmp_path / "geometry.jsonl"
    geometry.write_text("")
    out = tmp_path / "docile.jsonl"

    result = derive_docile([gt], geometry, CONFIG, out)

    assert result == out
    assert out.read_text().strip() == ""


def test_derive_docile_mixes_and_filters_multiple_document_types(tmp_path: Path) -> None:
    receipts = {
        "CASE002": {
            "layout": "receipt_fuel",
            "fields": {"DOCUMENT_TYPE": "RECEIPT", "SUPPLIER_NAME": "CBA"},
        }
    }
    invoices = {
        "CASE001": {"layout": "invoice_standard", "fields": INVOICE_FIELDS},
    }
    gt1 = tmp_path / "receipts.yml"
    gt1.write_text(yaml.safe_dump(receipts))
    gt2 = tmp_path / "invoices.yml"
    gt2.write_text(yaml.safe_dump(invoices))
    geometry = tmp_path / "geometry.jsonl"
    _write_geometry(geometry, "CASE001_invoice_standard.png", INVOICE_BOXES)
    out = tmp_path / "docile.jsonl"

    derive_docile([gt1, gt2], geometry, CONFIG, out)

    records = [json.loads(line) for line in out.read_text().strip().split("\n") if line]
    assert [r["case_id"] for r in records] == ["CASE001"]


def test_derive_docile_creates_parent_directories(tmp_path: Path) -> None:
    gt = tmp_path / "invoices.yml"
    gt.write_text(yaml.safe_dump({"CASE001": {"layout": "invoice_standard", "fields": INVOICE_FIELDS}}))
    geometry = tmp_path / "geometry.jsonl"
    _write_geometry(geometry, "CASE001_invoice_standard.png", INVOICE_BOXES)
    out = tmp_path / "nested" / "deeper" / "docile.jsonl"

    derive_docile([gt], geometry, CONFIG, out)

    assert out.exists()


def test_derive_docile_raises_when_geometry_file_is_missing(tmp_path: Path) -> None:
    gt = tmp_path / "invoices.yml"
    gt.write_text(yaml.safe_dump({"CASE001": {"layout": "invoice_standard", "fields": INVOICE_FIELDS}}))
    geometry = tmp_path / "does_not_exist.jsonl"
    out = tmp_path / "docile.jsonl"

    with pytest.raises(FileNotFoundError) as exc:
        derive_docile([gt], geometry, CONFIG, out)

    assert_diagnostic_error(exc.value)
    assert str(geometry.resolve()) in str(exc.value)


def test_derive_docile_raises_when_an_invoice_has_no_geometry_record(tmp_path: Path) -> None:
    """Every invoice has captured geometry in the real corpus; an absent
    record always signals a real capture bug, never a structural absence.
    """
    gt = tmp_path / "invoices.yml"
    gt.write_text(yaml.safe_dump({"CASE001": {"layout": "invoice_standard", "fields": INVOICE_FIELDS}}))
    geometry = tmp_path / "geometry.jsonl"
    # geometry.jsonl exists but has no record at all for CASE001's image_file.
    geometry.write_text(
        json.dumps(
            {
                "case_id": "OTHER",
                "image_file": "OTHER_invoice_standard.png",
                "width": 1000,
                "height": 1400,
                "boxes": {},
            }
        )
        + "\n"
    )
    out = tmp_path / "docile.jsonl"

    with pytest.raises(KeyError) as exc:
        derive_docile([gt], geometry, CONFIG, out)

    assert "CASE001_invoice_standard.png" in str(exc.value)
    assert_diagnostic_error(exc.value)
