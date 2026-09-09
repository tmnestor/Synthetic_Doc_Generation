"""Loader-coverage test: the real config/data_pools.yml satisfies content_engine's
required core keys and has the expected shape (local-only; tests/ is gitignored)."""

from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error

from generators.content_engine import load_pools
from generators.payment_block import load_pos_pools

# The staff pool as `generators/receipt.py`'s `_STAFF_NAMES` listed it, in
# order, before Task 14 deleted that module-level list with the legacy
# renderer. Pinned here rather than imported: the digest indexes into the
# YAML pool by position, so this is the only remaining record of the order
# every derived staff name depends on.
_LEGACY_STAFF_NAMES = [
    "Sarah",
    "James",
    "Emma",
    "Liam",
    "Olivia",
    "Noah",
    "Chloe",
    "Jack",
    "Mia",
    "Ethan",
    "Ava",
    "Will",
    "Sophie",
    "Ben",
    "Isla",
    "Tom",
]


def test_real_data_pools_loads_without_error():
    pools = load_pools()
    assert pools["faker_config"] == {"locale": "en_AU", "seed_base": 42}


def test_business_name_parts_covers_every_retailer_and_service_category():
    pools = load_pools()
    nouns = pools["business_name_parts"]["category_nouns"]
    receipt_categories = {r["category"] for r in pools["retailers"]}
    service_categories = {p["category"] for p in pools["professional_services"]}
    for category in receipt_categories | service_categories:
        assert category in nouns, f"missing category_nouns entry for {category!r}"
        assert len(nouns[category]) >= 3


def test_product_and_service_catalogs_have_positive_price_ranges():
    pools = load_pools()
    for item in pools["product_catalog"] + pools["service_catalog"]:
        assert item["price_low"] > 0
        assert item["price_high"] >= item["price_low"]


def test_bank_descriptions_grammar_never_embeds_the_forbidden_acronym():
    pools = load_pools()
    for template in pools["bank_descriptions"].values():
        assert "ATO" not in template


def test_retailers_and_professional_services_are_still_the_real_pools():
    pools = load_pools()
    assert len(pools["retailers"]) == 20
    assert len(pools["professional_services"]) == 5


def test_deleted_pools_are_gone():
    pools = load_pools()
    for stale_key in ("account_holders", "transaction_patterns", "trust_names", "trustee_names"):
        assert stale_key not in pools


def test_receipt_and_service_categories_present_and_cover_category_nouns():
    pools = load_pools()
    receipt = pools["receipt_categories"]
    service = pools["service_categories"]
    assert receipt == ["hardware", "grocery", "office", "electronics", "retail",
                       "pharmacy", "liquor", "fuel", "automotive"]
    assert service == ["accounting", "legal", "it_services", "consulting", "marketing"]
    nouns = pools["business_name_parts"]["category_nouns"]
    for cat in receipt + service:
        assert cat in nouns


# -- pos_terminal / load_pos_pools ---------------------------------------------
#
# Mirrors tests/test_payment_block.py's coverage of load_terminal_pools -- same
# real-file-plus-mutated-tmp_path shape, distinct root key ("pos_terminal").

_POOLS_PATH = Path("config/data_pools.yml")

_POS_REQUIRED = [
    "staff_names",
    "hour_min",
    "hour_span",
    "register_min",
    "register_span",
    "receipt_number_prefix",
    "receipt_number_digest_length",
]


def _write_pos_pools(tmp_path: Path, mutate) -> Path:
    """Copy the real pools file, apply `mutate` to pos_terminal, write it out."""
    data = yaml.safe_load(_POOLS_PATH.read_text())
    mutate(data["pos_terminal"])
    out = tmp_path / "data_pools.yml"
    out.write_text(yaml.safe_dump(data))
    return out


def test_loads_real_pos_pools_file():
    pools = load_pos_pools(_POOLS_PATH)
    for key in _POS_REQUIRED:
        assert key in pools, f"{key} missing from pos_terminal"


def test_pos_staff_names_are_byte_identical_to_the_legacy_pool_in_order():
    """The digest indexes into this list by position (`staff_idx = hash %
    len(staff_names)`), so a reordering -- not just a membership change --
    would silently change every derived staff name."""
    assert load_pos_pools(_POOLS_PATH)["staff_names"] == _LEGACY_STAFF_NAMES


def test_pos_windows_match_the_legacy_hardcoded_ranges():
    """08:00-19:59 (receipt.py:104), register 01-08 (receipt.py:109), 'R-' plus
    6 hex chars (receipt.py:81-82)."""
    pools = load_pos_pools(_POOLS_PATH)
    assert (pools["hour_min"], pools["hour_span"]) == (8, 12)
    assert (pools["register_min"], pools["register_span"]) == (1, 8)
    assert pools["receipt_number_prefix"] == "R-"
    assert pools["receipt_number_digest_length"] == 6


@pytest.mark.parametrize("key", _POS_REQUIRED)
def test_pos_missing_required_key_is_four_element_diagnostic(tmp_path, key):
    path = _write_pos_pools(tmp_path, lambda pt: pt.pop(key))
    with pytest.raises(ValueError) as exc_info:
        load_pos_pools(path)
    assert key in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_pos_missing_pos_terminal_block_is_diagnostic(tmp_path):
    data = yaml.safe_load(_POOLS_PATH.read_text())
    del data["pos_terminal"]
    path = tmp_path / "data_pools.yml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError) as exc_info:
        load_pos_pools(path)
    assert_diagnostic_error(exc_info.value)


def test_pos_staff_names_empty_list_is_diagnostic(tmp_path):
    path = _write_pos_pools(tmp_path, lambda pt: pt.__setitem__("staff_names", []))
    with pytest.raises(ValueError) as exc_info:
        load_pos_pools(path)
    assert "staff_names" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_pos_staff_names_non_string_entry_is_diagnostic(tmp_path):
    path = _write_pos_pools(tmp_path, lambda pt: pt.__setitem__("staff_names", ["Sarah", 7]))
    with pytest.raises(ValueError) as exc_info:
        load_pos_pools(path)
    assert "staff_names" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


@pytest.mark.parametrize("key", ["hour_min", "register_min"])
def test_pos_non_negative_int_key_rejects_a_negative_value(tmp_path, key):
    path = _write_pos_pools(tmp_path, lambda pt: pt.__setitem__(key, -1))
    with pytest.raises(ValueError) as exc_info:
        load_pos_pools(path)
    assert key in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


@pytest.mark.parametrize("key", ["hour_span", "register_span", "receipt_number_digest_length"])
def test_pos_positive_int_key_rejects_zero(tmp_path, key):
    path = _write_pos_pools(tmp_path, lambda pt: pt.__setitem__(key, 0))
    with pytest.raises(ValueError) as exc_info:
        load_pos_pools(path)
    assert key in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


@pytest.mark.parametrize("key", ["hour_min", "hour_span", "register_min", "register_span"])
def test_pos_int_key_rejects_a_string_value(tmp_path, key):
    path = _write_pos_pools(tmp_path, lambda pt: pt.__setitem__(key, "8"))
    with pytest.raises(ValueError) as exc_info:
        load_pos_pools(path)
    assert key in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_pos_receipt_number_prefix_empty_string_is_diagnostic(tmp_path):
    path = _write_pos_pools(tmp_path, lambda pt: pt.__setitem__("receipt_number_prefix", ""))
    with pytest.raises(ValueError) as exc_info:
        load_pos_pools(path)
    assert "receipt_number_prefix" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_pos_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pos_pools(tmp_path / "nope.yml")
