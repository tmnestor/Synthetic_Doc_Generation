# Layout DSL Stage 4 Implementation Plan — narrow the corpus

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the corpus from eight document types to three — bank statements, receipts, invoices — deleting the credit-card and four trust types, their layouts, ground truth, renderers, scripts and schema columns, while keeping receipt↔bank transaction linking intact.

**Architecture:** Pure subtraction. No new capability is built. Every task deletes something and proves the three surviving types are unaffected, using the pixel snapshots captured in Stage 3 as the gate.

**Tech Stack:** Python 3.12, Pillow 12.2.0 (pinned), PyYAML `safe_load`, pytest, conda env `synthetic`.

**Scope decided 2026-08-05 by the repo owner:**
- Credit-card statements are deleted, not kept — the corpus narrows to three types as originally designed.
- `config/field_definitions.yml` trims to match whatever survives.
- **Receipt↔bank transaction linking is RETAINED.** See `docs/layout_dsl_stage4_prerequisites.md`. This reverses an earlier draft of `docs/layout_dsl_design.md`.

## Global Constraints

- Conda env is `synthetic`. Run everything as `conda run -n synthetic <cmd>`.
- `tests/` is gitignored — write and run tests, never `git add tests/`.
- Every commit passes, in order: `pytest tests/`, `ruff check --fix --ignore ARG001,ARG002,F841 *.py`, `ruff format .`, `mypy . --ignore-missing-imports`. Never `--no-verify`.
- Line length 108. Google-style docstrings. `pathlib.Path`. Python 3.12 types. B904 in except blocks.
- Never write the Australian tax authority's three-letter acronym anywhere. Use "PROD" for the production environment; name document types directly otherwise.
- No commit attribution to Claude.
- **`environment.yml` carries an uncommitted change owned by the repo owner.** Never stage, revert or touch it. Stage by explicit path only — no `git add -A`, no `git commit -a`.
- Work on `main`. Commit only when asked.

### The gate

**`tests/test_bank_pixel_snapshot.py`, `tests/test_receipt_pixel_snapshot.py` and `tests/test_invoice_pixel_snapshot.py` — 116 tests — must stay green after every single deletion.** They are the only evidence Stage 3 preserved behaviour, and the legacy renderers they were captured from are gone.

Do **NOT** run any `regenerate_*_snapshot.py` script under any circumstance. If a deletion turns a snapshot red, the deletion removed something the surviving types depend on — revert it and report, do not re-bless.

### What must NOT be deleted

- `ground_truth/transaction_links.yml`
- `scripts/seed_transaction_links.py`
- `load_link_index` in `generators/payment_block.py`
- `linking/transaction_matcher.py` and the receipt↔bank half of `linking/link_validator.py`
- `generators/exporters/links.py` and the `doc_refs` derived output

Only the **trust-distribution** half of the linking machinery goes.

---

## File Structure

**Deleted:**

| Path | Note |
|---|---|
| `generators/cc_statement.py`, `trust_return.py`, `distribution_statement.py`, `trust_income_schedule.py`, `beneficiary_itr.py` | 5 renderers |
| `config/layouts/cc_statements.yml`, `trust_returns.yml`, `distribution_statements.yml`, `trust_income_schedules.yml`, `beneficiary_itrs.yml` | 5 layouts |
| `ground_truth/cc_statements.yml` (55), `trust_returns.yml` (50), `distribution_statements.yml` (50), `trust_income_schedules.yml` (50), `beneficiary_itrs.yml` (50) | 255 entries |
| `ground_truth/trust_distribution_links.yml` | trust linking only |
| `scripts/seed_trust_distribution_links.py`, `seed_trust_distributions.py`, `generate_trust_classification_gt.py`, `migrate_distribution_layouts.py` | trust scripts |

**Modified:** `config/generation_config.yml` (5 `document_types` entries), `config/field_definitions.yml` (46 → the surviving columns), `generators/pipeline.py`, `common.py`, `content_engine.py`, `derive_outputs.py`, `schema.py`, `exporters/native.py`, `exporters/links.py`, `linking/link_validator.py`, `scripts/seed_ground_truth.py`.

---

## Task 1: Baseline the surviving corpus

Before deleting anything, pin what the three surviving types currently produce **beyond** pixels — the derived outputs. The pixel snapshots cover rendering; nothing currently pins the CSV/JSONL exports, and the schema trim in Task 5 is exactly the change that could silently alter them.

**Files:**
- Create: `tests/fixtures/derived_baseline.json`, `tests/test_derived_baseline.py`

**Interfaces:**
- Produces: a baseline of every derived artefact for bank/receipt/invoice — row counts, column headers, and a content hash per output — that later tasks assert against.

- [ ] **Step 1: Regenerate derived outputs from the current tree**

Run `conda run -n synthetic python -m generators.pipeline derive` and record what it writes under `derived/`.

- [ ] **Step 2: Capture the baseline**

For each derived artefact belonging to bank statements, receipts and invoices, record: the exact column header, the row count, and a sha256 of the content. Exclude rows belonging to the five doomed types — those legitimately disappear.

