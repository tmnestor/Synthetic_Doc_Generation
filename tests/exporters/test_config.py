"""Tests for export config loading and validation."""

from pathlib import Path

import pytest
import yaml

from conftest import assert_diagnostic_error
from generators.exporters.config import load_export_config

VALID = {
    "abn_tfn_canonical_form": "spaced",
    "abn_tfn_equality_form": "digits_only",
    "cord_extension_scoring": "excluded_scored_separately",
    "export_targets": ["cord", "doc_refs"],
    "docile_fieldtypes": {"SUPPLIER_NAME": "vendor_name"},
}


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "export_config.yml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_loads_valid_config(tmp_path: Path) -> None:
    result = load_export_config(_write(tmp_path, VALID))
    assert result["abn_tfn_canonical_form"] == "spaced"
    assert result["export_targets"] == ["cord", "doc_refs"]


def test_missing_key_is_diagnostic(tmp_path: Path) -> None:
    data = {k: v for k, v in VALID.items() if k != "cord_extension_scoring"}
    path = _write(tmp_path, data)
    with pytest.raises(ValueError) as exc:
        load_export_config(path)
    assert_diagnostic_error(exc.value, path, "cord_extension_scoring")


def test_invalid_enum_value_is_diagnostic(tmp_path: Path) -> None:
    data = {**VALID, "abn_tfn_canonical_form": "hyphenated"}
    path = _write(tmp_path, data)
    with pytest.raises(ValueError) as exc:
        load_export_config(path)
    assert_diagnostic_error(exc.value, path, "hyphenated")
    # The allowed values themselves should also be surfaced.
    assert "spaced" in str(exc.value)
    assert "digits_only" in str(exc.value)


def test_empty_export_targets_is_allowed(tmp_path: Path) -> None:
    """An explicit empty list ships every target as a no-op — it is not a missing key."""
    result = load_export_config(_write(tmp_path, {**VALID, "export_targets": []}))
    assert result["export_targets"] == []


def test_missing_file_is_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "absent.yml"
    with pytest.raises(FileNotFoundError) as exc:
        load_export_config(path)
    assert_diagnostic_error(exc.value, path, "Export config not found")


def test_malformed_yaml_is_diagnostic(tmp_path: Path) -> None:
    """An unparseable YAML file must hit the yaml.YAMLError branch, not crash raw."""
    path = tmp_path / "export_config.yml"
    path.write_text("abn_tfn_canonical_form: [unclosed\n")
    with pytest.raises(ValueError) as exc:
        load_export_config(path)
    assert_diagnostic_error(exc.value, path, "Failed to parse YAML")


def test_non_dict_top_level_is_diagnostic(tmp_path: Path) -> None:
    """A YAML file whose top level is a list (not a mapping) must be rejected."""
    path = tmp_path / "export_config.yml"
    path.write_text("- cord\n- docile\n")
    with pytest.raises(ValueError) as exc:
        load_export_config(path)
    assert_diagnostic_error(exc.value, path, "got list")


def test_export_targets_wrong_type_is_diagnostic(tmp_path: Path) -> None:
    """export_targets must be a list, not e.g. a bare scalar."""
    data = {**VALID, "export_targets": "cord"}
    path = _write(tmp_path, data)
    with pytest.raises(ValueError) as exc:
        load_export_config(path)
    assert_diagnostic_error(exc.value, path, "export_targets")


def test_export_targets_unknown_member_is_diagnostic(tmp_path: Path) -> None:
    """Every export_targets member must be one of the allowed targets."""
    data = {**VALID, "export_targets": ["cord", "bogus_target"]}
    path = _write(tmp_path, data)
    with pytest.raises(ValueError) as exc:
        load_export_config(path)
    assert_diagnostic_error(exc.value, path, "bogus_target")


def test_docile_fieldtypes_wrong_type_is_diagnostic(tmp_path: Path) -> None:
    """docile_fieldtypes must be a mapping, not e.g. a list."""
    data = {**VALID, "docile_fieldtypes": ["not", "a", "mapping"]}
    path = _write(tmp_path, data)
    with pytest.raises(ValueError) as exc:
        load_export_config(path)
    assert_diagnostic_error(exc.value, path, "docile_fieldtypes")
