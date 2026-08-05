# Phase 1B — Content Widening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-script real-entity constants and `pool[i % len(pool)]` cycling in both seed scripts with a shared, testable `content_engine.py` that draws varied, de-correlated, fully-fictional AU content from `config/data_pools.yml`, then execute a coordinated, gated reseed of all 8 document types and both link files.

**Architecture:** A new `generators/content_engine.py` loads `config/data_pools.yml` once and exposes seeded primitives (`person`, `address`, `location`, `fictional_business`, `fictional_trust`, `sample`, `NonRepeatingSampler`) that both `scripts/seed_ground_truth.py` (core: bank/receipt/invoice/cc) and `scripts/seed_trust_distributions.py` (trust: trust_return/distribution_statement/trust_income_schedule/beneficiary_itr) call. Each script generates its per-case shared entities once and projects them across that case's linked docs, so widened content never desyncs a link. `scripts/seed_transaction_links.py` and `scripts/seed_trust_distribution_links.py` need no code changes — verified below — they just re-run against the reseeded entries.

**Tech Stack:** Python 3.12, PyYAML, Faker 40.8.0 (`en_AU` locale, already pinned in `environment.yml`), Pillow 12.2.0 (renderers untouched), pytest, typer (for `--dry-run` flags), ruff, mypy.

## Global Constraints

- Python 3.12 hints (`X | Y`; no `from __future__ import annotations`; no `TYPE_CHECKING` guards for runtime-signature types); line length ≤108.
- **YAML single source of truth:** all content lives in `config/data_pools.yml`; Python holds no content constants; every key required; a missing key fails fast (no silent default).
- **Fail-fast four-element diagnostics** (what / where — absolute path + dotted YAML key / valid example / how to recover); fail-fast tests assert all four via `tests/conftest.py::assert_diagnostic_error`.
- **B904** in except (`raise ... from err`/`from None`).
- **NEVER write the Australian tax authority's three-letter acronym** anywhere (use "PROD"); existing code may contain it — do not copy into new lines. (The bank-description template that once embedded it was rewritten to `"Salary PAYROLL {ref}"` for this reason — see Task 2.)
- **Determinism:** seeded `random.Random` + `Faker.seed(n)` on the per-case scheme; `faker==40.8.0`, `pillow==12.2.0` pins (both already in `environment.yml`, no dependency changes needed); reuse `generate_abn()`/`generate_tfn()` from `generators/common.py` (never real ABNs/TFNs).
- **No renderer changes** — all 8 renderers are already fit-safe (Phase 1A); 1B is content only.
- Tests: `conda run -n synthetic pytest tests/`; `tests/` gitignored (local-only); ≥80% coverage. Gate before every commit: `ruff check --fix --ignore ARG001,ARG002,F841` → `ruff format` → `mypy . --ignore-missing-imports` → `pytest tests/`. Never bypass the pre-commit hook. No Claude/AI attribution in commits.

## Deviation from the task hint (dependency-ordering fix)

The hint lists `sample(rng, pool)` + a non-repeating draw helper as Task 6, after `person`/`address` (Task 3) and `fictional_business`/`fictional_trust` (Tasks 4–5). But `location()`/`address()` call `sample()` internally, and `fictional_business`/`fictional_trust` call both `sample()` and `self.address()`. Landing `sample()` last would make Tasks 3–5's own code fail to import. This plan moves `sample()` + `NonRepeatingSampler` to **Task 3** (before any primitive that depends on them) and renumbers `person`/`address`/`location` to **Task 4**, `fictional_business` to **Task 5**, `fictional_trust` to **Task 6**. Task titles and total count are unchanged from the hint; only the internal ordering of 3 vs. 6 is swapped, for a hard dependency reason, not style.

## Verified: no changes needed to the link scripts

- `scripts/seed_transaction_links.py:108` — `shorthand = _RECEIPT_SHORTHANDS.get(supplier, supplier.upper())` already falls back to `supplier.upper()` for suppliers not in its hardcoded shorthand dict (which is keyed to the *old* real retailer/service names). Once `seed_ground_truth.py` emits fictional names, every lookup misses and falls back gracefully — no KeyError, no behavior change needed. Same for `_INVOICE_SHORTHANDS` at line 118.
- `scripts/seed_trust_distribution_links.py` — `_detect_discrepancy()` compares `Decimal` field values read generically by key (`SHARE_OF_NET_INCOME`, `FRANKING_CREDIT`, etc.); it never references a specific name. No change needed.
- Both scripts are **run, not modified**, in Stage 1B-ii (Tasks 10a/10b).

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `generators/content_engine.py` | Create | `load_pools()` fail-fast loader; `sample()`/`NonRepeatingSampler`; `ContentEngine` (`person`, `location`, `address`, `fictional_business`, `fictional_trust`); `build_engine()`. |
| `config/data_pools.yml` | Modify (rewrite) | Sole content source: `faker_config`, `locations`, `street_types`, `business_name_parts`, `trust_name_parts`, `product_catalog`, `service_catalog`, `payment_methods`, `banks`, `bank_descriptions`, `income_years`, `real_name_blocklist_extra`, plus unchanged `retailers`/`professional_services` (real data, blocklist-source only, never emitted). Deletes `account_holders`, `transaction_patterns`, `trust_names`, `trustee_names` (superseded by Faker/fictional generators). |
| `scripts/seed_ground_truth.py` | Modify (full rewrite) | Core GT orchestration via `content_engine`; per-case shared entity (`holder`, `location`) projected across bank/cc/invoice; `--dry-run`. |
| `scripts/seed_trust_distributions.py` | Modify (full rewrite) | Trust GT orchestration via `content_engine`; per-case shared entity (`trust`, `beneficiary`) projected across the 4 trust docs; `--dry-run`. |
| `scripts/seed_transaction_links.py` | No change (verified above) | Re-run only in Stage 1B-ii. |
| `scripts/seed_trust_distribution_links.py` | No change (verified above) | Re-run only in Stage 1B-ii. |
| `tests/test_content_engine.py` | Create | `load_pools()` + `sample`/`NonRepeatingSampler` + `ContentEngine` primitive unit tests (Tasks 1, 3, 4, 5, 6). |
| `tests/test_data_pools_core.py` | Create | Loader-coverage test against the real `config/data_pools.yml` core keys (Task 2). |
| `tests/test_data_pools_trust.py` | Create | Loader-coverage test against the real `config/data_pools.yml` trust keys (Task 8). |
| `tests/test_seed_ground_truth_dry_run.py` | Create | Core rewire + `--dry-run` tests (Task 7). |
| `tests/test_seed_trust_distributions_dry_run.py` | Create | Trust rewire + `--dry-run` tests (Task 9). |
| `ground_truth/{bank_statements,receipts,invoices,cc_statements,trust_returns,distribution_statements,trust_income_schedules,beneficiary_itrs}.yml`, `ground_truth/{transaction_links,trust_distribution_links}.yml` | Modify (1B-ii only, Tasks 10a/10b) | Reseeded content, git-tracked and revertible. |

---

## Stage 1B-i — Build + Validate Machinery (no corpus overwrite)

### Task 1: `content_engine.py` pool loader

**Files:**
- Create: `generators/content_engine.py`
- Test: `tests/test_content_engine.py`

**Interfaces:**
- Produces: `load_pools(path: Path = _DATA_POOLS_PATH) -> dict` — raises `FileNotFoundError` or `ValueError` (four-element diagnostic) on any missing required key.
- Produces: `_DATA_POOLS_PATH: Path` — `config/data_pools.yml` resolved from the repo root.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_content_engine.py`:

```python
"""Unit tests for generators/content_engine.py (local-only; tests/ is gitignored)."""

from pathlib import Path

import pytest
import yaml

from generators.content_engine import load_pools
from tests.conftest import assert_diagnostic_error

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
    "payment_methods": ["EFTPOS"],
    "banks": [{"code": "cba", "name": "Commonwealth Bank", "bsb_prefix": "06"}],
    "bank_descriptions": {"eftpos": "EFTPOS {merchant} {location} AUS"},
    "retailers": [{"name": "Bunnings Warehouse"}],
    "professional_services": [{"name": "Smith & Associates Accounting"}],
    "real_name_blocklist_extra": ["Aldi"],
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.content_engine'`

- [ ] **Step 3: Implement `load_pools()`**

Create `generators/content_engine.py`:

```python
"""Shared content-generation engine for seed scripts (core + trust).

Loads config/data_pools.yml once, owns a seeded Faker("en_AU"), and exposes
the primitives both scripts/seed_ground_truth.py and
scripts/seed_trust_distributions.py call in place of in-script constants and
`pool[i % len(pool)]` cycling: person/location/address (Faker + curated
locations), fictional_business / fictional_trust (invented AU entities
screened against a real-name blocklist), and sample / NonRepeatingSampler
(seeded pool draws). Every primitive is driven by an injected
`random.Random`, so a reseed is reproducible and diffable run-to-run.
"""

from pathlib import Path

import yaml

_DATA_POOLS_PATH = Path(__file__).resolve().parent.parent / "config" / "data_pools.yml"

# Top-level keys load_pools() requires; each maps to the dotted sub-keys (if
# any) that must also be present, so a missing nested key fails fast too.
_REQUIRED_KEYS: dict[str, list[str]] = {
    "faker_config": ["locale", "seed_base"],
    "locations": [],
    "street_types": [],
    "business_name_parts": ["surnames", "suburb_prefixes", "category_nouns"],
    "product_catalog": [],
    "service_catalog": [],
    "payment_methods": [],
    "banks": [],
    "bank_descriptions": [],
    "retailers": [],
    "professional_services": [],
    "real_name_blocklist_extra": [],
}


def _missing_key_error(path: Path, dotted_key: str, subkeys: list[str]) -> str:
    """Build a four-element fail-fast diagnostic for a missing pool key."""
    example = f"a mapping with keys {subkeys}" if subkeys else "a non-empty value"
    return (
        "content pool is missing a required key.\n"
        f"  What:     '{dotted_key}' not found in {path}.\n"
        f"  Where:    {path} -> '{dotted_key}'.\n"
        f"  Expected: {example}.\n"
        f"  Recover:  add the missing key to {path} under '{dotted_key}'."
    )


def load_pools(path: Path = _DATA_POOLS_PATH) -> dict:
    """Load and validate config/data_pools.yml, failing fast on any missing key.

    Args:
        path: Path to the pools YAML file.

    Returns:
        The parsed pools dict.

    Raises:
        FileNotFoundError: `path` does not exist.
        ValueError: a required top-level or nested key is missing.
    """
    if not path.exists():
        raise FileNotFoundError(
            "content pool file not found.\n"
            f"  What:     {path} does not exist.\n"
            f"  Where:    {path}\n"
            "  Expected: a YAML file with the required top-level pool keys "
            "(see generators/content_engine.py _REQUIRED_KEYS).\n"
            f"  Recover:  create {path} (see config/data_pools.yml in the repo for the canonical shape)."
        )

    data = yaml.safe_load(path.read_text())

    for key, subkeys in _REQUIRED_KEYS.items():
        if key not in data:
            raise ValueError(_missing_key_error(path, key, subkeys))
        if subkeys:
            if not isinstance(data[key], dict):
                raise ValueError(_missing_key_error(path, key, subkeys))
            for sub in subkeys:
                if sub not in data[key]:
                    raise ValueError(_missing_key_error(path, f"{key}.{sub}", []))

    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v`
Expected: `4 passed`

- [ ] **Step 5: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py
conda run -n synthetic ruff format generators/content_engine.py
conda run -n synthetic mypy generators/content_engine.py --ignore-missing-imports
git add generators/content_engine.py tests/test_content_engine.py
git commit -m "✨ feat: add content_engine pool loader with fail-fast diagnostics"
```

### Task 2: Migrate CORE content into `config/data_pools.yml`

**Files:**
- Modify: `config/data_pools.yml:1-271` (full rewrite)
- Test: `tests/test_data_pools_core.py`

**Interfaces:**
- Consumes: `generators.content_engine.load_pools` (Task 1).
- Produces: the real `config/data_pools.yml` now satisfies `_REQUIRED_KEYS` from Task 1, plus new keys `product_catalog`, `service_catalog`, `payment_methods`, `bank_descriptions` (widened), `business_name_parts`, `street_types`, `real_name_blocklist_extra` that Tasks 4–7 read via `engine.pools[...]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_pools_core.py`:

```python
"""Loader-coverage test: the real config/data_pools.yml satisfies content_engine's
required core keys and has the expected shape (local-only; tests/ is gitignored)."""

from generators.content_engine import load_pools


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
        # Assert the Australian tax authority's acronym is absent. The real test
        # (tests/test_data_pools_core.py) necessarily contains the literal to
        # compare against; this document does not reproduce it.
        ...


def test_retailers_and_professional_services_are_still_the_real_pools():
    pools = load_pools()
    assert len(pools["retailers"]) == 20
    assert len(pools["professional_services"]) == 5


def test_deleted_pools_are_gone():
    pools = load_pools()
    for stale_key in ("account_holders", "transaction_patterns", "trust_names", "trustee_names"):
        assert stale_key not in pools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_data_pools_core.py -v`
Expected: FAIL — `KeyError: 'business_name_parts'` (or similar, since the real file doesn't have the new keys yet)

- [ ] **Step 3: Rewrite `config/data_pools.yml`**

Replace the entire file with:

```yaml
# Australian business content pools for synthetic document generation.
#
# `retailers` and `professional_services` are REAL businesses. They are never
# emitted into generated documents — content_engine.py reads only their
# `name` fields to seed the real-name blocklist that fictional_business() /
# fictional_trust() screen invented names against.

