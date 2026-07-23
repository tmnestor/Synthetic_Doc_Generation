# Phase 1C — Deferred-Minor Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four non-blocking Minors from the Phase 1B review — move receipt/service categories into YAML, derive `distribution_date` from `income_year`, add a name-only bank-merchant helper, and harden `load_pools` — then reseed to absorb the two content-affecting changes.

**Architecture:** Four small code/config changes (Tasks 1-4, each TDD, corpus untouched via `--dry-run`), then one coordinated reseed (Task 5) that rewrites the corpus and regenerates the content-pinned baselines. No renderer changes. Determinism (seed=42, reproducible) preserved throughout.

**Tech Stack:** Python 3.12, PyYAML, Faker 40.8.0, pytest. Conda env `synthetic`.

## Global Constraints

- Python 3.12 hints (`X | Y`; no `from __future__ import annotations`; no `TYPE_CHECKING` guards for runtime-signature types); line length ≤108.
- **YAML single source of truth:** all content lives in `config/data_pools.yml`; every required key enforced by `content_engine._REQUIRED_KEYS`; a missing key fails fast (no silent default).
- **Fail-fast four-element diagnostics** (what / where — absolute path + dotted YAML key / valid example / how to recover); fail-fast tests assert all four via `tests/conftest.py::assert_diagnostic_error` (imported as `from conftest import assert_diagnostic_error`).
- **B904** in except (`raise ... from err`/`from None`). **NEVER write the forbidden 3-letter tax-authority acronym** (use "PROD"); note `ATF` (trustee names) is a different, allowed token.
- **Determinism:** seeded `random.Random(_SEED)` + `Faker.seed` + `random.seed(_SEED)` (global, for `generate_abn`/`generate_tfn`); reuse `generate_abn`/`generate_tfn` — never real ABNs/TFNs. A re-run must reproduce a byte-identical corpus.
- **No renderer changes** — 1C is content/loader only.
- Tests: `conda run -n synthetic pytest tests/`; `tests/` gitignored (local-only). Gate before every commit: `ruff check --fix --ignore ARG001,ARG002,F841` → `ruff format` → `mypy . --ignore-missing-imports` → `pytest tests/`. Never bypass the pre-commit hook. No Claude/AI attribution in commits.
- **Stage 1C-i (Tasks 1-4) must NOT overwrite `ground_truth/*.yml`** — use each seed script's `--dry-run`; never run `seed_ground_truth.py`/`seed_trust_distributions.py` without `--dry-run`. Only Task 5 reseeds.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `generators/content_engine.py` | Modify | `load_pools` hardening (Task 1); `_REQUIRED_KEYS` += `receipt_categories`/`service_categories` (Task 2); `fictional_business_name` + `fictional_business` refactor (Task 3). |
| `config/data_pools.yml` | Modify | add `receipt_categories`, `service_categories` (Task 2). |
| `scripts/seed_ground_truth.py` | Modify | read categories from pools, delete the 3 Python constants (Task 2); `_draw_bank_description` uses `fictional_business_name` (Task 3). |
| `scripts/seed_trust_distributions.py` | Modify | `distribution_date` derived from `income_year` (Task 4). |
| `tests/test_content_engine.py` | Modify | load_pools hardening tests (Task 1); `fictional_business_name` + unchanged-`fictional_business` tests (Task 3). |
| `tests/test_data_pools_core.py` | Modify | category-pools-present test (Task 2). |
| `tests/test_seed_ground_truth_dry_run.py` | Modify | byte-identical-after-item-1 dry-run check (Task 2). |
| `tests/test_seed_trust_distributions_dry_run.py` | Modify | `distribution_date` window test (Task 4). |
| `ground_truth/*.yml` + link files | Modify (Task 5 only) | reseeded corpus (git-tracked). |
| `tests/fixtures/*_baseline_hashes.json`, `tests/fixtures/tis_ref_CASE201.png` | Regenerate (Task 5) | content-pinned, gitignored. |

---

## Stage 1C-i — Code/config (no corpus overwrite)

### Task 1: Item 4 — harden `load_pools`

**Files:** Modify `generators/content_engine.py`, `tests/test_content_engine.py`.

**Interfaces:**
- Produces: `load_pools(path)` now raises a four-element `ValueError` for (a) a file that parses to a non-`dict` (empty/`None`/scalar) and (b) a required mapping-typed key present but not a `dict` — distinct from the missing-key message.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_engine.py`:

```python
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
    assert "mapping" in msg.lower()  # distinct from the "not found" message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v -k "empty_file or non_mapping"`
