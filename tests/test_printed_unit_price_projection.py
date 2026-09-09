"""The extraction projection must not emit a price the receipt never printed.

tests/ is gitignored — local-only.

A receipt line carries ONE amount, and that amount is the line total:

    3x <item name>                          9.72

The per-unit price (3.24) is nowhere on the page. The generator knows it because
it composed the line, so the projection was writing a DERIVED value into the
answer key. That makes LINE_ITEM_PRICES unscoreable in the honest sense: a model
reporting exactly what the receipt prints is marked wrong, and the only route to
a good score is division, which is arithmetic rather than extraction. Measured
on LMM_POC's 55-receipt corpus, two VLMs both read the printed amount correctly
and scored 0.20-0.46 on this field for it; with the derived positions blanked, a
model that reports what is printed scores 1.000.

Where the quantity is 1 the unit price and the line total coincide, so the
printed amount IS the unit price and is kept.

INVOICES ARE EXCLUDED, and that gate is the load-bearing part of this change:
the invoice layout has an explicit "Unit Price" column, so the value is on the
page and the answer key is already correct. Blanking it would destroy correct
ground truth.
"""

import pytest

from generators.eval_set import _blank_unprinted_unit_prices

PRICES = "LINE_ITEM_PRICES"
QUANTITIES = "LINE_ITEM_QUANTITIES"


def _receipt(prices: str, quantities: str, doc_type: str = "RECEIPT") -> dict[str, str]:
    return {
        "DOCUMENT_TYPE": doc_type,
        "SUPPLIER_NAME": "<supplier>",
        QUANTITIES: quantities,
        PRICES: prices,
        "LINE_ITEM_TOTAL_PRICES": "$9.30 | $54.26 | $102.27",
    }


class TestBlanksOnlyWhatIsNotPrinted:
    def test_quantity_one_keeps_its_amount(self) -> None:
        out = _blank_unprinted_unit_prices(_receipt("$9.30 | $7.77", "1 | 1"))
        assert out[PRICES] == "$9.30 | $7.77"

    def test_quantity_above_one_is_blanked(self) -> None:
        out = _blank_unprinted_unit_prices(_receipt("$9.30 | $27.13 | $34.09", "1 | 2 | 3"))
        assert out[PRICES] == "$9.30 | NOT_FOUND | NOT_FOUND"

    def test_nothing_printed_collapses_to_the_scalar(self) -> None:
        """A list of nothing but NOT_FOUND is noise; the field is simply absent."""
        out = _blank_unprinted_unit_prices(_receipt("$3.24 | $12.69", "3 | 2"))
        assert out[PRICES] == "NOT_FOUND"

    def test_decimal_quantity_is_not_treated_as_one(self) -> None:
        out = _blank_unprinted_unit_prices(_receipt("$9.30 | $7.77", "1.0 | 2.5"))
        assert out[PRICES] == "$9.30 | NOT_FOUND"


class TestInvoicesAreUntouched:
    """The invoice template prints a Unit Price column, so its key is correct."""

    def test_invoice_keeps_every_price(self) -> None:
        out = _blank_unprinted_unit_prices(_receipt("$9.30 | $27.13", "1 | 2", doc_type="INVOICE"))
        assert out[PRICES] == "$9.30 | $27.13"

    def test_bank_statement_keeps_every_price(self) -> None:
        out = _blank_unprinted_unit_prices(
            _receipt("$9.30 | $27.13", "1 | 2", doc_type="BANK_STATEMENT")
        )
        assert out[PRICES] == "$9.30 | $27.13"


class TestRefusesToGuess:
    """Guessing in an answer key is worse than leaving it as generated."""

    @pytest.mark.parametrize(
        ("prices", "quantities"),
        [
            ("NOT_FOUND", "1 | 2"),
            ("$9.30 | $27.13", "NOT_FOUND"),
            ("$9.30 | $27.13 | $1.00", "1 | 2"),  # columns of unequal length
            ("$9.30 | $27.13", "1 | many"),  # quantity is not a number
        ],
    )
    def test_leaves_the_field_alone(self, prices: str, quantities: str) -> None:
        assert _blank_unprinted_unit_prices(_receipt(prices, quantities))[PRICES] == prices


class TestProjectionContract:
    """Same guarantees the sibling _drop_credit_rows makes."""

    def test_key_order_is_preserved(self) -> None:
        record = _receipt("$9.30 | $27.13", "1 | 2")
        assert list(_blank_unprinted_unit_prices(record)) == list(record)

    def test_the_input_is_not_mutated(self) -> None:
        record = _receipt("$9.30 | $27.13", "1 | 2")
        before = dict(record)
        _blank_unprinted_unit_prices(record)
        assert record == before

    def test_other_fields_are_untouched(self) -> None:
        record = _receipt("$9.30 | $27.13", "1 | 2")
        out = _blank_unprinted_unit_prices(record)
        assert out["LINE_ITEM_TOTAL_PRICES"] == record["LINE_ITEM_TOTAL_PRICES"]
        assert out[QUANTITIES] == record[QUANTITIES]

    def test_is_idempotent(self) -> None:
        once = _blank_unprinted_unit_prices(_receipt("$9.30 | $27.13", "1 | 2"))
        assert _blank_unprinted_unit_prices(once) == once
