# Bank Statement Renderer Redesign

## Problem

The current bank statement renderer produces outputs that are unsatisfactory for VLM IE extraction benchmarking:

1. **Table heading misalignment**: Column headers are left-aligned at column `x` but numeric values are right-aligned to `x + width`, creating systematic misalignment on Debit/Credit/Balance columns.
2. **Too few transactions**: Ground truth contains 8-14 transactions per statement. Real Big 4 statements fill the page with 20-40+ rows.
3. **Generic layout**: A single renderer draws all 12 layouts identically (different column positions only). Real Big 4 statements have distinct visual structures per bank.

## Decisions

- **Ground truth regeneration**: Rerun `seed_ground_truth.py` with 25-40 transactions per bank statement entry. Transaction links reseeded afterward. Cleanest approach; no renderer-side padding.
- **Per-bank renderers**: Four dedicated renderers (CBA, Westpac, NAB, ANZ) each encoding that bank's visual DNA. Replaces the single generic renderer.
- **Layout YAML restructure**: 12 layouts reduced to 8 (2 per bank). Column x-positions removed; renderers compute their own positions from margins and page width.

## Ground Truth Regeneration

### Changes to `scripts/seed_ground_truth.py`

Bank statement entries get 25-40 transactions per entry (up from 8-14). All transactions must be chronologically sorted within the declared `STATEMENT_DATE_RANGE`. The current data has dates outside the statement period (e.g., CASEB004 has Feb/Jul/Mar/May dates for an Oct statement) — this is fixed by constraining generated dates to the statement period.

Seed remains `42` for determinism. Same pipe-delimited format, same 23-column schema, same 55 entries (CASEB001-CASEB055).

### Transaction Links Reseeding

`scripts/seed_transaction_links.py` reseeded against new ground truth. Same logic (110 links, 3 difficulty tiers), new target transaction indices to match the expanded transaction lists.

## Per-Bank Renderer Design

### Dispatch Mechanism

`render_bank_statement(entry, layout) -> Image` signature unchanged. Internally dispatches based on the `renderer` key in the layout config:

```python
RENDERERS = {"cba": render_cba, "westpac": render_westpac, "nab": render_nab, "anz": render_anz}

def render_bank_statement(entry: dict, layout: dict) -> Image.Image:
    renderer = RENDERERS[layout["renderer"]]
    return renderer(entry, layout)
```

Old helper functions (`_draw_column_headers`, `_draw_transactions`, `_draw_header`, `_draw_account_info`, `_normalize_layout`) are removed.

### CBA Renderer

Reference: user-provided CBA synthetic sample

Visual features:

- **"Commonwealth Bank"** in dark navy text (`#12107D`) at top left, bold, large font
- **Legal line** below in small text: "Commonwealth Bank of Australia", "ABN 48 123 456 789 AFSL and", "Australian credit licence 234567"
- **Account details block** (regular body text, no box):
  - "Account Holder: {PAYER_NAME}"
  - "BSB: {bsb}" / "Account Number: {account_number}"
  - "Statement Period: {start} to {end}"
- **Horizontal rule** above column headers
- **Column headers**: "Date", "Description", "Withdrawal", "Deposit", "Balance"
  - "Date" and "Description" left-aligned
  - "Withdrawal", "Deposit", "Balance" right-aligned (matching the right-aligned numeric values below)
- **Horizontal rule** below column headers
- **Simple single-line transaction rows** — one line per transaction, no sub-descriptions, no card numbers, no value dates
- **Amounts with $ prefix** (e.g., `$178.50`), no CR/DR suffix on balance
- **Opening balance row** as first entry
- **Horizontal rule** below last transaction
- **Footer section**: "TRANSACTION TYPES:" with definitions (EFTPOS, BPAY, DD, VISA DEBIT, ATM), then contact line ("CommBank.com.au | 13 2221")

Two variants:

- `cba_standard` — standard Withdrawal + Deposit columns (as in reference)
- `cba_date_grouped` — same visual style but transactions grouped under bold date headers

### Westpac Renderer

Reference: `westpac_debit_credit.png`

