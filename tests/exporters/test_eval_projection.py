"""Tests for the in-house extraction-schema projection.

Covers the five accessors `scripts/relabel_evaluation_set.py` needs
(`monetary_fields`, `boolean_fields`, `resolve_doc_type`,
`get_all_doc_type_fields`, `get_extraction_fields`), sourced from
`config/extraction_schema.yml` instead of LMM_POC's `common.field_schema`.
"""

from pathlib import Path

import pytest
import yaml

from conftest import assert_diagnostic_error
from generators.exporters.eval_projection import _SCHEMA_PATH, load_extraction_schema

VALID = {
    "document_fields": {
        "invoice": {"fields": ["DOCUMENT_TYPE", "BUSINESS_ABN", "TOTAL_AMOUNT"]},
        "receipt": {"fields": ["DOCUMENT_TYPE", "BUSINESS_ABN", "TOTAL_AMOUNT"]},
        "bank_statement": {
            "fields": [
                "DOCUMENT_TYPE",
                "STATEMENT_DATE_RANGE",
                "LINE_ITEM_DESCRIPTIONS",
                "TRANSACTION_DATES",
                "TRANSACTION_AMOUNTS_PAID",
            ]
        },
    },
    "evaluation": {
        "field_types": {
            "monetary": ["TOTAL_AMOUNT", "TRANSACTION_AMOUNTS_PAID"],
            "boolean": ["IS_GST_INCLUDED"],
        }
    },
}


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "extraction_schema.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _load(tmp_path: Path, data: dict = VALID):
    load_extraction_schema.cache_clear()
    return load_extraction_schema(_write(tmp_path, data))


# ---------------------------------------------------------------------------
# Real repo config
# ---------------------------------------------------------------------------


def test_loads_real_repo_config() -> None:
    """The actual config/extraction_schema.yml loads and exposes all three types."""
    load_extraction_schema.cache_clear()
    schema = load_extraction_schema(_SCHEMA_PATH)
    assert set(schema.get_all_doc_type_fields()) == {"invoice", "receipt", "bank_statement"}
    assert len(schema.monetary_fields) == 9
    assert len(schema.boolean_fields) == 1


# ---------------------------------------------------------------------------
# Field list per document type, including order
# ---------------------------------------------------------------------------


def test_extraction_fields_preserve_declared_order(tmp_path: Path) -> None:
    schema = _load(tmp_path)
    assert schema.get_extraction_fields("bank_statement") == [
        "DOCUMENT_TYPE",
        "STATEMENT_DATE_RANGE",
        "LINE_ITEM_DESCRIPTIONS",
        "TRANSACTION_DATES",
        "TRANSACTION_AMOUNTS_PAID",
    ]


def test_extraction_fields_returns_new_list(tmp_path: Path) -> None:
    """Callers can mutate the returned list without corrupting the schema."""
    schema = _load(tmp_path)
    fields = schema.get_extraction_fields("invoice")
    fields.append("MUTATED")
    assert "MUTATED" not in schema.get_extraction_fields("invoice")


def test_get_all_doc_type_fields_matches_yaml_order(tmp_path: Path) -> None:
    schema = _load(tmp_path)
    all_fields = schema.get_all_doc_type_fields()
    assert all_fields["invoice"] == ["DOCUMENT_TYPE", "BUSINESS_ABN", "TOTAL_AMOUNT"]
    assert all_fields["bank_statement"][0] == "DOCUMENT_TYPE"


def test_get_all_doc_type_fields_returns_new_dict(tmp_path: Path) -> None:
    schema = _load(tmp_path)
    all_fields = schema.get_all_doc_type_fields()
    all_fields["invoice"].append("MUTATED")
    assert "MUTATED" not in schema.get_extraction_fields("invoice")


# ---------------------------------------------------------------------------
# Document-type name resolution across this repo's conventions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BANK_STATEMENT", "bank_statement"),  # ground-truth DOCUMENT_TYPE convention
        ("INVOICE", "invoice"),
        ("RECEIPT", "receipt"),
        ("bank_statements", "bank_statement"),  # generation_config.yml pipeline-key convention
        ("invoices", "invoice"),
        ("receipts", "receipt"),
        ("bank_statement", "bank_statement"),  # extraction_schema.yml's own convention
        ("invoice", "invoice"),
        ("receipt", "receipt"),
        ("Bank-Statement", "bank_statement"),  # hyphen/mixed-case normalisation
    ],
)
def test_resolve_doc_type_across_conventions(tmp_path: Path, raw: str, expected: str) -> None:
    schema = _load(tmp_path)
    assert schema.resolve_doc_type(raw) == expected


