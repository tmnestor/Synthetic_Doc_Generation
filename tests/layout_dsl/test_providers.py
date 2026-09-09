from decimal import Decimal

import pytest
from conftest import assert_diagnostic_error

from generators.layout_dsl.providers import ProviderError, get_provider, provider_names, row_provider


def test_pipe_fields_zips_list_fields_into_rows():
    entry = {
        "fields": {
            "LINE_ITEM_DESCRIPTIONS": "Coffee|Muffin|Juice",
            "LINE_ITEM_TOTAL_PRICES": "4.50|6.00|5.25",
        }
    }
    provider = get_provider("pipe_fields")
    rows = provider(
        entry, {"fields": {"desc": "LINE_ITEM_DESCRIPTIONS", "amount": "LINE_ITEM_TOTAL_PRICES"}}
    )
    assert rows == [
        {"desc": "Coffee", "amount": "4.50"},
        {"desc": "Muffin", "amount": "6.00"},
        {"desc": "Juice", "amount": "5.25"},
    ]


def test_pipe_fields_rejects_ragged_lists():
    from conftest import assert_diagnostic_error

    entry = {"fields": {"A": "1|2|3", "B": "1|2"}}
    provider = get_provider("pipe_fields")
    with pytest.raises(ProviderError) as exc_info:
        provider(entry, {"fields": {"a": "A", "b": "B"}})
    message = str(exc_info.value)
    assert "3" in message and "2" in message
    assert_diagnostic_error(exc_info.value)


def test_pipe_fields_requires_fields_mapping():
    from conftest import assert_diagnostic_error

    provider = get_provider("pipe_fields")
    with pytest.raises(ProviderError) as exc_info:
        provider({"fields": {}}, {})
    assert_diagnostic_error(exc_info.value)
    assert "fields" in str(exc_info.value).lower()


def test_get_provider_rejects_unknown_name_and_lists_known():
    with pytest.raises(ProviderError) as exc_info:
        get_provider("no_such_provider")
    message = str(exc_info.value)
    assert "no_such_provider" in message
    assert "pipe_fields" in message
    assert "Remediation:" in message


def test_provider_names_includes_registered():
    assert "pipe_fields" in provider_names()


def test_row_provider_rejects_duplicate_registration():
    with pytest.raises(ProviderError, match="already registered"):

        @row_provider("pipe_fields")
        def _duplicate(entry: dict, params: dict) -> list[dict]:
            return []


def _bank_entry() -> dict:
    return {
        "fields": {
            "TRANSACTION_DATES": "01/07/2024|02/07/2024",
            "TRANSACTION_DESCRIPTIONS": "ATM WITHDRAWAL|SALARY",
            "TRANSACTION_AMOUNTS_PAID": "100.00|NOT_FOUND",
            "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|500.00",
            "ACCOUNT_BALANCE": "1400.00",
        }
    }


def test_bank_transactions_computes_running_balances_backwards():
    rows = get_provider("bank_transactions")(_bank_entry(), {})
    assert [r["date"] for r in rows] == ["01/07/2024", "02/07/2024"]
    # Closing 1400.00; reversing the last row (credit 500) gives 900.00 for row 0.
    assert rows[0]["balance"] == Decimal("900.00")
    assert rows[1]["balance"] == Decimal("1400.00")


def test_bank_transactions_prepends_opening_row_when_requested():
    rows = get_provider("bank_transactions")(
        _bank_entry(), {"opening_balance": True, "opening_balance_label": "Opening Balance"}
    )
    assert rows[0]["synthetic"] is True
    assert rows[0]["description"] == "Opening Balance"
    # Opening = first row balance - its credit + its debit = 900 - 0 + 100.
    assert rows[0]["balance"] == Decimal("1000.00")
    assert rows[0]["debit"] == "NOT_FOUND"
    assert len(rows) == 3


def test_bank_transactions_brought_forward_uses_its_own_label():
    rows = get_provider("bank_transactions")(
        _bank_entry(), {"brought_forward": True, "brought_forward_label": "Balance Brought Forward"}
    )
    assert rows[0]["description"] == "Balance Brought Forward"
    assert rows[0]["synthetic"] is True


def test_bank_transactions_rejects_both_synthetic_rows():
    with pytest.raises(ProviderError, match="mutually exclusive"):
        get_provider("bank_transactions")(
            _bank_entry(),
            {
                "opening_balance": True,
                "opening_balance_label": "Opening Balance",
                "brought_forward": True,
                "brought_forward_label": "Balance Brought Forward",
            },
        )


