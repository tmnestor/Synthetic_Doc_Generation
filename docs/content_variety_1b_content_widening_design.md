# Phase 1B — Content Widening + Coordinated Reseed: Design Spec

> Status: approved design (brainstorming output, 2026-07-23). Widens the *content*
> that fills all 8 document types so the corpus no longer repeats the same ~15
> people, ~20 merchants, ~10 suburbs, trust/beneficiary names, and line-items. The
> document **count is unchanged** — only the content that fills the existing set is
> widened. Builds directly on the merged Phase 1A fit-safety work (`main`, tip
> 5cf85f2): every renderer is now fit-safe, so widened content can only wrap/shrink
> losslessly or raise `FitError` — never silently clip.

Related: [`docs/content_variety_phase1_design.md`](content_variety_phase1_design.md)
(the parent Phase 1 spec; this doc is the focused 1B sub-project, extending its
§4–§7 with the all-8-types scope, trust-content architecture, and two-stage
sequencing decided during 1B brainstorming),
[`docs/content_variety_1a_trust_fit_safety_plan.md`](content_variety_1a_trust_fit_safety_plan.md)
(the completed prerequisite).

---

## 1. Goal

Every document draws from a large, varied, de-correlated content space, across
**all 8 doc types** (4 core: bank / receipt / invoice / cc; 4 trust/tax:
trust_return / distribution_statement / trust_income_schedule / beneficiary_itr).
A reader (human or LLM) no longer sees the same entities recur across the corpus,
and entity selection is no longer correlated across doc types. Count unchanged
(220 core + trust cases); only the fill content widens.

## 2. Scope decisions (from 1B brainstorming)

- **All 8 doc types are widened** (not just the 4 core types). 1A fit-safed the 4
  trust/tax renderers precisely so content could be widened into them.
- **Two-stage sequencing:** build + validate the generation machinery WITHOUT
  overwriting the committed corpus (1B-i), then execute the atomic destructive
  reseed as its own reviewed step (1B-ii).
- **Shared content-engine module:** one testable module serves both the core and
  trust seed scripts (not logic duplicated per script).
- **Fully fictional businesses:** the current real retailers become the seed of a
  real-name blocklist; generation emits only invented AU businesses. No real
  entity is ever written.

## 3. Architecture & module boundaries

### 3.1 `generators/content_engine.py` (new — the shared module)
Loads `config/data_pools.yml` once at construction and fails fast (four-element
diagnostic: what / where — absolute path + dotted YAML key / valid example / how to
recover) on any missing key. Owns a seeded `Faker("en_AU")`. Exposes the primitives
both seed scripts call:

- `person(rng) -> dict` — Faker `en_AU` person (name + parts).
- `address(rng) -> str` — Faker `en_AU` Australian address.
- `fictional_business(rng, category) -> dict` — invented AU business name assembled
  from curated name-parts for the category, paired with `generate_abn()`. **Screened
  against the real-name blocklist:** a name that collides with a blocklisted real
  entity is rejected and re-drawn (bounded retries); the engine fails fast with a
  diagnostic only if it cannot produce a clean name within the retry budget — a
  signal that the category's name-part pool is too small or the blocklist too broad,
  not a per-document abort. A clean name is always emitted or the run stops loudly.
