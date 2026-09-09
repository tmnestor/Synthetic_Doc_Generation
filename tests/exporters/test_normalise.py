"""Tests for the shared normalisation rules (spec section 3)."""

import pytest

from conftest import assert_diagnostic_error
from generators.exporters.normalise import (
    canonical_identifier,
    is_present,
    present_fields,
    split_pipe_list,
    zip_line_items,
)

CASE001 = {
    "LINE_ITEM_DESCRIPTIONS": "Dishwashing Liquid|Bandaids 40pk",
    "LINE_ITEM_QUANTITIES": "1|1",
    "LINE_ITEM_PRICES": "4.73|8.87",
    "LINE_ITEM_TOTAL_PRICES": "4.73|8.87",
}


def test_split_pipe_list_splits_on_pipe() -> None:
    assert split_pipe_list("a|b|c") == ["a", "b", "c"]


def test_split_pipe_list_handles_single_value() -> None:
    """A single-item list has no pipe — CASE002 stores '3.76' with no delimiter."""
    assert split_pipe_list("3.76") == ["3.76"]


def test_split_pipe_list_strips_whitespace() -> None:
    assert split_pipe_list("a | b") == ["a", "b"]


def test_zip_line_items_pairs_by_index() -> None:
    assert zip_line_items(CASE001) == [
        {
            "description": "Dishwashing Liquid",
            "quantity": "1",
            "unit_price": "4.73",
            "total_price": "4.73",
        },
        {
            "description": "Bandaids 40pk",
            "quantity": "1",
            "unit_price": "8.87",
            "total_price": "8.87",
        },
    ]


def test_zip_line_items_returns_empty_for_missing_columns() -> None:
    """If none of the LINE_ITEM_* columns are present, return empty list."""
    assert zip_line_items({"OTHER_FIELD": "value"}) == []


def test_zip_line_items_rejects_count_mismatch() -> None:
    """A short zip would silently emit a partial menu that scores as a near-match."""
    broken = {**CASE001, "LINE_ITEM_QUANTITIES": "1"}
    with pytest.raises(ValueError) as exc:
        zip_line_items(broken)
    message = str(exc.value)
    # Structural check: all four diagnostic elements are present.
    assert_diagnostic_error(message)
    # Behavioural check: the message names the offending column and counts.
    assert "LINE_ITEM_QUANTITIES" in message
    assert "1" in message
    assert "2" in message


def test_canonical_identifier_spaced_is_unchanged() -> None:
    assert canonical_identifier("79 104 332 181", "spaced") == "79 104 332 181"


def test_canonical_identifier_digits_only_strips_spaces() -> None:
    assert canonical_identifier("79 104 332 181", "digits_only") == "79104332181"


def test_canonical_identifier_rejects_unknown_form() -> None:
    with pytest.raises(ValueError) as exc:
        canonical_identifier("79 104 332 181", "hyphenated")
    message = str(exc.value)
    # Structural check: all four diagnostic elements are present.
    assert_diagnostic_error(message)
    # Behavioural check: the message names the offending form and an allowed one.
    assert "hyphenated" in message
    assert "spaced" in message


@pytest.mark.parametrize("value", ["NOT_FOUND", "", None])
def test_is_present_rejects_absent_markers(value: str | None) -> None:
    assert is_present(value) is False


def test_is_present_accepts_a_real_value() -> None:
    assert is_present("13.60") is True


def test_present_fields_drops_not_found() -> None:
    fields = {"TOTAL_AMOUNT": "13.60", "CREDIT_LIMIT": "NOT_FOUND", "PAYER_NAME": ""}
    assert present_fields(fields) == {"TOTAL_AMOUNT": "13.60"}


def test_present_fields_keeps_all_present() -> None:
    fields = {"FIELD_A": "1.0", "FIELD_B": "2.0"}
    assert present_fields(fields) == fields


def test_present_fields_empty_when_all_absent() -> None:
    """present_fields takes dict[str, str]; None-absence is covered by is_present above."""
    fields = {"FIELD_A": "NOT_FOUND", "FIELD_B": ""}
    assert present_fields(fields) == {}