def test_bank_transactions_without_synthetic_row_marks_all_real():
    rows = get_provider("bank_transactions")(_bank_entry(), {})
    assert all(row["synthetic"] is False for row in rows)


def test_malformed_amount_fails_loudly_rather_than_becoming_zero():
    entry = _bank_entry()
    entry["fields"]["TRANSACTION_AMOUNTS_PAID"] = "12.3.4|NOT_FOUND"
    with pytest.raises(ProviderError) as exc_info:
        get_provider("bank_transactions")(entry, {})
    message = str(exc_info.value)
    assert "12.3.4" in message
    assert "bank_statements.yml" in message
    assert_diagnostic_error(message)


def test_absent_value_sentinels_still_read_as_zero():
    from generators.layout_dsl.providers import _to_decimal

    assert _to_decimal("") == Decimal("0")
    assert _to_decimal("NOT_FOUND") == Decimal("0")
    assert _to_decimal("137.73") == Decimal("137.73")


def test_carried_forward_appends_a_trailing_synthetic_row():
    rows = get_provider("bank_transactions")(
        _bank_entry(), {"carried_forward": True, "carried_forward_label": "Carried forward"}
    )
    assert rows[-1]["synthetic"] is True
    assert rows[-1]["description"] == "Carried forward"
    # Closing balance is ACCOUNT_BALANCE itself, unchanged by any adjustment.
    assert rows[-1]["balance"] == Decimal("1400.00")
    assert len(rows) == 3


def test_carried_forward_row_is_bold_unlike_leading_synthetic_rows():
    """Legacy draws Carried forward in font_body_bold; Brought forward/Opening Balance stay regular."""
    rows = get_provider("bank_transactions")(
        _bank_entry(),
        {
            "brought_forward": True,
            "brought_forward_label": "Balance Brought Forward",
            "carried_forward": True,
            "carried_forward_label": "Carried forward",
        },
    )
    assert rows[0].get("bold") is not True  # leading Brought Forward row
    assert rows[1].get("bold") is not True  # real row
    assert rows[2].get("bold") is not True  # real row
    assert rows[-1]["bold"] is True  # trailing Carried forward row


def test_carried_forward_combines_with_a_leading_synthetic_row():
    """NAB shows both: Brought-forward leading, Carried-forward trailing."""
    rows = get_provider("bank_transactions")(
        _bank_entry(),
        {
            "brought_forward": True,
            "brought_forward_label": "Balance Brought Forward",
            "carried_forward": True,
            "carried_forward_label": "Carried forward",
        },
    )
    assert rows[0]["description"] == "Balance Brought Forward"
    assert rows[-1]["description"] == "Carried forward"
    assert len(rows) == 4
    # The two real rows in between keep their own balances, untouched.
    assert rows[1]["synthetic"] is False
    assert rows[2]["synthetic"] is False


def test_carried_forward_without_transactions_appends_nothing():
    entry = _bank_entry()
    entry["fields"]["TRANSACTION_DATES"] = ""
    entry["fields"]["TRANSACTION_DESCRIPTIONS"] = ""
    entry["fields"]["TRANSACTION_AMOUNTS_PAID"] = ""
    entry["fields"]["TRANSACTION_AMOUNTS_RECEIVED"] = ""
    assert (
        get_provider("bank_transactions")(
            entry, {"carried_forward": True, "carried_forward_label": "Carried forward"}
        )
        == []
    )


def test_references_adds_a_reference_key_to_every_real_row():
    import hashlib

    rows = get_provider("bank_transactions")(
        _bank_entry(),
        {
            "references": True,
            "reference_prefix": "Ref: ",
            "reference_pad_char": ".",
            "reference_pad_width": 40,
        },
    )
    assert all("reference" in row for row in rows)
    digest = hashlib.sha256("ATM WITHDRAWAL".encode()).hexdigest()
    ref_num = str(int(digest, 16) % 10**10).zfill(10)
    assert rows[0]["reference"] == f"Ref: {ref_num}" + "." * 40


def test_references_absent_by_default():
    rows = get_provider("bank_transactions")(_bank_entry(), {})
    assert all("reference" not in row for row in rows)