faker_config:
  locale: en_AU
  seed_base: 42

locations:
  - {suburb: Alexandria, postcode: "2015", state: NSW}
  - {suburb: Hawthorn East, postcode: "3123", state: VIC}
  - {suburb: Fortitude Valley, postcode: "4006", state: QLD}
  - {suburb: Norwood, postcode: "5067", state: SA}
  - {suburb: Subiaco, postcode: "6008", state: WA}
  - {suburb: Hobart, postcode: "7000", state: TAS}
  - {suburb: Parramatta, postcode: "2150", state: NSW}
  - {suburb: South Yarra, postcode: "3141", state: VIC}
  - {suburb: Toowoomba, postcode: "4350", state: QLD}
  - {suburb: Glenelg, postcode: "5045", state: SA}
  - {suburb: Newtown, postcode: "2042", state: NSW}
  - {suburb: Richmond, postcode: "3121", state: VIC}
  - {suburb: New Farm, postcode: "4005", state: QLD}
  - {suburb: Unley, postcode: "5061", state: SA}
  - {suburb: Fremantle, postcode: "6160", state: WA}
  - {suburb: Battery Point, postcode: "7004", state: TAS}
  - {suburb: Chatswood, postcode: "2067", state: NSW}
  - {suburb: St Kilda, postcode: "3182", state: VIC}
  - {suburb: Paddington, postcode: "4064", state: QLD}
  - {suburb: Prospect, postcode: "5082", state: SA}
  - {suburb: Leederville, postcode: "6007", state: WA}
  - {suburb: Manuka, postcode: "2603", state: ACT}
  - {suburb: Cronulla, postcode: "2230", state: NSW}
  - {suburb: Brunswick, postcode: "3056", state: VIC}

street_types: [St, Ave, Rd, Dr, Pl, Cres, Ct, Tce, Way, Ln, Gr, Blvd, Cl, Pde]

business_name_parts:
  surnames:
    [Ashcroft, Bramwell, Calloway, Denholm, Eastwick, Fenwick, Goswell, Harrowgate,
     Ibbotson, Kirriemuir, Lonsdale, Marchbank, Norcott, Ockendon, Penhallow, Quennell,
     Ravensdale, Southcott, Tremayne, Underhill, Verrall, Wakeling, Yarrow, Ashby,
     Blackwood, Carrington, Dunmore, Ellery, Farrant, Greenhalgh]
  suburb_prefixes:
    [Metro, National, Central, Coastal, Northern, Southern, Western, Eastern, Greater,
     Prime, Capital, Regional, Statewide, Riverside, Harbourside]
  category_nouns:
    hardware: ["Hardware", "Trade Supplies", "Building Centre", "Timber & Tools", "Home Improvement"]
    grocery: ["Grocer", "Fresh Market", "Foodstore", "Provisions", "Corner Market"]
    office: ["Office Supplies", "Stationery Co", "Business Supplies", "Print & Office"]
    electronics: ["Electronics", "Tech Store", "Digital Supplies", "AV & Appliances"]
    retail: ["Department Store", "General Store", "Retail Co", "Emporium"]
    pharmacy: ["Pharmacy", "Chemist", "Health Store", "Discount Chemist"]
    liquor: ["Cellars", "Liquor Merchants", "Bottle Shop", "Wine & Spirits"]
    fuel: ["Fuel", "Service Station", "Petroleum", "Roadhouse"]
    automotive: ["Auto Parts", "Automotive Supplies", "Motor Spares", "Tyre & Auto"]
    accounting: ["& Associates Accounting", "Chartered Accountants", "Tax & Advisory", "Accounting Group"]
    legal: ["Legal", "& Partners Lawyers", "Solicitors", "Legal Group"]
    it_services: ["IT Solutions", "Technology Group", "Digital Services", "IT Consulting"]
    consulting: ["Business Consulting", "Strategy Group", "Advisory", "Consulting Partners"]
    marketing: ["Marketing Group", "Creative Agency", "Brand & Media", "Marketing Co"]

product_catalog:
  - {description: "Milk 2L", unit: ea, price_low: 2.50, price_high: 5.50}
  - {description: "Bread White 700g", unit: ea, price_low: 3.00, price_high: 5.00}
  - {description: "Chicken Breast 500g", unit: ea, price_low: 7.00, price_high: 14.00}
  - {description: "Pasta 500g", unit: ea, price_low: 1.50, price_high: 4.00}
  - {description: "Tomato Sauce 500ml", unit: ea, price_low: 2.50, price_high: 5.50}
  - {description: "Chips BBQ 175g", unit: ea, price_low: 3.00, price_high: 6.00}
  - {description: "Toilet Paper 12pk", unit: ea, price_low: 8.00, price_high: 16.00}
  - {description: "Dishwashing Liquid", unit: ea, price_low: 3.50, price_high: 7.00}
  - {description: "Laundry Powder 2kg", unit: ea, price_low: 12.00, price_high: 22.00}
  - {description: "Shampoo 400ml", unit: ea, price_low: 5.00, price_high: 12.00}
  - {description: "Batteries AA 8pk", unit: ea, price_low: 8.00, price_high: 18.00}
  - {description: "HDMI Cable 2m", unit: ea, price_low: 12.00, price_high: 35.00}
  - {description: "USB Hub 4-port", unit: ea, price_low: 15.00, price_high: 45.00}
  - {description: "Phone Case", unit: ea, price_low: 10.00, price_high: 40.00}
  - {description: "Printer Paper A4 500pk", unit: ea, price_low: 8.00, price_high: 18.00}
  - {description: "Pens Ballpoint 10pk", unit: ea, price_low: 4.00, price_high: 10.00}
  - {description: "Paint Brush Set", unit: ea, price_low: 12.00, price_high: 35.00}
  - {description: "Drill Bit Set", unit: ea, price_low: 25.00, price_high: 80.00}
  - {description: "Garden Hose 20m", unit: ea, price_low: 35.00, price_high: 120.00}
  - {description: "Potting Mix 25L", unit: ea, price_low: 8.00, price_high: 20.00}
  - {description: "Motor Oil 5L", unit: ea, price_low: 28.00, price_high: 60.00}
  - {description: "Car Air Freshener", unit: ea, price_low: 5.00, price_high: 15.00}
  - {description: "Wine Red 750ml", unit: ea, price_low: 12.00, price_high: 35.00}
  - {description: "Beer Case 24", unit: ea, price_low: 45.00, price_high: 75.00}
  - {description: "Sparkling Water 12pk", unit: ea, price_low: 8.00, price_high: 16.00}
  - {description: "Coffee Beans 1kg", unit: ea, price_low: 15.00, price_high: 35.00}
  - {description: "Olive Oil 500ml", unit: ea, price_low: 8.00, price_high: 20.00}
  - {description: "Cereal Box 500g", unit: ea, price_low: 4.00, price_high: 9.00}
  - {description: "Yoghurt Tub 1kg", unit: ea, price_low: 5.00, price_high: 10.00}
  - {description: "Frozen Pizza", unit: ea, price_low: 6.00, price_high: 12.00}
  - {description: "Screwdriver Set", unit: ea, price_low: 15.00, price_high: 40.00}
  - {description: "Extension Cord 10m", unit: ea, price_low: 18.00, price_high: 45.00}
  - {description: "LED Light Bulb 4pk", unit: ea, price_low: 10.00, price_high: 25.00}
  - {description: "Kitchen Sponge 6pk", unit: ea, price_low: 3.00, price_high: 7.00}
  - {description: "Hand Soap Refill 1L", unit: ea, price_low: 6.00, price_high: 14.00}
  - {description: "Sunscreen SPF50 200ml", unit: ea, price_low: 10.00, price_high: 22.00}
  - {description: "Panadol 24pk", unit: ea, price_low: 6.00, price_high: 12.00}
  - {description: "Bandaids 40pk", unit: ea, price_low: 5.00, price_high: 10.00}
  - {description: "Tyre Pressure Gauge", unit: ea, price_low: 8.00, price_high: 20.00}
  - {description: "Wiper Blades Pair", unit: ea, price_low: 20.00, price_high: 50.00}
  - {description: "Car Vacuum Cleaner", unit: ea, price_low: 30.00, price_high: 70.00}

service_catalog:
  - {description: "Professional consultation services", unit: hrs, price_low: 150, price_high: 350}
  - {description: "Legal document preparation", unit: hrs, price_low: 200, price_high: 500}
  - {description: "Software development services", unit: hrs, price_low: 120, price_high: 280}
  - {description: "Business strategy consulting", unit: hrs, price_low: 250, price_high: 600}
  - {description: "Marketing campaign management", unit: hrs, price_low: 100, price_high: 200}
  - {description: "Accounting and bookkeeping", unit: hrs, price_low: 80, price_high: 180}
  - {description: "IT support and maintenance", unit: hrs, price_low: 90, price_high: 220}
  - {description: "Financial planning services", unit: hrs, price_low: 180, price_high: 400}
  - {description: "Tax return preparation", unit: ea, price_low: 350, price_high: 800}
  - {description: "Audit services", unit: hrs, price_low: 220, price_high: 450}
  - {description: "Trademark registration", unit: ea, price_low: 500, price_high: 1200}
  - {description: "Website design and development", unit: ea, price_low: 800, price_high: 3000}
  - {description: "Annual report preparation", unit: ea, price_low: 600, price_high: 1500}
  - {description: "Corporate training workshop", unit: day, price_low: 1200, price_high: 3500}
  - {description: "Risk assessment review", unit: ea, price_low: 900, price_high: 2500}
  - {description: "Contract review and drafting", unit: hrs, price_low: 220, price_high: 480}
  - {description: "Payroll processing services", unit: hrs, price_low: 70, price_high: 150}
  - {description: "Cloud infrastructure migration", unit: ea, price_low: 2000, price_high: 6000}
  - {description: "Brand identity design", unit: ea, price_low: 900, price_high: 2800}
  - {description: "Due diligence review", unit: hrs, price_low: 300, price_high: 650}
  - {description: "Cybersecurity assessment", unit: ea, price_low: 1500, price_high: 4500}
  - {description: "Employee mediation services", unit: hrs, price_low: 180, price_high: 350}

payment_methods: [EFTPOS, Visa, Mastercard, Cash, AMEX, PayPal, "Google Pay", "Apple Pay", "Bank Transfer", BPAY]

banks:
  - {code: cba, name: Commonwealth Bank, bsb_prefix: "06", header_color: "#FFD700", header_bg: "#000000"}
  - {code: westpac, name: Westpac, bsb_prefix: "03", header_color: "#FFFFFF", header_bg: "#D5002B"}
  - {code: nab, name: National Australia Bank, bsb_prefix: "08", header_color: "#FFFFFF", header_bg: "#C8102E"}
  - {code: anz, name: ANZ, bsb_prefix: "01", header_color: "#FFFFFF", header_bg: "#003087"}

# {merchant} is upper-cased by content_engine callers before formatting these
# templates, matching real AU bank-statement styling and keeping
# seed_transaction_links.py's _extract_suburb() (which distinguishes an
# ALL-CAPS merchant token from a Title-Case suburb) parsing correctly.
bank_descriptions:
  eftpos: "EFTPOS {merchant} {location} AUS"
  visa_debit: "VISA DEBIT PURCHASE CARD {last4} {merchant} {location} AU"
  mastercard_debit: "MASTERCARD DEBIT {merchant} {location} AU"
  bpay: "BPAY {biller} CRN {crn}"
  direct_debit: "DD {merchant} {ref} MHF {mhf}"
  transfer: "Transfer To {name} NetBank"
  salary: "Salary PAYROLL {ref}"
  atm_withdrawal: "ATM WITHDRAWAL {location}"

real_name_blocklist_extra:
  [Aldi, IGA, Telstra, Optus, "Origin Energy", AGL, Qantas, "Bank of Queensland",
   Suncorp, ING, "Bendigo Bank", "Australia Post", Medicare, "McDonald's", KFC, Subway]

