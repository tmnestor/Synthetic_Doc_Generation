"""Tests for the fail-fast field_budgets loader."""

import pytest
from conftest import assert_diagnostic_error

from generators.layout_budgets import LayoutBudgetError, field_budget

GOOD = {
    "field_budgets": {
        "SUPPLIER_NAME": {
            "width": 360,
            "fit": "shrink_then_wrap",
            "min_font": 12,
            "max_lines": 2,
        },
    }
}
_LP = "config/layouts/receipts.yml"


def test_returns_valid_budget():
    b = field_budget(GOOD, "receipt_thermal_80mm", "SUPPLIER_NAME", layout_path=_LP)
    assert b == GOOD["field_budgets"]["SUPPLIER_NAME"]


def test_missing_field_budgets_block_is_diagnostic():
    with pytest.raises(LayoutBudgetError) as exc:
        field_budget({}, "receipt_thermal_80mm", "SUPPLIER_NAME", layout_path=_LP)
    assert_diagnostic_error(str(exc.value))


def test_missing_field_entry_is_diagnostic():
    with pytest.raises(LayoutBudgetError) as exc:
        field_budget(GOOD, "receipt_thermal_80mm", "PHONE", layout_path=_LP)
    assert_diagnostic_error(str(exc.value))


def test_missing_required_key_is_diagnostic():
    bad = {"field_budgets": {"SUPPLIER_NAME": {"width": 360, "fit": "shrink"}}}
    with pytest.raises(LayoutBudgetError) as exc:
        field_budget(bad, "receipt_thermal_80mm", "SUPPLIER_NAME", layout_path=_LP)
    msg = str(exc.value)
    assert_diagnostic_error(msg)
    assert "min_font" in msg and "max_lines" in msg


def test_invalid_fit_enum_is_diagnostic():
    bad = {"field_budgets": {"X": {"width": 1, "fit": "chop", "min_font": 8, "max_lines": 1}}}
    with pytest.raises(LayoutBudgetError) as exc:
        field_budget(bad, "L", "X", layout_path=_LP)
    assert_diagnostic_error(str(exc.value))


def test_invalid_numeric_value_is_diagnostic():
    bad = {"field_budgets": {"X": {"width": 0, "fit": "shrink", "min_font": 8, "max_lines": 1}}}
    with pytest.raises(LayoutBudgetError) as exc:
        field_budget(bad, "L", "X", layout_path=_LP)
    assert_diagnostic_error(str(exc.value))
