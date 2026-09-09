"""Arithmetic invariants `pipeline validate` enforces on ground truth.

Two rules that a hand-edited entry can violate while still rendering and
exporting happily, because nothing downstream recomputes them:

* parallel pipe-delimited fields must carry the same number of items;
* GST_AMOUNT must equal TOTAL_AMOUNT / 11 when the total is GST-inclusive.

Both rules are declared in config/field_definitions.yml, so these tests also
cover the fail-fast path when that declaration is missing.
"""

from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error

from generators import schema as schema_mod
from generators.schema import SchemaError, validate_entry

_RECEIPT_DEFS = {
    "document_type_values": ["RECEIPT"],
    "document_fields": {"receipt": ["DOCUMENT_TYPE"]},
    "field_types": {"amount": ["GST_AMOUNT", "TOTAL_AMOUNT"]},
    "parallel_field_groups": {"RECEIPT": [["LINE_ITEM_PRICES", "LINE_ITEM_DESCRIPTIONS"]]},
    "gst_consistency": {
        "divisor": 11,
        "decimals": 2,
        "inclusive_field": "IS_GST_INCLUDED",
        "gst_field": "GST_AMOUNT",
        "total_field": "TOTAL_AMOUNT",
    },
}


@pytest.fixture(autouse=True)
def _reset_field_defs_cache():
    """Clear the module-level field-defs cache around each test."""
    schema_mod._FIELD_DEFS = None
    yield
    schema_mod._FIELD_DEFS = None


def _defs_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: dict) -> Path:
    path = tmp_path / "field_definitions.yml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(schema_mod, "_FIELD_DEFS_PATH", path)
    return path


def _entry(**fields) -> dict:
    base = {"DOCUMENT_TYPE": "RECEIPT"}
    base.update(fields)
    return {"layout": "some_layout", "degradation_seed": 1, "fields": base}


# --- GST arithmetic -----------------------------------------------------


def test_gst_inconsistent_with_total_is_reported(tmp_path, monkeypatch):
    _defs_at(tmp_path, monkeypatch, _RECEIPT_DEFS)

    errors = validate_entry(
        "CASE001",
        _entry(IS_GST_INCLUDED="true", TOTAL_AMOUNT="216.89", GST_AMOUNT="21.69"),
    )

    assert len(errors) == 1
    assert "GST_AMOUNT" in errors[0]
    assert "19.72" in errors[0], "the error must state the value GST should have been"


def test_gst_consistent_with_total_passes(tmp_path, monkeypatch):
    _defs_at(tmp_path, monkeypatch, _RECEIPT_DEFS)

    errors = validate_entry(
        "CASE001",
        _entry(IS_GST_INCLUDED="true", TOTAL_AMOUNT="216.89", GST_AMOUNT="19.72"),
    )

    assert errors == []


def test_gst_rounds_half_up_like_the_seeder(tmp_path, monkeypatch):
    """100.00 / 11 is 9.0909..., which must round to 9.09 rather than truncate."""
    _defs_at(tmp_path, monkeypatch, _RECEIPT_DEFS)

    assert (
        validate_entry("CASE001", _entry(IS_GST_INCLUDED="true", TOTAL_AMOUNT="100.00", GST_AMOUNT="9.09"))
        == []
    )


def test_gst_not_checked_when_total_excludes_gst(tmp_path, monkeypatch):
    """IS_GST_INCLUDED false means the total is not the base for the fraction."""
    _defs_at(tmp_path, monkeypatch, _RECEIPT_DEFS)

    errors = validate_entry(
        "CASE001",
        _entry(IS_GST_INCLUDED="false", TOTAL_AMOUNT="216.89", GST_AMOUNT="21.69"),
    )

    assert errors == []


def test_missing_gst_consistency_block_fails_with_a_diagnostic(tmp_path, monkeypatch):
    defs = {k: v for k, v in _RECEIPT_DEFS.items() if k != "gst_consistency"}
    path = _defs_at(tmp_path, monkeypatch, defs)

    with pytest.raises(SchemaError) as exc_info:
        validate_entry("CASE001", _entry(IS_GST_INCLUDED="true", TOTAL_AMOUNT="1.00"))

    assert_diagnostic_error(exc_info.value)
    assert "gst_consistency" in str(exc_info.value)
    assert str(path.resolve()) in str(exc_info.value)


def test_incomplete_gst_consistency_block_names_the_missing_keys(tmp_path, monkeypatch):
    defs = dict(_RECEIPT_DEFS)
    defs["gst_consistency"] = {"divisor": 11}
    _defs_at(tmp_path, monkeypatch, defs)

    with pytest.raises(SchemaError) as exc_info:
        validate_entry("CASE001", _entry(IS_GST_INCLUDED="true", TOTAL_AMOUNT="1.00"))

    assert_diagnostic_error(exc_info.value)
    for key in ("decimals", "inclusive_field", "gst_field", "total_field"):
        assert key in str(exc_info.value)


# --- parallel list parity ------------------------------------------------


def test_mismatched_parallel_list_lengths_are_reported(tmp_path, monkeypatch):
    _defs_at(tmp_path, monkeypatch, _RECEIPT_DEFS)

    errors = validate_entry(
        "CASE001",
        _entry(LINE_ITEM_DESCRIPTIONS="a|b|c", LINE_ITEM_PRICES="1.00|2.00"),
    )

    assert len(errors) == 1
    assert "count mismatch" in errors[0]


def test_equal_parallel_list_lengths_pass(tmp_path, monkeypatch):
    _defs_at(tmp_path, monkeypatch, _RECEIPT_DEFS)

    errors = validate_entry(
        "CASE001",
        _entry(LINE_ITEM_DESCRIPTIONS="a|b", LINE_ITEM_PRICES="1.00|2.00"),
    )

    assert errors == []


def test_missing_parallel_field_groups_fails_with_a_diagnostic(tmp_path, monkeypatch):
    defs = {k: v for k, v in _RECEIPT_DEFS.items() if k != "parallel_field_groups"}
    path = _defs_at(tmp_path, monkeypatch, defs)

    with pytest.raises(SchemaError) as exc_info:
        validate_entry("CASE001", _entry(LINE_ITEM_DESCRIPTIONS="a"))

    assert_diagnostic_error(exc_info.value)
    assert "parallel_field_groups" in str(exc_info.value)
    assert str(path.resolve()) in str(exc_info.value)


# --- the real corpus -----------------------------------------------------


def test_real_corpus_satisfies_both_invariants():
    """The shipped ground truth must pass what validate now enforces."""
    from generators.schema import validate_ground_truth_file

    root = Path(__file__).resolve().parent.parent
    for name in ("receipts", "invoices", "bank_statements"):
        errors = validate_ground_truth_file(root / "ground_truth" / f"{name}.yml")
        assert errors == [], f"{name}.yml: {errors[:3]}"