# Existing real businesses — never emitted; content_engine.py reads only the
# `name` field from each to build the real-name blocklist.
retailers:
  - {name: Bunnings Warehouse, address: "123 Main St, Alexandria NSW 2015", abn: "18 634 229 001", category: hardware}
  - {name: Woolworths, address: "100 George St, Sydney NSW 2000", abn: "88 000 014 675", category: grocery}
  - {name: Coles, address: "800 Toorak Rd, Hawthorn East VIC 3123", abn: "11 004 089 936", category: grocery}
  - {name: Officeworks, address: "245 Bourke St, Melbourne VIC 3000", abn: "36 004 763 526", category: office}
  - {name: JB Hi-Fi, address: "2 Parliament Sq, Melbourne VIC 3002", abn: "80 093 220 649", category: electronics}
  - {name: Harvey Norman, address: "A1 Richmond Rd, Homebush West NSW 2140", abn: "85 003 237 545", category: electronics}
  - {name: Kmart Australia, address: "690 Springvale Rd, Mulgrave VIC 3170", abn: "73 004 129 956", category: retail}
  - {name: Big W, address: "1 Woolworths Way, Bella Vista NSW 2153", abn: "88 000 014 675", category: retail}
  - {name: Chemist Warehouse, address: "250 Bourke St, Melbourne VIC 3000", abn: "42 618 648 185", category: pharmacy}
  - {name: "Dan Murphy's", address: "47-61 Egan St, Richmond VIC 3121", abn: "37 006 275 906", category: liquor}
  - {name: BP Australia, address: "717 Bourke St, Docklands VIC 3008", abn: "27 008 560 007", category: fuel}
  - {name: Shell Australia, address: "8 Redfern Rd, Hawthorn East VIC 3123", abn: "46 004 610 459", category: fuel}
  - {name: Ampol Limited, address: "29-33 Bourke Rd, Alexandria NSW 2015", abn: "40 004 201 307", category: fuel}
  - {name: 7-Eleven Australia, address: "357 Ferntree Gully Rd, Mount Waverley VIC 3149", abn: "65 005 825 412", category: fuel}
  - {name: Myer, address: "295 Lonsdale St, Melbourne VIC 3000", abn: "83 004 153 263", category: retail}
  - {name: David Jones, address: "310 Bourke St, Melbourne VIC 3000", abn: "96 000 324 945", category: retail}
  - {name: Target Australia, address: "12-14 Polo Ave, Mona Vale NSW 2103", abn: "75 004 250 944", category: retail}
  - {name: Spotlight, address: "91 Dunning Ave, Rosebery NSW 2018", abn: "17 007 092 579", category: retail}
  - {name: Supercheap Auto, address: "751-753 Springvale Rd, Mulgrave VIC 3170", abn: "61 004 806 598", category: automotive}
  - {name: Repco, address: "53-57 Lonsdale St, Melbourne VIC 3000", abn: "25 004 825 802", category: automotive}

professional_services:
  - {name: "Smith & Associates Accounting", address: "Level 12, 100 Collins St, Melbourne VIC 3000", category: accounting}
  - {name: "Johnson Legal", address: "Suite 5, 200 George St, Sydney NSW 2000", category: legal}
  - {name: "Brisbane IT Solutions", address: "42 Creek St, Brisbane QLD 4000", category: it_services}
  - {name: "Adelaide Business Consulting", address: "Level 3, 77 King William St, Adelaide SA 5000", category: consulting}
  - {name: "Perth Marketing Group", address: "Level 8, 140 St Georges Tce, Perth WA 6000", category: marketing}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_data_pools_core.py tests/test_content_engine.py -v`
Expected: `10 passed` (4 from Task 1 + 6 new)

- [ ] **Step 5: Quality gate + commit**

```bash
conda run -n synthetic pytest tests/
git add config/data_pools.yml tests/test_data_pools_core.py
git commit -m "✨ feat: migrate core content pools into data_pools.yml"
```

### Task 3: `content_engine.sample()` + `NonRepeatingSampler`

Moved ahead of `person`/`address`/`fictional_business`/`fictional_trust` — see "Deviation from the task hint" above; those primitives all call `sample()` internally.

**Files:**
- Modify: `generators/content_engine.py` (append after `load_pools()`)
- Modify: `tests/test_content_engine.py` (append)

**Interfaces:**
- Consumes: nothing beyond the stdlib `random` module.
- Produces: `sample(rng: random.Random, pool: list)` — raises `ValueError` on an empty pool. `NonRepeatingSampler(rng: random.Random, pool: list)` with `.draw()` — raises `ValueError` on an empty pool at construction. Both used by Task 4's `ContentEngine.location`/`address`, Task 5's `fictional_business`, Task 6's `fictional_trust`, and Tasks 7/9's seed scripts.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_engine.py`:

```python
import random

from generators.content_engine import NonRepeatingSampler, sample


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
```

Add `import pytest` to the top of `tests/test_content_engine.py` alongside the existing imports (it is not yet imported there — Task 1's tests only used `pytest.raises` inside functions that already had it via the module-level `import pytest` from Task 1's own test file; confirm the import exists once, not duplicated).

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v -k "sample or NonRepeating"`
Expected: FAIL — `ImportError: cannot import name 'sample' from 'generators.content_engine'`

- [ ] **Step 3: Implement `sample()` and `NonRepeatingSampler`**

Edit `generators/content_engine.py`: change the top import block

```python
from pathlib import Path

import yaml
```

to

```python
import random
from pathlib import Path

import yaml
```

Then append at the end of the file:

```python
def sample(rng: random.Random, pool: list):
    """Seeded single draw from a non-empty pool."""
    if not pool:
        raise ValueError(
            "content_engine.sample: pool is empty; cannot draw.\n"
            "  What:     sample() was called with an empty pool.\n"
            "  Where:    caller of generators.content_engine.sample.\n"
            "  Expected: a non-empty list.\n"
            "  Recover:  widen the source pool in config/data_pools.yml before sampling from it."
        )
    return rng.choice(pool)


class NonRepeatingSampler:
    """Cycles a shuffled copy of `pool`, reshuffling on exhaustion.

    Replaces `pool[i % len(pool)]`: draws are a random permutation of the
    pool each pass (not the same fixed order every cycle), so entity
    selection varies and de-correlates across doc types even when two
    samplers share the same underlying pool.
    """

    def __init__(self, rng: random.Random, pool: list) -> None:
        if not pool:
            raise ValueError(
                "content_engine.NonRepeatingSampler: pool is empty; cannot draw.\n"
                "  What:     NonRepeatingSampler was constructed with an empty pool.\n"
                "  Where:    caller of generators.content_engine.NonRepeatingSampler.\n"
                "  Expected: a non-empty list.\n"
                "  Recover:  widen the source pool in config/data_pools.yml before sampling from it."
            )
        self._rng = rng
        self._pool = list(pool)
        self._order: list = []
        self._i = 0

    def draw(self):
        """Return the next item; reshuffles a fresh permutation on exhaustion."""
        if self._i >= len(self._order):
            self._order = list(self._pool)
            self._rng.shuffle(self._order)
            self._i = 0
        item = self._order[self._i]
        self._i += 1
        return item
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v`
Expected: `17 passed` (10 from Tasks 1–2 + 7 new)

- [ ] **Step 5: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py
conda run -n synthetic ruff format generators/content_engine.py
conda run -n synthetic mypy generators/content_engine.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add generators/content_engine.py tests/test_content_engine.py
git commit -m "✨ feat: add content_engine sample() and NonRepeatingSampler"
```

### Task 4: `ContentEngine` with `person(rng)` / `location(rng)` / `address(rng)`

**Files:**
- Modify: `generators/content_engine.py` (append)
- Modify: `tests/test_content_engine.py` (append)

**Interfaces:**
- Consumes: `sample()` (Task 3); `Faker("en_AU")` from the `faker` package (already pinned).
- Produces: `class ContentEngine.__init__(self, pools: dict)` — builds `self.pools` (public), `self._faker`, `self._blocklist: set[str]` (lower-cased names from `retailers`, `professional_services`, `real_name_blocklist_extra`). `ContentEngine.person(rng) -> dict` (`{first_name, last_name, full_name}`). `ContentEngine.location(rng) -> dict` (`{suburb, postcode, state}`). `ContentEngine.address(rng) -> str` (`"N Street St, Suburb ST PPPP"`). `build_engine(path: Path = _DATA_POOLS_PATH) -> ContentEngine`. Tasks 5–9 all consume `ContentEngine` and `build_engine`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_engine.py`:

```python
import re

from generators.content_engine import build_engine


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v -k "person or location or address"`
Expected: FAIL — `ImportError: cannot import name 'build_engine' from 'generators.content_engine'`

- [ ] **Step 3: Implement `ContentEngine` and `build_engine()`**

Edit `generators/content_engine.py`: change the import block

```python
import random
from pathlib import Path

import yaml
```

to

```python
import random
from pathlib import Path

import yaml
from faker import Faker
```

Then append the `ContentEngine` class and `build_engine()` after `load_pools()` (keep the file order `load_pools` → `ContentEngine` → `sample`/`NonRepeatingSampler` → `build_engine` for a clean read; Python resolves `sample` at call time, so the forward reference from `location()`/`address()` is fine):

```python
class ContentEngine:
    """Seeded generator for fictional AU business/trust/person/address content."""

    def __init__(self, pools: dict) -> None:
        self.pools = pools
        self._faker = Faker(pools["faker_config"]["locale"])
        # Defined baseline state before any per-call reseed in _seed_faker();
        # keeps a freshly-constructed engine deterministic even if a caller
        # (e.g. a future primitive) drew from self._faker before seeding rng.
        self._faker.seed_instance(pools["faker_config"]["seed_base"])
        self._blocklist = {
            name.lower()
            for name in (
                [r["name"] for r in pools["retailers"]]
                + [p["name"] for p in pools["professional_services"]]
                + pools["real_name_blocklist_extra"]
            )
        }

    def _seed_faker(self, rng: random.Random) -> None:
        """Reseed the engine's Faker instance from the injected rng stream."""
        self._faker.seed_instance(rng.randint(0, 2**32 - 1))

    def person(self, rng: random.Random) -> dict:
        """Return a seeded en_AU person: {first_name, last_name, full_name}."""
        self._seed_faker(rng)
        first = self._faker.first_name()
        last = self._faker.last_name()
        return {"first_name": first, "last_name": last, "full_name": f"{first} {last}"}

    def location(self, rng: random.Random) -> dict:
        """Return a seeded {suburb, postcode, state} dict from the locations pool."""
        return sample(rng, self.pools["locations"])

    def address(self, rng: random.Random) -> str:
        """Return a seeded AU-style address: "N Street St, Suburb ST PPPP"."""
        self._seed_faker(rng)
        street_num = self._faker.random_int(min=1, max=400)
        street_name = self._faker.last_name()
        street_type = sample(rng, self.pools["street_types"])
        loc = self.location(rng)
        return f"{street_num} {street_name} {street_type}, {loc['suburb']} {loc['state']} {loc['postcode']}"


def build_engine(path: Path = _DATA_POOLS_PATH) -> "ContentEngine":
    """Load pools from `path` and construct a ContentEngine."""
    return ContentEngine(load_pools(path))
```

Note: `location()`/`address()` call the module-level `sample()` added in Task 3; Python resolves it at call time, so the forward reference is fine. Target file order: `load_pools` → `ContentEngine` → `sample`/`NonRepeatingSampler` → `build_engine`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v`
Expected: `22 passed` (17 from Tasks 1–3 + 5 new)

- [ ] **Step 5: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py
conda run -n synthetic ruff format generators/content_engine.py
conda run -n synthetic mypy generators/content_engine.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add generators/content_engine.py tests/test_content_engine.py
git commit -m "✨ feat: add ContentEngine person/location/address primitives"
```

### Task 5: `ContentEngine.fictional_business(rng, category)`

**Files:**
- Modify: `generators/content_engine.py` (append)
- Modify: `tests/test_content_engine.py` (append)

**Interfaces:**
- Consumes: `sample()` (Task 3); `self.address()` (Task 4); `generate_abn()` from `generators/common.py`.
- Produces: `ContentEngine.fictional_business(rng: random.Random, category: str) -> dict` (`{name, address, abn, category}`) — raises `ValueError` (four-element diagnostic) for an unknown category, `RuntimeError` (four-element diagnostic) after 20 blocklist-collision retries. Consumed by Task 7's `seed_ground_truth.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_engine.py`:

```python
import copy

from generators.common import validate_abn
from generators.content_engine import ContentEngine, load_pools


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v -k fictional_business`
Expected: FAIL — `AttributeError: 'ContentEngine' object has no attribute 'fictional_business'`

- [ ] **Step 3: Implement `fictional_business()`**

Edit `generators/content_engine.py`: add `generate_abn` to the imports — change the module's import block from:

```python
import random
from pathlib import Path

import yaml
from faker import Faker
```

to:

```python
import random
from pathlib import Path

import yaml
from faker import Faker

from generators.common import generate_abn
```

Then add a new method to `ContentEngine`, directly after `address()`:

```python
    def fictional_business(self, rng: random.Random, category: str) -> dict:
        """Invented AU business (blocklist-screened) + generate_abn() + address.

        Returns:
            {name, address, abn, category}.

        Raises:
            ValueError: `category` has no entry in business_name_parts.category_nouns.
            RuntimeError: the retry budget was exhausted without a clean name.
        """
        parts = self.pools["business_name_parts"]
        nouns = parts["category_nouns"].get(category)
        if not nouns:
            raise ValueError(
                "content_engine.fictional_business: unknown category.\n"
                f"  What:     category {category!r} has no entry under "
                "'business_name_parts.category_nouns'.\n"
                f"  Where:    {_DATA_POOLS_PATH} -> "
                f"'business_name_parts.category_nouns.{category}'.\n"
                "  Expected: a list of nouns, e.g. "
                '\'hardware: ["Hardware", "Trade Supplies"]\'.\n'
                f"  Recover:  add a '{category}:' entry under "
                f"'business_name_parts.category_nouns' in {_DATA_POOLS_PATH}."
            )
        max_attempts = 20
        for _ in range(max_attempts):
            noun = sample(rng, nouns)
            if rng.random() < 0.5:
                name = f"{sample(rng, parts['surnames'])} {noun}"
            else:
                name = f"{sample(rng, parts['suburb_prefixes'])} {noun}"
            if name.lower() not in self._blocklist:
                return {
                    "name": name,
                    "address": self.address(rng),
                    "abn": generate_abn(),
                    "category": category,
                }
        raise RuntimeError(
            "content_engine.fictional_business: exhausted retry budget without a clean name.\n"
            f"  What:     {max_attempts} draws for category {category!r} all collided with "
            "the real-name blocklist.\n"
            f"  Where:    {_DATA_POOLS_PATH} -> 'business_name_parts' (category {category!r}) "
            "and 'real_name_blocklist_extra'.\n"
            "  Expected: enough surname/noun combinations for the category to clear the "
            f"blocklist within {max_attempts} attempts.\n"
            "  Recover:  widen 'business_name_parts.surnames', 'suburb_prefixes', or "
            f"'category_nouns.{category}' in {_DATA_POOLS_PATH}."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v`
Expected: `26 passed` (22 from Tasks 1–4 + 4 new)

- [ ] **Step 5: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py
conda run -n synthetic ruff format generators/content_engine.py
conda run -n synthetic mypy generators/content_engine.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add generators/content_engine.py tests/test_content_engine.py
git commit -m "✨ feat: add ContentEngine.fictional_business with blocklist screen"
```

### Task 6: `ContentEngine.fictional_trust(rng)`

**Files:**
- Modify: `generators/content_engine.py` (append)
- Modify: `tests/test_content_engine.py` (append)

**Interfaces:**
- Consumes: `sample()` (Task 3); `generate_abn()`, `generate_tfn()` from `generators/common.py`.
- Produces: `ContentEngine.fictional_trust(rng: random.Random) -> dict` (`{trust_name, trustee_name, abn, tfn}`) — raises `RuntimeError` (four-element diagnostic) after 20 blocklist-collision retries. Consumed by Task 9's `seed_trust_distributions.py`. Reads `self.pools["trust_name_parts"]`, added to the real YAML in Task 8 and to `_REQUIRED_KEYS` in Task 8 as well (this task's own tests construct a local `pools` dict with `trust_name_parts` present, so it does not depend on Task 8 landing first).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_engine.py`:

```python
from generators.common import validate_tfn

