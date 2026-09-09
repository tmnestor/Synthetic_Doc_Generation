"""The extraction projection must emit debit-only bank transaction rows.

tests/ is gitignored — local-only.

The canonical register in ground_truth/bank_statements.yml is the FULL table:
index-aligned TRANSACTION_* columns where a credit row carries NOT_FOUND in the
paid column and a debit row carries NOT_FOUND in the received column. That is
correct for the register and for transaction linking, and is not changed here.

But the extraction contract (config/extraction_schema.yml, bank_statement) asks
for only five fields and has no home for a credit amount — there is no
TRANSACTION_AMOUNTS_RECEIVED in it. Projecting the full register into that
5-field answer key leaves placeholder rows a model is never asked to produce.
LMM_POC's order-aware scorer then compares position-by-position, the two lists
sit offset by the credit count, and a correct extraction scores 0.000.

Older ground truths (bank/, synthetic_original, synthetic_21, synthetic_20260622)
were debit-only; every 55-case corpus since has carried placeholders. This
restores the earlier contract for the extraction projection only.
"""

from generators.eval_set import _drop_credit_rows

BANK = "BANK_STATEMENT"


def _bank() -> dict[str, str]:
    """Projected bank record: rows 0 and 3 are credits."""
    return {
        "DOCUMENT_TYPE": BANK,
        "STATEMENT_DATE_RANGE": "02/12/2023 - 31/12/2023",
        "LINE_ITEM_DESCRIPTIONS": "Salary PAYROLL | BPAY VERRALL | ATM WITHDRAWAL | Transfer In",
        "TRANSACTION_DATES": "02/12/2023 | 03/12/2023 | 05/12/2023 | 06/12/2023",
        "TRANSACTION_AMOUNTS_PAID": "NOT_FOUND | $42805.81 | $587.22 | NOT_FOUND",
    }


class TestDropsCreditRows:
    def test_every_register_column_is_filtered_together(self) -> None:
        out = _drop_credit_rows(_bank())
        assert out["TRANSACTION_AMOUNTS_PAID"] == "$42805.81 | $587.22"
        assert out["LINE_ITEM_DESCRIPTIONS"] == "BPAY VERRALL | ATM WITHDRAWAL"
        assert out["TRANSACTION_DATES"] == "03/12/2023 | 05/12/2023"

    def test_no_placeholder_survives_the_paid_column(self) -> None:
        assert "NOT_FOUND" not in _drop_credit_rows(_bank())["TRANSACTION_AMOUNTS_PAID"]

    def test_scalars_untouched(self) -> None:
        out = _drop_credit_rows(_bank())
        assert out["STATEMENT_DATE_RANGE"] == "02/12/2023 - 31/12/2023"
        assert out["DOCUMENT_TYPE"] == BANK

    def test_key_order_is_preserved(self) -> None:
        # The JSONL key order is the contract (see write_jsonl).
        assert list(_drop_credit_rows(_bank())) == list(_bank())

    def test_input_not_mutated(self) -> None:
        src = _bank()
        _drop_credit_rows(src)
        assert src["TRANSACTION_AMOUNTS_PAID"].startswith("NOT_FOUND")

    def test_separator_style_is_preserved(self) -> None:
        rec = {
            "DOCUMENT_TYPE": BANK,
            "TRANSACTION_DATES": "01/01/2024|02/01/2024",
            "TRANSACTION_AMOUNTS_PAID": "NOT_FOUND|$2.00",
        }
        assert _drop_credit_rows(rec)["TRANSACTION_AMOUNTS_PAID"] == "$2.00"
        assert _drop_credit_rows(rec)["TRANSACTION_DATES"] == "02/01/2024"


class TestLeavesEverythingElseAlone:
    def test_non_bank_untouched(self) -> None:
        inv = {
            "DOCUMENT_TYPE": "INVOICE",
            "LINE_ITEM_DESCRIPTIONS": "Consulting | Travel",
            "TRANSACTION_AMOUNTS_PAID": "NOT_FOUND | $5.00",
        }
        assert _drop_credit_rows(inv) == inv

    def test_already_debit_only_unchanged(self) -> None:
        rec = {
            "DOCUMENT_TYPE": BANK,
            "TRANSACTION_DATES": "01/01/2024 | 02/01/2024",
            "TRANSACTION_AMOUNTS_PAID": "$1.00 | $2.00",
        }
        assert _drop_credit_rows(rec) == rec

    def test_all_rows_credit_unchanged(self) -> None:
        # Emitting an empty register would be a silently wrong answer key.
        rec = {
            "DOCUMENT_TYPE": BANK,
            "TRANSACTION_DATES": "01/01/2024 | 02/01/2024",
            "TRANSACTION_AMOUNTS_PAID": "NOT_FOUND | NOT_FOUND",
        }
        assert _drop_credit_rows(rec) == rec

    def test_absent_paid_column_unchanged(self) -> None:
        rec = {"DOCUMENT_TYPE": BANK, "TRANSACTION_DATES": "01/01/2024 | 02/01/2024"}
        assert _drop_credit_rows(rec) == rec

    def test_mismatched_column_length_is_left_whole(self) -> None:
        rec = {
            "DOCUMENT_TYPE": BANK,
            "LINE_ITEM_DESCRIPTIONS": "A | B | C",
            "TRANSACTION_DATES": "01/01/2024 | 02/01/2024",
            "TRANSACTION_AMOUNTS_PAID": "NOT_FOUND | $2.00",
        }
        out = _drop_credit_rows(rec)
        assert out["LINE_ITEM_DESCRIPTIONS"] == "A | B | C"
        assert out["TRANSACTION_DATES"] == "02/01/2024"

    def test_scalar_paid_value_unchanged(self) -> None:
        rec = {
            "DOCUMENT_TYPE": BANK,
            "TRANSACTION_DATES": "01/01/2024",
            "TRANSACTION_AMOUNTS_PAID": "$1.00",
        }
        assert _drop_credit_rows(rec) == rec