Expected: FAIL — empty-file raises a raw `TypeError` (not `ValueError`); non-mapping reuses the "not found" message (no "mapping").

- [ ] **Step 3: Implement the hardening**

In `generators/content_engine.py`, add a helper next to `_missing_key_error`:

```python
def _not_mapping_error(path: Path, dotted_key: str) -> str:
    """Four-element diagnostic for a key that is present but not a mapping."""
    return (
        "content pool key is present but not a mapping.\n"
        f"  What:     '{dotted_key}' in {path} is not a YAML mapping (dict).\n"
        f"  Where:    {path} -> '{dotted_key}'.\n"
        "  Expected: a mapping, e.g. 'faker_config:\\n  locale: en_AU\\n  seed_base: 42'.\n"
        f"  Recover:  make '{dotted_key}' a mapping with the required sub-keys in {path}."
    )
```

In `load_pools`, after `data = yaml.safe_load(path.read_text())`, add:

```python
    if not isinstance(data, dict):
        raise ValueError(
            "content pool file is empty or not a mapping.\n"
            f"  What:     {path} did not parse to a YAML mapping (got {type(data).__name__}).\n"
            f"  Where:    {path}\n"
            "  Expected: a non-empty YAML file whose top level is a mapping of pool keys.\n"
            f"  Recover:  populate {path} with the required top-level pool keys "
            "(see generators/content_engine.py _REQUIRED_KEYS)."
        )
```

Then change the nested-parent check from `raise ValueError(_missing_key_error(path, key, subkeys))` to use the new message:

```python
        if subkeys:
            if not isinstance(data[key], dict):
                raise ValueError(_not_mapping_error(path, key))
            for sub in subkeys:
                if sub not in data[key]:
                    raise ValueError(_missing_key_error(path, f"{key}.{sub}", []))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v`
Expected: all pass (the two new + all existing).

- [ ] **Step 5: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py
conda run -n synthetic ruff format generators/content_engine.py
conda run -n synthetic mypy generators/content_engine.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add generators/content_engine.py
git commit -m "🐛 fix: load_pools fails fast on empty file and non-mapping nested key"
```

### Task 2: Item 1 — receipt/service categories → YAML

**Files:** Modify `config/data_pools.yml`, `generators/content_engine.py`, `scripts/seed_ground_truth.py`, `tests/test_data_pools_core.py`, `tests/test_seed_ground_truth_dry_run.py`.

**Interfaces:**
- Consumes: `load_pools` (Task 1).
- Produces: `config/data_pools.yml` gains `receipt_categories` + `service_categories`; `_REQUIRED_KEYS` enforces both; `seed_ground_truth.py` reads them via `engine.pools[...]` (no Python category constants). Byte-identical corpus (same values/order).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_data_pools_core.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_data_pools_core.py -v -k receipt_and_service`
Expected: FAIL — `KeyError: 'receipt_categories'`.

- [ ] **Step 3: Add the pools to `config/data_pools.yml`**

Append (anywhere top-level, e.g. after `real_name_blocklist_extra`):

```yaml
# Which category_nouns categories feed receipts (retail) vs invoices (services).
# Semantic partition — not derivable from category_nouns keys alone.
receipt_categories: [hardware, grocery, office, electronics, retail, pharmacy, liquor, fuel, automotive]
service_categories: [accounting, legal, it_services, consulting, marketing]
```

- [ ] **Step 4: Enforce in `_REQUIRED_KEYS`**

In `generators/content_engine.py`, add to `_REQUIRED_KEYS` (leaf lists, `[]`):

```python
    "receipt_categories": [],
    "service_categories": [],
```

- [ ] **Step 5: Rewire `scripts/seed_ground_truth.py`**

Delete the three constants (`_RECEIPT_CATEGORIES`, `_SERVICE_CATEGORIES`, `_ALL_CATEGORIES`, lines ~76-89). At each use site, read from the engine:
- `_generate_receipt_entries` (`category = sample(rng, _RECEIPT_CATEGORIES)`) → `category = sample(rng, engine.pools["receipt_categories"])`.
- `_generate_invoice_entries` (`category = sample(rng, _SERVICE_CATEGORIES)`) → `category = sample(rng, engine.pools["service_categories"])`.
- `_draw_bank_description` (`sample(rng, _ALL_CATEGORIES)`) → `sample(rng, engine.pools["receipt_categories"] + engine.pools["service_categories"])` (keep the receipt+service concatenation order for byte-identity).

- [ ] **Step 6: Prove byte-identical via dry-run vs the committed corpus**

