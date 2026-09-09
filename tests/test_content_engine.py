"""Unit tests for generators/content_engine.py."""

import copy
import random
import re
from pathlib import Path

import pytest
import yaml

from conftest import assert_diagnostic_error
from generators.common import validate_abn
from generators.content_engine import (
    ContentEngine,
    NonRepeatingSampler,
    build_engine,
    load_pools,
    sample,
)

_MINIMAL_VALID_POOLS = {
    "faker_config": {"locale": "en_AU", "seed_base": 42},
    "locations": [{"suburb": "Sydney", "postcode": "2000", "state": "NSW"}],
    "street_types": ["St"],
    "business_name_parts": {
        "surnames": ["Ashcroft"],
        "suburb_prefixes": ["Metro"],
        "category_nouns": {"hardware": ["Hardware"]},
    },
    "product_catalog": [{"description": "Widget", "unit": "ea", "price_low": 1.0, "price_high": 2.0}],
    "service_catalog": [{"description": "Consulting", "unit": "hrs", "price_low": 100, "price_high": 200}],
    "banks": [{"code": "cba", "name": "Commonwealth Bank", "bsb_prefix": "06"}],
    "bank_descriptions": {"eftpos": "EFTPOS {merchant} {location} AUS"},
    "retailers": [{"name": "Bunnings Warehouse"}],
    "professional_services": [{"name": "Smith & Associates Accounting"}],
    "real_name_blocklist_extra": ["Aldi"],
    "receipt_categories": ["hardware"],
    "service_categories": ["accounting"],
}


