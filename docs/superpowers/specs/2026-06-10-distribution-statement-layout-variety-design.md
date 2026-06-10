# Distribution Statement Layout Variety — Design Spec

**Date:** 2026-06-10
**Status:** Approved (design); pending spec review
**Scope:** `Synthetic_Doc_Generation` — trust distribution flow, Distribution Statement document only

## Problem

The trust distribution flow is generated as 50 document quads across four YAML files
(`trust_returns`, `distribution_statements`, `trust_income_schedules`, `beneficiary_itrs`).
Each document type currently has **exactly one layout** applied to all 50 entries.

Our research (`ResearchSpikeReport/private_wealth_research_response.docx`) established that
the **Distribution Statement is the one document in the flow with no ATO proforma** — trustees
and their accounting software produce their own, so real-world layouts vary widely. The other
three documents are standardised ATO statutory forms (Trust Tax Return NAT 0660, Trust Income
Schedule, Individual Tax Return NAT 2541) whose layouts are effectively fixed.

A single Distribution Statement layout therefore under-represents reality and fails to test the
LMM's robustness to layout and label variation. This spec increases Distribution Statement layout
variety to match the research, **without changing any ground-truth values**.

## Goals

- Expand the Distribution Statement from 1 layout to **6 layouts** spanning 3 realistic archetypes.
- **Vary field labels** per layout (realistic synonyms), since real statements word the same field
  differently.
- **Reuse the existing ground truth**: field values, CASE ids, and degradation seeds stay
  byte-identical. Only each entry's `layout:` reference changes.
- Regenerate clean and degraded Distribution Statement images.

## Non-Goals

- No changes to the three ATO statutory forms (they have fixed proformas — varying them would be
  *less* research-consistent).
- No change to ground-truth field values, the compliant/non-compliant split, or the linking
  ground truth (`trust_distribution_links.yml`).
- No prose-embedded amounts. The "formal trustee resolution / minutes" archetype (amounts buried
  in numbered clauses) is explicitly excluded — it works against clean scalar extraction.
- No per-entry RNG style jitter (rejected Approach B). Variety is enumerable, YAML-driven config.

## Constraints (from repo CLAUDE.md)

- **YAML is the single source of truth.** All 6 layouts and their labels are fully specified in
  `config/layouts/distribution_statements.yml`. No layout/label values hardcoded in Python.
- **Fail fast with diagnostics.** Unknown layout references already fail in `pipeline.validate`
  with a diagnostic listing available layouts; this behaviour is preserved.
- Tests local-only (`tests/` gitignored), `pytest`, ≥80% coverage. Lint/format/type gates:
  `ruff check --fix`, `ruff format`, `mypy . --ignore-missing-imports`.
- Domain term "ATO" (Australian Taxation Office) is used as-is in this research domain.

## Design

### 1. Layout set — 3 archetypes × 2 variants

All defined in `config/layouts/distribution_statements.yml`. Every layout renders the identical
scalar field set: `TRUST_NAME`, `TRUST_ABN`, `TRUST_ADDRESS`, `BENEFICIARY_NAME`,
`BENEFICIARY_TFN`, `BENEFICIARY_ADDRESS`, `INCOME_YEAR`, `DATE_OF_DISTRIBUTION`,
`SHARE_OF_NET_INCOME`, `FRANKING_CREDIT`, `CAPITAL_GAIN_COMPONENT`, `FOREIGN_INCOME`,
`TAX_FREE_AMOUNT`, `TAX_DEFERRED_AMOUNT`.

