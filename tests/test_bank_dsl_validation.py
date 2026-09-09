"""Bank layouts validate through the DSL, and legacy dispatch keys are gone.

Companion to Task 14's deletion of generators/bank_statement.py's per-bank
renderers: `pipeline validate` must reject a malformed layout body before any
rendering starts, and the YAML must carry no key only the deleted legacy
renderers ever read.
"""

from pathlib import Path

import pytest

from generators.layout_dsl.schema import LayoutSchemaError, validate_body, validate_layout
from generators.loader import load_layout_registry

from conftest import assert_diagnostic_error

LAYOUT_PATH = Path("config/layouts/bank_statements.yml")
BANK_FIELDS = {
    "DOCUMENT_TYPE", "SUPPLIER_NAME", "STATEMENT_DATE_RANGE", "TRANSACTION_DATES",
    "TRANSACTION_DESCRIPTIONS", "TRANSACTION_AMOUNTS_PAID", "TRANSACTION_AMOUNTS_RECEIVED",
    "ACCOUNT_BALANCE", "PAYER_NAME",
}


def test_every_bank_layout_validates():
    for layout_id, layout in load_layout_registry(LAYOUT_PATH).items():
        validate_layout(
            layout,
            layout_id=layout_id,
            layout_path=str(LAYOUT_PATH),
            known_fields=BANK_FIELDS,
        )


def test_no_bank_layout_retains_dead_dispatch_keys():
    dead = {"renderer", "variant", "column_headers", "show_opening_balance",
            "show_brought_forward", "show_references", "show_totals_row",
            "show_rewards_section", "show_footer_transaction_types", "date_grouping",
            "bank_name_color", "header_bar_color", "header_color", "logo_color",
            "balance_suffix", "balance_suffix_debit", "balance_suffix_credit",
            "bank_code", "date_format"}
    for layout_id, layout in load_layout_registry(LAYOUT_PATH).items():
        assert not (dead & set(layout)), f"{layout_id} still carries {sorted(dead & set(layout))}"


def test_bank_statement_module_no_longer_exposes_per_bank_renderers():
    import generators.bank_statement as module

    for name in ("render_cba", "render_westpac", "render_nab", "render_anz"):
        assert not hasattr(module, name), f"{name} should have been deleted"


def test_validation_rejects_a_broken_layout():
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            {
                "content_width": 1600,
                "field_budgets": {},
                "body": [{"type": "text", "content": "{NO_SUCH_FIELD}"}],
            },
            layout_id="broken",
            layout_path=str(LAYOUT_PATH),
            known_fields=BANK_FIELDS,
        )
    assert_diagnostic_error(str(exc_info.value))


def test_unclosed_placeholder_is_rejected():
    """An unclosed '{FIELD' renders as a silent literal today. Hand-authored
    receipt and invoice bodies are exactly where this typo happens."""
    body = [{"type": "text", "content": "Account: {PAYER_NAME"}]
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_body(body, layout_id="probe", layout_path="config/layouts/receipts.yml",
                      known_fields={"PAYER_NAME"})
    assert_diagnostic_error(exc_info.value)
    assert "PAYER_NAME" in str(exc_info.value)