def _write_pools(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "data_pools.yml"
    path.write_text(yaml.dump(data))
    return path


def test_load_pools_succeeds_with_all_required_keys(tmp_path):
    path = _write_pools(tmp_path, _MINIMAL_VALID_POOLS)
    pools = load_pools(path)
    assert pools["faker_config"]["locale"] == "en_AU"


def test_load_pools_fails_fast_on_missing_top_level_key(tmp_path):
    data = dict(_MINIMAL_VALID_POOLS)
    del data["banks"]
    path = _write_pools(tmp_path, data)
    with pytest.raises(ValueError) as exc_info:
        load_pools(path)
    assert_diagnostic_error(str(exc_info.value))


def test_load_pools_fails_fast_on_missing_nested_key(tmp_path):
    data = dict(_MINIMAL_VALID_POOLS)
    data["faker_config"] = {"locale": "en_AU"}  # missing seed_base
    path = _write_pools(tmp_path, data)
    with pytest.raises(ValueError) as exc_info:
        load_pools(path)
    assert_diagnostic_error(str(exc_info.value))


def test_load_pools_fails_fast_on_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.yml"
    with pytest.raises(FileNotFoundError) as exc_info:
        load_pools(missing)
    assert_diagnostic_error(str(exc_info.value))


def test_load_pools_fails_fast_on_empty_file(tmp_path):
    path = tmp_path / "empty.yml"
    path.write_text("")
    with pytest.raises(ValueError) as exc_info:
        load_pools(path)
    assert_diagnostic_error(str(exc_info.value))


def test_load_pools_fails_fast_on_non_mapping_nested_parent(tmp_path):
    data = dict(_MINIMAL_VALID_POOLS)
    data["faker_config"] = "oops-not-a-mapping"
    path = _write_pools(tmp_path, data)
    with pytest.raises(ValueError) as exc_info:
        load_pools(path)
    msg = str(exc_info.value)
    assert_diagnostic_error(msg)
    # Sharp differentiator: must be the "present but not a mapping" path, NOT the
    # missing-key ("not found") path (whose Expected line also contains "mapping").
    assert "is not a YAML mapping" in msg
    assert "not found" not in msg


def test_sample_is_deterministic_for_same_seed():
    pool = ["a", "b", "c", "d", "e"]
    r1 = [sample(random.Random(20), pool) for _ in range(10)]
    r2 = [sample(random.Random(20), pool) for _ in range(10)]
    assert r1 == r2


def test_sample_empty_pool_fails_fast():
    with pytest.raises(ValueError) as exc_info:
        sample(random.Random(1), [])
    assert_diagnostic_error(str(exc_info.value))


def test_non_repeating_sampler_visits_every_item_before_repeating():
    pool = ["a", "b", "c", "d"]
    sampler = NonRepeatingSampler(random.Random(1), pool)
    draws = [sampler.draw() for _ in range(len(pool))]
    assert sorted(draws) == sorted(pool)


def test_non_repeating_sampler_reshuffles_on_exhaustion():
    pool = ["a", "b", "c"]
    sampler = NonRepeatingSampler(random.Random(2), pool)
    first_pass = [sampler.draw() for _ in range(3)]
    second_pass = [sampler.draw() for _ in range(3)]
    assert sorted(first_pass) == sorted(pool)
    assert sorted(second_pass) == sorted(pool)


def test_non_repeating_sampler_is_deterministic_for_same_seed():
    pool = ["a", "b", "c", "d", "e", "f"]
    s1 = NonRepeatingSampler(random.Random(99), pool)
    s2 = NonRepeatingSampler(random.Random(99), pool)
    assert [s1.draw() for _ in range(12)] == [s2.draw() for _ in range(12)]


def test_non_repeating_sampler_distribution_is_not_lockstep_across_seeds():
    pool = list(range(10))
    s1 = NonRepeatingSampler(random.Random(1), pool)
    s2 = NonRepeatingSampler(random.Random(2), pool)
    seq1 = [s1.draw() for _ in range(10)]
    seq2 = [s2.draw() for _ in range(10)]
    assert seq1 != seq2


def test_non_repeating_sampler_empty_pool_fails_fast():
    with pytest.raises(ValueError) as exc_info:
        NonRepeatingSampler(random.Random(1), [])
    assert_diagnostic_error(str(exc_info.value))


def test_person_returns_en_au_name_shape():
    engine = build_engine()
    p = engine.person(random.Random(1))
    assert p["full_name"] == f"{p['first_name']} {p['last_name']}"
    assert p["first_name"] and p["last_name"]


def test_person_is_deterministic_for_same_seed():
    engine = build_engine()
    p1 = engine.person(random.Random(7))
    p2 = engine.person(random.Random(7))
    assert p1 == p2


def test_location_draws_from_the_locations_pool():
    engine = build_engine()
    loc = engine.location(random.Random(3))
    assert loc in engine.pools["locations"]


def test_address_matches_expected_format():
    engine = build_engine()
    addr = engine.address(random.Random(5))
    pattern = r"^\d+ .+ (St|Ave|Rd|Dr|Pl|Cres|Ct|Tce|Way|Ln|Gr|Blvd|Cl|Pde), .+ [A-Z]{2,3} \d{4}$"
    assert re.match(pattern, addr), addr


def test_address_is_deterministic_for_same_seed():
    engine = build_engine()
    a1 = engine.address(random.Random(42))
    a2 = engine.address(random.Random(42))
    assert a1 == a2


def test_fictional_business_never_emits_a_blocklisted_name():
    engine = build_engine()
    rng = random.Random(11)
    blocked = {r["name"].lower() for r in engine.pools["retailers"]}
    blocked |= {p["name"].lower() for p in engine.pools["professional_services"]}
    blocked |= {n.lower() for n in engine.pools["real_name_blocklist_extra"]}
    for _ in range(300):
        biz = engine.fictional_business(rng, "hardware")
        assert biz["name"].lower() not in blocked


def test_fictional_business_returns_a_valid_abn():
    engine = build_engine()
    biz = engine.fictional_business(random.Random(4), "grocery")
    assert validate_abn(biz["abn"])


def test_fictional_business_unknown_category_fails_fast():
    engine = build_engine()
    with pytest.raises(ValueError) as exc_info:
        engine.fictional_business(random.Random(2), "not_a_real_category")
    assert_diagnostic_error(str(exc_info.value))


def test_fictional_business_exhausted_retries_fails_fast():
    pools = copy.deepcopy(load_pools())
    pools["business_name_parts"]["surnames"] = ["Ashcroft"]
    pools["business_name_parts"]["suburb_prefixes"] = ["Metro"]
    pools["business_name_parts"]["category_nouns"]["hardware"] = ["Hardware"]
    engine = ContentEngine(pools)
    engine._blocklist = {"ashcroft hardware", "metro hardware"}
    with pytest.raises(RuntimeError) as exc_info:
        engine.fictional_business(random.Random(9), "hardware")
    assert_diagnostic_error(str(exc_info.value))


def test_fictional_business_name_is_name_only_and_screened():
    engine = build_engine()
    rng = random.Random(11)
    blocked = {r["name"].lower() for r in engine.pools["retailers"]}
    blocked |= {p["name"].lower() for p in engine.pools["professional_services"]}
    blocked |= {n.lower() for n in engine.pools["real_name_blocklist_extra"]}
    for _ in range(300):
        name = engine.fictional_business_name(rng, "hardware")
        assert isinstance(name, str)
        assert name.lower() not in blocked


def test_fictional_business_name_unknown_category_fails_fast():
    engine = build_engine()
    with pytest.raises(ValueError) as exc_info:
        engine.fictional_business_name(random.Random(2), "nope")
    assert_diagnostic_error(str(exc_info.value))


# CHARACTERIZATION test — pins fictional_business's CURRENT output so the Task 3
# refactor (extracting the name loop into fictional_business_name) cannot silently
# change its draw order/values. No gate would otherwise catch a refactor that
# produced a different-but-valid corpus. This test passes before AND after the
# refactor; it only goes RED if the refactor changed behavior.
#
# NOTE: `abn` is deliberately excluded from the golden dict and compared via
# validate_abn() instead of exact-match. generate_abn() (generators/common.py)
# draws from the unseeded global `random` module, not the `rng` parameter passed
# in here — it is non-deterministic per call regardless of seed (confirmed by
# calling fictional_business(Random(4), "grocery") twice in the same process and
# observing two different ABNs with identical name/address). Pinning an exact ABN
# value would make this test permanently flaky, independent of whether the
# refactor is correct.
_FICTIONAL_BUSINESS_GOLDEN: dict[tuple[int, str], dict] = {
    (4, "grocery"): {
        "name": "Ashby Fresh Market",
        "address": "100 Rogers Rd, Fortitude Valley QLD 4006",
        "category": "grocery",
    },
    (11, "hardware"): {
        "name": "Riverside Timber & Tools",
        "address": "290 Hernandez Way, Paddington QLD 4064",
        "category": "hardware",
    },
    (7, "legal"): {
        "name": "Western Solicitors",
        "address": "186 Stark Ave, St Kilda VIC 3182",
        "category": "legal",
    },
    (21, "fuel"): {
        "name": "Ockendon Service Station",
        "address": "81 Shelton Tce, Parramatta NSW 2150",
        "category": "fuel",
    },
    (99, "marketing"): {
        "name": "Underhill Marketing Co",
        "address": "214 Wright Dr, Subiaco WA 6008",
        "category": "marketing",
    },
}


def test_fictional_business_unchanged_by_name_only_refactor():
    engine = build_engine()
    assert _FICTIONAL_BUSINESS_GOLDEN, "populate _FICTIONAL_BUSINESS_GOLDEN in Step 1a"
    for (seed, cat), expected in _FICTIONAL_BUSINESS_GOLDEN.items():
        got = engine.fictional_business(random.Random(seed), cat)
        abn = got.pop("abn")
        assert validate_abn(abn)
        assert got == expected, f"fictional_business({seed},{cat}) changed: {got} != {expected}"