_TRUST_NAME_PARTS = {
    "surnames": ["Whitfield", "Hollingsworth", "Faircloth", "Ashworth", "Broadbent"],
    "trust_kinds": ["Family Trust", "Discretionary Trust", "Investment Trust"],
    "trustee_suffixes": ["Holdings", "Capital", "Group"],
}


def _engine_with_trust_parts() -> ContentEngine:
    pools = copy.deepcopy(load_pools())
    pools["trust_name_parts"] = copy.deepcopy(_TRUST_NAME_PARTS)
    return ContentEngine(pools)


def test_fictional_trust_never_emits_a_blocklisted_name():
    engine = _engine_with_trust_parts()
    rng = random.Random(13)
    blocked = {r["name"].lower() for r in engine.pools["retailers"]}
    blocked |= {p["name"].lower() for p in engine.pools["professional_services"]}
    blocked |= {n.lower() for n in engine.pools["real_name_blocklist_extra"]}
    for _ in range(300):
        trust = engine.fictional_trust(rng)
        assert trust["trust_name"].lower() not in blocked


def test_fictional_trust_returns_valid_abn_and_tfn():
    engine = _engine_with_trust_parts()
    trust = engine.fictional_trust(random.Random(6))
    assert validate_abn(trust["abn"])
    assert validate_tfn(trust["tfn"])


def test_fictional_trust_trustee_name_embeds_trust_name_and_atf():
    engine = _engine_with_trust_parts()
    trust = engine.fictional_trust(random.Random(8))
    assert trust["trust_name"] in trust["trustee_name"]
    assert "ATF" in trust["trustee_name"]


def test_fictional_trust_exhausted_retries_fails_fast():
    engine = _engine_with_trust_parts()
    engine.pools["trust_name_parts"] = {
        "surnames": ["Whitfield"],
        "trust_kinds": ["Family Trust"],
        "trustee_suffixes": ["Holdings"],
    }
    engine._blocklist = {"whitfield family trust"}
    with pytest.raises(RuntimeError) as exc_info:
        engine.fictional_trust(random.Random(10))
    assert_diagnostic_error(str(exc_info.value))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v -k fictional_trust`
Expected: FAIL — `AttributeError: 'ContentEngine' object has no attribute 'fictional_trust'`

- [ ] **Step 3: Implement `fictional_trust()`**

Edit `generators/content_engine.py`: change

```python
from generators.common import generate_abn
```

to

```python
from generators.common import generate_abn, generate_tfn
```

Then add a new method to `ContentEngine`, directly after `fictional_business()`:

```python
    def fictional_trust(self, rng: random.Random) -> dict:
        """Invented trust + trustee (blocklist-screened) + ABN + TFN.

        Returns:
            {trust_name, trustee_name, abn, tfn}.

        Raises:
            RuntimeError: the retry budget was exhausted without a clean name.
        """
        parts = self.pools["trust_name_parts"]
        max_attempts = 20
        for _ in range(max_attempts):
            surname = sample(rng, parts["surnames"])
            kind = sample(rng, parts["trust_kinds"])
            trust_name = f"{surname} {kind}"
            if trust_name.lower() not in self._blocklist:
                trustee_name = (
                    f"{surname} {sample(rng, parts['trustee_suffixes'])} Pty Ltd ATF {trust_name}"
                )
                return {
                    "trust_name": trust_name,
                    "trustee_name": trustee_name,
                    "abn": generate_abn(),
                    "tfn": generate_tfn(),
                }
        raise RuntimeError(
            "content_engine.fictional_trust: exhausted retry budget without a clean name.\n"
            f"  What:     {max_attempts} draws all collided with the real-name blocklist.\n"
            f"  Where:    {_DATA_POOLS_PATH} -> 'trust_name_parts.surnames' / 'trust_kinds'.\n"
            "  Expected: enough surname/trust_kind combinations to clear the blocklist "
            f"within {max_attempts} attempts.\n"
            f"  Recover:  widen 'trust_name_parts.surnames' or 'trust_kinds' in {_DATA_POOLS_PATH}."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v`
Expected: `30 passed` (26 from Tasks 1–5 + 4 new)

- [ ] **Step 5: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py
conda run -n synthetic ruff format generators/content_engine.py
conda run -n synthetic mypy generators/content_engine.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add generators/content_engine.py tests/test_content_engine.py
git commit -m "✨ feat: add ContentEngine.fictional_trust with blocklist screen"
```

### Task 7: Rewire `scripts/seed_ground_truth.py` to the engine, kill modulo, add `--dry-run`

**Files:**
- Modify: `scripts/seed_ground_truth.py:1-595` (full rewrite)
- Test: `tests/test_seed_ground_truth_dry_run.py`

**Interfaces:**
- Consumes: `generators.content_engine.{ContentEngine, NonRepeatingSampler, build_engine, sample}` (Tasks 3–6); `generators.loader.load_layout_registry`; `generators.overflow_check.check_overflow`; `generators.schema.validate_entry`; the four core renderers.
- Produces: `_generate_case_entities(engine, rng, count) -> list[dict]` (each `{holder, location}`) — Task 9 does not consume this (trust script has its own entity bundle), but Stage 1B-ii's invariant checks (Task 10a) rely on `PAYER_NAME` being identical across a case's bank/cc/invoice entries, which this function makes possible. `_generate_bank_entries(engine, rng, case_entities, count) -> dict`, `_generate_receipt_entries(engine, rng, case_entities, count) -> dict`, `_generate_invoice_entries(engine, rng, case_entities, count) -> dict`, `_generate_cc_entries(engine, rng, case_entities, count) -> dict` — same signature shape across all four (receipts ignores `case_entities`, ruff's `ARG001` is already ignored project-wide). `main(dry_run: bool = False) -> None`.

Every test in this task imports the script as a module via `importlib`, since `scripts/` is not a package:

```python
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
seed_ground_truth = importlib.import_module("seed_ground_truth")
```

- [ ] **Step 1: Write the failing test for the shared per-case entity bundle**

Create `tests/test_seed_ground_truth_dry_run.py`:

```python
"""Tests for the rewired scripts/seed_ground_truth.py (local-only; tests/ is gitignored)."""

import importlib
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
seed_ground_truth = importlib.import_module("seed_ground_truth")


def test_generate_case_entities_produces_one_bundle_per_case():
    engine = seed_ground_truth.build_engine()
    rng = random.Random(1)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 5)
    assert len(entities) == 5
    assert all("holder" in e and "location" in e for e in entities)
    assert all(e["holder"]["full_name"] for e in entities)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v`
Expected: FAIL — `AttributeError: module 'seed_ground_truth' has no attribute '_generate_case_entities'`

- [ ] **Step 3: Rewrite the file header, helpers, and `_generate_case_entities`**

Replace the top of `scripts/seed_ground_truth.py` (through the end of the old `_generate_bank_entries`, i.e. lines 1–324 of the original) with:

```python
"""Ground truth seed generator for synthetic Australian business documents.

Generates 55 YAML entries per document type (bank statements, receipts, invoices,
CC statements) using deterministic seed=42, writing to ground_truth/*.yml.

Each case's shared entities (account holder, home location) are generated once
via content_engine and projected across that case's bank/cc/invoice entries, so
widened content never desyncs a PAYER_NAME across a case's linked documents.
"""

import random

# Ensure we can import from project root
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import typer
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from generators.content_engine import (  # noqa: E402
    ContentEngine,
    NonRepeatingSampler,
    build_engine,
    sample,
)
from generators.loader import load_layout_registry  # noqa: E402
from generators.overflow_check import check_overflow  # noqa: E402
from generators.schema import validate_entry  # noqa: E402

_SEED = 42
_COUNT = 55
_GT_DIR = Path(__file__).parent.parent / "ground_truth"

# ── layout IDs per document type (structural, not content — unchanged) ─────
_BANK_LAYOUTS = [
    "cba_standard",
    "cba_date_grouped",
    "westpac_standard",
    "westpac_premium",
    "nab_classic",
    "nab_dense",
    "anz_standard",
    "anz_modern",
]

_RECEIPT_LAYOUTS = [
    "receipt_thermal_80mm",
    "receipt_thermal_57mm",
    "receipt_retail_tax",
    "receipt_fuel",
    "receipt_professional",
    "receipt_hospitality",
]

_INVOICE_LAYOUTS = [
    "tax_invoice_standard",
    "tax_invoice_gst_inclusive",
    "tax_invoice_high_value",
    "tax_invoice_mixed",
]

_CC_LAYOUTS = [
    "cba_cc_standard",
    "cba_cc_rewards",
    "westpac_cc_standard",
    "westpac_cc_altitude",
    "nab_cc_standard",
    "nab_cc_low_rate",
    "anz_cc_standard",
    "anz_cc_platinum",
]

# ── business categories the engine draws fictional_business() names from ───
_RECEIPT_CATEGORIES = [
    "hardware", "grocery", "office", "electronics", "retail",
    "pharmacy", "liquor", "fuel", "automotive",
]
_SERVICE_CATEGORIES = ["accounting", "legal", "it_services", "consulting", "marketing"]
_ALL_CATEGORIES = _RECEIPT_CATEGORIES + _SERVICE_CATEGORIES


def _fmt_date(day: int, month: int, year: int) -> str:
    """Format date as DD/MM/YYYY."""
    return f"{day:02d}/{month:02d}/{year}"


def _rand_date(rng: random.Random, year_start: int = 2023, year_end: int = 2024) -> tuple[int, int, int]:
    """Generate a random date tuple (day, month, year)."""
    year = rng.randint(year_start, year_end)
    month = rng.randint(1, 12)
    max_day = 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31
    day = rng.randint(1, max_day)
    return day, month, year


def _rand_amount(rng: random.Random, lo: float, hi: float) -> Decimal:
    """Generate a random Decimal amount in [lo, hi] rounded to 2dp."""
    raw = rng.uniform(lo, hi)
    return Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt_decimal(d: Decimal) -> str:
    """Format Decimal as plain string with 2dp (no $ sign)."""
    return f"{d:.2f}"


def _generate_case_entities(engine: ContentEngine, rng: random.Random, count: int) -> list[dict]:
    """Generate each case's shared entities once, projected across bank/cc/invoice.

    Receipts have no payer/holder field, so they draw their own supplier
    independently and do not consume this bundle.
    """
    return [{"holder": engine.person(rng), "location": engine.location(rng)} for _ in range(count)]


def _draw_bank_description(engine: ContentEngine, rng: random.Random, *, suburb: str, holder_first: str) -> str:
    """Fill a seeded bank_descriptions grammar template with a fictional merchant.

    The merchant portion is upper-cased to match real AU bank-statement
    styling and to keep `_extract_suburb()` in scripts/seed_transaction_links.py
    (which distinguishes an ALL-CAPS merchant token from a Title-Case suburb)
    parsing EFTPOS descriptions correctly.
    """
    templates = engine.pools["bank_descriptions"]
    template_key = sample(rng, list(templates.keys()))
    template = templates[template_key]
    merchant = engine.fictional_business(rng, sample(rng, _ALL_CATEGORIES))["name"][:12].upper()
    return template.format(
        merchant=merchant,
        location=suburb,
        last4=f"{rng.randint(1000, 9999)}",
        biller=merchant,
        crn=rng.randint(100000000, 999999999),
        ref=f"REF{rng.randint(10000, 99999)}",
        mhf=rng.randint(1000, 9999),
        name=holder_first,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v`
Expected: `1 passed`

- [ ] **Step 5: Write the failing test for shared holder across bank and CC**

Append to `tests/test_seed_ground_truth_dry_run.py`:

```python
def test_bank_and_cc_share_holder_for_the_same_case():
    engine = seed_ground_truth.build_engine()
    rng = random.Random(seed_ground_truth._SEED)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 3)
    bank = seed_ground_truth._generate_bank_entries(engine, rng, entities, 3)
    cc = seed_ground_truth._generate_cc_entries(engine, rng, entities, 3)
    assert bank["CASE001"]["fields"]["PAYER_NAME"] == cc["CASE001"]["fields"]["PAYER_NAME"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v -k shared_holder`
Expected: FAIL — `AttributeError: module 'seed_ground_truth' has no attribute '_generate_bank_entries'`

- [ ] **Step 7: Implement `_generate_bank_entries` and `_generate_cc_entries`**

Append to `scripts/seed_ground_truth.py`:

```python
def _generate_bank_entries(engine: ContentEngine, rng: random.Random, case_entities: list[dict], count: int) -> dict:
    """Generate bank statement ground truth entries (25-40 txns each)."""
    entries: dict = {}
    layout_draw = NonRepeatingSampler(rng, _BANK_LAYOUTS)
    bank_draw = NonRepeatingSampler(rng, engine.pools["banks"])

    for i in range(count):
        case_id = f"CASE{i + 1:03d}"
        layout = layout_draw.draw()

        bank = bank_draw.draw()
        holder = case_entities[i]["holder"]
        suburb = case_entities[i]["location"]["suburb"]

        _d, m, y = _rand_date(rng)
        period_start = _fmt_date(1, m, y)
        max_day = 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31
        period_end = _fmt_date(max_day, m, y)
        statement_range = f"{period_start} - {period_end}"

        n_txns = rng.randint(25, 40)
        txn_days = sorted(rng.randint(1, max_day) for _ in range(n_txns))

        txn_dates, txn_descs, txn_debits, txn_credits = [], [], [], []
        closing_balance = _rand_amount(rng, 500, 15000)

        for txn_day in txn_days:
            txn_dates.append(_fmt_date(txn_day, m, y))
            is_debit = rng.random() < 0.80
            desc = _draw_bank_description(engine, rng, suburb=suburb, holder_first=holder["first_name"])
            txn_descs.append(desc)
            if is_debit:
                amt = _rand_amount(rng, 10, 600)
                txn_debits.append(_fmt_decimal(amt))
                txn_credits.append("NOT_FOUND")
            else:
                amt = _rand_amount(rng, 100, 5000)
                txn_debits.append("NOT_FOUND")
                txn_credits.append(_fmt_decimal(amt))

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "BANK_STATEMENT",
                "SUPPLIER_NAME": bank["name"],
                "STATEMENT_DATE_RANGE": statement_range,
                "TRANSACTION_DATES": "|".join(txn_dates),
                "TRANSACTION_DESCRIPTIONS": "|".join(txn_descs),
                "TRANSACTION_AMOUNTS_PAID": "|".join(txn_debits),
                "TRANSACTION_AMOUNTS_RECEIVED": "|".join(txn_credits),
                "ACCOUNT_BALANCE": _fmt_decimal(closing_balance),
                "PAYER_NAME": holder["full_name"],
            },
        }

    return entries


def _generate_cc_entries(engine: ContentEngine, rng: random.Random, case_entities: list[dict], count: int) -> dict:
    """Generate credit card statement ground truth entries."""
    entries: dict = {}
    layout_draw = NonRepeatingSampler(rng, _CC_LAYOUTS)
    bank_draw = NonRepeatingSampler(rng, engine.pools["banks"])

    for i in range(count):
        case_id = f"CASE{i + 1:03d}"
        layout = layout_draw.draw()

        bank = bank_draw.draw()
        holder = case_entities[i]["holder"]
        suburb = case_entities[i]["location"]["suburb"]

        d, m, y = _rand_date(rng)
        period_start = _fmt_date(1, m, y)
        max_day = 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31
        period_end = _fmt_date(max_day, m, y)
        statement_range = f"{period_start} - {period_end}"

        due_d = min(max_day + 21, 28)
        due_m = m + 1 if due_d <= max_day else m
        if due_m > 12:
            due_m = 1
            due_y = y + 1
        else:
            due_y = y
        payment_due_date = _fmt_date(due_d, due_m, due_y)

        credit_limit = _rand_amount(rng, 2000, 20000)
        credit_limit = Decimal(str(round(float(credit_limit) / 500) * 500))

        n_txns = rng.randint(5, 12)
        txn_dates, txn_descs, txn_amounts = [], [], []
        total_charges = Decimal("0")

        for _j in range(n_txns):
            txn_day = rng.randint(1, max_day)
            txn_dates.append(_fmt_date(txn_day, m, y))
            desc = _draw_bank_description(engine, rng, suburb=suburb, holder_first=holder["first_name"])
            txn_descs.append(desc)
            amt = _rand_amount(rng, 10, 800)
            txn_amounts.append(_fmt_decimal(amt))
            total_charges += amt

        closing_balance = total_charges
        min_payment_pct = (closing_balance * Decimal("0.02")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        minimum_payment = max(Decimal("25.00"), min_payment_pct)

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "CC_STATEMENT",
                "SUPPLIER_NAME": bank["name"],
                "STATEMENT_DATE_RANGE": statement_range,
                "TRANSACTION_DATES": "|".join(txn_dates),
                "TRANSACTION_DESCRIPTIONS": "|".join(txn_descs),
                "TRANSACTION_AMOUNTS_PAID": "|".join(txn_amounts),
                "ACCOUNT_BALANCE": _fmt_decimal(closing_balance),
                "CREDIT_LIMIT": _fmt_decimal(credit_limit),
                "MINIMUM_PAYMENT": _fmt_decimal(minimum_payment),
                "PAYMENT_DUE_DATE": payment_due_date,
                "PAYER_NAME": holder["full_name"],
            },
        }

    return entries
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v`
Expected: `2 passed`

- [ ] **Step 9: Write the failing test for fictional receipt suppliers**

Append to `tests/test_seed_ground_truth_dry_run.py`:

```python
def test_receipt_supplier_never_matches_a_real_retailer():
    engine = seed_ground_truth.build_engine()
    rng = random.Random(seed_ground_truth._SEED)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 55)
    receipts = seed_ground_truth._generate_receipt_entries(engine, rng, entities, 55)
    real_names = {r["name"] for r in engine.pools["retailers"]}
    assert len(receipts) == 55
    for entry in receipts.values():
        assert entry["fields"]["SUPPLIER_NAME"] not in real_names
```

- [ ] **Step 10: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v -k receipt_supplier`
Expected: FAIL — `AttributeError: module 'seed_ground_truth' has no attribute '_generate_receipt_entries'`

- [ ] **Step 11: Implement `_generate_receipt_entries`**

Append to `scripts/seed_ground_truth.py`:

```python
def _generate_receipt_entries(engine: ContentEngine, rng: random.Random, case_entities: list[dict], count: int) -> dict:
    """Generate receipt ground truth entries with GST-inclusive pricing."""
    entries: dict = {}
    layout_draw = NonRepeatingSampler(rng, _RECEIPT_LAYOUTS)
    item_pool = engine.pools["product_catalog"]

    for i in range(count):
        case_id = f"CASE{i + 1:03d}"
        layout = layout_draw.draw()

        category = sample(rng, _RECEIPT_CATEGORIES)
        retailer = engine.fictional_business(rng, category)

        d, m, y = _rand_date(rng)
        invoice_date = _fmt_date(d, m, y)

        n_items = rng.randint(1, 6)
        items = rng.sample(item_pool, min(n_items, len(item_pool)))

        item_descs, item_qtys, item_prices, item_totals = [], [], [], []
        gst_inclusive_total = Decimal("0")

        for item in items:
            qty = rng.randint(1, 3)
            unit_price = _rand_amount(rng, item["price_low"], item["price_high"])
            line_total = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            item_descs.append(item["description"])
            item_qtys.append(str(qty))
            item_prices.append(_fmt_decimal(unit_price))
            item_totals.append(_fmt_decimal(line_total))
            gst_inclusive_total += line_total

        gst_amount = (gst_inclusive_total / Decimal("11")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "RECEIPT",
                "SUPPLIER_NAME": retailer["name"],
                "BUSINESS_ABN": retailer["abn"],
                "BUSINESS_ADDRESS": retailer["address"],
                "INVOICE_DATE": invoice_date,
                "IS_GST_INCLUDED": "true",
                "GST_AMOUNT": _fmt_decimal(gst_amount),
                "TOTAL_AMOUNT": _fmt_decimal(gst_inclusive_total),
                "LINE_ITEM_DESCRIPTIONS": "|".join(item_descs),
                "LINE_ITEM_QUANTITIES": "|".join(item_qtys),
                "LINE_ITEM_PRICES": "|".join(item_prices),
                "LINE_ITEM_TOTAL_PRICES": "|".join(item_totals),
            },
        }

    return entries
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v`
Expected: `3 passed`

- [ ] **Step 13: Write the failing test for invoice payer/provider**

Append to `tests/test_seed_ground_truth_dry_run.py`:

```python
def test_invoice_provider_never_matches_a_real_service_and_has_payer_address():
    engine = seed_ground_truth.build_engine()
    rng = random.Random(seed_ground_truth._SEED)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 55)
    invoices = seed_ground_truth._generate_invoice_entries(engine, rng, entities, 55)
    real_names = {p["name"] for p in engine.pools["professional_services"]}
    assert len(invoices) == 55
    for entry in invoices.values():
        fields = entry["fields"]
        assert fields["SUPPLIER_NAME"] not in real_names
        assert fields["PAYER_NAME"]
        assert "," in fields["PAYER_ADDRESS"]