def test_references_not_added_to_synthetic_rows():
    rows = get_provider("bank_transactions")(
        _bank_entry(),
        {
            "opening_balance": True,
            "opening_balance_label": "Opening Balance",
            "carried_forward": True,
            "carried_forward_label": "Carried forward",
            "references": True,
            "reference_prefix": "Ref: ",
            "reference_pad_char": ".",
            "reference_pad_width": 40,
        },
    )
    assert "reference" not in rows[0]  # leading synthetic (Opening Balance)
    assert "reference" not in rows[-1]  # trailing synthetic (Carried forward)
    assert all("reference" in row for row in rows[1:-1])


def test_brought_forward_label_is_printed_verbatim():
    rows = get_provider("bank_transactions")(
        _bank_entry(), {"brought_forward": True, "brought_forward_label": "BALANCE BROUGHT FORWARD"}
    )
    assert rows[0]["description"] == "BALANCE BROUGHT FORWARD"
    assert rows[0]["synthetic"] is True


def test_opening_balance_label_is_printed_verbatim():
    rows = get_provider("bank_transactions")(
        _bank_entry(), {"opening_balance": True, "opening_balance_label": "Opening"}
    )
    assert rows[0]["description"] == "Opening"


def test_differing_labels_leave_the_computed_balance_untouched():
    plain = get_provider("bank_transactions")(
        _bank_entry(), {"brought_forward": True, "brought_forward_label": "Balance Brought Forward"}
    )
    other = get_provider("bank_transactions")(
        _bank_entry(), {"brought_forward": True, "brought_forward_label": "BALANCE BROUGHT FORWARD"}
    )
    assert plain[0]["balance"] == other[0]["balance"]


@pytest.mark.parametrize(
    ("params", "missing"),
    [
        ({"opening_balance": True}, "opening_balance_label"),
        ({"brought_forward": True}, "brought_forward_label"),
        ({"carried_forward": True}, "carried_forward_label"),
        ({"references": True}, "reference_prefix"),
        ({"references": True, "reference_prefix": "Ref: "}, "reference_pad_char"),
        (
            {"references": True, "reference_prefix": "Ref: ", "reference_pad_char": "."},
            "reference_pad_width",
        ),
    ],
)
def test_printed_text_params_are_required_not_defaulted(params, missing):
    """Every string this provider prints comes from the layout, or it fails fast.

    Each of these six params decides text on a rendered bank statement page.
    A Python fallback would put the decision back in this module, so the
    provider refuses to guess.
    """
    with pytest.raises(ProviderError) as err:
        get_provider("bank_transactions")(_bank_entry(), params)
    assert_diagnostic_error(err.value)
    assert missing in str(err.value)
    assert "config/layouts/bank_statements.yml" in str(err.value)


def test_balance_suffix_formats_a_positive_balance_with_the_credit_suffix():
    rows = get_provider("bank_transactions")(
        _bank_entry(), {"balance_suffix": {"debit": "DR", "credit": "CR"}}
    )
    # Both real rows carry a positive balance (900.00, 1400.00 -- see the
    # backwards-balance test above), so both take the credit suffix.
    assert rows[0]["balance"] == "$900.00 CR"
    assert rows[1]["balance"] == "$1,400.00 CR"


def test_balance_suffix_formats_a_negative_balance_with_the_debit_suffix_and_abs_value():
    entry = _bank_entry()
    entry["fields"]["ACCOUNT_BALANCE"] = "-50.00"
    rows = get_provider("bank_transactions")(entry, {"balance_suffix": {"debit": "DR", "credit": "CR"}})
    # Closing -50.00; reversing the credit-500 row gives -550.00 for row 0.
    assert rows[0]["balance"] == "$550.00 DR"
    assert rows[1]["balance"] == "$50.00 DR"


def test_balance_suffix_applies_to_a_leading_synthetic_row_too():
    rows = get_provider("bank_transactions")(
        _bank_entry(),
        {
            "brought_forward": True,
            "brought_forward_label": "Balance Brought Forward",
            "balance_suffix": {"debit": "DR", "credit": "CR"},
        },
    )
    assert rows[0]["synthetic"] is True
    assert rows[0]["balance"] == "$1,000.00 CR"


def test_balance_suffix_absent_by_default_leaves_balance_as_decimal():
    rows = get_provider("bank_transactions")(_bank_entry(), {})
    assert all(isinstance(row["balance"], Decimal) for row in rows)


def test_bank_transaction_totals_sums_debits_and_credits():
    rows = get_provider("bank_transaction_totals")(_bank_entry(), {"label": "Totals at end of period"})
    assert len(rows) == 1
    row = rows[0]
    assert row["debit"] == Decimal("100.00")
    assert row["credit"] == Decimal("500.00")
    assert row["description"] == "Totals at end of period"
    assert row["date"] == ""
    assert "balance" not in row


