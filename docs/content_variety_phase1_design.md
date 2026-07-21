# Phase 1 — Content Variety: Design Spec

> Status: approved design (brainstorming output). Widens the *content* that fills
> the documents (people, addresses, merchants, products, narratives) to kill the
> entity-repetition described in `docs/content_variety_options.md`. Builds on the
> merged fit-safety work (PR #1) on `main`.

Related: [`docs/content_variety_options.md`](content_variety_options.md) (options paper),
[`docs/fit_safety_design.md`](fit_safety_design.md) (the guardrail this depends on).

---

## 1. Goal

Every document draws from a large, varied content space so a reader (human or
LLM) no longer sees the same ~15 people, ~20 merchants, ~10 suburbs and ~40
line-items recur across the corpus. The document **count is unchanged** — only
the content that fills the existing set is widened.

## 2. Decomposition & sequence

Phase 1 is **two sub-projects, implemented in order**. Each gets its own
implementation plan and its own reseed/validation cycle.

- **1A — Trust/tax renderer fit-safety (prerequisite).**
- **1B — Content widening + coordinated reseed.**

**Hard gate (non-negotiable):** no content widening ships until *every* renderer
is fit-safe. The trust/tax renderers currently have no overflow protection and
the backstop cannot detect their clipping (it only catches `FitError`, which
those renderers never raise). Widening into them would silently clip/truncate —
the exact benchmark corruption Phase 0 eliminated. **Trust renderers must not
clip.** 1A closes that gap before 1B begins.

---

## 3. Sub-project 1A — Trust/tax renderer fit-safety

Apply the Phase 0 mechanism (already on `main`) to the 4 trust/tax renderers:
`trust_return`, `distribution_statement`, `trust_income_schedule`,
`beneficiary_itr`.

**Per renderer:**
1. Enumerate the variable fields it draws (names, addresses, ABN/TFN lines,
   line-item/schedule descriptions, amounts).
2. Derive per-field pixel budgets from the renderer's current geometry and commit
   them to the corresponding `config/layouts/*.yml` as `field_budgets`
   (all keys required: `width`, `fit`, `min_font`, `max_lines`).
3. Route text draws through `draw_fitted_left/center/right` / `fit_text`
   (from `generators/common.py`), matching the fit strategy per field class
   (columns/amounts `shrink`, wrappable text `wrap`/`shrink_then_wrap` —
   descriptions wrap, never shrink, to keep font uniform).
4. Capture pristine per-renderer baselines and prove **byte-identical** output
   where current content fits; fix any pre-existing clip/truncation the way
   Phase 0 did (fix, don't enshrine).

**Outcome:** all 8 doc types are fit-safe. The existing overflow backstop
(`generators/overflow_check.py`) then covers the trust types automatically —
their renderers now raise `FitError` on impossible fit, which `validate` and
`generate` already catch.

**Determinism preconditions** (already established, must hold): measure with the
bundled DejaVu font; `pillow==12.2.0` (matches the PROD Artifactory mirror);
fail loud on non-bundled font.

---

## 4. Sub-project 1B — Content widening architecture

### 4.1 Mechanism
- **Faker (`en_AU`)** for people and addresses — already pinned (`faker==40.8.0`),
  locale-aware, deterministic (`Faker.seed`). Kills person/address repetition.
- **Curated pools** for domain content Faker can't do well — merchants, products,
  service catalogs, transaction narratives, GST-correct line items.
- **`generate_abn()`** for every ABN (never real ABNs), preserving the checksum.

### 4.2 Fully fictional businesses
Generate plausible invented AU business names per category (e.g. hardware,
grocery, legal, accounting) from curated name-parts, each paired with a
`generate_abn()` ABN. Screen every generated name against a **real-name
blocklist** (the current real retailers + a curated list) so no real entity is
emitted. Removes real-entity/privacy exposure and gives unlimited merchant
variety.

### 4.3 YAML is the single source of truth
`config/data_pools.yml` becomes the sole content source:
- All curated pools move here: fictional-merchant name-parts by category,
  product/SKU catalogs, service catalogs, transaction-narrative grammar, street
  types, the real-name blocklist.
- Faker settings are config keys (`locale: en_AU`, seed base).
- The in-script constants in `scripts/seed_ground_truth.py` (`_RETAILERS`,
  `_ACCOUNT_HOLDERS`, `_LOCATIONS`, `_BANKS`, `_BANK_DESCS`, `_INVOICE_SERVICES`,
  `_RECEIPT_ITEMS`, `_PROFESSIONAL_SERVICES`, `_PAYMENT_METHODS`) are **deleted**;
  the seed script reads only YAML. Missing keys fail fast with a diagnostic.

### 4.4 Kill deterministic cycling
Replace the `[i % len(pool)]` modulo indexing (which makes the same entities
appear in the same order across every doc type) with proper seeded sampling, so
entity selection is varied and de-correlated across documents.

---

## 5. Reseed & linking integrity

One **coordinated, atomic reseed** with a validation gate — entries and links can
never disagree:

1. Regenerate all `ground_truth/*.yml` entries from the widened YAML pools.
2. Regenerate links **derived from those same entries**
   (`seed_transaction_links.py`, `seed_trust_distribution_links.py`), so a
   receipt/invoice ↔ bank-transaction match at easy/medium/hard difficulty stays
   valid by construction.
3. **Validation gate — all must pass or nothing ships:**
   - `python -m generators.pipeline validate` (schema + layout references +
     overflow backstop across all 8 now-fit-safe types).
   - Linking metrics compute: precision/recall/F1 overall and per difficulty via
     the existing `linking/` module; link counts match expectations.
   - Invariants hold: ABN checksum; `GST = total / 11` when `IS_GST_INCLUDED`;
     pipe-delimited `LINE_ITEM_*` counts aligned; amounts decimal-string without
     `$`; dates `DD/MM/YYYY`; `CASE###` IDs shared across the 4 core types.

A full destructive reseed is accepted; it rewrites the 220 core entries, the
trust cases, and their link files in lockstep.

## 6. Determinism

Keep per-document RNG seeding; add `Faker.seed(n)` tied to the same per-document
scheme so a reseed is reproducible and diffable run-to-run. Consistent with the
existing `faker==40.8.0` / `pillow==12.2.0` pins.

## 7. Testing (TDD, local `tests/`)

- **1A:** per-trust-renderer budget presence, no-overflow, byte-identical
  regression (mirror the Phase 0 renderer tests).
- **1B:** name/address generators (shape, locale); fictional-merchant generator +
  real-name blocklist screen (never emits a blocklisted name); pool loaders
  fail-fast on missing YAML keys (four-element diagnostic); invariant preservation
  (ABN/GST/pipe-count/date/amount); determinism (same seed → identical entries);
  no-modulo-cycling (entity distribution is varied, not lockstep).
- **Coordinated reseed:** post-reseed `validate` exits 0; linking metrics compute
  with expected counts.

## 8. Scope / non-goals

**In scope:** trust/tax fit-safety (1A); Faker + fictional-merchant generation;
consolidation of all pools into `data_pools.yml`; removal of in-script constants
and modulo cycling; coordinated reseed of entries + links with a validation gate.

**Out of scope (later phases):** deep procedural narrative grammar (full Option 2);
the edge-case matrix — refunds, GST mixes, near-duplicates, awkward strings
(Phase 3); growing the corpus size; LLM-seeded pools (Option 5).

## 9. Key files

- `config/data_pools.yml` — becomes the single content source (pools + Faker config + blocklist).
- `config/layouts/{trust_returns,distribution_statements,trust_income_schedules,beneficiary_itrs}.yml` — gain `field_budgets` (1A).
- `generators/{trust_return,distribution_statement,trust_income_schedule,beneficiary_itr}.py` — routed through `fit_text` (1A).
- `scripts/seed_ground_truth.py` — reads only YAML; Faker + fictional-merchant generation; seeded sampling (1B).
- `scripts/seed_transaction_links.py`, `scripts/seed_trust_distribution_links.py` — re-derive links from reseeded entries.
- `generators/common.py`, `generators/layout_budgets.py`, `generators/overflow_check.py` — reused as-is from fit-safety.