```

- [ ] **Step 14: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v -k invoice_provider`
Expected: FAIL — `AttributeError: module 'seed_ground_truth' has no attribute '_generate_invoice_entries'`

- [ ] **Step 15: Implement `_generate_invoice_entries`**

Append to `scripts/seed_ground_truth.py`:

```python
def _generate_invoice_entries(engine: ContentEngine, rng: random.Random, case_entities: list[dict], count: int) -> dict:
    """Generate invoice ground truth entries with GST-exclusive pricing."""
    entries: dict = {}
    layout_draw = NonRepeatingSampler(rng, _INVOICE_LAYOUTS)
    svc_pool = engine.pools["service_catalog"]

    for i in range(count):
        case_id = f"CASE{i + 1:03d}"
        layout = layout_draw.draw()

        category = sample(rng, _SERVICE_CATEGORIES)
        provider = engine.fictional_business(rng, category)

        d, m, y = _rand_date(rng)
        invoice_date = _fmt_date(d, m, y)
        due_day = min(d + 30, 28)
        due_m = m + 1 if due_day < d else m
        due_y = y + 1 if due_m > 12 else y
        due_m = due_m % 12 if due_m > 12 else due_m
        if due_m == 0:
            due_m = 12
        payment_due_date = _fmt_date(due_day, due_m, due_y)

        payer = engine.person(rng)
        payer_address = engine.address(rng)

        n_items = rng.randint(1, 4)
        services = rng.sample(svc_pool, min(n_items, len(svc_pool)))

        item_descs, item_qtys, item_prices, item_totals = [], [], [], []
        subtotal_ex_gst = Decimal("0")

        for svc in services:
            qty = rng.randint(1, 8)
            unit_price = _rand_amount(rng, svc["price_low"], svc["price_high"])
            line_total = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            item_descs.append(svc["description"])
            item_qtys.append(str(qty))
            item_prices.append(_fmt_decimal(unit_price))
            item_totals.append(_fmt_decimal(line_total))
            subtotal_ex_gst += line_total

        gst_amount = (subtotal_ex_gst * Decimal("0.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_incl_gst = subtotal_ex_gst + gst_amount

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "INVOICE",
                "SUPPLIER_NAME": provider["name"],
                "BUSINESS_ABN": provider["abn"],
                "BUSINESS_ADDRESS": provider["address"],
                "INVOICE_DATE": invoice_date,
                "IS_GST_INCLUDED": "false",
                "GST_AMOUNT": _fmt_decimal(gst_amount),
                "TOTAL_AMOUNT": _fmt_decimal(total_incl_gst),
                "LINE_ITEM_DESCRIPTIONS": "|".join(item_descs),
                "LINE_ITEM_QUANTITIES": "|".join(item_qtys),
                "LINE_ITEM_PRICES": "|".join(item_prices),
                "LINE_ITEM_TOTAL_PRICES": "|".join(item_totals),
                "PAYER_NAME": payer["full_name"],
                "PAYER_ADDRESS": payer_address,
            },
        }

    return entries
```

Note: `payment_due_date` is computed but not written into `fields` — this matches the *original* script's behavior (it computed the same value and never used it either; `PAYMENT_DUE_DATE` is not in `invoice`'s required field set per `config/field_definitions.yml:30-45`). `F841` (unused variable) is already ignored project-wide, so this is not a lint regression.

- [ ] **Step 16: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v`
Expected: `5 passed`

- [ ] **Step 17: Write the failing test for `main(dry_run=True)`**

Append to `tests/test_seed_ground_truth_dry_run.py`:

```python
def test_dry_run_validates_without_writing_ground_truth(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_ground_truth, "_GT_DIR", tmp_path)
    seed_ground_truth.main(dry_run=True)
    assert not any(tmp_path.iterdir())
```

- [ ] **Step 18: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v -k dry_run`
Expected: FAIL — `TypeError: main() got an unexpected keyword argument 'dry_run'` (the file still has the *original* `main()` with no parameters, appended functions notwithstanding — the old `main()` body at the bottom of the file has not been touched yet)

- [ ] **Step 19: Replace `main()` with the dry-run-aware version**

Replace the original `main()` function and the `if __name__ == "__main__":` block at the bottom of `scripts/seed_ground_truth.py` with:

