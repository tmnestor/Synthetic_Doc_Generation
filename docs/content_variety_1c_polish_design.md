# Phase 1C — Deferred-Minor Polish: Design Spec

> Status: approved design (brainstorming output, 2026-07-23). Closes the four
> non-blocking Minor findings from the Phase 1B whole-branch review. No new
> features and no renderer changes — code/config cleanup plus a coordinated
> reseed to absorb the two content-affecting items. Builds on Phase 1B (merged to
> `main`, tip 5d70833).

Related: [`docs/content_variety_1b_content_widening_design.md`](content_variety_1b_content_widening_design.md)
(the phase this polishes). The four items are recorded in the Phase 1B final review
and the `content-reseed-workflow` memory.

---

## 1. Goal

Resolve the four deferred Minors without regressing any Phase 1B invariant. Keep
the corpus fully reproducible (deterministic seed=42) and every gate green. Two
items change the corpus (a reseed absorbs them); one is a pure code+test change;
one is byte-identical by construction.

## 2. Items

### 2.1 Item 1 — receipt/service categories → YAML (single source)
**Problem:** `scripts/seed_ground_truth.py` holds `_RECEIPT_CATEGORIES`,
`_SERVICE_CATEGORIES`, `_ALL_CATEGORIES` as Python constants — content-adjacent
config invisible in YAML (mild YAML-single-source gap). The receipt-vs-service
partition is semantic and NOT derivable from `business_name_parts.category_nouns`
keys alone.

**Fix:** Add `receipt_categories` and `service_categories` (lists) to
`config/data_pools.yml`, verbatim the current Python values and order. Add both to
`content_engine._REQUIRED_KEYS` (each `[]` — leaf lists). The seed script reads
`engine.pools["receipt_categories"]` / `["service_categories"]` and derives
`all_categories = receipt + service` locally. Delete the three Python constants.

**Corpus impact:** none — byte-identical if the YAML values/order match the current
constants and the seed reads them in the same order (verified by the post-change
reseed producing a corpus that differs ONLY where items 2/3 intend).

### 2.2 Item 2 — `distribution_date` derived from `income_year`
**Problem:** `scripts/seed_trust_distributions.py` pins
`distribution_date = _rand_date(rng, 2024, 2024)` while `income_year` spreads
2022-23 / 2023-24 / 2024-25 — mild temporal oddity (a 2022-23 distribution dated
2024, or a distribution that could predate its income year).

**Fix:** Derive the date from the case's `income_year`. Parse `"YYYY-YY"` → the
calendar year the income year ENDS (e.g. `"2023-24"` → 2024). Draw a seeded date in
the ~12 months following year-end: **1 July of end-year through 30 June of
end-year+1** (a trust distributes after the income year closes). Deterministic via
the existing `rng`. Keep the `DD/MM/YYYY` output format.

**Corpus impact:** yes — `DATE_OF_DISTRIBUTION` values change (spread + made
consistent with `income_year`).

### 2.3 Item 3 — name-only bank-description merchant
**Problem:** `_draw_bank_description` (`scripts/seed_ground_truth.py`) calls
`engine.fictional_business(rng, ...)["name"][:12].upper()` — builds a full business
(name + Faker address + `generate_abn()`) only to keep 12 chars of the name.
Wasteful, and the discarded draws consume RNG.

**Fix:** Add `ContentEngine.fictional_business_name(rng, category) -> str` — the
invented name only (surname/suburb-prefix + category noun, blocklist
reject-and-redraw, four-element fail-fast on exhaustion), no address/ABN. Refactor
`fictional_business` to DELEGATE to it (`fictional_business` = `fictional_business_name`
result + `self.address(rng)` + `generate_abn()`), so `fictional_business`'s draw
order and output are UNCHANGED (name draws first, then address, then ABN).
`_draw_bank_description` switches to `fictional_business_name`, dropping the
address/ABN draws. Keep the existing `[:12].upper()` abbreviation — real EFTPOS
merchant tokens hard-truncate; changing the truncation is out of scope.

**Corpus impact:** yes — `fictional_business` output is byte-identical, but
`_draw_bank_description` no longer draws the Faker-address / global-ABN stream, so
those shared streams advance differently from the first bank description onward,
shifting downstream identifier/address values corpus-wide. (Selection determinism
still holds; a re-run reproduces the new corpus exactly.)

