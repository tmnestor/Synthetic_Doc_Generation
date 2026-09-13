"""Tests for the native statement schema (spec section 7)."""

import pytest

from conftest import assert_diagnostic_error
from generators.exporters.native import STATEMENT_TYPES, TRANSACTION_COLUMNS, to_native

BANK = {
    "DOCUMENT_TYPE": "BANK_STATEMENT",
    "SUPPLIER_NAME": "CBA",
    "PAYER_NAME": "J Smith",
    "STATEMENT_DATE_RANGE": "01/03/2023 - 31/03/2023",
    "TRANSACTION_DATES": "02/03/2023|05/03/2023",
    "TRANSACTION_DESCRIPTIONS": "VISA DEBIT PURCHASE RAVENSDALE|SALARY",
    "TRANSACTION_AMOUNTS_PAID": "13.60|",
    "TRANSACTION_AMOUNTS_RECEIVED": "|2400.00",
    "ACCOUNT_BALANCE": "1500.00",
}

# A non-statement type: no TRANSACTION_* columns, so to_native must never
# attach a 'transactions' key for it, regardless of DOCUMENT_TYPE.
NON_STATEMENT = {
    "DOCUMENT_TYPE": "RECEIPT",
    "SUPPLIER_NAME": "Ravensdale Health Store",
    "TOTAL_AMOUNT": "73.48",
    "CREDIT_LIMIT": "NOT_FOUND",
}

# The real corpus stores an absent transaction-register member as the literal
# NOT_FOUND sentinel between pipes (verified against ground_truth/bank_statements.yml),
# not as a bare empty string. Both must survive the zip as "" — never as literal
# "NOT_FOUND" — since the sentinel must never be emitted (spec + normalise.is_present).
BANK_WITH_NOT_FOUND_MEMBERS = {
    "DOCUMENT_TYPE": "BANK_STATEMENT",
    "SUPPLIER_NAME": "ANZ",
    "STATEMENT_DATE_RANGE": "01/07/2024 - 31/07/2024",
    "TRANSACTION_DATES": "01/07/2024|02/07/2024",
    "TRANSACTION_DESCRIPTIONS": "ATM WITHDRAWAL|Salary PAYROLL",
    "TRANSACTION_AMOUNTS_PAID": "219.04|NOT_FOUND",
    "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|906.72",
    "ACCOUNT_BALANCE": "14064.96",
}


def test_statement_transactions_are_unzipped_per_row() -> None:
    result = to_native(BANK)
    assert result["transactions"] == [
        {"date": "02/03/2023", "description": "VISA DEBIT PURCHASE RAVENSDALE",
         "amount_paid": "13.60", "amount_received": ""},
        {"date": "05/03/2023", "description": "SALARY",
         "amount_paid": "", "amount_received": "2400.00"},
    ]


def test_statement_scalars_are_preserved_alongside_transactions() -> None:
    result = to_native(BANK)
    assert result["ACCOUNT_BALANCE"] == "1500.00"
    assert result["STATEMENT_DATE_RANGE"] == "01/03/2023 - 31/03/2023"
    assert "TRANSACTION_DATES" not in result


def test_non_statement_document_has_no_transactions_array() -> None:
    result = to_native(NON_STATEMENT)
    assert "transactions" not in result
    assert result["TOTAL_AMOUNT"] == "73.48"


def test_not_found_is_dropped() -> None:
    assert "CREDIT_LIMIT" not in to_native(NON_STATEMENT)


def test_ragged_transaction_lists_are_rejected() -> None:
    broken = {**BANK, "TRANSACTION_DATES": "02/03/2023"}
    with pytest.raises(ValueError) as exc:
        to_native(broken)
    assert "TRANSACTION_DATES" in str(exc.value)


# ---------------------------------------------------------------------------
# Additional coverage beyond the brief's five tests: diagnostic-message
# quality, the real corpus's NOT_FOUND-per-member convention, structural
# assertions, and the "sentinel must never be emitted" requirement.
# ---------------------------------------------------------------------------