def test_bank_transaction_totals_row_is_synthetic_bold_and_ruled_above():
    row = get_provider("bank_transaction_totals")(_bank_entry(), {"label": "Totals at end of period"})[0]
    assert row["synthetic"] is True
    assert row["bold"] is True
    assert row["rule_above"] is True


def test_bank_transaction_totals_label_overrides_the_default():
    row = get_provider("bank_transaction_totals")(_bank_entry(), {"label": "Totals"})[0]
    assert row["description"] == "Totals"


def test_bank_transaction_totals_ignores_not_found_amounts():
    entry = _bank_entry()
    entry["fields"]["TRANSACTION_AMOUNTS_PAID"] = "NOT_FOUND|NOT_FOUND"
    row = get_provider("bank_transaction_totals")(entry, {"label": "Totals at end of period"})[0]
    assert row["debit"] == Decimal("0")
    assert row["credit"] == Decimal("500.00")


def test_empty_transaction_list_with_synthetic_row_requested_returns_no_rows():
    entry = {
        "fields": {
            "TRANSACTION_DATES": "",
            "TRANSACTION_DESCRIPTIONS": "",
            "TRANSACTION_AMOUNTS_PAID": "",
            "TRANSACTION_AMOUNTS_RECEIVED": "",
            "ACCOUNT_BALANCE": "0.00",
        }
    }
    assert (
        get_provider("bank_transactions")(
            entry, {"opening_balance": True, "opening_balance_label": "Opening Balance"}
        )
        == []
    )


def test_bank_transaction_totals_label_must_come_from_yaml():
    from conftest import assert_diagnostic_error

    entry = {
        "fields": {
            "TRANSACTION_AMOUNTS_PAID": "10.00|20.00",
            "TRANSACTION_AMOUNTS_RECEIVED": "5.00|NOT_FOUND",
        }
    }
    with pytest.raises(ProviderError) as exc_info:
        get_provider("bank_transaction_totals")(entry, {})
    assert_diagnostic_error(exc_info.value)
    assert "label" in str(exc_info.value).lower()


def test_quantity_prefix_is_applied_only_above_one():
    entry = {
        "fields": {
            "LINE_ITEM_DESCRIPTIONS": "Coffee|Muffin",
            "LINE_ITEM_QUANTITIES": "2|1",
            "LINE_ITEM_PRICES": "4.50|3.20",
            "LINE_ITEM_TOTAL_PRICES": "9.00|3.20",
        }
    }
    rows = get_provider("receipt_line_items")(
        entry,
        {
            "fields": {
                "description": "LINE_ITEM_DESCRIPTIONS",
                "quantity": "LINE_ITEM_QUANTITIES",
                "price": "LINE_ITEM_PRICES",
                "total": "LINE_ITEM_TOTAL_PRICES",
            },
            "quantity_prefix_format": "{quantity}x ",
        },
    )
    assert rows[0]["description"] == "2x Coffee"
    assert rows[1]["description"] == "Muffin"


def _line_item_rows(total="9.00|3.20", quantities="2|1"):
    entry = {
        "fields": {
            "LINE_ITEM_DESCRIPTIONS": "Coffee|Muffin",
            "LINE_ITEM_QUANTITIES": quantities,
            "LINE_ITEM_PRICES": "4.50|3.20",
            "LINE_ITEM_TOTAL_PRICES": total,
        }
    }
    return get_provider("receipt_line_items")(
        entry,
        {
            "fields": {
                "description": "LINE_ITEM_DESCRIPTIONS",
                "quantity": "LINE_ITEM_QUANTITIES",
                "price": "LINE_ITEM_PRICES",
                "total": "LINE_ITEM_TOTAL_PRICES",
            },
            "quantity_prefix_format": "{quantity}x ",
        },
    )


def test_applied_quantity_prefix_is_re_exposed_for_geometry_capture():
    """The prefix is a ground-truth value with its own recorded box, and once
    it is concatenated into `description` its extent is unrecoverable."""
    rows = _line_item_rows()
    assert rows[0]["quantity_prefix"] == "2x "
    assert rows[1]["quantity_prefix"] == ""


def test_amount_columns_are_coerced_to_decimal():
    """The legacy renderer printed f"{Decimal(total):,.2f}", not the raw
    string, so a one-decimal-place amount must not render as `9.5`."""
    rows = _line_item_rows(total="9.5|3.20")
    assert rows[0]["total"] == Decimal("9.5")
    assert rows[0]["price"] == Decimal("4.50")