### 2.4 Item 4 — `load_pools` hardening
**Problem:** `generators/content_engine.py::load_pools` mishandles two malformed
inputs (noted in the Task 1 review): a required nested-key parent that exists but
isn't a mapping (reuses the misleading "not found" message), and an empty file
(`yaml.safe_load` → `None` → raw `TypeError` instead of a diagnostic).

**Fix:** Add two explicit checks with four-element diagnostics:
- `yaml.safe_load(...)` returns a non-`dict` (empty/`None`/scalar file) → diagnostic
  "pools file is empty or not a mapping".
- a required key whose value must be a mapping (has subkeys) is present but not a
  `dict` → diagnostic naming the key and that it must be a mapping (distinct from
  the missing-key message).
TDD with the shared `assert_diagnostic_error` helper.

**Corpus impact:** none (loader robustness only).

## 3. Sequencing

1. **Code/config, no reseed yet:** Item 1 (YAML + loader read + delete constants),
   Item 3 (engine `fictional_business_name` + refactor + use in bank desc),
   Item 2 (`distribution_date` derivation), Item 4 (loader hardening). Each is
   TDD-tested; the seed scripts' `--dry-run` validates in-memory without writing.
2. **Coordinated reseed** (absorbs items 1–3): run the 4 seed scripts in order
   (`seed_ground_truth` → `seed_transaction_links` → `seed_trust_distributions` →
   `seed_trust_distribution_links`), regenerate the 8 `tests/fixtures/*_baseline_hashes.json`
   + `tis_ref_CASE201.png`, then the full gate.

Item 4 has no corpus impact and can land before or independent of the reseed.

## 4. Gate (unchanged from 1B; all must pass)

- `python -m generators.pipeline validate` → "Validation passed." (all 8 types).
- Transaction links 110 (easy 48 / medium 41 / hard 21), precision/recall/f1 = 1.0.
- Trust 50/50 quads, 35 compliant / 15 non-compliant (`_COMPLIANT_CASES=35`).
- GST = total/11 for all 55 receipts; `PAYER_NAME` identical across bank/cc/invoice
  for all 55 cases; `SHARE_OF_NET_INCOME` reconciles for compliant trust cases.
- Full local suite green; 0 blocklisted real names in any field.
- **Determinism:** re-running the 4 seed scripts reproduces a byte-identical corpus
  (aggregate-hash stable across runs).

## 5. Testing (TDD, local `tests/`)

- Item 1: `receipt_categories`/`service_categories` present in `data_pools.yml` and
  enforced by `_REQUIRED_KEYS`; seed derives `all_categories` from them.
- Item 2: `distribution_date` parses/derives from `income_year` — the drawn date's
  year is `end_year` or `end_year+1` and never precedes 1 July of `end_year`; format
  `DD/MM/YYYY`; deterministic for a fixed seed.
- Item 3: `fictional_business_name` never emits a blocklisted name (300-draw),
  fails fast on retry exhaustion, returns a name only (no address/ABN);
  `fictional_business` output is UNCHANGED by the refactor (same seed → same dict).
- Item 4: empty/non-mapping file and non-mapping nested parent each raise a
  four-element diagnostic (via `assert_diagnostic_error`).
- Reseed: post-reseed gate (§4) passes; baselines/PNG regenerated for the new corpus.

## 6. Scope / non-goals

**In scope:** the four deferred Minors + the reseed they require. **Out of scope:**
renderer changes (none); the edge-case matrix (refunds/GST-mixes/near-dupes);
deep narrative grammar; corpus growth; LLM-seeded pools; changing the
`[:12]` bank-merchant truncation; widening `distribution_date` beyond the
income-year-derived window.

## 7. Key files

- `config/data_pools.yml` — add `receipt_categories`, `service_categories` (Item 1).
- `generators/content_engine.py` — `_REQUIRED_KEYS` += the two category keys;
  `fictional_business_name` + `fictional_business` refactor (Item 3); `load_pools`
  hardening (Item 4).
- `scripts/seed_ground_truth.py` — read categories from pools, delete constants
  (Item 1); use `fictional_business_name` in `_draw_bank_description` (Item 3).
- `scripts/seed_trust_distributions.py` — `distribution_date` derived from
  `income_year` (Item 2).
- `ground_truth/*.yml`, `ground_truth/{transaction_links,trust_distribution_links}.yml`
  — rewritten by the reseed (git-tracked, revertible).
- `tests/fixtures/*_baseline_hashes.json`, `tests/fixtures/tis_ref_CASE201.png` —
  regenerated after the reseed (gitignored, local-only).