Append to `tests/test_seed_ground_truth_dry_run.py`:

```python
def test_item1_categories_dry_run_is_byte_identical_to_committed_corpus():
    # Item 1 (categories -> YAML) must not change generation: the dry-run entries
    # must hash-match the currently committed ground_truth (pre-reseed).
    import hashlib
    import yaml
    import scripts.seed_ground_truth as sgt

    generated = sgt.build_all_entries()  # in-memory {doc_type: {case_id: entry}}
    for doc_type in ("bank_statements", "receipts", "invoices", "cc_statements"):
        committed = yaml.safe_load(open(f"ground_truth/{doc_type}.yml"))
        gen = generated[doc_type]
        assert gen.keys() == committed.keys()
        for cid in committed:
            gh = hashlib.sha256(yaml.dump(gen[cid], sort_keys=True).encode()).hexdigest()
            ch = hashlib.sha256(yaml.dump(committed[cid], sort_keys=True).encode()).hexdigest()
            assert gh == ch, f"{doc_type}/{cid} changed — item 1 was not byte-identical"
```

If `seed_ground_truth.py` has no `build_all_entries()` returning the in-memory dict, add a thin one that `main(dry_run=True)` already builds (extract the generation into a function `build_all_entries() -> dict` that both `main` and this test call). Keep `main`'s behavior identical.

- [ ] **Step 7: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_data_pools_core.py tests/test_seed_ground_truth_dry_run.py -v`
Expected: all pass — categories present AND the dry-run is byte-identical to the committed corpus (confirming item 1 changed nothing).

- [ ] **Step 8: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py scripts/seed_ground_truth.py
conda run -n synthetic ruff format generators/content_engine.py scripts/seed_ground_truth.py
conda run -n synthetic mypy generators/content_engine.py scripts/seed_ground_truth.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add config/data_pools.yml generators/content_engine.py scripts/seed_ground_truth.py
git commit -m "♻️ refactor: move receipt/service categories into data_pools.yml"
```

### Task 3: Item 3 — name-only bank-merchant helper

**Files:** Modify `generators/content_engine.py`, `scripts/seed_ground_truth.py`, `tests/test_content_engine.py`.

**Interfaces:**
- Produces: `ContentEngine.fictional_business_name(rng, category) -> str` (invented name only; blocklist reject-and-redraw; `ValueError` unknown category; `RuntimeError` on exhaustion — all four-element). `fictional_business` refactored to delegate; its `{name,address,abn,category}` output is UNCHANGED for a given seed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_engine.py`:

```python
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
_FICTIONAL_BUSINESS_GOLDEN: dict[tuple[int, str], dict] = {}  # FILL IN — see Step 1a


def test_fictional_business_unchanged_by_name_only_refactor():
    engine = build_engine()
    assert _FICTIONAL_BUSINESS_GOLDEN, "populate _FICTIONAL_BUSINESS_GOLDEN in Step 1a"
    for (seed, cat), expected in _FICTIONAL_BUSINESS_GOLDEN.items():
        got = engine.fictional_business(random.Random(seed), cat)
        assert got == expected, f"fictional_business({seed},{cat}) changed: {got} != {expected}"
```

**Step 1a — capture the golden values BEFORE refactoring.** Run this against the
CURRENT (pre-refactor) engine and paste the printed dict as `_FICTIONAL_BUSINESS_GOLDEN`:

```bash
conda run -n synthetic python -c "
import random
from generators.content_engine import build_engine
e = build_engine()
pairs = [(4,'grocery'),(11,'hardware'),(7,'legal'),(21,'fuel'),(99,'marketing')]
print({(s,c): e.fictional_business(random.Random(s), c) for s,c in pairs})
"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v -k "business_name or unchanged_by_name"`
Expected: FAIL — `AttributeError: ... 'fictional_business_name'`.

- [ ] **Step 3: Refactor `fictional_business` + add `fictional_business_name`**

In `generators/content_engine.py`, replace the body of `fictional_business` with a delegation and add `fictional_business_name` (extract the existing name-loop verbatim so draw order is preserved: `noun = sample(...)`, then `rng.random() < 0.5` coin, then surname/prefix `sample(...)`, blocklist check):