def test_absent_amounts_are_left_as_sentinels():
    """`_cell_text` maps both to a cell that draws nothing; coercing them to
    Decimal("0") would print a fabricated $0.00."""
    rows = _line_item_rows(total="|NOT_FOUND")
    assert rows[0]["total"] == ""
    assert rows[1]["total"] == "NOT_FOUND"


def test_malformed_amount_is_a_diagnostic_not_a_silent_zero():
    with pytest.raises(ProviderError) as exc_info:
        _line_item_rows(total="nine dollars|3.20")
    message = str(exc_info.value)
    # Points at the receipt ground truth, not the bank statements the other
    # caller of this parse reads.
    assert "ground_truth/receipts.yml" in message
    assert_diagnostic_error(message)


def test_missing_prefix_format_fails_diagnostically():
    from conftest import assert_diagnostic_error

    with pytest.raises(ProviderError) as exc_info:
        get_provider("receipt_line_items")({"fields": {}}, {"fields": {"description": "X"}})
    assert_diagnostic_error(exc_info.value)


def test_missing_fields_delegates_validation_to_pipe_fields():
    """Verify that missing 'fields' delegates to pipe_fields for diagnostic error."""
    from conftest import assert_diagnostic_error

    with pytest.raises(ProviderError) as exc_info:
        get_provider("receipt_line_items")({"fields": {}}, {"quantity_prefix_format": "{quantity}x "})
    assert_diagnostic_error(exc_info.value)


# --- pipe_fields decimal_keys (Task 15) --------------------------------------
#
# The invoice line-item table draws straight off pipe_fields, and legacy printed
# `fmt_amount(Decimal(price))`. Without coercion the table draws the raw
# ground-truth string, so a one-decimal-place amount renders "9.5", not "$9.50".

_INVOICE_ENTRY = {
    "fields": {
        "LINE_ITEM_DESCRIPTIONS": "Consulting|Postage",
        "LINE_ITEM_PRICES": "716.52|9.5",
        "LINE_ITEM_TOTAL_PRICES": "2866.08|NOT_FOUND",
    }
}

_INVOICE_PARAMS = {
    "fields": {
        "description": "LINE_ITEM_DESCRIPTIONS",
        "price": "LINE_ITEM_PRICES",
        "total": "LINE_ITEM_TOTAL_PRICES",
    },
    "decimal_keys": ["price", "total"],
}


def test_decimal_keys_coerce_named_columns_to_decimal():
    rows = get_provider("pipe_fields")(_INVOICE_ENTRY, _INVOICE_PARAMS)
    assert rows[0]["price"] == Decimal("716.52")
    assert rows[1]["price"] == Decimal("9.5")
    assert rows[0]["total"] == Decimal("2866.08")


def test_decimal_keys_leave_unnamed_columns_and_sentinels_alone():
    rows = get_provider("pipe_fields")(_INVOICE_ENTRY, _INVOICE_PARAMS)
    assert rows[0]["description"] == "Consulting"  # not named in decimal_keys
    assert rows[1]["total"] == "NOT_FOUND"  # the absent sentinel draws nothing


def test_absent_decimal_keys_changes_nothing():
    rows = get_provider("pipe_fields")(_INVOICE_ENTRY, {"fields": _INVOICE_PARAMS["fields"]})
    assert rows[0]["price"] == "716.52"


def test_decimal_keys_naming_an_unmapped_row_key_fails_diagnostically():
    """A typo here would otherwise silently coerce nothing — indistinguishable
    from the amounts having been drawn correctly all along."""
    from conftest import assert_diagnostic_error

    with pytest.raises(ProviderError) as exc_info:
        get_provider("pipe_fields")(_INVOICE_ENTRY, {**_INVOICE_PARAMS, "decimal_keys": ["price", "totl"]})
    assert_diagnostic_error(exc_info.value)
    assert "totl" in str(exc_info.value)


def test_malformed_decimal_key_amount_names_its_source_field():
    from conftest import assert_diagnostic_error

    entry = {"fields": {"LINE_ITEM_PRICES": "not-a-number"}}
    with pytest.raises(ProviderError) as exc_info:
        get_provider("pipe_fields")(
            entry, {"fields": {"price": "LINE_ITEM_PRICES"}, "decimal_keys": ["price"]}
        )
    assert_diagnostic_error(exc_info.value)
    assert "LINE_ITEM_PRICES" in str(exc_info.value)
