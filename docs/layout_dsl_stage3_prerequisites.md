# Layout DSL — carry-forward notes for Stages 3 and 4

Stage 2 is complete: all 8 bank-statement layouts are declarative and the legacy per-bank
renderers are deleted. This file records what the whole-branch review triaged as needing
attention *before* the next stage, so it is not rediscovered.

Stages 3 and 4 are: migrate receipts and invoices to the DSL; narrow the corpus to three
document types; drop transaction linking; re-baseline and re-export.

## Fix before Stage 3

These are all inert against the current bank layouts and become live the moment receipts
and invoices are hand-authored.

| Item | Why it bites in Stage 3 |
|---|---|
| A malformed placeholder such as `{FIELD` (unclosed) renders as a silent literal | Nothing detects it. Verified zero occurrences across all 8 bank layouts, but Stage 3 bodies are hand-written and this is the likeliest typo shape. A second regex for unbalanced braces in `validate_body` closes it. |
| `Region.divide` uses floor division | Columns can under-fill by up to `n-1` px and the last column never reaches `region.right`. Westpac's only split is `1600 // 2 = 800`, exact — any odd width or 3+ columns hits it. |
| `rule_above` draws its separator before `_validate_bold_spec` | A row combining `rule_above` with an invalid bold collection marks the canvas before raising. Unreachable today; a one-line statement swap fixes it. |
| `Region.indent`/`divide` raise bare `ValueError`s | They lack the four-element diagnostic form. Unreachable from YAML today because `_validate_geometry` rejects bad padding and gaps first. |

## The architectural rule to hold

The provider/YAML boundary held under expressiveness pressure — SHA-256 reference numbers,
cross-transaction sums, and value-dependent DR/CR suffixes all routed cleanly through row
providers with no filter or expression added to the binding layer.

It bent under *convenience* pressure, on the easiest case:

- `balance_suffix` returns a finished display string (`"$137.73 CR"`) rather than row data,
  and as a direct consequence the column's own `currency`/`currency_suffix` silently stop
  working on it.
- `rule_above` expresses in Python what `{type: rule}` + `{type: spacer}` already express in
  YAML — two existing primitives, no new key, no new code path.

**The rule: a provider may not emit a fact that a `body:` tree can already state.**

## What no gate currently protects

The pixel snapshot proves output has not *changed*. It cannot say output is *correct*, and
it is blind to anything that alters `derived/geometry.jsonl` without altering pixels.

Unguarded, roughly in order of how quietly a change slips through:

1. **Geometry content.** No test asserts the *contents* of a bank geometry record. A
   box-convention change or a recorder-threading mistake is invisible.
2. **Page-length overflow.** See below — 22 of 55 entries already fail it with every gate
   green.
3. **Provider `params` semantics.** Key names are now validated, but a valid key with the
   wrong value still silently changes a statement's structure.

A `final_y <= page_height` assertion plus a per-layout `geometry.jsonl` key-set assertion
would close 1 and 2 in roughly 30 lines. Worth having before Stage 3 adds two more document
types.

## Pre-existing corpus defects, unrelated to the DSL

Both predate this work and are reproduced faithfully by the DSL, because it reproduces
legacy exactly.

**22 of 55 bank statements render content below the page bottom.** Worst case `CASE007`
ends at y=6021 against a 3508px page — roughly half a page drawn onto nothing. 373 geometry
boxes are degenerate, and `ACCOUNT_BALANCE` is clamped in 20 of 55 statements, meaning its
ground truth is meaningless there. `overflow_check.py` backstops `fit_text` width overflow,
not page-length overflow. Options: cap transaction counts at seed time, grow the page,
paginate, or accept and document.

**Every recorded box is shifted up by the ascender gap.** The codebase's "ink box" uses
`top = y` with `height = bbox[3] - bbox[1]`, where the true ink top is `y + bbox[1]` — 4 to
9px lower at the sizes in use. Uniform across all eight document types and every exporter,
so correcting it is a corpus-wide re-baseline with a downstream dataset attached.

## Test-infrastructure note

`tests/fixtures/bank_baseline_hashes.json` and `bank_dsl_pixel_hashes.json` are now
identical in content — the older independent Phase-1B baseline was re-blessed to DSL output
during Stage 2. Two fixtures, one assertion, and only `bank_dsl_pixel_hashes.json` has a
regeneration path. After any legitimate re-bless, `test_bank_fit.py` will fail with no
documented way to fix it.

Also: `regenerate_bank_pixel_snapshot.py` still labels `render_bank_statement` as "legacy",
which is now the DSL adapter. Running `--confirm` would overwrite the frozen
legacy-identity record — the only surviving evidence of what the migration changed — with
DSL-vs-DSL data showing everything identical, and the shape-only test would still pass.
