# PBI Title
Increase content variety in synthetic document dataset (Phase 1–2)

## Description
The synthetic document dataset (ref #5147048) was flagged for insufficient
**content** variety. Layouts already vary (30 layouts), but the textual/numeric
content is drawn from small hand-authored pools (~15 account holders, ~20
merchants, ~10 suburbs, ~40 line-item types), so entities repeat across all 220
documents. Analysis and a phased roadmap are documented in
`docs/content_variety_options.md`.

This PBI delivers the first two phases of that roadmap:
1. **Expand the content pools** and add **combinatorial name generation**.
2. **Procedural composition** of transaction descriptions and line-items from
   primitives/catalogs (rather than fixed literals).

The result: the 220 documents draw from a much larger, more realistic content
space, while preserving all data invariants and the transaction-linking ground
truth.

**Out of scope (candidate follow-up PBIs):** semantic edge-case matrix (Phase 3),
Faker / open-dataset integration, and LLM-seeded content pools.

## Acceptance Criteria
- [ ] Combinatorial name generation implemented; distinct account-holder names
      across the corpus increases from 15 to **≥ 100**.
- [ ] Merchant, suburb/postcode, product, service, and trust pools expanded;
      distinct merchants and suburbs appearing in generated output increase
      correspondingly (targets agreed with team).
- [ ] Transaction descriptions and line-items are generated **procedurally**
      from primitives/catalogs, not fixed literal lists.
- [ ] All data invariants hold: `python -m generators.pipeline validate` passes;
      ABNs pass the checksum; `GST = total / 11`; pipe-delimited `LINE_ITEM_*`
      counts match.
- [ ] Ground truth reseeded **deterministically** (fixed RNG seed → reproducible
      output). `transaction_links.yml` and trust-distribution links re-seeded in
      lockstep; linking precision/recall/F1 not regressed.
- [ ] Local tests updated and passing (≥ 80% coverage per project standard).
- [ ] README / relevant docs updated to describe the new pools and generators.

## Suggested Tasks
- [ ] Restructure `config/data_pools.yml` (split names into first/last; expand
      merchants, suburbs, trusts, services).
- [ ] Implement combinatorial name + address generators.
- [ ] Refactor `scripts/seed_ground_truth.py` to procedural composition; expand
      product (`_RECEIPT_ITEMS`) and service (`_INVOICE_SERVICES`) catalogs.
- [ ] Re-seed ground truth + all linking files; run validation.
- [ ] Add a variety-metrics check (distinct-entity counts before/after).
- [ ] Update tests and docs; regenerate images.

## Definition of Done
Acceptance criteria met · `validate` passes · tests green · code reviewed &
merged · images regenerated · change demoed at sprint review.

---
**Area:** EST\SDP\MDT\GEN AI
**Iteration:** PI49 · Sprint 49.2  *(set to your next 2-week sprint)*
**Tags:** synthetic-data; content-variety; gen-ai
**Effort/Story Points:** _<set at planning>_
