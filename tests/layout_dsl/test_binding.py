import pytest

from generators.layout_dsl.binding import BindingError, interpolate, is_present, referenced_fields


def test_referenced_fields_finds_all_placeholders():
    assert referenced_fields("From {SUPPLIER_NAME} to {PAYER_NAME}") == [
        "SUPPLIER_NAME",
        "PAYER_NAME",
    ]


def test_referenced_fields_ignores_lowercase_braces():
    assert referenced_fields("literal {not_a_field} text") == []


def test_referenced_fields_on_literal_returns_empty():
    assert referenced_fields("Tax Invoice") == []


def test_interpolate_substitutes_values():
    fields = {"PAYER_NAME": "Robin Wood"}
    assert interpolate("Account Holder: {PAYER_NAME}", fields) == "Account Holder: Robin Wood"


def test_interpolate_raises_on_unknown_field():
    with pytest.raises(BindingError) as exc_info:
        interpolate("{NOPE}", {"PAYER_NAME": "Robin Wood"})
    message = str(exc_info.value)
    assert "NOPE" in message
    assert "Remediation:" in message


def test_interpolate_renders_not_found_as_empty():
    assert interpolate("Balance: {ACCOUNT_BALANCE}", {"ACCOUNT_BALANCE": "NOT_FOUND"}) == "Balance: "


def test_is_present_false_for_missing_blank_and_not_found():
    assert is_present({}, "X") is False
    assert is_present({"X": ""}, "X") is False
    assert is_present({"X": "NOT_FOUND"}, "X") is False


def test_is_present_true_for_real_value():
    assert is_present({"X": "01/07/2024 - 29/07/2024"}, "X") is True