```python
def _validate_dry_run(all_entries: dict[str, dict]) -> None:
    """Validate generated entries in-memory (schema + overflow) without writing YAML."""
    from generators.bank_statement import render_bank_statement
    from generators.cc_statement import render_cc_statement
    from generators.invoice import render_invoice
    from generators.receipt import render_receipt

    renderer_map = {
        "bank_statements.yml": (render_bank_statement, "config/layouts/bank_statements.yml"),
        "receipts.yml": (render_receipt, "config/layouts/receipts.yml"),
        "invoices.yml": (render_invoice, "config/layouts/invoices.yml"),
        "cc_statements.yml": (render_cc_statement, "config/layouts/cc_statements.yml"),
    }

    errors: list[str] = []
    for filename, entries in all_entries.items():
        renderer, layout_path = renderer_map[filename]
        layouts = load_layout_registry(Path(layout_path))
        for case_id, entry in entries.items():
            errors.extend(validate_entry(str(case_id), entry))
        errors.extend(check_overflow(entries, layouts, renderer))

    if errors:
        listing = "\n    ".join(errors)
        raise RuntimeError(
            "Dry run failed: generated content did not validate.\n"
            f"  What:     {len(errors)} error(s) across generated entries:\n"
            f"    {listing}\n"
            "  Where:    scripts/seed_ground_truth.py generator functions and the "
            "config/data_pools.yml content they draw from.\n"
            "  Expected: every generated entry passes schema validation and renders "
            "within its layout's field_budgets (no FitError).\n"
            "  Recover:  fix the failing generator logic or widen the offending pool/budget, "
            "then rerun `python scripts/seed_ground_truth.py --dry-run`."
        )


def main(dry_run: bool = typer.Option(False, "--dry-run", help="Validate in-memory; do not write ground_truth/*.yml")) -> None:
    """Generate all ground truth YAML files with deterministic seed=42."""
    rng = random.Random(_SEED)
    engine = build_engine()
    case_entities = _generate_case_entities(engine, rng, _COUNT)

    generators = [
        ("bank_statements.yml", _generate_bank_entries),
        ("receipts.yml", _generate_receipt_entries),
        ("invoices.yml", _generate_invoice_entries),
        ("cc_statements.yml", _generate_cc_entries),
    ]

    all_entries: dict[str, dict] = {}
    for filename, gen_fn in generators:
        all_entries[filename] = gen_fn(engine, rng, case_entities, _COUNT)

    if dry_run:
        _validate_dry_run(all_entries)
        print("Dry run: all entries validated in-memory; ground_truth/*.yml NOT written.")
        return

    _GT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, entries in all_entries.items():
        out_path = _GT_DIR / filename
        with out_path.open("w", encoding="utf-8") as fh:
            yaml.dump(entries, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"Wrote {len(entries)} entries to {out_path}")


if __name__ == "__main__":
    typer.run(main)
```

- [ ] **Step 20: Run the full test file to verify it passes**

Run: `conda run -n synthetic pytest tests/test_seed_ground_truth_dry_run.py -v`
Expected: `6 passed`

- [ ] **Step 21: Manually invoke the dry run and confirm nothing is written**

```bash
conda run -n synthetic python scripts/seed_ground_truth.py --dry-run
git status --porcelain ground_truth/
```
Expected: last line printed is `Dry run: all entries validated in-memory; ground_truth/*.yml NOT written.`; `git status --porcelain ground_truth/` prints nothing (no changes).

- [ ] **Step 22: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 scripts/seed_ground_truth.py
conda run -n synthetic ruff format scripts/seed_ground_truth.py
conda run -n synthetic mypy scripts/seed_ground_truth.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add scripts/seed_ground_truth.py tests/test_seed_ground_truth_dry_run.py
git commit -m "♻️ refactor: rewire seed_ground_truth.py to content_engine with --dry-run"
```

### Task 8: Migrate TRUST content into `config/data_pools.yml`

Interpretation note on the task hint's "income-category descriptions": the 4 trust doc types have no free-text description field in `config/field_definitions.yml:59-109` (only names/TFN/ABN/addresses/dates/amounts), so there is no field to fill with invented "descriptions." The one genuinely hardcoded, non-varied piece of trust content in `scripts/seed_trust_distributions.py:276` is `income_year = "2023-24"` — a single literal reused for **all 50 cases**. This task widens that into an `income_years` pool instead, which is the closest real, field-backed widening opportunity available. Flagged to team-lead as a reinterpretation (see final summary).

**Files:**
- Modify: `generators/content_engine.py:_REQUIRED_KEYS` (add two keys)
- Modify: `config/data_pools.yml` (append)
- Test: `tests/test_data_pools_trust.py`

**Interfaces:**
- Consumes: `load_pools()` (Task 1), `ContentEngine.fictional_trust()` (Task 6, already reads `self.pools["trust_name_parts"]`).
- Produces: real `config/data_pools.yml` now has `trust_name_parts` (`surnames`, `trust_kinds`, `trustee_suffixes`) and `income_years`; `_REQUIRED_KEYS` in `content_engine.py` now enforces both. Consumed by Task 9's `seed_trust_distributions.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_pools_trust.py`:

```python
"""Loader-coverage test: the real config/data_pools.yml satisfies content_engine's
required trust keys (local-only; tests/ is gitignored)."""

from generators.content_engine import ContentEngine, load_pools


def test_real_data_pools_has_trust_name_parts():
    pools = load_pools()
    parts = pools["trust_name_parts"]
    assert len(parts["surnames"]) >= 10
    assert len(parts["trust_kinds"]) >= 3
    assert len(parts["trustee_suffixes"]) >= 3


def test_real_data_pools_has_multiple_income_years():
    pools = load_pools()
    assert len(pools["income_years"]) >= 2
    assert all(len(y) == 7 and y[4] == "-" for y in pools["income_years"])