| ID | Archetype | Distinguishing structure / style |
|---|---|---|
| `dist_software_navy` | Accounting-software | Navy title letterhead + accent rule; dotted-underline amount rows (refined current style) |
| `dist_software_teal` | Accounting-software | Filled teal header-bar with firm name; **two-column** trust/beneficiary block; amount rows |
| `dist_table_plain` | Tabular / grid | Identity as plain rows; light-bordered **2-column table** (Component \| Amount) |
| `dist_table_ruled` | Tabular / grid | Heavier ruled **3-column table** (Code \| Description \| Amount $); gray header row; **"Net income share" total row that displays `SHARE_OF_NET_INCOME`** (BGL/export look) |
| `dist_letter_formal` | Trustee letter | Letterhead, date, addressee block, salutation, body paragraph, indented component summary, **signature block** ("Trustee for <Trust>") |
| `dist_letter_compact` | Trustee letter | Short self-prepared look: small header, brief paragraph, compact boxed component summary, signature line |

**Invariant for every layout:** each component amount appears on its own clearly-labelled line or
table row — never as a long list, never embedded in prose. This preserves the scalar-extraction
property the research identified as the feasibility precondition.

The existing `distribution_statement_standard` id is retired; all entries migrate to one of the
six ids above.

### 2. Renderer / interpreter changes

`generators/distribution_statement.py::render_distribution_statement` remains a single
section-walking interpreter. Existing section types are retained: `letterhead`, `spacer`,
`section`, `separator`, `declaration`, `footer`. New section types added:

- `header_bar` — filled colored bar with title/subtitle (same visual pattern as the trust income
  schedule header bar).
- `two_column` — two field groups rendered side by side (e.g. trust details | beneficiary details).
- `table` — bordered table built from `columns` + `rows`, where each row maps to a component
  field; optional `total_row` that **displays a single named field** (e.g. `SHARE_OF_NET_INCOME`)
  as a labelled total row. It is a display reference, **not** a computed sum across rows — the
  components (franking credit, capital gain, foreign income, tax-free/deferred) are not arithmetic
  addends of net income, so summing them would fabricate a non-reconciling total.
- `letter_meta` — date line + addressee block (beneficiary name/address) + salutation.
- `letter_body` — word-wrapped paragraph(s) supporting `{INCOME_YEAR}` and `{TRUST_NAME}`
  substitution only. **Amounts are never substituted into prose.**
- `signature_block` — signature rule + "Trustee for <TRUST_NAME>" + date.

**Shared table helper.** The grid-drawing logic currently inlined in
`generators/trust_income_schedule.py` (the `grid_section` branch) is extracted into a reusable
`draw_table(...)` helper in `generators/common.py`. Both the trust income schedule renderer and
the new Distribution Statement `table` section type call it. This deepens a shallow duplication
rather than copy-pasting grid code into a second renderer. The trust income schedule output must
remain pixel-equivalent after the refactor (verified by its existing render test).

### 3. Label variation

Field **labels live in the layout YAML**; field **keys** are separate and unchanged. Varying
labels is therefore pure configuration with no extra renderer logic. Each layout selects from a
realistic synonym set. Representative synonyms (final wording assigned per layout in the YAML):

- `SHARE_OF_NET_INCOME` → "Share of net income" / "Net income distributed" / "Income entitlement"
  / "Beneficiary's share of net income"
- `FRANKING_CREDIT` → "Franking credit" / "Franking credits attached" / "Imputation credit"
- `CAPITAL_GAIN_COMPONENT` → "Capital gain component" / "Net capital gain" / "Share of capital gains"
- `FOREIGN_INCOME` → "Foreign income" / "Foreign source income" / "Assessable foreign income"
- `TAX_FREE_AMOUNT` → "Tax-free amount" / "Tax-free distribution"
- `TAX_DEFERRED_AMOUNT` → "Tax-deferred amount" / "Tax-deferred distribution"
- identity labels: "ABN" / "Australian Business Number"; "TFN" / "Tax file number";
  "Income year" / "Year ended 30 June 2024"

Because keys are unchanged, the linking evaluator (which matches on field values) is unaffected.

### 4. Layout assignment & ground-truth migration

**Assignment rule (deterministic, no RNG):** for entries CASE201–CASE250,
`layout = LAYOUTS[(case_no − 201) % 6]`. This yields a balanced spread of ~8–9 entries per
layout (50 = 6×8 + 2).