def test_ragged_transaction_lists_raise_a_four_element_diagnostic() -> None:
    """The mismatch error must be a fail-fast diagnostic, not a bare ValueError:
    it must name what disagrees, where to fix it, what a valid entry looks
    like, and how to recover — per the project's fail-fast standard.
    """
    broken = {**BANK, "TRANSACTION_DATES": "02/03/2023"}
    with pytest.raises(ValueError) as exc:
        to_native(broken)
    assert_diagnostic_error(exc.value)


def test_per_member_not_found_sentinel_becomes_empty_string() -> None:
    """The real corpus (ground_truth/bank_statements.yml) writes an absent
    register member as the literal NOT_FOUND token between pipes, e.g.
    'TRANSACTION_AMOUNTS_PAID: 219.04|NOT_FOUND'. That must be scrubbed to ""
    like a genuinely empty member — the NOT_FOUND sentinel must never survive
    into a transactions row.
    """
    result = to_native(BANK_WITH_NOT_FOUND_MEMBERS)
    assert result["transactions"] == [
        {"date": "01/07/2024", "description": "ATM WITHDRAWAL",
         "amount_paid": "219.04", "amount_received": ""},
        {"date": "02/07/2024", "description": "Salary PAYROLL",
         "amount_paid": "", "amount_received": "906.72"},
    ]


def test_not_found_sentinel_never_appears_anywhere_in_output() -> None:
    """Sweeps every emitted string (top-level and per-transaction-row) for the
    literal NOT_FOUND token, rather than checking just the one field the
    other tests target.
    """
    for fixture in (BANK, NON_STATEMENT, BANK_WITH_NOT_FOUND_MEMBERS):
        result = to_native(fixture)
        assert "NOT_FOUND" not in result.values()
        for row in result.get("transactions", []):
            assert "NOT_FOUND" not in row.values()


def test_statement_missing_amounts_received_column_defaults_to_empty() -> None:
    """A statement entry with no TRANSACTION_AMOUNTS_RECEIVED column at all
    (not merely an empty value for it) must still carry the key with "" on
    each transaction row.
    """
    charges_only = {
        "DOCUMENT_TYPE": "BANK_STATEMENT",
        "SUPPLIER_NAME": "NAB",
        "TRANSACTION_DATES": "03/07/2024",
        "TRANSACTION_DESCRIPTIONS": "COFFEE SHOP",
        "TRANSACTION_AMOUNTS_PAID": "4.50",
    }
    result = to_native(charges_only)
    assert result["transactions"] == [
        {"date": "03/07/2024", "description": "COFFEE SHOP", "amount_paid": "4.50", "amount_received": ""}
    ]


def test_statement_type_with_no_register_columns_present_has_no_transactions_key() -> None:
    """A statement-type document with none of the TRANSACTION_* columns present
    must omit the 'transactions' key entirely, not emit an empty list.
    """
    bare = {"DOCUMENT_TYPE": "BANK_STATEMENT", "SUPPLIER_NAME": "CBA", "ACCOUNT_BALANCE": "100.00"}
    result = to_native(bare)
    assert "transactions" not in result
    assert result == {"DOCUMENT_TYPE": "BANK_STATEMENT", "SUPPLIER_NAME": "CBA", "ACCOUNT_BALANCE": "100.00"}


def test_structural_shape_of_a_statement_record() -> None:
    """Structural assertion alongside the content assertions above: every
    transaction row has exactly the four expected keys, in the schema's
    column mapping, and 'transactions' is a list of dicts.
    """
    result = to_native(BANK)
    assert isinstance(result["transactions"], list)
    for row in result["transactions"]:
        assert set(row.keys()) == set(TRANSACTION_COLUMNS.values())
        assert all(isinstance(v, str) for v in row.values())
    # Scalar fields keep their original keys (no relabeling), register columns
    # are removed, non-register fields (SUPPLIER_NAME, PAYER_NAME, etc.) pass through.
    assert set(result.keys()) == {
        "DOCUMENT_TYPE", "SUPPLIER_NAME", "PAYER_NAME", "STATEMENT_DATE_RANGE",
        "ACCOUNT_BALANCE", "transactions",
    }


def test_document_type_membership_constants() -> None:
    """Guards the module's public constants against silent drift."""
    assert STATEMENT_TYPES == {"BANK_STATEMENT"}
    assert set(TRANSACTION_COLUMNS.values()) == {
        "date", "description", "amount_paid", "amount_received",
    }
