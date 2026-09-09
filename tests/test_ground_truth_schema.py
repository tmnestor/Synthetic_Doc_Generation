"""Tests for generators/schema.py's ground-truth fail-fast diagnostics (local-only; tests/ is gitignored).

Named test_ground_truth_schema.py, not test_schema.py, to avoid a pytest
basename collision with tests/layout_dsl/test_schema.py (this test tree has
no __init__.py files, so module basenames must be unique across it).

Covers the two config-driven lookups that read config/field_definitions.yml
with bare dict subscripts: _valid_doc_types() (the 'document_type_values' key)
and _field_type_group() (the 'field_types' key). Both must raise SchemaError
with a four-element diagnostic on a missing key rather than an unhandled
KeyError, since generators/pipeline.py's `validate` command does not catch
KeyError around generators.schema.validate_entry.
"""

from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error

from generators import schema as schema_mod
from generators.schema import SchemaError, _field_type_group, _valid_doc_types, validate_entry

_MINIMAL_DOC_TYPE_VALUES = {"document_type_values": ["RECEIPT"]}
_MINIMAL_FIELD_TYPES = {"field_types": {"date": ["INVOICE_DATE"]}}


@pytest.fixture(autouse=True)
def _reset_field_defs_cache():
    """Clear generators.schema's module-level field-defs cache around each test.

    _load_field_defs() memoizes its result into the module-level _FIELD_DEFS
    global the first time it's called. Tests that point _FIELD_DEFS_PATH at a
    temp file must clear this cache first, or they would silently see
    whatever an earlier test (or an earlier call against the real config)
    already cached; clearing afterward keeps the cache from leaking into
    tests that run after this module.
    """
    schema_mod._FIELD_DEFS = None
    yield
    schema_mod._FIELD_DEFS = None


def _write_field_defs(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "field_definitions.yml"
    path.write_text(yaml.safe_dump(data))
    return path


def _point_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(schema_mod, "_FIELD_DEFS_PATH", path)


# --- _valid_doc_types() ------------------------------------------------


def test_valid_doc_types_raises_schema_error_when_document_type_values_missing(tmp_path, monkeypatch):
    path = _write_field_defs(tmp_path, {"document_fields": {}})
    _point_at(monkeypatch, path)

    with pytest.raises(SchemaError) as exc_info:
        _valid_doc_types()

    assert_diagnostic_error(exc_info.value)
    message = str(exc_info.value)
    assert "document_type_values" in message
    assert str(path.resolve()) in message


def test_valid_doc_types_returns_correct_values_against_real_config():
    values = _valid_doc_types()
    assert values == {"BANK_STATEMENT", "RECEIPT", "INVOICE"}


# --- _field_type_group() ------------------------------------------------


def test_field_type_group_raises_schema_error_when_field_types_key_missing(tmp_path, monkeypatch):
    path = _write_field_defs(tmp_path, {"document_type_values": ["RECEIPT"]})
    _point_at(monkeypatch, path)

    with pytest.raises(SchemaError) as exc_info:
        _field_type_group("date")

    assert_diagnostic_error(exc_info.value)
    message = str(exc_info.value)
    assert "field_types" in message
    assert str(path.resolve()) in message


def test_field_type_group_returns_empty_set_when_requested_group_absent(tmp_path, monkeypatch):
    """field_types present but with no 'abn' key is not a schema error — this
    is deliberate existing behaviour (not every field type applies to every
    document type) and must not change."""
    path = _write_field_defs(tmp_path, {"field_types": {"date": ["INVOICE_DATE"]}})
    _point_at(monkeypatch, path)

    assert _field_type_group("abn") == set()


def test_field_type_group_returns_correct_values_against_real_config():
    assert _field_type_group("date") == {"INVOICE_DATE"}
    assert _field_type_group("abn") == {"BUSINESS_ABN"}
    assert _field_type_group("amount") == {"GST_AMOUNT", "TOTAL_AMOUNT", "ACCOUNT_BALANCE"}
    assert _field_type_group("date_range") == {"STATEMENT_DATE_RANGE"}


# --- validate_entry() integration: SchemaError must not propagate raw -----


def test_validate_entry_surfaces_missing_document_type_values_as_error_string(tmp_path, monkeypatch):
    """pipeline.py:76 calls validate_entry() without a try/except around it,
    so a SchemaError raised deep inside must be caught and turned into an
    error string here rather than propagating as a raw exception."""
    path = _write_field_defs(tmp_path, {"document_fields": {}})
    _point_at(monkeypatch, path)

    entry = {
        "layout": "some_layout",
        "degradation_seed": 1,
        "fields": {"DOCUMENT_TYPE": "RECEIPT"},
    }
    errors = validate_entry("CASE001", entry)

    assert len(errors) == 1
    assert_diagnostic_error(errors[0])
    assert "document_type_values" in errors[0]


def test_validate_entry_surfaces_missing_field_types_as_error_string(tmp_path, monkeypatch):
    path = _write_field_defs(
        tmp_path,
        {
            "document_type_values": ["RECEIPT"],
            "document_fields": {"receipt": ["DOCUMENT_TYPE"]},
        },
    )
    _point_at(monkeypatch, path)

    entry = {
        "layout": "some_layout",
        "degradation_seed": 1,
        "fields": {"DOCUMENT_TYPE": "RECEIPT"},
    }
    errors = validate_entry("CASE001", entry)

    assert len(errors) == 1
    assert_diagnostic_error(errors[0])
    assert "field_types" in errors[0]