**Migration mechanism:** a new script `scripts/migrate_distribution_layouts.py` that:
1. Loads `ground_truth/distribution_statements.yml`.
2. For each entry, sets `entry["layout"]` per the assignment rule.
3. Rewrites the file, leaving `fields:`, `degradation_seed`, and CASE ids untouched.
4. Asserts (in-script) that the set of `fields` dicts is unchanged versus a pre-run snapshot,
   failing loudly if any value would change.

A `git diff` on `distribution_statements.yml` must show **only** `layout:` lines changed.

**Seed-script consistency:** `scripts/seed_trust_distributions.py` is updated so
`_DISTRIBUTION_STATEMENT_LAYOUTS` lists the six ids and its assignment uses the same index-based
rule (no RNG draw, so a future full reseed at `_SEED = 42` reproduces identical field values with
these layouts). The seed script is **not** re-run as part of this work — the migration is the
regeneration path — but the two remain in agreement.

### 5. Regeneration & output handling

1. Run `scripts/migrate_distribution_layouts.py`.
2. `python -m generators.pipeline validate` — all six refs resolve.
3. Delete stale outputs: `output/clean/distribution_statements/` and
   `output/degraded/distribution_statements/` (filenames embed the old
   `_distribution_statement_standard` and would otherwise orphan).
4. `python -m generators.pipeline generate --type distribution_statements` — fresh clean +
   degraded PNGs (`{case_id}_{layout_ref}.png`).
5. `python -m generators.pipeline derive` — CSV/JSONL (values unchanged; run for consistency).

The other three document types and `trust_distribution_links.yml` are untouched.

### 6. Testing & verification

Local tests (`pytest`, ≥80% coverage):

- `tests/test_renderers_trust.py` (extend): each of the 6 layouts renders without error, at the
  configured dimensions, producing a non-blank image. Exercise every new section type path:
  `table` including the `total_row`, `two_column`, `letter_meta`, `letter_body`,
  `signature_block`, `header_bar`.
- `tests/test_layout_assignment.py` (new): the index→layout mapping covers all 6 ids and is
  balanced (each id used 8–9 times across CASE201–CASE250); every ground-truth entry references a
  layout present in the registry.
- **Value-invariance test:** post-migration field values equal a committed pre-migration snapshot
  (proves "reuse the ground truth").
- **Refactor-safety test:** trust income schedule render output is unchanged after the `draw_table`
  extraction.
- Re-run `tests/test_ground_truth_trust.py` and `tests/test_linking_trust.py` to confirm linking
  is unaffected.
- Gates: `ruff check --fix --ignore ARG001,ARG002,F841 *.py`, `ruff format .`,
  `mypy . --ignore-missing-imports`.

## Files Touched

- `config/layouts/distribution_statements.yml` — replace single layout with 6 layouts.
- `generators/distribution_statement.py` — add new section-type handlers.
- `generators/common.py` — add shared `draw_table` helper.
- `generators/trust_income_schedule.py` — call shared `draw_table` (behaviour-preserving refactor).
- `scripts/migrate_distribution_layouts.py` — new migration script.
- `scripts/seed_trust_distributions.py` — update layout list + index-based assignment.
- `ground_truth/distribution_statements.yml` — `layout:` keys only (via migration).
- `output/clean|degraded/distribution_statements/` — regenerated.
- `tests/test_renderers_trust.py`, `tests/test_layout_assignment.py` — added/extended.

## Risks & Mitigations

- **Accidental value drift during migration** → in-script value-invariance assertion + `git diff`
  review + value-invariance test.
- **Refactor changes trust income schedule output** → existing render test must pass unchanged
  (pixel-equivalent).
- **Orphaned stale PNGs** → explicit output-directory cleanup step before regeneration.
- **Label variation confuses linking** → mitigated by design: linking matches on field keys/values,
  not labels; confirmed by re-running linking tests.

## Open Questions

None outstanding. Archetype set, breadth (6 layouts), label variation, and value-preservation
constraint are all confirmed.