- `fictional_trust(rng) -> dict` — invented trust name (e.g. "The ⟨Surname⟩ Family
  Trust", "⟨Word⟩ Nominees Trust") from curated parts, paired with `generate_abn()`
  and `generate_tfn()`. Same reject-and-redraw blocklist screen as
  `fictional_business`.
- `sample(rng, pool)` and a non-repeating draw helper — replaces every
  `i % len(pool)` modulo cycle with seeded sampling.

Reuses `generate_abn()` and `generate_tfn()` from `generators/common.py` (both
already exist, both preserve their respective checksums). The engine never emits a
real ABN/TFN — always generated.

**Determinism:** every primitive is driven by an injected `random.Random` (or a
`Faker.seed(n)`) tied to the per-case seeding scheme, so a reseed is reproducible
and diffable run-to-run.

### 3.2 `config/data_pools.yml` (the single content source)
All curated content moves here; Python holds no content constants.

Migrated from `scripts/seed_ground_truth.py`: `_RETAILERS`, `_ACCOUNT_HOLDERS`,
`_LOCATIONS`, `_BANKS`, `_BANK_DESCS`, `_INVOICE_SERVICES`, `_RECEIPT_ITEMS`,
`_PAYMENT_METHODS`. Migrated from `scripts/seed_trust_distributions.py`:
`_TRUST_NAMES`, `_BENEFICIARY_FIRST_NAMES`, `_BENEFICIARY_LAST_NAMES`, and its
layout lists.

Restructured into: fictional-business name-parts by category; fictional-trust
name-parts; product/SKU + service catalogs; transaction-narrative grammar; bank
list + bank-description grammar; street types; the **real-name blocklist** (seeded
from the current real `retailers` pool + a curated list); and Faker config
(`locale: en_AU`, seed base). Every key is required — a missing key fails fast; no
silent Python default.

### 3.3 Seed scripts shrink to orchestration
- `scripts/seed_ground_truth.py`: per core case, pull an entity bundle from the
  engine and project it across the case's linked docs, keeping `CASE###` shared
  entities consistent across bank / receipt / invoice / cc. In-script constants
  deleted; reads only YAML via the engine.
- `scripts/seed_trust_distributions.py`: per trust case (CASE201–250), generate the
  shared trust entities (trust, trustee, beneficiary/individual) once and project
  them across the 4 trust docs — the structure that already keeps trust links valid.
  In-script constants deleted; reads only YAML via the engine.
- `scripts/seed_transaction_links.py`, `scripts/seed_trust_distribution_links.py`:
  re-derive links from the reseeded entries so every receipt/invoice ↔ bank match
  (easy/medium/hard) and every trust distribution link stays valid by construction.

### 3.4 Cross-case consistency invariant
Each case's shared entities are generated **once** and projected into all its linked
docs. A widened value can therefore never desync a link — links are a projection of
the same generated bundle, not an independent draw.

## 4. Kill deterministic cycling

Both seed scripts currently use `pool[i % len(pool)]`, which makes the same entities
appear in the same order across every doc type. Replace all such indexing with
seeded sampling from the engine, so entity selection is varied and **de-correlated
across documents**.

## 5. Two-stage sequencing

### Stage 1B-i — build + validate machinery (no corpus overwrite)
1. Create `generators/content_engine.py`.
2. Migrate all pools + blocklist + Faker config into `config/data_pools.yml`.
3. Delete the in-script constants from both seed scripts; rewire them to the engine.
4. Replace all modulo cycling with seeded sampling.
5. Prove it with **unit tests + a dry-run** that generates entries in-memory and
   validates them WITHOUT writing `ground_truth/*.yml`. The committed corpus is
   untouched at the end of 1B-i.

### Stage 1B-ii — coordinated destructive reseed
1. Execute the atomic reseed of all `ground_truth/*.yml` (core + trust).
2. Re-derive both link files from those same entries.
3. **Validation gate — all pass or nothing ships:**
   - `python -m generators.pipeline validate` — schema + layout references +
     overflow backstop across all 8 now-fit-safe types.
   - Linking metrics compute (precision / recall / F1 overall and per difficulty via
     the existing `linking/` module); link counts match expectations.
   - Invariants hold: ABN checksum; TFN checksum; `GST = total / 11` when
     `IS_GST_INCLUDED`; pipe-delimited `LINE_ITEM_*` counts aligned; amounts decimal
     string without `$`; dates `DD/MM/YYYY`; `CASE###` shared across the 4 core
     types.
   The reseed is git-tracked and therefore revertible; it lands as its own reviewed
   step.

## 6. Testing (TDD, local `tests/`)

- **Engine:** person/address shape + `en_AU` locale; `fictional_business` /
  `fictional_trust` never emit a blocklisted name (the screen rejects-and-redraws)
  and fail fast with a four-element diagnostic when a pool cannot yield a clean name
  within the retry budget; `sample` determinism (same seed → identical draws) and
  distribution spread (not lockstep); pool loaders fail-fast on missing YAML keys
  (four-element diagnostic, via the shared `assert_diagnostic_error` helper).
- **Invariant preservation:** ABN/TFN checksum, GST = total/11, pipe-count
  alignment, date format, amount format on generated entries.
- **Determinism:** same seed → byte-identical generated entries; no-modulo-cycling
  (entity distribution is varied, not lockstep across doc types).
- **Coordinated reseed (1B-ii):** post-reseed `validate` exits 0; linking metrics
  compute with expected counts; both link files re-derive consistently.

## 7. Scope / non-goals

**In scope:** shared `content_engine.py`; Faker `en_AU` people/addresses;
fictional-business and fictional-trust generation with a real-name blocklist screen;
consolidation of all core + trust pools into `data_pools.yml`; deletion of in-script
constants; removal of modulo cycling; coordinated destructive reseed of all 8 doc
types + both link files with a validation gate. All 8 renderers are already fit-safe
(1A) — no renderer changes in 1B.

**Out of scope (later phases):** deep procedural narrative grammar (full Option 2);
the edge-case matrix — refunds, GST mixes, near-duplicates, awkward strings (Phase
3); growing the corpus size; LLM-seeded pools (Option 5); the four non-blocking
Phase 1A final-review polish items (byte-identical-test count floor, section-type
derivation of the distribution have-budgets test, `AMOUNT_VALUE`-for-date naming,
two_column comment) — tracked separately, addressable opportunistically.

## 8. Key files

- `generators/content_engine.py` — NEW shared generation module (Faker + fictional
  generators + seeded sampling + blocklist screen + fail-fast pool loader).
- `config/data_pools.yml` — becomes the sole content source (all pools + name-parts
  + narrative grammar + blocklist + Faker config).
- `scripts/seed_ground_truth.py` — reads only YAML via the engine; seeded sampling;
  in-script constants deleted (1B-i); executes core reseed (1B-ii).
- `scripts/seed_trust_distributions.py` — same treatment for the 4 trust doc types.
- `scripts/seed_transaction_links.py`, `scripts/seed_trust_distribution_links.py` —
  re-derive links from reseeded entries (1B-ii).
- `generators/common.py` (`generate_abn`, `generate_tfn`), `generators/overflow_check.py`,
  `linking/` — reused as-is; no changes.
- `ground_truth/*.yml`, `ground_truth/{transaction_links,trust_distribution_links}.yml`
  — rewritten by the 1B-ii reseed (git-tracked, revertible).