```python
    def fictional_business_name(self, rng: random.Random, category: str) -> str:
        """Invented AU business NAME only (blocklist-screened); no address/ABN.

        Raises:
            ValueError: `category` has no entry in business_name_parts.category_nouns.
            RuntimeError: the retry budget was exhausted without a clean name.
        """
        parts = self.pools["business_name_parts"]
        nouns = parts["category_nouns"].get(category)
        if not nouns:
            raise ValueError(
                "content_engine.fictional_business_name: unknown category.\n"
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
                return name
        raise RuntimeError(
            "content_engine.fictional_business_name: exhausted retry budget without a clean name.\n"
            f"  What:     {max_attempts} draws for category {category!r} all collided with "
            "the real-name blocklist.\n"
            f"  Where:    {_DATA_POOLS_PATH} -> 'business_name_parts' (category {category!r}) "
            "and 'real_name_blocklist_extra'.\n"
            "  Expected: enough surname/noun combinations for the category to clear the "
            f"blocklist within {max_attempts} attempts.\n"
            "  Recover:  widen 'business_name_parts.surnames', 'suburb_prefixes', or "
            f"'category_nouns.{category}' in {_DATA_POOLS_PATH}."
        )

    def fictional_business(self, rng: random.Random, category: str) -> dict:
        """Invented AU business (blocklist-screened) + generate_abn() + address.

        Returns:
            {name, address, abn, category}.
        """
        name = self.fictional_business_name(rng, category)
        return {
            "name": name,
            "address": self.address(rng),
            "abn": generate_abn(),
            "category": category,
        }
```

(The draw order inside `fictional_business` is unchanged: name loop → address → ABN → so its output is byte-identical for a given seed.)

- [ ] **Step 4: Use the name-only helper in `_draw_bank_description`**

In `scripts/seed_ground_truth.py`, change the merchant line to skip the discarded address/ABN:

```python
    merchant = engine.fictional_business_name(
        rng, sample(rng, engine.pools["receipt_categories"] + engine.pools["service_categories"])
    )[:12].upper()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_content_engine.py -v`
Expected: all pass (name-only screened; `fictional_business` unchanged/deterministic).

- [ ] **Step 6: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/content_engine.py scripts/seed_ground_truth.py
conda run -n synthetic ruff format generators/content_engine.py scripts/seed_ground_truth.py
conda run -n synthetic mypy generators/content_engine.py scripts/seed_ground_truth.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add generators/content_engine.py scripts/seed_ground_truth.py
git commit -m "♻️ refactor: name-only fictional_business_name for bank descriptions"
```

### Task 4: Item 2 — `distribution_date` derived from `income_year`

**Files:** Modify `scripts/seed_trust_distributions.py`, `tests/test_seed_trust_distributions_dry_run.py`.

**Interfaces:**
- Produces: `_distribution_date(rng, income_year) -> str` — a `DD/MM/YYYY` date in [1 Jul end-year, 30 Jun end-year+1], where end-year = start-year+1 of the `"YYYY-YY"` income year. Deterministic.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_seed_trust_distributions_dry_run.py`:

```python
from datetime import date


def test_distribution_date_follows_income_year():
    import scripts.seed_trust_distributions as std

    for iy, start_year in (("2022-23", 2022), ("2023-24", 2023), ("2024-25", 2024)):
        end_year = start_year + 1
        lo = date(end_year, 7, 1)
        hi = date(end_year + 1, 6, 30)
        for seed in range(50):
            import random as _r
            d = std._distribution_date(_r.Random(seed), iy)
            dd, mm, yy = (int(x) for x in d.split("/"))
            got = date(yy, mm, dd)
            assert lo <= got <= hi, f"{iy}: {d} outside [{lo}, {hi}]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_seed_trust_distributions_dry_run.py -v -k distribution_date_follows`
Expected: FAIL — `AttributeError: ... '_distribution_date'`.

- [ ] **Step 3: Implement `_distribution_date` and use it**

In `scripts/seed_trust_distributions.py`, add `from datetime import date, timedelta` to the imports, then add:

```python
def _distribution_date(rng: random.Random, income_year: str) -> str:
    """DD/MM/YYYY date in the 12 months after the income year ends.

    income_year is "YYYY-YY" (e.g. "2023-24"); the year ends 30 Jun of
    start_year+1, and a trust distributes in the following financial window
    (1 Jul end_year .. 30 Jun end_year+1).
    """
    start_year = int(income_year.split("-")[0])
    end_year = start_year + 1
    lo = date(end_year, 7, 1)
    span = (date(end_year + 1, 6, 30) - lo).days
    d = lo + timedelta(days=rng.randint(0, span))
    return f"{d.day:02d}/{d.month:02d}/{d.year}"
```

Replace `distribution_date = _rand_date(rng, 2024, 2024)` (line ~144) with:

```python
        distribution_date = _distribution_date(rng, income_year)
```