Visual features:
- **"Westpac" logo** in red (`#C41E3A`) top-right corner, clean white background (no header bar)
- **Section headers** like "Westpac Premium CardII transactions" as bold text above table
- **Column headers**: "Date of Transaction", "Description", "Debits", "Credits ()"
- **Multi-line descriptions** — multiple merchants grouped under one date on separate lines
- **Dense row spacing** — tight vertical spacing to fit many transactions
- **Page numbers** top-right (e.g., "Page 4 of 6")
- **Rewards Points Balance Summary** box above transaction table

Two variants:
- `westpac_standard` — standard personal account
- `westpac_premium` — premium card with rewards section

### NAB Renderer

Reference: `nab_classic_highligted.png`

Visual features:
- **Light blue background** (`#E8F0FE`) on header bar and date-group rows
- **Columns**: "Date", "Particulars", "Debits", "Credits", "Balance"
- **Date grouping**: bold date header row (e.g., "22 Mar 2024"), indented transactions below
- **"Brought forward" / "Carried forward"** rows with running balance
- **Reference numbers** with dotted leader lines (e.g., `Ref: 98765432168...............................`)
- **Balance with "Cr" suffix**
- **Account Details box** at top: name, BSB Number, Account Number in bordered box
- **"Transaction Details (continued)"** section header

Two variants:
- `nab_classic` — standard classic banking layout with date grouping
- `nab_dense` — tighter spacing, no reference numbers

### ANZ Renderer

Reference: `ANZ Statement.png`

Visual features:
- **Blue header/branding** area at top
- **Columns**: "Date", "Transaction Description", "Debits", "Credits", "Balance"
- **"BALANCE BROUGHT FORWARD"** opening row
- **Balance with "DR"/"CR" suffix** — "DR" for debit balances, "CR" for credit balances
- **Underline separators** between date groups
- **Transfer references** with full account numbers (e.g., "TRANSFER 365363 TO 12345123456789")
- **"Totals at end of period"** summary row at bottom

Two variants:
- `anz_standard` — standard layout
- `anz_modern` — cleaner modern style

### Shared Utilities (common.py additions)

- `draw_separator_line(draw, x1, x2, y, color)` — thin horizontal rule across the table width
- Existing `draw_text_right()`, `load_font()`, `fmt_amount()` reused as-is

## Layout YAML Restructure

### New `config/layouts/bank_statements.yml` Structure

Column x-positions removed. Each renderer computes column positions internally from `margin` and `page_dimensions.width`. Layout YAML provides variant configuration only:

