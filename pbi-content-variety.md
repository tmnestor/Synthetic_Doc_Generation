# PBI Title
Increase content variety in synthetic document dataset (Phase 1–2)

## Description
The synthetic document dataset (ref #5147048) was flagged for insufficient
**content** variety. Layouts already vary (30 layouts), but the textual/numeric
content is drawn from small hand-authored pools (~15 account holders, ~20
merchants, ~10 suburbs, ~40 line-item types), so entities repeat across all 220
documents. Analysis and a phased roadmap are documented in
`docs/content_variety_options.md`.

This PBI delivers:
0. **Fit safety (prerequisite)** — per-field width/char budgets, generation-time
   fitting, and fail-fast overflow validation, so richer content cannot overflow
   the fixed layouts. See §3a of the options doc.
1. **Expand the content pools** and add **combinatorial name generation**.
2. **Procedural composition** of transaction descriptions and line-items from
   primitives/catalogs (rather than fixed literals).

The result: the 220 documents draw from a much larger, more realistic content
space **while preserving the pixel-perfect image ↔ ground-truth contract** and
all data invariants and transaction-linking ground truth.

**Out of scope (candidate follow-up PBIs):** semantic edge-case matrix (Phase 3),
Faker / open-dataset integration beyond names/addresses, and LLM-seeded pools.

## Acceptance Criteria
### Fit safety (must land with the variety work)
- [ ] Every variable text field has an explicit width/char **budget** defined in
      the layout config (`config/layouts/*.yml`).
- [ ] Generated content is **fitted** to its field (measured with the actual
      font); ground truth equals exactly what is rendered — **no clipping,
      column overlap, or silent truncation**.
- [ ] `python -m generators.pipeline validate` **fails** if any field would
      overflow its box (fail-fast overflow check added).
- [ ] Any renderer-side fitting is **lossless** (shrink-to-fit or wrap); the
      displayed string is never silently shortened relative to ground truth.

### Content variety
- [ ] Combinatorial name generation implemented; distinct account-holder names
      across the corpus increases from 15 to **≥ 100**.
- [ ] Merchant, suburb/postcode, product, service, and trust pools expanded;
      distinct merchants and suburbs appearing in generated output increase
      correspondingly (targets agreed with team).
- [ ] Transaction descriptions and line-items are generated **procedurally**
      from primitives/catalogs, not fixed literal lists.

### Integrity (unchanged invariants)
- [ ] ABNs pass the checksum; `GST = total / 11`; pipe-delimited `LINE_ITEM_*`
      counts match; amounts decimal strings; dates `DD/MM/YYYY`.
- [ ] Ground truth reseeded **deterministically** (fixed RNG seed → reproducible
      output). `transaction_links.yml` and trust-distribution links re-seeded in
      lockstep; linking precision/recall/F1 not regressed.
- [ ] Local tests updated and passing (≥ 80% coverage per project standard).
- [ ] README / relevant docs updated to describe the new pools and generators.

## Suggested Tasks
- [ ] Add per-field width/char budgets to `config/layouts/*.yml`.
- [ ] Implement generation-time fit (measure with actual font; regenerate /
      shorten to fit); optional lossless shrink/wrap safety net in renderers.
- [ ] Add fail-fast overflow validation to `pipeline validate`.
- [ ] Restructure `config/data_pools.yml` (split names into first/last; expand
      merchants, suburbs, trusts, services).
- [ ] Implement combinatorial name + address generators (Faker-backed).
- [ ] Refactor `scripts/seed_ground_truth.py` to procedural composition; expand
      product (`_RECEIPT_ITEMS`) and service (`_INVOICE_SERVICES`) catalogs.
- [ ] Re-seed ground truth + all linking files; run validation.
- [ ] Add a variety-metrics check (distinct-entity counts before/after).
- [ ] Update tests and docs; regenerate images.

## Definition of Done
Acceptance criteria met (incl. fit-safety) · `validate` passes · tests green ·
code reviewed & merged · images regenerated and spot-checked for overflow ·
change demoed at sprint review.

---
**Area:** EST\SDP\MDT\GEN AI
**Iteration:** PI49 · Sprint 49.2  *(set to your next 2-week sprint)*
**Tags:** synthetic-data; content-variety; fit-safety; gen-ai
**Effort/Story Points:** _<set at planning>_