(`income_year` is drawn on the preceding line, so it is in scope.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_seed_trust_distributions_dry_run.py -v`
Expected: all pass.

- [ ] **Step 5: Quality gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 scripts/seed_trust_distributions.py
conda run -n synthetic ruff format scripts/seed_trust_distributions.py
conda run -n synthetic mypy scripts/seed_trust_distributions.py --ignore-missing-imports
conda run -n synthetic pytest tests/
git add scripts/seed_trust_distributions.py
git commit -m "✨ feat: derive trust distribution_date from income_year"
```

---

## Stage 1C-ii — Coordinated reseed

### Task 5: Reseed corpus + regenerate baselines + full gate

**Files:** Modify (generated) all `ground_truth/*.yml` + both link files; regenerate `tests/fixtures/*_baseline_hashes.json` + `tis_ref_CASE201.png` (gitignored).

- [ ] **Step 1: Confirm clean start** — `git status --porcelain` empty (Tasks 1-4 committed).

- [ ] **Step 2: Run the full reseed IN ORDER**

```bash
conda run -n synthetic python scripts/seed_ground_truth.py
conda run -n synthetic python scripts/seed_transaction_links.py
conda run -n synthetic python scripts/seed_trust_distributions.py
conda run -n synthetic python scripts/seed_trust_distribution_links.py
```
Expected: `Wrote 55 ...` ×4; `Generated 110 transaction links: {'easy': 48, 'medium': 41, 'hard': 21}`; `Wrote 50 ...` ×4; `Generated 50 trust distribution links: 35 compliant, 15 non-compliant`.

- [ ] **Step 3: Prove determinism** — re-run the 4 scripts a second time; `find ground_truth -name '*.yml' | sort | xargs shasum | shasum` must equal the first run's aggregate hash (byte-identical). If not, STOP — a non-deterministic draw slipped in.

- [ ] **Step 4: Validation gate**

```bash
conda run -n synthetic python -m generators.pipeline validate     # "Validation passed." exit 0
```
Plus the invariant checks (revert with `git checkout -- ground_truth/` and STOP on any failure): transaction links 110 (48/41/21) precision/recall/f1=1.0, 110 TP; trust 50/50 quads, 35/15; GST=total/11 for all 55 receipts; PAYER_NAME identical across bank/cc/invoice for all 55 cases; SHARE_OF_NET_INCOME reconciles for compliant cases. (Use the same inline `python -c` checks as the Phase 1B reseed — see `content-reseed-workflow` memory / the 1B plan Tasks 10a/10b.)

- [ ] **Step 5: Regenerate the content-pinned fixtures**

Render each entry with `layouts[entry["layout"]]`, hash `sha256(img.tobytes())`, key `f"{case_id}_{layout}"`, write `tests/fixtures/{bank,cc,invoice,receipt,trust_return,beneficiary_itr,distribution_statement,trust_income_schedule}_baseline_hashes.json`; and re-save `tests/fixtures/tis_ref_CASE201.png` from `render_trust_income_schedule(CASE201, trust_income_schedule_standard)`. (Reuse the capture scripts from the Phase 1B reseed.)

- [ ] **Step 6: Full suite + leak check**

```bash
conda run -n synthetic pytest tests/ -q            # all green
```
Plus the 0-real-name-leak check (word-boundary sweep of every field against the blocklist) — must be 0.

- [ ] **Step 7: Commit**

```bash
git add ground_truth/
git commit -m "🌱 content: reseed corpus for income-year-aligned dates and name-only bank merchants"
```
(`tests/` fixtures are gitignored — not staged.)

---

## Self-Review notes (author)

- **Spec coverage:** §2.1→Task 2, §2.2→Task 4, §2.3→Task 3, §2.4→Task 1; §3 sequencing→Stage split; §4 gate→Task 5 Steps 3-6; §5 testing→each task's tests.
- **Byte-identity isolation:** Task 2 verifies item 1 is byte-identical via a dry-run hash compare against the CURRENTLY committed corpus (run BEFORE Task 3/4 shift the stream). Tasks 3/4 intentionally change the corpus; Task 5's reseed absorbs both, and the determinism re-run (Step 3) proves reproducibility.
- **Ordering:** Task 1 (loader, orthogonal) first; Task 2 (byte-identical) before 3/4 so its no-change property is verifiable in isolation; Task 5 reseeds last.
- **Assumption to confirm at implementation:** `seed_ground_truth.py` may need a small `build_all_entries()` extraction (Task 2 Step 6) if `main(dry_run=True)` doesn't already expose the in-memory dict; keep `main` behavior identical.