def test_resolve_doc_type_strips_surrounding_whitespace(tmp_path: Path) -> None:
    """More lenient than LMM_POC by design: padding only ever helps resolution."""
    schema = _load(tmp_path)
    assert schema.resolve_doc_type("  BANK_STATEMENT\n") == "bank_statement"


def test_resolve_doc_type_unresolved_returns_normalised_unchanged(tmp_path: Path) -> None:
    """Mirrors LMM_POC: no match means normalised-but-unchanged, not a raise."""
    schema = _load(tmp_path)
    assert schema.resolve_doc_type("credit card statement") == "credit_card_statement"


# ---------------------------------------------------------------------------
# Monetary / boolean classification
# ---------------------------------------------------------------------------


def test_monetary_and_boolean_fields(tmp_path: Path) -> None:
    schema = _load(tmp_path)
    assert schema.monetary_fields == frozenset({"TOTAL_AMOUNT", "TRANSACTION_AMOUNTS_PAID"})
    assert schema.boolean_fields == frozenset({"IS_GST_INCLUDED"})
    # A field absent from both classifications is neither.
    assert "DOCUMENT_TYPE" not in schema.monetary_fields
    assert "DOCUMENT_TYPE" not in schema.boolean_fields


# ---------------------------------------------------------------------------
# Unknown document type fails clearly rather than returning empty
# ---------------------------------------------------------------------------


def test_unknown_document_type_raises(tmp_path: Path) -> None:
    schema = _load(tmp_path)
    with pytest.raises(ValueError) as exc:
        schema.get_extraction_fields("credit_card_statement")
    assert_diagnostic_error(exc.value, schema.source_path, "credit_card_statement")


def test_get_all_doc_type_fields_excludes_unknown_type(tmp_path: Path) -> None:
    schema = _load(tmp_path)
    assert "credit_card_statement" not in schema.get_all_doc_type_fields()


# ---------------------------------------------------------------------------
# Fail-fast diagnostics: missing config file
# ---------------------------------------------------------------------------


def test_missing_file_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "absent.yml"
    load_extraction_schema.cache_clear()
    with pytest.raises(FileNotFoundError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "Extraction schema not found")


def test_malformed_yaml_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "extraction_schema.yml"
    path.write_text("document_fields: [unclosed\n")
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "Failed to parse YAML")


def test_non_dict_top_level_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "extraction_schema.yml"
    path.write_text("- invoice\n- receipt\n")
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "got list")


# ---------------------------------------------------------------------------
# Fail-fast diagnostics: required keys inside the config
# ---------------------------------------------------------------------------


def test_missing_document_fields_is_diagnostic(tmp_path: Path) -> None:
    data = {k: v for k, v in VALID.items() if k != "document_fields"}
    path = _write(tmp_path, data)
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "document_fields")


def test_doc_type_missing_fields_list_is_diagnostic(tmp_path: Path) -> None:
    data = {
        **VALID,
        "document_fields": {**VALID["document_fields"], "invoice": {"not_fields": []}},
    }
    path = _write(tmp_path, data)
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "document_fields.invoice.fields")


def test_empty_fields_list_is_diagnostic(tmp_path: Path) -> None:
    data = {
        **VALID,
        "document_fields": {**VALID["document_fields"], "invoice": {"fields": []}},
    }
    path = _write(tmp_path, data)
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "document_fields.invoice.fields")


def test_missing_evaluation_is_diagnostic(tmp_path: Path) -> None:
    data = {k: v for k, v in VALID.items() if k != "evaluation"}
    path = _write(tmp_path, data)
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "evaluation")


def test_missing_field_types_is_diagnostic(tmp_path: Path) -> None:
    data = {**VALID, "evaluation": {}}
    path = _write(tmp_path, data)
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "field_types")


def test_missing_monetary_is_diagnostic(tmp_path: Path) -> None:
    data = {**VALID, "evaluation": {"field_types": {"boolean": ["IS_GST_INCLUDED"]}}}
    path = _write(tmp_path, data)
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "evaluation.field_types.monetary")


def test_missing_boolean_is_diagnostic(tmp_path: Path) -> None:
    data = {**VALID, "evaluation": {"field_types": {"monetary": ["TOTAL_AMOUNT"]}}}
    path = _write(tmp_path, data)
    load_extraction_schema.cache_clear()
    with pytest.raises(ValueError) as exc:
        load_extraction_schema(path)
    assert_diagnostic_error(exc.value, path, "evaluation.field_types.boolean")
