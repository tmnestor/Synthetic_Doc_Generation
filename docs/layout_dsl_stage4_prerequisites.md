# Layout DSL — carry-forward notes for Stage 4

Stage 3 is complete: receipts and invoices render from declarative `body:` trees, the
imperative renderers are deleted, and all three document types are pinned byte-identical by
pixel snapshots. This file records what the whole-plan review triaged as carrying forward,
so it is not rediscovered.

Stage 4 is: narrow the corpus to three document types, drop transaction linking,
re-baseline and re-export.

## What Stage 3 actually delivered

| | Before | After |
|---|---|---|
| `generators/receipt.py` | 442 lines | 69 |
| `generators/invoice.py` | 482 lines | 65 |
| Python literals deciding a rendered value | many | none in the three live document types |

Verified at the end of the plan: three pixel snapshots green (116 tests, all byte-identical
to baselines captured from the legacy renderers before deletion), `pipeline validate` clean,
full suite 1122 passed / 1 skipped, `generate --clean-only` producing 420 documents across
all eight document types.

## Fix before Stage 4

Nothing blocks Stage 4. The items below are live but narrow.

| Item | Why it matters |
|---|---|
| `schema.py`'s `_UNBALANCED` misses `{{FIELD}` and `{FIELD}}` | Confirmed live. Narrow class — the inner placeholder still resolves, so only a literal brace renders. No layout has one. |
| `regenerate_doc_pixel_snapshot.py:160` is 111 chars | Gitignored, never committed, no CI gate. Opportunistic. |

## Accepted as designed — do not "fix" these

- **`schema.py` duplicates `context.py`'s overflow arithmetic.** Geometry validation has no
  `Region` object to delegate to. Both sites are tested and in sync.
- **The stray `str()` wrap on the sub_line role site.** `str(resolve_param(...))` is the
  house pattern at all ~30 other resolution sites; removing it only here would be the
  inconsistency.
- **`FieldProviderError` is not in `_DSL_ERRORS`.** It cannot be path-tagged — verified
  independently twice. The asymmetry with the tagged classes is deliberate.
- **`PaymentDetails.purchase_total` is unused outside tests.** Deliberate: the slip's
  `Purchase   AUD` line binds `{TOTAL_AMOUNT}` directly so the printed amount can never
  drift from the scored field.

## What has no pixel oracle

The snapshots pin the 55-entry corpus. These paths are unreachable through it and are
covered only by targeted tests:

- **The cash EFTPOS slip.** `Cash` carries weight 0 in `receipt_method_weights` and every
  receipt is linked to a bank row, so the weighted pool never runs.
  `test_a_whole_cash_receipt_page_renders_on_every_layout` renders full cash pages across
  all six layouts with the provider chain forced; that is the only coverage.
- **The budgeted `draw_pair` path.** No layout uses `budget:` on a `pair`.
- **`pair.min_gap` with a budget.** Now rejected at validate time rather than silently
  dropped.

## Receipt↔bank linking is retained — do not drop it

**Decided 2026-08-05 by the repo owner**, reversing an earlier draft of
`docs/layout_dsl_design.md` that had Stage 4 delete transaction linking entirely.

All 55 receipts are linked — verified: 55 ground-truth entries, 55 keys in
`load_link_index()`, zero unlinked. For a linked receipt, `derive_payment` takes the card
scheme from the linked bank row's description via `method_from_bank_description`, and the
`receipt_method_weights` pool is never consulted for the method (only
`wallet_presentation_weights`, which 90% of the time changes nothing). That is what makes
the receipt and the statement agree on how a purchase was paid for, and a transaction-linking
benchmark is only scoreable because they do.

Stage 4 therefore **keeps** `ground_truth/transaction_links.yml`,
`scripts/seed_transaction_links.py`, `load_link_index`, `linking/`,
`generators/exporters/links.py`, and the `doc_refs` derived output. Only the
trust-distribution half of the linking machinery goes.

**No receipt re-baseline is required on this account.** The scheme-selection mechanism is
unchanged, so the printed schemes — and the pixels — stay as they are.

Had linking been dropped, every one of the 55 receipts would have fallen through to the
weighted pool and printed a different scheme. That is the failure this decision avoids.

## Two config keys kept deliberately, pending a decision

- **`minimum_amount: 10000` and `mixed_tax_mode: true`** in `config/layouts/invoices.yml`
  are read by nothing — not renderers, not `scripts/seed_ground_truth.py`, not any test.
  They are the only record of which invoices each layout is *for*. Either wire them into
  layout assignment or drop them.
- **`format:`** is unread for receipts and invoices, but `tests/test_layout_assignment.py`
  reads it for other document types, so the key has a live contract elsewhere. Confirm that
  contract before removing it anywhere.

## The architectural rule that held

Stage 2 recorded: *a provider may not emit a fact that a `body:` tree can already state.*
Stage 3 extended it to field providers and it held under real pressure — SHA-256 POS
derivations, seventeen EFTPOS terminal values, and a three-variant slip all routed through
providers returning **data only**, with every label, every line order and the variant
selection itself stated in YAML via `when:`.

The one place it bent was found and closed: the printed slip strings briefly existed in two
config files at once, and `config/layouts/receipts.yml` is now the single source of truth
for what the page prints.