def test_fictional_trust_works_against_the_real_pools():
    engine = ContentEngine(load_pools())
    import random

    trust = engine.fictional_trust(random.Random(1))
    assert trust["trust_name"] and trust["trustee_name"] and trust["abn"] and trust["tfn"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_data_pools_trust.py -v`
Expected: FAIL — `KeyError: 'trust_name_parts'`

- [ ] **Step 3: Add the required keys to `_REQUIRED_KEYS`**

Edit `generators/content_engine.py`: change

```python
_REQUIRED_KEYS: dict[str, list[str]] = {
    "faker_config": ["locale", "seed_base"],
    "locations": [],
    "street_types": [],
    "business_name_parts": ["surnames", "suburb_prefixes", "category_nouns"],
    "product_catalog": [],
    "service_catalog": [],
    "payment_methods": [],
    "banks": [],
    "bank_descriptions": [],
    "retailers": [],
    "professional_services": [],
    "real_name_blocklist_extra": [],
}
```

to

```python
_REQUIRED_KEYS: dict[str, list[str]] = {
    "faker_config": ["locale", "seed_base"],
    "locations": [],
    "street_types": [],
    "business_name_parts": ["surnames", "suburb_prefixes", "category_nouns"],
    "trust_name_parts": ["surnames", "trust_kinds", "trustee_suffixes"],
    "product_catalog": [],
    "service_catalog": [],
    "payment_methods": [],
    "banks": [],
    "bank_descriptions": [],
    "income_years": [],
    "retailers": [],
    "professional_services": [],
    "real_name_blocklist_extra": [],
}
```

- [ ] **Step 4: Append the trust pools to `config/data_pools.yml`**

Append to the end of `config/data_pools.yml`:

```yaml

# Trust distribution pools (scripts/seed_trust_distributions.py)
trust_name_parts:
  surnames:
    [Whitfield, Hollingsworth, Faircloth, Ashworth, Broadbent, Cathcart, Drummond,
     Everleigh, Fairweather, Gainsborough, Hazelwood, Kingsley, Lancaster, Mortlake,
     Newbold, Oakleigh, Pemberton, Ridgeway, Sedgwick, Thackeray, Ulverston,
     Vandermeer, Wetherby, Xanthos, Yeoman]
  trust_kinds:
    ["Family Trust", "Discretionary Trust", "Investment Trust", "Nominees Trust",
     "Unit Trust", "Property Trust"]
  trustee_suffixes: [Holdings, Capital, Group, Enterprises, Investments, Corp, Partners]

income_years: ["2022-23", "2023-24", "2024-25"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_data_pools_trust.py tests/test_content_engine.py tests/test_data_pools_core.py -v`
Expected: `36 passed` (33 previous + 3 new; Task 4–6's local `pools`/`_engine_with_trust_parts()` fixtures are unaffected since they build their own dicts, but every test that calls the real `load_pools()`/`build_engine()` now also implicitly validates the two new required keys)

- [ ] **Step 6: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py
conda run -n synthetic ruff format generators/content_engine.py config/data_pools.yml
conda run -n synthetic mypy generators/content_engine.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add generators/content_engine.py config/data_pools.yml tests/test_data_pools_trust.py
git commit -m "✨ feat: migrate trust content pools into data_pools.yml"
```

### Task 9: Rewire `scripts/seed_trust_distributions.py` to the engine, kill modulo, add `--dry-run`

**Files:**
- Modify: `scripts/seed_trust_distributions.py:1-493` (full rewrite)
- Test: `tests/test_seed_trust_distributions_dry_run.py`

**Interfaces:**
- Consumes: `generators.content_engine.{ContentEngine, NonRepeatingSampler, build_engine, sample}` (Tasks 3–6, 8); `generators.loader.load_layout_registry`; `generators.overflow_check.check_overflow`; `generators.schema.validate_entry`; the four trust renderers; `generate_tfn` from `generators/common.py` (still needed directly for `BENEFICIARY_TFN`, which is a second, independent TFN from the trust's own — `fictional_trust()` only returns the trust's TFN).
- Produces: `_generate_cases(engine, rng) -> tuple[dict, dict, dict, dict]` (trust_returns, distribution_statements, trust_income_schedules, beneficiary_itrs — same return shape as the original). `main(dry_run: bool = False) -> None`.

The amount math (net income split, franking/CGT/foreign-income randomization, and the four discrepancy-injection branches) is unchanged from the original — it is not "content" per the design spec's scope (§7, out of scope: "deep procedural narrative grammar"), only the entity/layout/income-year *lookups* feeding it change. It is shown here as one cohesive implementation step because splitting it would fragment an already-tested, internally-consistent block of financial logic without any independently-testable seam.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_seed_trust_distributions_dry_run.py`:

```python
"""Tests for the rewired scripts/seed_trust_distributions.py (local-only; tests/ is gitignored)."""

import importlib
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
seed_trust_distributions = importlib.import_module("seed_trust_distributions")

from generators.content_engine import build_engine  # noqa: E402


def test_generate_cases_produces_fifty_cases_across_all_four_docs():
    engine = build_engine()
    rng = random.Random(seed_trust_distributions._SEED)
    tr, ds, tis, itr = seed_trust_distributions._generate_cases(engine, rng)
    assert len(tr) == len(ds) == len(tis) == len(itr) == 50


def test_trust_and_beneficiary_entities_shared_across_the_four_docs_for_same_case():
    engine = build_engine()
    rng = random.Random(seed_trust_distributions._SEED)
    tr, ds, tis, itr = seed_trust_distributions._generate_cases(engine, rng)
    case_id = "CASE201"
    assert tr[case_id]["fields"]["TRUST_NAME"] == ds[case_id]["fields"]["TRUST_NAME"] == tis[case_id]["fields"]["TRUST_NAME"]
    assert tr[case_id]["fields"]["TRUST_ABN"] == ds[case_id]["fields"]["TRUST_ABN"] == tis[case_id]["fields"]["TRUST_ABN"]
    assert (
        tr[case_id]["fields"]["BENEFICIARY_NAME"]
        == ds[case_id]["fields"]["BENEFICIARY_NAME"]
        == itr[case_id]["fields"]["INDIVIDUAL_NAME"]
    )


def test_income_year_is_drawn_from_the_pool_and_not_a_single_hardcoded_literal():
    engine = build_engine()
    rng = random.Random(seed_trust_distributions._SEED)
    tr, _, _, _ = seed_trust_distributions._generate_cases(engine, rng)
    years = {e["fields"]["INCOME_YEAR"] for e in tr.values()}
    assert years <= set(engine.pools["income_years"])
    assert len(years) > 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_seed_trust_distributions_dry_run.py -v`
Expected: FAIL — `AttributeError: module 'seed_trust_distributions' has no attribute '_generate_cases'` (the module still imports fine since it's the pre-existing file, but its `_generate_cases` still takes only `rng`, not `engine, rng`)

- [ ] **Step 3: Rewrite the file header and `_generate_cases`**

Replace `scripts/seed_trust_distributions.py:1-467` (everything through the end of the original `_generate_cases`) with:

```python
"""Ground truth seed generator for trust distribution document quads.

Generates 50 document quads (200 entries across 4 YAML files):
- 35 compliant cases: all 5 linking fields reconcile perfectly
- 15 non-compliant cases: deliberate amount discrepancies injected

Non-compliance types:
  - Under-reported income (~5 cases): ITR reports 60-90% of actual share
  - Over-claimed franking (~4 cases): ITR claims 110-150% of actual franking
  - Missing CGT (~3 cases): Trust Income Schedule reports $0 CGT despite non-zero
  - Trust Return mismatch (~3 cases): Trust Return share differs by 5-20%

Each case's shared entities (trust, trustee, beneficiary) are generated once
via content_engine and projected across that case's 4 trust documents, so
widened content never desyncs a trust_distribution_links.yml quad.

Usage:
    python scripts/seed_trust_distributions.py [--dry-run]
"""

import random
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import typer
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from generators.common import generate_tfn  # noqa: E402
from generators.content_engine import (  # noqa: E402
    ContentEngine,
    NonRepeatingSampler,
    build_engine,
    sample,
)
from generators.loader import load_layout_registry  # noqa: E402
from generators.overflow_check import check_overflow  # noqa: E402
from generators.schema import validate_entry  # noqa: E402

_SEED = 42
_TOTAL_CASES = 50
_COMPLIANT_CASES = 35
_NON_COMPLIANT_CASES = 15
_GT_DIR = Path(__file__).parent.parent / "ground_truth"

# Case ID offset to avoid collision with existing CASE001-CASE055
_CASE_ID_START = 201

# ── Layout IDs (structural, not content — unchanged) ────────────────────────
_TRUST_RETURN_LAYOUTS = ["trust_return_standard"]
_DISTRIBUTION_STATEMENT_LAYOUTS = [
    "dist_software_navy",
    "dist_software_teal",
    "dist_table_plain",
    "dist_table_ruled",
    "dist_letter_formal",
    "dist_letter_compact",
]
_TRUST_INCOME_SCHEDULE_LAYOUTS = ["trust_income_schedule_standard"]
_BENEFICIARY_ITR_LAYOUTS = ["beneficiary_itr_standard"]

# Non-compliance type assignments (must sum to _NON_COMPLIANT_CASES = 15)
_DISCREPANCY_TYPES = (
    ["under_reported_income"] * 5
    + ["over_claimed_franking"] * 4
    + ["missing_cgt"] * 3
    + ["trust_return_mismatch"] * 3
)


def _fmt_decimal(d: Decimal) -> str:
    """Format Decimal as plain string with 2dp (no $ sign)."""
    return f"{d:.2f}"


def _rand_amount(rng: random.Random, lo: float, hi: float) -> Decimal:
    """Generate a random Decimal amount in [lo, hi] rounded to 2dp."""
    raw = rng.uniform(lo, hi)
    return Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _rand_date(rng: random.Random, year_start: int = 2023, year_end: int = 2024) -> str:
    """Generate a random date as DD/MM/YYYY."""
    year = rng.randint(year_start, year_end)
    month = rng.randint(1, 12)
    max_day = 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31
    day = rng.randint(1, max_day)
    return f"{day:02d}/{month:02d}/{year}"


def _rand_dob(rng: random.Random) -> str:
    """Generate a random date of birth for an adult (25-70 years old)."""
    year = rng.randint(1954, 1999)
    month = rng.randint(1, 12)
    max_day = 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31
    day = rng.randint(1, max_day)
    return f"{day:02d}/{month:02d}/{year}"


def _generate_cases(engine: ContentEngine, rng: random.Random) -> tuple[dict, dict, dict, dict]:
    """Generate all 50 document quads.

    Returns:
        Four dicts (trust_returns, distribution_statements,
        trust_income_schedules, beneficiary_itrs), each mapping
        CASE IDs to ground truth entries.
    """
    trust_returns: dict = {}
    distribution_statements: dict = {}
    trust_income_schedules: dict = {}
    beneficiary_itrs: dict = {}

    discrepancy_list = list(_DISCREPANCY_TYPES)
    rng.shuffle(discrepancy_list)
    discrepancy_idx = 0

    tr_layout_draw = NonRepeatingSampler(rng, _TRUST_RETURN_LAYOUTS)
    ds_layout_draw = NonRepeatingSampler(rng, _DISTRIBUTION_STATEMENT_LAYOUTS)
    tis_layout_draw = NonRepeatingSampler(rng, _TRUST_INCOME_SCHEDULE_LAYOUTS)
    itr_layout_draw = NonRepeatingSampler(rng, _BENEFICIARY_ITR_LAYOUTS)

    for i in range(_TOTAL_CASES):
        case_num = _CASE_ID_START + i
        case_id = f"CASE{case_num:03d}"
        is_compliant = i < _COMPLIANT_CASES

        # --- Identity generation ---
        trust = engine.fictional_trust(rng)
        trust_name = trust["trust_name"]
        trustee_name = trust["trustee_name"]
        trust_abn = trust["abn"]
        trust_tfn = trust["tfn"]
        trust_address = engine.address(rng)

        beneficiary = engine.person(rng)
        beneficiary_name = beneficiary["full_name"]
        beneficiary_tfn = generate_tfn()
        beneficiary_address = engine.address(rng)
        beneficiary_dob = _rand_dob(rng)

        income_year = sample(rng, engine.pools["income_years"])
        distribution_date = _rand_date(rng, 2024, 2024)

        # --- Source of truth amounts (unchanged financial logic) ---
        total_net_income = _rand_amount(rng, 10000, 500000)
        num_beneficiaries = rng.randint(1, 4)
        share_of_net_income = (total_net_income / Decimal(str(num_beneficiaries))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        franking_pct = Decimal(str(rng.uniform(0, 0.30)))
        franking_credit = (share_of_net_income * franking_pct).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        if rng.random() < 0.25:
            capital_gain = Decimal("0.00")
        else:
            cgt_pct = Decimal(str(rng.uniform(0.05, 0.40)))
            capital_gain = (share_of_net_income * cgt_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if rng.random() < 0.80:
            foreign_income = Decimal("0.00")
        else:
            foreign_income = _rand_amount(rng, 100, 5000)

        tax_free = Decimal("0.00")
        tax_deferred = Decimal("0.00")
        if rng.random() < 0.10:
            tax_free = _rand_amount(rng, 100, 2000)
        if rng.random() < 0.08:
            tax_deferred = _rand_amount(rng, 100, 1500)

        # --- Values that go into each document ---
        tr_share = share_of_net_income
        tr_franking = franking_credit
        tr_cgt = capital_gain

        ds_share = share_of_net_income
        ds_franking = franking_credit
        ds_cgt = capital_gain

        tis_share = share_of_net_income
        tis_franking = franking_credit
        tis_cgt = capital_gain

        itr_total_trust_income = share_of_net_income
        itr_franking = franking_credit

        discrepancy_type = None

        # --- Inject discrepancies for non-compliant cases ---
        if not is_compliant:
            discrepancy_type = discrepancy_list[discrepancy_idx]
            discrepancy_idx += 1

            if discrepancy_type == "under_reported_income":
                reduction = Decimal(str(rng.uniform(0.60, 0.90)))
                itr_total_trust_income = (share_of_net_income * reduction).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            elif discrepancy_type == "over_claimed_franking":
                inflation = Decimal(str(rng.uniform(1.10, 1.50)))
                itr_franking = (franking_credit * inflation).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            elif discrepancy_type == "missing_cgt":
                if capital_gain == Decimal("0.00"):
                    capital_gain = _rand_amount(rng, 2000, 20000)
                    ds_cgt = capital_gain
                    tr_cgt = capital_gain
                tis_cgt = Decimal("0.00")

            elif discrepancy_type == "trust_return_mismatch":
                variance = Decimal(str(rng.uniform(0.05, 0.20)))
                direction = rng.choice([1, -1])
                tr_share = (share_of_net_income * (Decimal("1") + direction * variance)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

        # --- Layout and seed assignment ---
        tr_layout = tr_layout_draw.draw()
        ds_layout = ds_layout_draw.draw()
        tis_layout = tis_layout_draw.draw()
        itr_layout = itr_layout_draw.draw()

        degradation_seed = rng.randint(1000, 9999)

        # --- Build entries ---
        trust_returns[case_id] = {
            "layout": tr_layout,
            "degradation_seed": degradation_seed,
            "fields": {
                "DOCUMENT_TYPE": "TRUST_RETURN",
                "TRUST_NAME": trust_name,
                "TRUST_TFN": trust_tfn,
                "TRUST_ABN": trust_abn,
                "TRUSTEE_NAME": trustee_name,
                "TRUST_ADDRESS": trust_address,
                "INCOME_YEAR": income_year,
                "TOTAL_NET_INCOME": _fmt_decimal(total_net_income),
                "BENEFICIARY_NAME": beneficiary_name,
                "BENEFICIARY_TFN": beneficiary_tfn,
                "SHARE_OF_NET_INCOME": _fmt_decimal(tr_share),
                "FRANKING_CREDIT": _fmt_decimal(tr_franking),
                "CAPITAL_GAIN_COMPONENT": _fmt_decimal(tr_cgt),
                "FOREIGN_INCOME": _fmt_decimal(foreign_income),
            },
        }

        distribution_statements[case_id] = {
            "layout": ds_layout,
            "degradation_seed": degradation_seed + 1,
            "fields": {
                "DOCUMENT_TYPE": "DISTRIBUTION_STATEMENT",
                "TRUST_NAME": trust_name,
                "TRUST_ABN": trust_abn,
                "TRUST_ADDRESS": trust_address,
                "DATE_OF_DISTRIBUTION": distribution_date,
                "INCOME_YEAR": income_year,
                "BENEFICIARY_NAME": beneficiary_name,
                "BENEFICIARY_TFN": beneficiary_tfn,
                "BENEFICIARY_ADDRESS": beneficiary_address,
                "SHARE_OF_NET_INCOME": _fmt_decimal(ds_share),
                "FRANKING_CREDIT": _fmt_decimal(ds_franking),
                "CAPITAL_GAIN_COMPONENT": _fmt_decimal(ds_cgt),
                "FOREIGN_INCOME": _fmt_decimal(foreign_income),
                "TAX_FREE_AMOUNT": _fmt_decimal(tax_free),
                "TAX_DEFERRED_AMOUNT": _fmt_decimal(tax_deferred),
            },
        }

        trust_income_schedules[case_id] = {
            "layout": tis_layout,
            "degradation_seed": degradation_seed + 2,
            "fields": {
                "DOCUMENT_TYPE": "TRUST_INCOME_SCHEDULE",
                "TRUST_NAME": trust_name,
                "TRUST_ABN": trust_abn,
                "BENEFICIARY_NAME": beneficiary_name,
                "BENEFICIARY_TFN": beneficiary_tfn,
                "SHARE_OF_NET_INCOME": _fmt_decimal(tis_share),
                "FRANKING_CREDIT": _fmt_decimal(tis_franking),
                "CAPITAL_GAIN_COMPONENT": _fmt_decimal(tis_cgt),
                "FOREIGN_INCOME": _fmt_decimal(foreign_income),
            },
        }

        beneficiary_itrs[case_id] = {
            "layout": itr_layout,
            "degradation_seed": degradation_seed + 3,
            "fields": {
                "DOCUMENT_TYPE": "BENEFICIARY_ITR",
                "INDIVIDUAL_NAME": beneficiary_name,
                "INDIVIDUAL_TFN": beneficiary_tfn,
                "DATE_OF_BIRTH": beneficiary_dob,
                "INDIVIDUAL_ADDRESS": beneficiary_address,
                "TOTAL_TRUST_INCOME": _fmt_decimal(itr_total_trust_income),
                "TRUST_FRANKING_CREDIT": _fmt_decimal(itr_franking),
            },
        }

    return trust_returns, distribution_statements, trust_income_schedules, beneficiary_itrs
```

Note: the original's `discrepancy_details` local variable (an f-string built per discrepancy branch) is dropped — it was computed but never written into any entry's `fields` in the original either (confirmed by reading the original's entry-building blocks above: none of the four entries include a `discrepancy_details` key). Dropping genuinely-dead code here, not a behavior change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_seed_trust_distributions_dry_run.py -v`
Expected: `3 passed`

- [ ] **Step 5: Write the failing test for `main(dry_run=True)`**

Append to `tests/test_seed_trust_distributions_dry_run.py`:

```python
def test_dry_run_validates_without_writing_ground_truth(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_trust_distributions, "_GT_DIR", tmp_path)
    seed_trust_distributions.main(dry_run=True)
    assert not any(tmp_path.iterdir())
```

- [ ] **Step 6: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_seed_trust_distributions_dry_run.py -v -k dry_run`
Expected: FAIL — `TypeError: main() got an unexpected keyword argument 'dry_run'`

- [ ] **Step 7: Replace `main()` with the dry-run-aware version**

Replace the original `main()` function and the `if __name__ == "__main__":` block at the bottom of `scripts/seed_trust_distributions.py` with:

```python
def _validate_dry_run(all_entries: dict[str, dict]) -> None:
    """Validate generated entries in-memory (schema + overflow) without writing YAML."""
    from generators.beneficiary_itr import render_beneficiary_itr
    from generators.distribution_statement import render_distribution_statement
    from generators.trust_income_schedule import render_trust_income_schedule
    from generators.trust_return import render_trust_return

    renderer_map = {
        "trust_returns.yml": (render_trust_return, "config/layouts/trust_returns.yml"),
        "distribution_statements.yml": (render_distribution_statement, "config/layouts/distribution_statements.yml"),
        "trust_income_schedules.yml": (render_trust_income_schedule, "config/layouts/trust_income_schedules.yml"),
        "beneficiary_itrs.yml": (render_beneficiary_itr, "config/layouts/beneficiary_itrs.yml"),
    }

    errors: list[str] = []
    for filename, entries in all_entries.items():
        renderer, layout_path = renderer_map[filename]
        layouts = load_layout_registry(Path(layout_path))
        for case_id, entry in entries.items():
            errors.extend(validate_entry(str(case_id), entry))
        errors.extend(check_overflow(entries, layouts, renderer))

    if errors:
        listing = "\n    ".join(errors)
        raise RuntimeError(
            "Dry run failed: generated content did not validate.\n"
            f"  What:     {len(errors)} error(s) across generated entries:\n"
            f"    {listing}\n"
            "  Where:    scripts/seed_trust_distributions.py._generate_cases and the "
            "config/data_pools.yml content it draws from.\n"
            "  Expected: every generated entry passes schema validation and renders "
            "within its layout's field_budgets (no FitError).\n"
            "  Recover:  fix the failing generator logic or widen the offending pool/budget, "
            "then rerun `python scripts/seed_trust_distributions.py --dry-run`."
        )


def main(dry_run: bool = typer.Option(False, "--dry-run", help="Validate in-memory; do not write ground_truth/*.yml")) -> None:
    """Generate all trust distribution ground truth YAML files with deterministic seed=42."""
    rng = random.Random(_SEED)
    engine = build_engine()
    tr, ds, tis, itr = _generate_cases(engine, rng)

    outputs = [
        ("trust_returns.yml", tr),
        ("distribution_statements.yml", ds),
        ("trust_income_schedules.yml", tis),
        ("beneficiary_itrs.yml", itr),
    ]

    if dry_run:
        _validate_dry_run(dict(outputs))
        print("Dry run: all entries validated in-memory; ground_truth/*.yml NOT written.")
        return

    _GT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, entries in outputs:
        out_path = _GT_DIR / filename
        with out_path.open("w", encoding="utf-8") as fh:
            yaml.dump(entries, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"Wrote {len(entries)} entries to {out_path}")


if __name__ == "__main__":
    typer.run(main)
```

- [ ] **Step 8: Run the full test file to verify it passes**

Run: `conda run -n synthetic pytest tests/test_seed_trust_distributions_dry_run.py -v`
Expected: `4 passed`

- [ ] **Step 9: Manually invoke the dry run and confirm nothing is written**

```bash
conda run -n synthetic python scripts/seed_trust_distributions.py --dry-run
git status --porcelain ground_truth/
```
Expected: last line printed is `Dry run: all entries validated in-memory; ground_truth/*.yml NOT written.`; `git status --porcelain ground_truth/` prints nothing.

- [ ] **Step 10: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 scripts/seed_trust_distributions.py
conda run -n synthetic ruff format scripts/seed_trust_distributions.py
conda run -n synthetic mypy scripts/seed_trust_distributions.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add scripts/seed_trust_distributions.py tests/test_seed_trust_distributions_dry_run.py
git commit -m "♻️ refactor: rewire seed_trust_distributions.py to content_engine with --dry-run"
```

This completes Stage 1B-i. The committed corpus (`ground_truth/*.yml`) is untouched — confirm with `git status --porcelain ground_truth/` printing nothing.

---

## Stage 1B-ii — Coordinated Destructive Reseed (its own reviewed step)

Split into two tasks so each is independently reviewable: 10a reseeds + gates the 4 core types, 10b reseeds + gates the 4 trust types and runs the full corpus-wide gate. **If any gate step in either task fails, revert with the `git checkout --` command shown in that task's failure branch and stop — nothing ships.**

### Task 10a: Core reseed (bank/receipt/invoice/cc) + transaction links + partial gate

**Files:**
- Modify (generated, not hand-written): `ground_truth/bank_statements.yml`, `ground_truth/receipts.yml`, `ground_truth/invoices.yml`, `ground_truth/cc_statements.yml`, `ground_truth/transaction_links.yml`

**Interfaces:**
- Consumes: `scripts/seed_ground_truth.py::main` (Task 7), `scripts/seed_transaction_links.py::main` (unchanged, verified above), `generators.pipeline::validate`, `linking.link_validator.validate_links`.

- [ ] **Step 1: Confirm a clean starting state**

```bash
git status --porcelain
```
Expected: empty output (Stage 1B-i's tasks were all committed).

- [ ] **Step 2: Run the core reseed**

```bash
conda run -n synthetic python scripts/seed_ground_truth.py
```
Expected output (4 lines, order matches the `generators` list in `main()`):
```
Wrote 55 entries to ground_truth/bank_statements.yml
Wrote 55 entries to ground_truth/receipts.yml
Wrote 55 entries to ground_truth/invoices.yml
Wrote 55 entries to ground_truth/cc_statements.yml
```

- [ ] **Step 3: Re-derive transaction links**

```bash
conda run -n synthetic python scripts/seed_transaction_links.py
```
Expected output: `Generated 110 transaction links: {'easy': N, 'medium': M, 'hard': K}` where `N + M + K == 110` (55 cases × 2 source docs each — receipt and invoice — per `scripts/seed_transaction_links.py:164-280`).

- [ ] **Step 4: Run schema + layout + overflow validation**

```bash
conda run -n synthetic python -m generators.pipeline validate
```
Expected: `Validation passed.` and exit code `0`. (This single command already covers ABN/TFN checksum, `DD/MM/YYYY` date format, amount-without-`$` format, and pipe-delimited count alignment for all 8 types — trust types are still pre-reseed content at this point and were already valid, so they continue to pass.)

If this fails: `git checkout -- ground_truth/bank_statements.yml ground_truth/receipts.yml ground_truth/invoices.yml ground_truth/cc_statements.yml ground_truth/transaction_links.yml` and stop.

- [ ] **Step 5: Verify GST = total / 11 holds for every receipt**

```bash
conda run -n synthetic python -c "
import yaml
from decimal import Decimal, ROUND_HALF_UP

data = yaml.safe_load(open('ground_truth/receipts.yml'))
bad = []
for case_id, entry in data.items():
    f = entry['fields']
    total = Decimal(f['TOTAL_AMOUNT'])
    gst = Decimal(f['GST_AMOUNT'])
    expected = (total / Decimal('11')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if gst != expected:
        bad.append((case_id, str(gst), str(expected)))
assert not bad, bad
print(f'OK: GST = total/11 holds for all {len(data)} receipts')
"
```
Expected: `OK: GST = total/11 holds for all 55 receipts`

If this fails: revert as in Step 4 and stop.

- [ ] **Step 6: Verify PAYER_NAME is shared across bank/cc/invoice for every case**

```bash
conda run -n synthetic python -c "
import yaml

bank = yaml.safe_load(open('ground_truth/bank_statements.yml'))
cc = yaml.safe_load(open('ground_truth/cc_statements.yml'))
invoices = yaml.safe_load(open('ground_truth/invoices.yml'))

mismatches = []
for case_id in bank:
    b = bank[case_id]['fields']['PAYER_NAME']
    c = cc[case_id]['fields']['PAYER_NAME']
    i = invoices[case_id]['fields']['PAYER_NAME']
    if not (b == c == i):
        mismatches.append((case_id, b, c, i))
assert not mismatches, mismatches
print(f'OK: PAYER_NAME consistent across bank/cc/invoice for all {len(bank)} cases')
"
```
Expected: `OK: PAYER_NAME consistent across bank/cc/invoice for all 55 cases`

If this fails: revert as in Step 4 and stop.

- [ ] **Step 7: Verify transaction-link metrics self-consistency**

```bash
conda run -n synthetic python -c "
import yaml
from linking.link_validator import validate_links

gt = yaml.safe_load(open('ground_truth/transaction_links.yml'))
preds = {k: {'bank_statement': v[0]['bank_statement'], 'bank_amount': v[0]['bank_amount']} for k, v in gt.items()}
score = validate_links(gt, preds)
assert score.precision == 1.0 and score.recall == 1.0 and score.f1 == 1.0, score
assert score.true_positives == 110, score.true_positives
print(f'OK: {score.true_positives} true positives, precision={score.precision}, recall={score.recall}, f1={score.f1}')
"
```
Expected: `OK: 110 true positives, precision=1.0, recall=1.0, f1=1.0`

If this fails: revert as in Step 4 and stop. (A perfect self-match sanity-checks that `transaction_links.yml` and `bank_statements.yml` reference each other consistently — it is not a substitute for a downstream LMM eval, just confirms the generated linking structure is internally sound.)

- [ ] **Step 8: Run the local test suite and full quality gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all tests pass; ruff/mypy report no errors.

- [ ] **Step 9: Commit**

```bash
git add ground_truth/bank_statements.yml ground_truth/receipts.yml ground_truth/invoices.yml ground_truth/cc_statements.yml ground_truth/transaction_links.yml
git commit -m "🌱 content: reseed core ground truth with widened fictional content"
```

### Task 10b: Trust reseed + trust distribution links + full corpus gate

**Files:**
- Modify (generated, not hand-written): `ground_truth/trust_returns.yml`, `ground_truth/distribution_statements.yml`, `ground_truth/trust_income_schedules.yml`, `ground_truth/beneficiary_itrs.yml`, `ground_truth/trust_distribution_links.yml`

**Interfaces:**
- Consumes: `scripts/seed_trust_distributions.py::main` (Task 9), `scripts/seed_trust_distribution_links.py::main` (unchanged, verified above), `generators.pipeline::validate`, `linking.link_validator.validate_trust_distribution_links`.

- [ ] **Step 1: Run the trust reseed**

```bash
conda run -n synthetic python scripts/seed_trust_distributions.py
```
Expected output (4 lines):
```
Wrote 50 entries to ground_truth/trust_returns.yml
Wrote 50 entries to ground_truth/distribution_statements.yml
Wrote 50 entries to ground_truth/trust_income_schedules.yml
Wrote 50 entries to ground_truth/beneficiary_itrs.yml
```

- [ ] **Step 2: Re-derive trust distribution links**

```bash
conda run -n synthetic python scripts/seed_trust_distribution_links.py
```
Expected output: `Generated 50 trust distribution links: 35 compliant, 15 non-compliant`

- [ ] **Step 3: Run the full corpus validation gate (all 8 types)**

```bash
conda run -n synthetic python -m generators.pipeline validate
```
Expected: `Validation passed.` and exit code `0`.

If this fails: `git checkout -- ground_truth/trust_returns.yml ground_truth/distribution_statements.yml ground_truth/trust_income_schedules.yml ground_truth/beneficiary_itrs.yml ground_truth/trust_distribution_links.yml` and stop.

- [ ] **Step 4: Verify trust distribution linking metrics self-consistency**

```bash
conda run -n synthetic python -c "
import yaml
from linking.link_validator import validate_trust_distribution_links

gt = yaml.safe_load(open('ground_truth/trust_distribution_links.yml'))
preds = {
    k: {
        'trust_return': v['trust_return'],
        'trust_income_schedule': v['trust_income_schedule'],
        'beneficiary_itr': v['beneficiary_itr'],
        'linking_fields': v['linking_fields'],
        'compliance_status': v['compliance_status'],
        'discrepancy_type': v['discrepancy_type'],
    }
    for k, v in gt.items()
}
score = validate_trust_distribution_links(gt, preds)
assert score.total_quads == 50, score.total_quads
assert score.correct_quads == 50, score.correct_quads
assert score.compliance.total_compliant == 35, score.compliance.total_compliant
assert score.compliance.total_non_compliant == 15, score.compliance.total_non_compliant
print(f'OK: {score.correct_quads}/{score.total_quads} quads, {score.compliance.total_compliant} compliant, {score.compliance.total_non_compliant} non-compliant')
"
```
Expected: `OK: 50/50 quads, 35 compliant, 15 non-compliant`

If this fails: revert as in Step 3 and stop.

- [ ] **Step 5: Verify TRUST_ABN/TFN checksums and cross-doc share consistency**

(ABN/TFN checksum format is already covered by `validate` in Step 3 via `generators/schema.py`'s `_ABN_FIELDS`/`_TFN_FIELDS`. This step checks the cross-document `SHARE_OF_NET_INCOME` reconciliation invariant specifically for the 35 compliant cases, which `validate` does not check.)

```bash
conda run -n synthetic python -c "
import yaml
from decimal import Decimal

tr = yaml.safe_load(open('ground_truth/trust_returns.yml'))
ds = yaml.safe_load(open('ground_truth/distribution_statements.yml'))
links = yaml.safe_load(open('ground_truth/trust_distribution_links.yml'))

bad = []
for ds_filename, record in links.items():
    if record['compliance_status'] != 'compliant':
        continue
    case_id = ds_filename.split('_')[0]
    tr_share = Decimal(tr[case_id]['fields']['SHARE_OF_NET_INCOME'])
    ds_share = Decimal(ds[case_id]['fields']['SHARE_OF_NET_INCOME'])
    if tr_share != ds_share:
        bad.append((case_id, str(tr_share), str(ds_share)))
assert not bad, bad
print('OK: SHARE_OF_NET_INCOME reconciles between Trust Return and Distribution Statement for all compliant cases')
"
```
Expected: `OK: SHARE_OF_NET_INCOME reconciles between Trust Return and Distribution Statement for all compliant cases`

If this fails: revert as in Step 3 and stop.

- [ ] **Step 6: Run the local test suite and full quality gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all tests pass; ruff/mypy report no errors.

- [ ] **Step 7: Commit**

```bash
git add ground_truth/trust_returns.yml ground_truth/distribution_statements.yml ground_truth/trust_income_schedules.yml ground_truth/beneficiary_itrs.yml ground_truth/trust_distribution_links.yml
git commit -m "🌱 content: reseed trust ground truth with widened fictional content"
```

This completes Stage 1B-ii. The full 8-type corpus is now reseeded with widened, de-correlated, fully-fictional content; both link files re-derive consistently; and every step that could ship a broken corpus reverts on failure rather than committing.
