"""Tests for the native JSONL derivation (spec section 7).

Mirrors tests/test_derive_cord.py's structure. Native covers the one document
type with no CORD or DocILE equivalent: bank statements.
"""

import json
from pathlib import Path

import pytest
import yaml

from conftest import assert_diagnostic_error
from generators.derive_outputs import NATIVE_DOCUMENT_TYPES, derive_native

BANK_FIELDS = {
    "DOCUMENT_TYPE": "BANK_STATEMENT",
    "SUPPLIER_NAME": "CBA",
    "PAYER_NAME": "J Smith",
    "STATEMENT_DATE_RANGE": "01/03/2023 - 31/03/2023",
    "TRANSACTION_DATES": "02/03/2023|05/03/2023",
    "TRANSACTION_DESCRIPTIONS": "VISA DEBIT PURCHASE RAVENSDALE|SALARY",
    "TRANSACTION_AMOUNTS_PAID": "13.60|NOT_FOUND",
    "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|2400.00",
    "ACCOUNT_BALANCE": "1500.00",
}

FIXTURE = {
    "CASE001": {
        "layout": "cba_standard",
        "degradation_seed": 6363,
        "fields": BANK_FIELDS,
    }
}


def test_derive_native_writes_one_line_per_document(tmp_path: Path) -> None:
    gt = tmp_path / "bank_statements.yml"
    gt.write_text(yaml.safe_dump(FIXTURE))
    out = tmp_path / "native.jsonl"

    result = derive_native([gt], out)

    assert result == out
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["case_id"] == "CASE001"
    assert record["image_file"] == "CASE001_cba_standard.png"
    assert record["ACCOUNT_BALANCE"] == "1500.00"
    assert record["transactions"] == [
        {"date": "02/03/2023", "description": "VISA DEBIT PURCHASE RAVENSDALE",
         "amount_paid": "13.60", "amount_received": ""},
        {"date": "05/03/2023", "description": "SALARY",
         "amount_paid": "", "amount_received": "2400.00"},
    ]
    # Structural: exact record shape, not just presence of one field.
    assert set(record.keys()) == {
        "case_id", "image_file", "DOCUMENT_TYPE", "SUPPLIER_NAME", "PAYER_NAME",
        "STATEMENT_DATE_RANGE", "ACCOUNT_BALANCE", "transactions",
    }
    assert "NOT_FOUND" not in json.dumps(record), "NOT_FOUND sentinel leaked into a native record"


def test_derive_native_skips_document_types_with_a_cord_equivalent(tmp_path: Path) -> None:
    """Receipts and invoices have a CORD equivalent and must not appear here —
    the whole corpus partitions into CORD xor native, never both.
    """
    fixture = {
        "CASE001": {
            "layout": "receipt_fuel",
            "fields": {"DOCUMENT_TYPE": "RECEIPT", "SUPPLIER_NAME": "Ravensdale Health Store"},
        }
    }
    gt = tmp_path / "receipts.yml"
    gt.write_text(yaml.safe_dump(fixture))
    out = tmp_path / "native.jsonl"

    result = derive_native([gt], out)

    assert result == out
    assert out.read_text().strip() == ""


def test_derive_native_mixes_and_filters_multiple_document_types(tmp_path: Path) -> None:
    mixed = {
        "CASE001": {"layout": "cba_standard", "fields": BANK_FIELDS},
        "CASE002": {
            "layout": "receipt_fuel",
            "fields": {"DOCUMENT_TYPE": "RECEIPT", "SUPPLIER_NAME": "Ravensdale Health Store"},
        },
    }
    other_bank = {
        "CASE003": {
            "layout": "nab_classic",
            "fields": {**BANK_FIELDS, "SUPPLIER_NAME": "NAB"},
        }
    }
    gt1 = tmp_path / "bank_statements.yml"
    gt1.write_text(yaml.safe_dump(mixed))
    gt2 = tmp_path / "bank_statements_2.yml"
    gt2.write_text(yaml.safe_dump(other_bank))
    out = tmp_path / "native.jsonl"

    derive_native([gt1, gt2], out)

    records = [json.loads(line) for line in out.read_text().strip().split("\n") if line]
    assert [r["case_id"] for r in records] == ["CASE001", "CASE003"]


def test_derive_native_creates_parent_directories(tmp_path: Path) -> None:
    gt = tmp_path / "bank_statements.yml"
    gt.write_text(yaml.safe_dump(FIXTURE))
    out = tmp_path / "nested" / "deeper" / "native.jsonl"

    derive_native([gt], out)

    assert out.exists()


def test_derive_native_propagates_ragged_transaction_diagnostic(tmp_path: Path) -> None:
    """A malformed ground-truth entry (mismatched TRANSACTION_* list lengths)
    must surface to_native's four-element diagnostic, not a bare traceback.
    """
    broken_fields = {**BANK_FIELDS, "TRANSACTION_DATES": "02/03/2023"}
    fixture = {"CASE001": {"layout": "cba_standard", "fields": broken_fields}}
    gt = tmp_path / "bank_statements.yml"
    gt.write_text(yaml.safe_dump(fixture))
    out = tmp_path / "native.jsonl"

    with pytest.raises(ValueError) as exc:
        derive_native([gt], out)

    assert "TRANSACTION_DATES" in str(exc.value)
    assert_diagnostic_error(exc.value)


def test_native_document_types_constant() -> None:
    """Guards the module's document-type membership against silent drift —
    exactly the one type with no CORD/DocILE equivalent (spec section 7).
    """
    assert NATIVE_DOCUMENT_TYPES == {"BANK_STATEMENT"}