```yaml
layouts:
  cba_standard:
    bank: Commonwealth Bank of Australia
    bank_code: CBA
    renderer: cba
    variant: standard
    page_dimensions: { width: 2480, height: 3508 }
    font_sizes: { header: 28, body: 18, footer: 10 }
    margin: 100
    row_height: 45
    bank_name_color: "#12107D"
    column_headers: ["Date", "Description", "Withdrawal", "Deposit", "Balance"]
    show_opening_balance: true
    show_footer_transaction_types: true
    date_format: "DD/MM/YYYY"

  cba_date_grouped:
    bank: Commonwealth Bank of Australia
    bank_code: CBA
    renderer: cba
    variant: date_grouped
    page_dimensions: { width: 2480, height: 3508 }
    font_sizes: { header: 28, body: 18, footer: 10 }
    margin: 100
    row_height: 45
    bank_name_color: "#12107D"
    column_headers: ["Date", "Description", "Withdrawal", "Deposit", "Balance"]
    show_opening_balance: true
    show_footer_transaction_types: true
    date_grouping: true
    date_format: "DD MMM YYYY"

  westpac_standard:
    bank: Westpac Banking Corporation
    bank_code: WBC
    renderer: westpac
    variant: standard
    page_dimensions: { width: 2480, height: 3508 }
    font_sizes: { header: 26, body: 16, sub_description: 13, footer: 9 }
    margin: 80
    row_height: 40
    logo_color: "#C41E3A"
    date_format: "DD MMM YY"

  westpac_premium:
    bank: Westpac Banking Corporation
    bank_code: WBC
    renderer: westpac
    variant: premium
    page_dimensions: { width: 2480, height: 3508 }
    font_sizes: { header: 26, body: 16, sub_description: 13, footer: 9 }
    margin: 80
    row_height: 40
    logo_color: "#C41E3A"
    show_rewards_section: true
    date_format: "DD MMM YY"

  nab_classic:
    bank: National Australia Bank
    bank_code: NAB
    renderer: nab
    variant: classic
    page_dimensions: { width: 2480, height: 3508 }
    font_sizes: { header: 26, body: 16, sub_description: 13, footer: 9 }
    margin: 80
    row_height: 42
    header_bar_color: "#E8F0FE"
    balance_suffix: "Cr"
    date_grouping: true
    show_references: true
    show_brought_forward: true
    date_format: "DD MMM YYYY"

  nab_dense:
    bank: National Australia Bank
    bank_code: NAB
    renderer: nab
    variant: dense
    page_dimensions: { width: 2480, height: 3508 }
    font_sizes: { header: 24, body: 14, sub_description: 11, footer: 8 }
    margin: 80
    row_height: 32
    header_bar_color: "#E8F0FE"
    balance_suffix: "Cr"
    date_grouping: true
    show_references: false
    show_brought_forward: true
    date_format: "DD MMM YY"

  anz_standard:
    bank: Australia and New Zealand Banking Group
    bank_code: ANZ
    renderer: anz
    variant: standard
    page_dimensions: { width: 2480, height: 3508 }
    font_sizes: { header: 28, body: 18, sub_description: 14, footer: 10 }
    margin: 100
    row_height: 45
    header_color: "#0061B5"
    balance_suffix_debit: "DR"
    balance_suffix_credit: "CR"
    show_totals_row: true
    show_brought_forward: true
    date_format: "DD/MM/YY"

  anz_modern:
    bank: Australia and New Zealand Banking Group
    bank_code: ANZ
    renderer: anz
    variant: modern
    page_dimensions: { width: 2480, height: 3508 }
    font_sizes: { header: 26, body: 16, sub_description: 13, footer: 9 }
    margin: 100
    row_height: 40
    header_color: "#0061B5"
    balance_suffix_debit: "DR"
    balance_suffix_credit: "CR"
    show_totals_row: true
    show_brought_forward: true
    date_format: "DD MMM YYYY"
```

### Ground Truth Layout References

The 55 bank statement entries cycle through the 8 layouts. Each entry's `layout` field references one of these 8 keys. The existing `seed_ground_truth.py` layout cycling logic is updated for the new layout names.

## Validation & Loader Changes

### `generators/loader.py`
- Layout loader validates that `renderer` key exists and is one of `{cba, westpac, nab, anz}`
- No longer needs to normalize column lists

### `generators/schema.py`
- No schema changes (same fields, same validation rules)
- Layout reference validation updated for new layout names

## Files Changed

| File | Change |
|------|--------|
| `config/layouts/bank_statements.yml` | Restructured: 12 to 8 layouts, column positions removed, `renderer`/`variant` keys added |
| `generators/bank_statement.py` | Rewritten: single renderer to 4 per-bank renderers + dispatch |
| `generators/common.py` | Addition: `draw_separator_line()` |
| `scripts/seed_ground_truth.py` | Bank statements: 25-40 transactions, chronologically sorted |
| `scripts/seed_transaction_links.py` | Reseeded against new ground truth |
| `ground_truth/bank_statements.yml` | Regenerated (55 entries, 25-40 transactions each) |
| `ground_truth/transaction_links.yml` | Regenerated (110 links) |
| `generators/loader.py` | Layout loader validates `renderer` key |

## Files NOT Changed

- `generators/receipt.py`, `invoice.py`, `cc_statement.py`
- `generators/pipeline.py` (calls `render_bank_statement` — same signature)
- `generators/derive_outputs.py` (reads regenerated YAML as-is)
- `linking/` module (validates against regenerated links as-is)
- `config/generation_config.yml`
- `config/field_definitions.yml`
- `config/data_pools.yml`

## Interface Contract

`render_bank_statement(entry: dict, layout: dict) -> Image.Image` — unchanged. The `generate` CLI command works without modification.