- [ ] **Step 3: Write the assertion test and confirm it passes**

Run: `conda run -n synthetic pytest tests/test_derived_baseline.py -v`
Expected: PASS against the current tree.

- [ ] **Step 4: Commit**

Nothing to stage — `tests/` is gitignored. Record completion in the report.

---

## Task 2: Delete the trust document types

Four renderers, four layouts, four ground-truth files, `trust_distribution_links.yml`, and the four trust scripts.

**Files:** as listed in File Structure, trust rows only.

- [ ] **Step 1: Delete the four trust renderers and their layouts and ground truth**

- [ ] **Step 2: Remove their four `document_types` entries from `config/generation_config.yml`**

- [ ] **Step 3: Delete the four trust scripts**

- [ ] **Step 4: Unpick trust references from surviving code**

`generators/pipeline.py`, `schema.py`, `content_engine.py`, `derive_outputs.py`, `exporters/native.py`, `exporters/links.py`, `linking/link_validator.py`, `scripts/seed_ground_truth.py`. Keep the receipt↔bank half of every linking file.

- [ ] **Step 5: Verify**

```bash
conda run -n synthetic pytest tests/test_bank_pixel_snapshot.py tests/test_receipt_pixel_snapshot.py tests/test_invoice_pixel_snapshot.py
conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic python -m generators.pipeline generate --clean-only
```

Expected: 116 snapshot tests pass; validate clean; generation completes for **four** types (the three survivors plus cc, still present).

- [ ] **Step 6: Commit**

---

## Task 3: Delete the credit-card statements

**Files:** `generators/cc_statement.py`, `config/layouts/cc_statements.yml`, `ground_truth/cc_statements.yml`, plus its `document_types` entry and the six real references outside its own files.

- [ ] **Step 1: Delete the renderer, layout and ground truth**

- [ ] **Step 2: Remove the `document_types` entry**

- [ ] **Step 3: Unpick the references**

`generators/common.py`, `pipeline.py`, `exporters/native.py`, `scripts/seed_ground_truth.py`, `config/field_definitions.yml`, `config/generation_config.yml`. Note the design doc's claim that cc references are "comments only" is **out of date** — verify each site rather than trusting it.

- [ ] **Step 4: Verify**

Same three commands. Generation now completes for exactly three types, 165 documents.

- [ ] **Step 5: Commit**

---

## Task 4: Trim the field schema

`config/field_definitions.yml` drops to the columns the three surviving types actually use. **Seven modules read this file** — `pipeline.py`, `derive_outputs.py`, `schema.py`, `layout_dsl/field_providers.py`, `layout_dsl/schema.py`, `scripts/generate_extraction_gt.py`, `scripts/relabel_evaluation_set.py` — so this is the highest-risk task in the plan.

Two of them matter especially:
- `layout_dsl/field_providers.py` reads `all_columns` for its emit-collision check. It reads the file generically, so a shorter list needs no code change — but confirm no provider emit name was only "safe" because it collided with nothing in a longer list.
- `scripts/generate_extraction_gt.py` builds the extraction ground truth consumed downstream.

- [ ] **Step 1: Determine the surviving column set empirically**

Derive it from `document_fields` for the three surviving types, not by hand.

- [ ] **Step 2: Trim `all_columns` and the per-type blocks**

- [ ] **Step 3: Verify against the Task 1 baseline**

```bash
conda run -n synthetic pytest tests/test_derived_baseline.py
```

The surviving types' derived outputs must be **unchanged** — same headers, same row counts, same hashes. A changed header for a surviving type means a column was trimmed that is still in use.

- [ ] **Step 4: Verify rendering and generation**

Three snapshots, `validate`, `generate --clean-only`.

- [ ] **Step 5: Commit**

---

## Task 5: Re-derive and re-export

**Files:** `derived/`, and the shared dataset at `/Users/tod/Desktop/evaluation_data/`.

- [ ] **Step 1: Regenerate the full corpus**

`conda run -n synthetic python -m generators.pipeline generate` — clean and degraded, 330 images.

- [ ] **Step 2: Re-derive**

`conda run -n synthetic python -m generators.pipeline derive`.

- [ ] **Step 3: Report what a downstream consumer must do**

`evaluation_data/synthetic_20260731` was shared with the team. Do **not** overwrite it without instruction — report what changed and what a re-export would need, and stop.

- [ ] **Step 4: Commit the regenerated corpus**

---

## Task 6: Final sweep and verification

- [ ] **Step 1: Confirm nothing references a deleted type**

```bash
grep -rn --include='*.py' --include='*.yml' -iE "trust|beneficiary|distribution_statement|cc_statement" generators/ scripts/ config/ linking/
```

Every remaining hit must be a deliberate, explained survivor. Report the list.

- [ ] **Step 2: Update the docs**

`CLAUDE.md`'s project overview still describes 840 images and eight types. `docs/layout_dsl_design.md` and `docs/layout_dsl_stage4_prerequisites.md` need their Stage 4 sections marked done.

- [ ] **Step 3: Full verification**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic python -m generators.pipeline generate --clean-only
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```

- [ ] **Step 4: Commit**
