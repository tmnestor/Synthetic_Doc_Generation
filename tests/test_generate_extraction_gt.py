"""Tests for scripts/generate_extraction_gt.py after its move from LMM_POC.

The script has no package, so it is loaded by path. Its `--schema` argument must be
LMM_POC's extraction contract; this repo's own config/field_definitions.yml is the
generation contract and would silently produce a wrong-shaped CSV, so the loader
rejects it.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "generate_extraction_gt.py"
SDG_SCHEMA = REPO / "config" / "field_definitions.yml"
EXTRACTION_SCHEMA = REPO / "config" / "extraction_schema.yml"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_extraction_gt", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_module()


def assert_diagnostic_error(message: str) -> None:
    """Assert a fail-fast message carries what, where, expected and remedy."""
    assert "What:" in message
    assert "Where:" in message
    assert "Expected:" in message
    assert "How to fix:" in message


def test_script_lives_in_this_repo():
    assert SCRIPT.is_file()


def test_this_repos_generation_schema_is_rejected(gen, tmp_path):
    """The generation contract must not be accepted as the extraction contract."""
    with pytest.raises(ValueError) as excinfo:
        gen._load_schema(SDG_SCHEMA)
    message = str(excinfo.value)
    assert_diagnostic_error(message)
    assert "evaluation.field_types" in message
    assert "GENERATION contract" in message


def test_missing_schema_file_is_rejected(gen, tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        gen._load_schema(tmp_path / "nope.yaml")
    assert_diagnostic_error(str(excinfo.value))


def test_schema_without_evaluation_key_is_rejected(gen, tmp_path):
    """A YAML with document_fields but no evaluation block must not slip through."""
    path = tmp_path / "schema.yaml"
    path.write_text(yaml.safe_dump({"document_fields": {"invoice": {"fields": ["DOCUMENT_TYPE"]}}}))
    with pytest.raises(ValueError) as excinfo:
        gen._load_schema(path)
    assert_diagnostic_error(str(excinfo.value))


def test_valid_schema_yields_field_lists_and_type_sets(gen, tmp_path):
    path = tmp_path / "schema.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "document_fields": {
                    "invoice": {"fields": ["DOCUMENT_TYPE", "TOTAL_AMOUNT"]},
                    "bank_statement": {"fields": ["DOCUMENT_TYPE", "TRANSACTION_DATES"]},
                },
                "evaluation": {
                    "field_types": {"monetary": ["TOTAL_AMOUNT"], "boolean": ["IS_GST_INCLUDED"]}
                },
            }
        )
    )
    schema = gen._load_schema(path)
    assert schema["invoice_fields"] == ["DOCUMENT_TYPE", "TOTAL_AMOUNT"]
    assert schema["bank_fields"] == ["DOCUMENT_TYPE", "TRANSACTION_DATES"]
    assert schema["monetary"] == frozenset({"TOTAL_AMOUNT"})
    assert schema["boolean"] == frozenset({"IS_GST_INCLUDED"})


def test_columns_put_image_file_first_and_append_bank_only_fields(gen):
    schema = {
        "invoice_fields": ["DOCUMENT_TYPE", "TOTAL_AMOUNT"],
        "bank_fields": ["DOCUMENT_TYPE", "TRANSACTION_DATES"],
    }
    assert gen._build_columns(schema) == [
        "image_file",
        "DOCUMENT_TYPE",
        "TOTAL_AMOUNT",
        "TRANSACTION_DATES",
    ]


def test_yaml_dir_defaults_to_this_repos_ground_truth(gen):
    """The default must be repo-relative, not a path on the author's machine."""
    source = SCRIPT.read_text()
    assert "/Users/tod" not in source, "absolute developer paths must not ship in a shared repo"
    assert (REPO / "ground_truth").is_dir()


def test_schema_defaults_to_the_repo_local_extraction_contract(gen):
    """The generator must be self-contained — no path into another checkout."""
    assert EXTRACTION_SCHEMA.is_file()
    assert "extraction_schema.yml" in SCRIPT.read_text().split('"--schema"')[1][:300]


def test_shipped_extraction_contract_loads_and_matches_the_prompts(gen):
    """The vendored contract must be the extraction field set, not the generation one."""
    schema = gen._load_schema(EXTRACTION_SCHEMA)
    assert len(schema["invoice_fields"]) == 14
    assert len(schema["bank_fields"]) == 5
    # Receipts show no payer, but the prompt asks: scored, expecting NOT_FOUND.
    assert "PAYER_NAME" in schema["invoice_fields"]
    # Generated on bank statements, but never part of the 5-field extraction task.
    assert "ACCOUNT_BALANCE" not in schema["bank_fields"]
    assert "IS_GST_INCLUDED" in schema["boolean"]


def test_validation_only_fields_are_not_csv_columns(gen):
    """ACCOUNT_BALANCE etc. have formatting declared but must add no columns."""
    schema = gen._load_schema(EXTRACTION_SCHEMA)
    columns = gen._build_columns(schema)
    for field in gen._VALIDATION_ONLY:
        assert field not in columns
