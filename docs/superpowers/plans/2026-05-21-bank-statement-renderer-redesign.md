# Bank Statement Renderer Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic bank statement renderer with four per-bank renderers (CBA, Westpac, NAB, ANZ) that produce realistic, page-filling transaction tables, and regenerate ground truth with 25-40 transactions per entry.

**Architecture:** Layout YAML reduced from 12 generic layouts to 8 bank-specific configs (2 per bank) with a `renderer` dispatch key. Each per-bank renderer computes its own column positions from margins/page width (eliminating the misalignment caused by hardcoded x-positions). Ground truth regenerated with more transactions and chronologically sorted dates.

**Tech Stack:** Python 3.12, Pillow (PIL), PyYAML, typer, pytest

**Spec:** `docs/superpowers/specs/2026-05-21-bank-statement-renderer-redesign.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config/layouts/bank_statements.yml` | Rewrite | 8 layouts with `renderer`/`variant` keys, no column x-positions |
| `generators/common.py` | Modify | Add `draw_separator_line()` |
| `generators/bank_statement.py` | Rewrite | 4 per-bank renderers + dispatch, keep `_parse_transactions` and `_compute_running_balances` |
| `scripts/seed_ground_truth.py` | Modify | Bank entries: 25-40 txns, sorted dates within statement period, new layout names |
| `ground_truth/bank_statements.yml` | Regenerate | 55 entries with 25-40 transactions each |
| `ground_truth/transaction_links.yml` | Regenerate | 110 links reseeded against new ground truth |
| `generators/loader.py` | Modify | Validate `renderer` key in layout registry |
| `tests/test_bank_statement.py` | Create | Tests for all renderers and shared utilities |
| `tests/test_common.py` | Create | Test for `draw_separator_line` |
| `tests/test_seed_ground_truth.py` | Create | Tests for bank entry generation |

---

### Task 1: Layout YAML Restructure

**Files:**
- Rewrite: `config/layouts/bank_statements.yml`
- Modify: `generators/loader.py:52-84`
- Test: `tests/test_loader.py`

- [ ] **Step 1: Write failing test for loader renderer-key validation**

Create `tests/test_loader.py`:

```python
"""Tests for layout loader renderer-key validation."""

import tempfile
from pathlib import Path

import yaml

from generators.loader import load_layout_registry


def test_load_layout_registry_returns_layouts_with_renderer_key():
    """Layout entries must have a 'renderer' key after loading."""
    registry_path = Path("config/layouts/bank_statements.yml")
    layouts = load_layout_registry(registry_path)
    for layout_id, layout_cfg in layouts.items():
        assert "renderer" in layout_cfg, (
            f"Layout '{layout_id}' missing 'renderer' key. "
            f"Keys present: {sorted(layout_cfg.keys())}"
        )


def test_load_layout_registry_renderer_key_is_valid_bank():
    """Renderer key must be one of the Big 4 bank codes."""
    valid_renderers = {"cba", "westpac", "nab", "anz"}
    registry_path = Path("config/layouts/bank_statements.yml")
    layouts = load_layout_registry(registry_path)
    for layout_id, layout_cfg in layouts.items():
        renderer = layout_cfg.get("renderer")
        assert renderer in valid_renderers, (
            f"Layout '{layout_id}' has renderer='{renderer}', "
            f"expected one of {sorted(valid_renderers)}"
        )


def test_load_layout_registry_has_eight_layouts():
    """Bank statement registry should have exactly 8 layouts (2 per bank)."""
    registry_path = Path("config/layouts/bank_statements.yml")
    layouts = load_layout_registry(registry_path)
    assert len(layouts) == 8, f"Expected 8 layouts, got {len(layouts)}: {sorted(layouts.keys())}"


def test_load_layout_registry_two_per_bank():
    """Each bank should have exactly 2 layout variants."""
    registry_path = Path("config/layouts/bank_statements.yml")
    layouts = load_layout_registry(registry_path)
    bank_counts: dict[str, int] = {}
    for layout_cfg in layouts.values():
        renderer = layout_cfg["renderer"]
        bank_counts[renderer] = bank_counts.get(renderer, 0) + 1
    for bank, count in bank_counts.items():
        assert count == 2, f"Bank '{bank}' has {count} layouts, expected 2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n du pytest tests/test_loader.py -v`
Expected: FAIL — current YAML has 12 layouts, no `renderer` key.

- [ ] **Step 3: Rewrite layout YAML**

Replace the entire contents of `config/layouts/bank_statements.yml` with:

```yaml
layouts:
  cba_standard:
    bank: Commonwealth Bank of Australia
    bank_code: CBA
    renderer: cba
    variant: standard
    page_dimensions:
      width: 2480
      height: 3508
    font_sizes:
      header: 28
      body: 18
      footer: 10
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
    page_dimensions:
      width: 2480
      height: 3508
    font_sizes:
      header: 28
      body: 18
      footer: 10
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
    page_dimensions:
      width: 2480
      height: 3508
    font_sizes:
      header: 26
      body: 16
      sub_description: 13
      footer: 9
    margin: 80
    row_height: 40
    logo_color: "#C41E3A"
    date_format: "DD MMM YY"

  westpac_premium:
    bank: Westpac Banking Corporation
    bank_code: WBC
    renderer: westpac
    variant: premium
    page_dimensions:
      width: 2480
      height: 3508
    font_sizes:
      header: 26
      body: 16
      sub_description: 13
      footer: 9
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
    page_dimensions:
      width: 2480
      height: 3508
    font_sizes:
      header: 26
      body: 16
      sub_description: 13
      footer: 9
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
    page_dimensions:
      width: 2480
      height: 3508
    font_sizes:
      header: 24
      body: 14
      sub_description: 11
      footer: 8
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
    page_dimensions:
      width: 2480
      height: 3508
    font_sizes:
      header: 28
      body: 18
      sub_description: 14
      footer: 10
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
    page_dimensions:
      width: 2480
      height: 3508
    font_sizes:
      header: 26
      body: 16
      sub_description: 13
      footer: 9
    margin: 100
    row_height: 40
    header_color: "#0061B5"
    balance_suffix_debit: "DR"
    balance_suffix_credit: "CR"
    show_totals_row: true
    show_brought_forward: true
    date_format: "DD MMM YYYY"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n du pytest tests/test_loader.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add config/layouts/bank_statements.yml tests/test_loader.py
git commit -m "refactor: restructure bank statement layouts to 8 bank-specific configs with renderer dispatch key"
```

---

### Task 2: Add `draw_separator_line` to common.py

**Files:**
- Modify: `generators/common.py:110-124` (near existing `draw_separator`)
- Test: `tests/test_common.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_common.py`:

```python
"""Tests for common.py utility additions."""

from PIL import Image, ImageDraw

from generators.common import draw_separator_line


def test_draw_separator_line_draws_horizontal_line():
    """draw_separator_line should draw a 1px line between x1 and x2 at y."""
    img = Image.new("RGB", (500, 100), "white")
    draw = ImageDraw.Draw(img)
    draw_separator_line(draw, x1=50, x2=450, y=50, color="black")
    # Check that pixels on the line are black
    assert img.getpixel((50, 50)) == (0, 0, 0)
    assert img.getpixel((250, 50)) == (0, 0, 0)
    assert img.getpixel((449, 50)) == (0, 0, 0)
    # Check that pixels above/below the line are white
    assert img.getpixel((250, 48)) == (255, 255, 255)
    assert img.getpixel((250, 52)) == (255, 255, 255)


def test_draw_separator_line_respects_color():
    """draw_separator_line should use the specified color."""
    img = Image.new("RGB", (500, 100), "white")
    draw = ImageDraw.Draw(img)
    draw_separator_line(draw, x1=50, x2=450, y=50, color="#CCCCCC")
    pixel = img.getpixel((250, 50))
    assert pixel == (204, 204, 204)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n du pytest tests/test_common.py -v`
Expected: FAIL — `ImportError: cannot import name 'draw_separator_line'`

- [ ] **Step 3: Implement draw_separator_line**

Add to `generators/common.py` after the existing `draw_separator` function (after line 123):

```python
def draw_separator_line(
    draw: ImageDraw.ImageDraw,
    x1: int,
    x2: int,
    y: int,
    color: str = "black",
    width: int = 1,
) -> None:
    """Draw a thin horizontal rule from x1 to x2 at vertical position y.

    Args:
        draw: PIL ImageDraw object.
        x1: Left x coordinate.
        x2: Right x coordinate.
        y: Vertical position.
        color: Line color (hex or name).
        width: Line width in pixels.
    """
    draw.line([(x1, y), (x2, y)], fill=color, width=width)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n du pytest tests/test_common.py -v`
Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add generators/common.py tests/test_common.py
git commit -m "feat: add draw_separator_line utility to common.py"
```

---

### Task 3: CBA Renderer

**Files:**
- Modify: `generators/bank_statement.py` (rewrite — keep `_parse_transactions`, `_compute_running_balances`, `_parse_hex_color`; remove old rendering functions; add CBA renderer)
- Test: `tests/test_bank_statement.py`

- [ ] **Step 1: Write failing test for CBA renderer**

Create `tests/test_bank_statement.py`:

```python
"""Tests for per-bank renderers in bank_statement.py."""

from decimal import Decimal

from PIL import Image

from generators.bank_statement import (
    _compute_running_balances,
    _parse_hex_color,
    _parse_transactions,
    render_cba,
)


# ── Shared utility tests ────────────────────────────────────────────────────


def test_parse_hex_color():
    assert _parse_hex_color("#FF0000") == (255, 0, 0)
    assert _parse_hex_color("#12107D") == (18, 16, 125)
    assert _parse_hex_color("#000000") == (0, 0, 0)


def test_parse_transactions():
    fields = {
        "TRANSACTION_DATES": "01/01/2024|05/01/2024",
        "TRANSACTION_DESCRIPTIONS": "Salary|EFTPOS COLES",
        "TRANSACTION_AMOUNTS_PAID": "NOT_FOUND|45.00",
        "TRANSACTION_AMOUNTS_RECEIVED": "3000.00|NOT_FOUND",
    }
    txns = _parse_transactions(fields)
    assert len(txns) == 2
    assert txns[0]["date"] == "01/01/2024"
    assert txns[0]["description"] == "Salary"
    assert txns[0]["debit"] == "NOT_FOUND"
    assert txns[0]["credit"] == "3000.00"
    assert txns[1]["debit"] == "45.00"


def test_compute_running_balances():
    txns = [
        {"date": "01/01", "description": "A", "debit": "100.00", "credit": "NOT_FOUND"},
        {"date": "02/01", "description": "B", "debit": "NOT_FOUND", "credit": "500.00"},
    ]
    result = _compute_running_balances(txns, "1400.00")
    # Last txn balance = closing = 1400.00
    assert result[1]["balance"] == Decimal("1400.00")
    # Before credit of 500: 1400 - 500 = 900, then before debit of 100: 900 + 100 = 1000
    assert result[0]["balance"] == Decimal("900.00")


# ── CBA renderer tests ──────────────────────────────────────────────────────

_CBA_LAYOUT = {
    "bank": "Commonwealth Bank of Australia",
    "bank_code": "CBA",
    "renderer": "cba",
    "variant": "standard",
    "page_dimensions": {"width": 2480, "height": 3508},
    "font_sizes": {"header": 28, "body": 18, "footer": 10},
    "margin": 100,
    "row_height": 45,
    "bank_name_color": "#12107D",
    "column_headers": ["Date", "Description", "Withdrawal", "Deposit", "Balance"],
    "show_opening_balance": True,
    "show_footer_transaction_types": True,
    "date_format": "DD/MM/YYYY",
}

_CBA_ENTRY = {
    "layout": "cba_standard",
    "degradation_seed": 1234,
    "fields": {
        "DOCUMENT_TYPE": "BANK_STATEMENT",
        "SUPPLIER_NAME": "Commonwealth Bank",
        "STATEMENT_DATE_RANGE": "01/01/2024 - 31/01/2024",
        "TRANSACTION_DATES": "03/01/2024|05/01/2024|10/01/2024|15/01/2024|20/01/2024",
        "TRANSACTION_DESCRIPTIONS": "Salary PAYROLL|EFTPOS COLES Sydney AUS|BPAY ORIGIN ENERGY|ATM WITHDRAWAL|Transfer To Sarah NetBank",
        "TRANSACTION_AMOUNTS_PAID": "NOT_FOUND|85.50|150.00|200.00|500.00",
        "TRANSACTION_AMOUNTS_RECEIVED": "3500.00|NOT_FOUND|NOT_FOUND|NOT_FOUND|NOT_FOUND",
        "ACCOUNT_BALANCE": "5064.50",
        "PAYER_NAME": "Sophie Martin",
    },
}


def test_render_cba_returns_correct_size_image():
    img = render_cba(_CBA_ENTRY, _CBA_LAYOUT)
    assert isinstance(img, Image.Image)
    assert img.size == (2480, 3508)
    assert img.mode == "RGB"


def test_render_cba_is_not_blank():
    """The rendered image should have non-white pixels (actual content drawn)."""
    img = render_cba(_CBA_ENTRY, _CBA_LAYOUT)
    pixels = list(img.getdata())
    non_white = sum(1 for p in pixels if p != (255, 255, 255))
    # A real rendered statement should have substantial content
    assert non_white > 1000, f"Image appears blank: only {non_white} non-white pixels"


def test_render_cba_has_dark_header_area():
    """CBA bank name is drawn in dark navy near the top."""
    img = render_cba(_CBA_ENTRY, _CBA_LAYOUT)
    # Sample pixels in the header area (top 200px, left half)
    header_pixels = [img.getpixel((x, y)) for x in range(100, 400, 20) for y in range(100, 160, 10)]
    dark_pixels = [p for p in header_pixels if sum(p) < 400]
    assert len(dark_pixels) > 0, "Expected dark pixels in header area for bank name"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n du pytest tests/test_bank_statement.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_cba'`

- [ ] **Step 3: Rewrite bank_statement.py with shared utilities and CBA renderer**

Replace the entire contents of `generators/bank_statement.py`:

```python
"""Bank statement renderer — Big 4 Australian banks.

Per-bank renderers (CBA, Westpac, NAB, ANZ) dispatched via layout['renderer'] key.
Each renderer encodes the bank's visual DNA: header style, column layout, row
separators, balance formatting, and footer structure.
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    draw_separator_line,
    draw_text_right,
    fmt_amount,
    load_font,
)


# ── Shared utilities ─────────────────────────────────────────────────────────


def _parse_hex_color(hex_str: str) -> tuple[int, int, int]:
    """Parse '#RRGGBB' to (R, G, B) tuple."""
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _parse_transactions(fields: dict) -> list[dict]:
    """Parse pipe-delimited transaction fields into a list of transaction dicts."""
    dates = fields.get("TRANSACTION_DATES", "").split("|")
    descs = fields.get("TRANSACTION_DESCRIPTIONS", "").split("|")
    debits = fields.get("TRANSACTION_AMOUNTS_PAID", "").split("|")
    credits = fields.get("TRANSACTION_AMOUNTS_RECEIVED", "").split("|")

    txns = []
    for i in range(len(dates)):
        txn = {
            "date": dates[i].strip() if i < len(dates) else "",
            "description": descs[i].strip() if i < len(descs) else "",
            "debit": debits[i].strip() if i < len(debits) else "NOT_FOUND",
            "credit": credits[i].strip() if i < len(credits) else "NOT_FOUND",
        }
        txns.append(txn)
    return txns


def _compute_running_balances(txns: list[dict], closing_balance: str) -> list[dict]:
    """Compute running balances working backward from closing balance."""
    try:
        balance = Decimal(closing_balance)
    except Exception:  # noqa: BLE001
        balance = Decimal("0")

    for txn in reversed(txns):
        txn["balance"] = balance
        debit = Decimal(txn["debit"]) if txn["debit"] != "NOT_FOUND" else Decimal("0")
        credit = Decimal(txn["credit"]) if txn["credit"] != "NOT_FOUND" else Decimal("0")
        balance = balance + debit - credit
    return txns


# ── CBA Renderer ─────────────────────────────────────────────────────────────


def render_cba(entry: dict, layout: dict) -> Image.Image:
    """Render a Commonwealth Bank statement.

    Visual DNA: dark navy bank name, horizontal rules framing column headers,
    'Withdrawal'/'Deposit' columns, $ amounts, footer with transaction types.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout config with 'page_dimensions', 'font_sizes', etc.

    Returns:
        PIL Image of the rendered CBA bank statement.
    """
    dims = layout["page_dimensions"]
    width, height = dims["width"], dims["height"]
    margin = layout["margin"]
    font_sizes = layout["font_sizes"]
    row_height = layout["row_height"]
    fields = entry["fields"]

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_header = load_font(font_sizes["header"], bold=True)
    font_body = load_font(font_sizes["body"])
    font_body_bold = load_font(font_sizes["body"], bold=True)
    font_footer = load_font(font_sizes["footer"])

    right_edge = width - margin
    y = margin

    # ── Bank name and legal lines ──
    bank_color = layout.get("bank_name_color", "#12107D")
    draw.text((margin, y), "Commonwealth Bank", font=font_header, fill=bank_color)
    y += 45

    legal_lines = [
        "Commonwealth Bank of Australia",
        "ABN 48 123 456 789 AFSL and",
        "Australian credit licence 234567",
    ]
    for line in legal_lines:
        draw.text((margin, y), line, font=font_footer, fill="#666666")
        y += 16
    y += 30

    # ── Account details ──
    payer = fields.get("PAYER_NAME", "")
    date_range = fields.get("STATEMENT_DATE_RANGE", "")

    draw.text((margin, y), f"Account Holder: {payer}", font=font_body, fill="black")
    y += 30
    if date_range:
        parts = date_range.split(" - ")
        if len(parts) == 2:
            draw.text(
                (margin, y),
                f"Statement Period: {parts[0].strip()} to {parts[1].strip()}",
                font=font_body,
                fill="black",
            )
        y += 30
    y += 20

    # ── Column positions ──
    # Text columns left-aligned, numeric columns right-aligned
    col_date_x = margin
    col_desc_x = margin + 200
    col_withdrawal_right = right_edge - 420
    col_deposit_right = right_edge - 210
    col_balance_right = right_edge

    # ── Column header bar ──
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 8

    headers = layout.get("column_headers", ["Date", "Description", "Withdrawal", "Deposit", "Balance"])
    draw.text((col_date_x, y), headers[0], font=font_body_bold, fill="black")
    draw.text((col_desc_x, y), headers[1], font=font_body_bold, fill="black")
    draw_text_right(draw, headers[2], x_right=col_withdrawal_right, y=y, font=font_body_bold)
    draw_text_right(draw, headers[3], x_right=col_deposit_right, y=y, font=font_body_bold)
    draw_text_right(draw, headers[4], x_right=col_balance_right, y=y, font=font_body_bold)
    y += 28
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 12

    # ── Transactions ──
    txns = _parse_transactions(fields)
    txns = _compute_running_balances(txns, fields.get("ACCOUNT_BALANCE", "0"))

    # Opening balance row
    if layout.get("show_opening_balance") and txns:
        opening_balance = txns[0]["balance"]
        # Reverse the first txn to get opening
        first_debit = Decimal(txns[0]["debit"]) if txns[0]["debit"] != "NOT_FOUND" else Decimal("0")
        first_credit = Decimal(txns[0]["credit"]) if txns[0]["credit"] != "NOT_FOUND" else Decimal("0")
        opening = opening_balance - first_credit + first_debit
        draw.text((col_desc_x, y), "Opening Balance", font=font_body, fill="black")
        draw_text_right(draw, fmt_amount(opening), x_right=col_balance_right, y=y, font=font_body)
        y += row_height

    for txn in txns:
        draw.text((col_date_x, y), txn["date"], font=font_body, fill="black")

        # Truncate description to fit column
        desc = txn["description"]
        max_desc_width = col_withdrawal_right - col_desc_x - 220
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_width and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_desc_x, y), desc, font=font_body, fill="black")

        if txn["debit"] != "NOT_FOUND":
            draw_text_right(
                draw, fmt_amount(Decimal(txn["debit"])),
                x_right=col_withdrawal_right, y=y, font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            draw_text_right(
                draw, fmt_amount(Decimal(txn["credit"])),
                x_right=col_deposit_right, y=y, font=font_body,
            )
        if "balance" in txn:
            draw_text_right(
                draw, fmt_amount(txn["balance"]),
                x_right=col_balance_right, y=y, font=font_body,
            )
        y += row_height

    # ── Bottom rule ──
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 40

    # ── Footer ──
    if layout.get("show_footer_transaction_types"):
        draw.text((margin, y), "TRANSACTION TYPES:", font=font_body_bold, fill="black")
        y += 28
        txn_types = [
            "EFTPOS — Electronic Funds Transfer at Point of Sale",
            "BPAY — Bill Payment",
            "DD — Direct Debit",
            "VISA DEBIT — Visa card purchase",
            "ATM — Automated Teller Machine withdrawal",
        ]
        for desc in txn_types:
            draw.text((margin, y), desc, font=font_footer, fill="#666666")
            y += 16
        y += 20
        draw.text((margin, y), "CommBank.com.au  |  13 2221", font=font_footer, fill="#666666")

    return img


# ── Dispatch ─────────────────────────────────────────────────────────────────

# Placeholder stubs — replaced in Tasks 4-6
def render_westpac(entry: dict, layout: dict) -> Image.Image:
    """Westpac renderer stub — replaced in Task 4."""
    raise NotImplementedError("Westpac renderer not yet implemented")


def render_nab(entry: dict, layout: dict) -> Image.Image:
    """NAB renderer stub — replaced in Task 5."""
    raise NotImplementedError("NAB renderer not yet implemented")


def render_anz(entry: dict, layout: dict) -> Image.Image:
    """ANZ renderer stub — replaced in Task 6."""
    raise NotImplementedError("ANZ renderer not yet implemented")


_BANK_RENDERERS: dict[str, callable] = {
    "cba": render_cba,
    "westpac": render_westpac,
    "nab": render_nab,
    "anz": render_anz,
}


def render_bank_statement(entry: dict, layout: dict) -> Image.Image:
    """Render a bank statement image from ground truth entry and layout config.

    Dispatches to the per-bank renderer based on layout['renderer'].

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with 'renderer' key.

    Returns:
        PIL Image of the rendered bank statement.
    """
    renderer_key = layout.get("renderer")
    if renderer_key not in _BANK_RENDERERS:
        valid = sorted(_BANK_RENDERERS.keys())
        msg = (
            f"Unknown renderer '{renderer_key}' in layout. "
            f"Expected one of {valid}. "
            f"Check the 'renderer' key in config/layouts/bank_statements.yml."
        )
        raise ValueError(msg)
    return _BANK_RENDERERS[renderer_key](entry, layout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n du pytest tests/test_bank_statement.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Lint and commit**

```bash
cd /Users/tod/Desktop/LMM_POC-synthetic-benchmark
conda run -n du ruff check --fix --ignore ARG001,ARG002,F841 generators/bank_statement.py tests/test_bank_statement.py
conda run -n du ruff format generators/bank_statement.py tests/test_bank_statement.py
git add generators/bank_statement.py tests/test_bank_statement.py
git commit -m "feat: add CBA renderer with dispatch, replace generic bank statement renderer"
```

---

### Task 4: Westpac Renderer

**Files:**
- Modify: `generators/bank_statement.py` (replace `render_westpac` stub)
- Test: `tests/test_bank_statement.py` (add Westpac tests)

- [ ] **Step 1: Write failing test for Westpac renderer**

Append to `tests/test_bank_statement.py`:

```python
from generators.bank_statement import render_westpac

# ── Westpac renderer tests ───────────────────────────────────────────────────

_WESTPAC_LAYOUT = {
    "bank": "Westpac Banking Corporation",
    "bank_code": "WBC",
    "renderer": "westpac",
    "variant": "standard",
    "page_dimensions": {"width": 2480, "height": 3508},
    "font_sizes": {"header": 26, "body": 16, "sub_description": 13, "footer": 9},
    "margin": 80,
    "row_height": 40,
    "logo_color": "#C41E3A",
    "date_format": "DD MMM YY",
}

_WESTPAC_ENTRY = {
    "layout": "westpac_standard",
    "degradation_seed": 2345,
    "fields": {
        "DOCUMENT_TYPE": "BANK_STATEMENT",
        "SUPPLIER_NAME": "Westpac",
        "STATEMENT_DATE_RANGE": "01/11/2023 - 30/11/2023",
        "TRANSACTION_DATES": "03/11/2023|05/11/2023|10/11/2023|12/11/2023|15/11/2023|20/11/2023",
        "TRANSACTION_DESCRIPTIONS": (
            "RETAIL STORE SUBURB AUS|SHOPPING CENTRE SUBURB|AUTOMOTIVE SERVICE|"
            "PHARMACY PTY LTD|FUEL AUSTRALIA PTY|CRED VOUCHER"
        ),
        "TRANSACTION_AMOUNTS_PAID": "234.80|37.20|156.70|78.40|456.90|NOT_FOUND",
        "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|NOT_FOUND|NOT_FOUND|NOT_FOUND|NOT_FOUND|2500.00",
        "ACCOUNT_BALANCE": "8500.00",
        "PAYER_NAME": "David Nguyen",
    },
}


def test_render_westpac_returns_correct_size():
    img = render_westpac(_WESTPAC_ENTRY, _WESTPAC_LAYOUT)
    assert isinstance(img, Image.Image)
    assert img.size == (2480, 3508)


def test_render_westpac_is_not_blank():
    img = render_westpac(_WESTPAC_ENTRY, _WESTPAC_LAYOUT)
    pixels = list(img.getdata())
    non_white = sum(1 for p in pixels if p != (255, 255, 255))
    assert non_white > 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n du pytest tests/test_bank_statement.py::test_render_westpac_returns_correct_size -v`
Expected: FAIL — `NotImplementedError: Westpac renderer not yet implemented`

- [ ] **Step 3: Implement Westpac renderer**

Replace the `render_westpac` stub in `generators/bank_statement.py` with:

```python
def render_westpac(entry: dict, layout: dict) -> Image.Image:
    """Render a Westpac bank statement.

    Visual DNA: red 'Westpac' logo top-right, 'Date of Transaction' column,
    dense multi-line layout, 'Debits'/'Credits ()' headers, page numbers.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout config with rendering parameters.

    Returns:
        PIL Image of the rendered Westpac bank statement.
    """
    dims = layout["page_dimensions"]
    width, height = dims["width"], dims["height"]
    margin = layout["margin"]
    font_sizes = layout["font_sizes"]
    row_height = layout["row_height"]
    fields = entry["fields"]

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_header = load_font(font_sizes["header"], bold=True)
    font_body = load_font(font_sizes["body"])
    font_body_bold = load_font(font_sizes["body"], bold=True)
    font_small = load_font(font_sizes.get("sub_description", 13))
    font_footer = load_font(font_sizes["footer"])

    right_edge = width - margin
    y = margin

    # ── Westpac logo (top-right, red) ──
    logo_color = layout.get("logo_color", "#C41E3A")
    draw_text_right(draw, "Westpac", x_right=right_edge, y=y, font=font_header, fill=logo_color)
    y += 50

    # ── Page number (top-right) ──
    draw_text_right(draw, "Page 1 of 1", x_right=right_edge, y=y, font=font_footer, fill="#666666")
    y += 30

    # ── Account info ──
    payer = fields.get("PAYER_NAME", "")
    date_range = fields.get("STATEMENT_DATE_RANGE", "")
    supplier = fields.get("SUPPLIER_NAME", "Westpac")

    if layout.get("show_rewards_section"):
        draw.text((margin, y), "Rewards Points Balance Summary", font=font_body_bold, fill="black")
        y += 30
        draw.text((margin, y), "Available Points: 12,456", font=font_small, fill="#666666")
        y += 25
        draw_separator_line(draw, margin, right_edge, y, color="#CCCCCC")
        y += 20

    draw.text((margin, y), f"{supplier}: Premium CardII transactions", font=font_body_bold, fill="black")
    y += 30
    draw.text((margin, y), payer, font=font_body, fill="black")
    y += 25
    if date_range:
        draw.text((margin, y), f"Statement Period: {date_range}", font=font_small, fill="#666666")
        y += 25
    y += 15

    # ── Column positions ──
    col_date_x = margin
    col_desc_x = margin + 220
    col_debit_right = right_edge - 260
    col_credit_right = right_edge

    # ── Column headers ──
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 6
    draw.text((col_date_x, y), "Date of", font=font_body_bold, fill="black")
    y_sub = y + 20
    draw.text((col_date_x, y_sub), "Transaction", font=font_body_bold, fill="black")
    draw.text((col_desc_x, y), "Description", font=font_body_bold, fill="black")
    draw_text_right(draw, "Debits", x_right=col_debit_right, y=y, font=font_body_bold)
    draw_text_right(draw, "Credits ()", x_right=col_credit_right, y=y, font=font_body_bold)
    y = y_sub + 22
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 8

    # ── Transactions (dense) ──
    txns = _parse_transactions(fields)

    for txn in txns:
        draw.text((col_date_x, y), txn["date"], font=font_body, fill="black")

        # Truncate description to fit
        desc = txn["description"]
        max_desc_w = col_debit_right - col_desc_x - 180
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_w and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_desc_x, y), desc, font=font_body, fill="black")

        if txn["debit"] != "NOT_FOUND":
            draw_text_right(
                draw, fmt_amount(Decimal(txn["debit"])),
                x_right=col_debit_right, y=y, font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            draw_text_right(
                draw, fmt_amount(Decimal(txn["credit"])),
                x_right=col_credit_right, y=y, font=font_body,
            )
        y += row_height

    # ── Bottom rule ──
    draw_separator_line(draw, margin, right_edge, y, color="black")

    return img
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n du pytest tests/test_bank_statement.py -v -k westpac`
Expected: Both Westpac tests PASS.

- [ ] **Step 5: Lint and commit**

```bash
conda run -n du ruff check --fix --ignore ARG001,ARG002,F841 generators/bank_statement.py tests/test_bank_statement.py
conda run -n du ruff format generators/bank_statement.py tests/test_bank_statement.py
git add generators/bank_statement.py tests/test_bank_statement.py
git commit -m "feat: add Westpac renderer with dense multi-line layout"
```

---

### Task 5: NAB Renderer

**Files:**
- Modify: `generators/bank_statement.py` (replace `render_nab` stub)
- Test: `tests/test_bank_statement.py` (add NAB tests)

- [ ] **Step 1: Write failing test for NAB renderer**

Append to `tests/test_bank_statement.py`:

```python
from generators.bank_statement import render_nab

_NAB_LAYOUT = {
    "bank": "National Australia Bank",
    "bank_code": "NAB",
    "renderer": "nab",
    "variant": "classic",
    "page_dimensions": {"width": 2480, "height": 3508},
    "font_sizes": {"header": 26, "body": 16, "sub_description": 13, "footer": 9},
    "margin": 80,
    "row_height": 42,
    "header_bar_color": "#E8F0FE",
    "balance_suffix": "Cr",
    "date_grouping": True,
    "show_references": True,
    "show_brought_forward": True,
    "date_format": "DD MMM YYYY",
}

_NAB_ENTRY = {
    "layout": "nab_classic",
    "degradation_seed": 3456,
    "fields": {
        "DOCUMENT_TYPE": "BANK_STATEMENT",
        "SUPPLIER_NAME": "National Australia Bank",
        "STATEMENT_DATE_RANGE": "01/03/2024 - 31/03/2024",
        "TRANSACTION_DATES": "05/03/2024|05/03/2024|10/03/2024|15/03/2024|20/03/2024",
        "TRANSACTION_DESCRIPTIONS": "EFTPOS Fresh Grocers|Pizza Delivery|Farmland Markets|Gas Station|Auto Repair",
        "TRANSACTION_AMOUNTS_PAID": "34.85|45.50|89.75|78.40|NOT_FOUND",
        "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|NOT_FOUND|NOT_FOUND|NOT_FOUND|580.00",
        "ACCOUNT_BALANCE": "8926.65",
        "PAYER_NAME": "Emma Wilson",
    },
}


def test_render_nab_returns_correct_size():
    img = render_nab(_NAB_ENTRY, _NAB_LAYOUT)
    assert isinstance(img, Image.Image)
    assert img.size == (2480, 3508)


def test_render_nab_is_not_blank():
    img = render_nab(_NAB_ENTRY, _NAB_LAYOUT)
    pixels = list(img.getdata())
    non_white = sum(1 for p in pixels if p != (255, 255, 255))
    assert non_white > 1000


def test_render_nab_has_blue_header_area():
    """NAB uses light blue (#E8F0FE) background on header bar."""
    img = render_nab(_NAB_ENTRY, _NAB_LAYOUT)
    # Sample pixels in the area where the header bar should be drawn (y~200-260)
    blue_pixels = []
    for x in range(100, 400, 20):
        for y_pos in range(200, 280, 10):
            p = img.getpixel((x, y_pos))
            if p[2] > p[0] and p[2] > 200:  # blue channel dominant and bright
                blue_pixels.append(p)
    assert len(blue_pixels) > 0, "Expected light blue pixels in NAB header area"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n du pytest tests/test_bank_statement.py -v -k nab`
Expected: FAIL — `NotImplementedError: NAB renderer not yet implemented`

- [ ] **Step 3: Implement NAB renderer**

Replace the `render_nab` stub in `generators/bank_statement.py`:

```python
def render_nab(entry: dict, layout: dict) -> Image.Image:
    """Render a National Australia Bank statement.

    Visual DNA: light blue header bar and date-group rows, 'Particulars' column,
    date grouping with bold date headers, brought-forward/carried-forward rows,
    reference numbers with dotted leaders, balance with 'Cr' suffix.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout config with rendering parameters.

    Returns:
        PIL Image of the rendered NAB bank statement.
    """
    dims = layout["page_dimensions"]
    width, height = dims["width"], dims["height"]
    margin = layout["margin"]
    font_sizes = layout["font_sizes"]
    row_height = layout["row_height"]
    fields = entry["fields"]

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_header = load_font(font_sizes["header"], bold=True)
    font_body = load_font(font_sizes["body"])
    font_body_bold = load_font(font_sizes["body"], bold=True)
    font_small = load_font(font_sizes.get("sub_description", 13))
    font_footer = load_font(font_sizes["footer"])

    right_edge = width - margin
    header_color = _parse_hex_color(layout.get("header_bar_color", "#E8F0FE"))
    balance_suffix = layout.get("balance_suffix", "Cr")
    y = margin

    # ── Bank name header ──
    draw.text((margin, y), "NAB Classic Banking", font=font_header, fill="#003366")
    y += 50

    # ── Account Details box ──
    box_top = y
    payer = fields.get("PAYER_NAME", "")
    draw.rectangle([(margin, y), (right_edge, y + 100)], outline="#003366", width=2)
    y += 12
    draw.text((margin + 15, y), "Account Details", font=font_body_bold, fill="black")
    y += 25
    draw.text((margin + 15, y), payer, font=font_body, fill="black")
    draw_text_right(draw, "BSB Number", x_right=right_edge - 250, y=y, font=font_small, fill="#666666")
    draw_text_right(draw, "082-456", x_right=right_edge - 15, y=y, font=font_body, fill="black")
    y += 22
    draw_text_right(draw, "Account Number", x_right=right_edge - 250, y=y, font=font_small, fill="#666666")
    draw_text_right(draw, "98-765-4321", x_right=right_edge - 15, y=y, font=font_body, fill="black")
    y = box_top + 120

    # ── Section header ──
    draw.text((margin, y), "Transaction Details (continued)", font=font_body_bold, fill="black")
    y += 35

    # ── Column header bar (light blue background) ──
    draw.rectangle([(margin, y), (right_edge, y + 30)], fill=header_color)

    col_date_x = margin + 10
    col_desc_x = margin + 160
    col_debit_right = right_edge - 380
    col_credit_right = right_edge - 190
    col_balance_right = right_edge - 10

    draw.text((col_date_x, y + 5), "Date", font=font_body_bold, fill="black")
    draw.text((col_desc_x, y + 5), "Particulars", font=font_body_bold, fill="black")
    draw_text_right(draw, "Debits", x_right=col_debit_right, y=y + 5, font=font_body_bold)
    draw_text_right(draw, "Credits", x_right=col_credit_right, y=y + 5, font=font_body_bold)
    draw_text_right(draw, "Balance", x_right=col_balance_right, y=y + 5, font=font_body_bold)
    y += 35

    # ── Transactions with date grouping ──
    txns = _parse_transactions(fields)
    txns = _compute_running_balances(txns, fields.get("ACCOUNT_BALANCE", "0"))

    # Brought forward row
    if layout.get("show_brought_forward") and txns:
        first_debit = Decimal(txns[0]["debit"]) if txns[0]["debit"] != "NOT_FOUND" else Decimal("0")
        first_credit = Decimal(txns[0]["credit"]) if txns[0]["credit"] != "NOT_FOUND" else Decimal("0")
        opening = txns[0]["balance"] - first_credit + first_debit
        draw.text((col_desc_x, y), "Brought forward", font=font_body, fill="black")
        draw_text_right(
            draw, f"{fmt_amount(opening)} {balance_suffix}",
            x_right=col_balance_right, y=y, font=font_body,
        )
        y += row_height

    current_date_group = ""
    for txn in txns:
        # Date grouping: bold date header when date changes
        if layout.get("date_grouping") and txn["date"] != current_date_group:
            current_date_group = txn["date"]
            # Light blue date group row
            draw.rectangle([(margin, y), (right_edge, y + row_height - 2)], fill=header_color)
            draw.text((col_date_x, y + 4), txn["date"], font=font_body_bold, fill="black")
            y += row_height

        # Indented transaction description
        desc = txn["description"]
        max_desc_w = col_debit_right - col_desc_x - 200
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_w and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_desc_x + 20, y + 4), desc, font=font_body, fill="black")

        # Reference number with dotted leader (if enabled)
        if layout.get("show_references"):
            ref_num = str(hash(txn["description"]) % 10**10).zfill(10)
            ref_text = f"Ref: {ref_num}"
            dots = "." * 40
            draw.text((col_desc_x + 20, y + 22), f"{ref_text}{dots}", font=font_small, fill="#999999")

        if txn["debit"] != "NOT_FOUND":
            draw_text_right(
                draw, fmt_amount(Decimal(txn["debit"])),
                x_right=col_debit_right, y=y + 4, font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            draw_text_right(
                draw, fmt_amount(Decimal(txn["credit"])),
                x_right=col_credit_right, y=y + 4, font=font_body,
            )
        if "balance" in txn:
            draw_text_right(
                draw, f"{fmt_amount(txn['balance'])} {balance_suffix}",
                x_right=col_balance_right, y=y + 4, font=font_body,
            )

        ref_extra = 20 if layout.get("show_references") else 0
        y += row_height + ref_extra

    # ── Carried forward ──
    if layout.get("show_brought_forward") and txns:
        draw.text((col_desc_x, y), "Carried forward", font=font_body_bold, fill="black")
        draw_text_right(
            draw, f"{fmt_amount(Decimal(fields.get('ACCOUNT_BALANCE', '0')))} {balance_suffix}",
            x_right=col_balance_right, y=y, font=font_body_bold,
        )

    return img
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n du pytest tests/test_bank_statement.py -v -k nab`
Expected: All 3 NAB tests PASS.

- [ ] **Step 5: Lint and commit**

```bash
conda run -n du ruff check --fix --ignore ARG001,ARG002,F841 generators/bank_statement.py tests/test_bank_statement.py
conda run -n du ruff format generators/bank_statement.py tests/test_bank_statement.py
git add generators/bank_statement.py tests/test_bank_statement.py
git commit -m "feat: add NAB renderer with date grouping and dotted reference leaders"
```

---

### Task 6: ANZ Renderer

**Files:**
- Modify: `generators/bank_statement.py` (replace `render_anz` stub)
- Test: `tests/test_bank_statement.py` (add ANZ tests)

- [ ] **Step 1: Write failing test for ANZ renderer**

Append to `tests/test_bank_statement.py`:

```python
from generators.bank_statement import render_anz

_ANZ_LAYOUT = {
    "bank": "Australia and New Zealand Banking Group",
    "bank_code": "ANZ",
    "renderer": "anz",
    "variant": "standard",
    "page_dimensions": {"width": 2480, "height": 3508},
    "font_sizes": {"header": 28, "body": 18, "sub_description": 14, "footer": 10},
    "margin": 100,
    "row_height": 45,
    "header_color": "#0061B5",
    "balance_suffix_debit": "DR",
    "balance_suffix_credit": "CR",
    "show_totals_row": True,
    "show_brought_forward": True,
    "date_format": "DD/MM/YY",
}

_ANZ_ENTRY = {
    "layout": "anz_standard",
    "degradation_seed": 4567,
    "fields": {
        "DOCUMENT_TYPE": "BANK_STATEMENT",
        "SUPPLIER_NAME": "ANZ",
        "STATEMENT_DATE_RANGE": "01/06/2024 - 30/06/2024",
        "TRANSACTION_DATES": "03/06/2024|05/06/2024|10/06/2024|15/06/2024|20/06/2024",
        "TRANSACTION_DESCRIPTIONS": "LOAN PAYMENT SAMPLE|INTEREST|ATM WITHDRAWAL|SALARY PAYMENT|TRANSFER",
        "TRANSACTION_AMOUNTS_PAID": "1200.00|1671.18|NOT_FOUND|NOT_FOUND|2400.00",
        "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|NOT_FOUND|1200.00|5778.51|NOT_FOUND",
        "ACCOUNT_BALANCE": "7500.00",
        "PAYER_NAME": "James Wilson",
    },
}


def test_render_anz_returns_correct_size():
    img = render_anz(_ANZ_ENTRY, _ANZ_LAYOUT)
    assert isinstance(img, Image.Image)
    assert img.size == (2480, 3508)


def test_render_anz_is_not_blank():
    img = render_anz(_ANZ_ENTRY, _ANZ_LAYOUT)
    pixels = list(img.getdata())
    non_white = sum(1 for p in pixels if p != (255, 255, 255))
    assert non_white > 1000


def test_render_anz_has_blue_header():
    """ANZ uses blue (#0061B5) branding at the top."""
    img = render_anz(_ANZ_ENTRY, _ANZ_LAYOUT)
    blue_pixels = []
    for x in range(100, 400, 20):
        for y_pos in range(100, 180, 10):
            p = img.getpixel((x, y_pos))
            if p[2] > 150 and p[0] < 50:
                blue_pixels.append(p)
    assert len(blue_pixels) > 0, "Expected blue pixels in ANZ header area"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n du pytest tests/test_bank_statement.py -v -k anz`
Expected: FAIL — `NotImplementedError: ANZ renderer not yet implemented`

- [ ] **Step 3: Implement ANZ renderer**

Replace the `render_anz` stub in `generators/bank_statement.py`:

```python
def render_anz(entry: dict, layout: dict) -> Image.Image:
    """Render an ANZ bank statement.

    Visual DNA: blue header bar, 'Transaction Description' column, DR/CR balance
    suffixes, BALANCE BROUGHT FORWARD opening, totals row at bottom.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout config with rendering parameters.

    Returns:
        PIL Image of the rendered ANZ bank statement.
    """
    dims = layout["page_dimensions"]
    width, height = dims["width"], dims["height"]
    margin = layout["margin"]
    font_sizes = layout["font_sizes"]
    row_height = layout["row_height"]
    fields = entry["fields"]

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_header = load_font(font_sizes["header"], bold=True)
    font_body = load_font(font_sizes["body"])
    font_body_bold = load_font(font_sizes["body"], bold=True)
    font_small = load_font(font_sizes.get("sub_description", 14))
    font_footer = load_font(font_sizes["footer"])

    right_edge = width - margin
    header_color = _parse_hex_color(layout.get("header_color", "#0061B5"))
    suffix_dr = layout.get("balance_suffix_debit", "DR")
    suffix_cr = layout.get("balance_suffix_credit", "CR")
    y = margin

    # ── Blue header bar ──
    draw.rectangle([(0, 0), (width, 80)], fill=header_color)
    draw.text((margin, 20), "ANZ", font=font_header, fill="white")

    # ── Account info ──
    y = 100
    payer = fields.get("PAYER_NAME", "")
    date_range = fields.get("STATEMENT_DATE_RANGE", "")

    draw_text_right(draw, "Account number    0000-00000", x_right=right_edge, y=y, font=font_small, fill="#666666")
    y += 25
    draw.text((margin, y), "Transaction Details", font=font_body_bold, fill="black")
    y += 35

    # ── Column header with underline ──
    col_date_x = margin
    col_desc_x = margin + 200
    col_debit_right = right_edge - 400
    col_credit_right = right_edge - 200
    col_balance_right = right_edge

    draw.text((col_date_x, y), "Date", font=font_body_bold, fill="black")
    draw.text((col_desc_x, y), "Transaction Description", font=font_body_bold, fill="black")
    draw_text_right(draw, "Debits", x_right=col_debit_right, y=y, font=font_body_bold)
    draw_text_right(draw, "Credits", x_right=col_credit_right, y=y, font=font_body_bold)
    draw_text_right(draw, "Balance", x_right=col_balance_right, y=y, font=font_body_bold)
    y += 28
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 10

    # ── Transactions ──
    txns = _parse_transactions(fields)
    txns = _compute_running_balances(txns, fields.get("ACCOUNT_BALANCE", "0"))

    def _format_balance(bal: Decimal) -> str:
        """Format balance with DR/CR suffix."""
        if bal >= 0:
            return f"{fmt_amount(bal)} {suffix_cr}"
        return f"{fmt_amount(abs(bal))} {suffix_dr}"

    # BALANCE BROUGHT FORWARD
    if layout.get("show_brought_forward") and txns:
        first_debit = Decimal(txns[0]["debit"]) if txns[0]["debit"] != "NOT_FOUND" else Decimal("0")
        first_credit = Decimal(txns[0]["credit"]) if txns[0]["credit"] != "NOT_FOUND" else Decimal("0")
        opening = txns[0]["balance"] - first_credit + first_debit
        draw.text((col_desc_x, y), "BALANCE BROUGHT FORWARD", font=font_body_bold, fill="black")
        draw_text_right(draw, _format_balance(opening), x_right=col_balance_right, y=y, font=font_body)
        y += row_height

    total_debits = Decimal("0")
    total_credits = Decimal("0")

    for txn in txns:
        draw.text((col_date_x, y), txn["date"], font=font_body, fill="black")

        desc = txn["description"]
        max_desc_w = col_debit_right - col_desc_x - 220
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_w and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_desc_x, y), desc, font=font_body, fill="black")

        if txn["debit"] != "NOT_FOUND":
            debit_val = Decimal(txn["debit"])
            total_debits += debit_val
            draw_text_right(
                draw, fmt_amount(debit_val),
                x_right=col_debit_right, y=y, font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            credit_val = Decimal(txn["credit"])
            total_credits += credit_val
            draw_text_right(
                draw, fmt_amount(credit_val),
                x_right=col_credit_right, y=y, font=font_body,
            )
        if "balance" in txn:
            draw_text_right(
                draw, _format_balance(txn["balance"]),
                x_right=col_balance_right, y=y, font=font_body,
            )
        y += row_height

    # ── Totals row ──
    if layout.get("show_totals_row"):
        draw_separator_line(draw, margin, right_edge, y, color="black")
        y += 8
        draw.text((col_desc_x, y), "Totals at end of period", font=font_body_bold, fill="black")
        draw_text_right(draw, fmt_amount(total_debits), x_right=col_debit_right, y=y, font=font_body_bold)
        draw_text_right(draw, fmt_amount(total_credits), x_right=col_credit_right, y=y, font=font_body_bold)

    return img
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n du pytest tests/test_bank_statement.py -v -k anz`
Expected: All 3 ANZ tests PASS.

- [ ] **Step 5: Run ALL bank statement tests**

Run: `conda run -n du pytest tests/test_bank_statement.py -v`
Expected: All tests PASS (CBA + Westpac + NAB + ANZ + shared utils).

- [ ] **Step 6: Lint and commit**

```bash
conda run -n du ruff check --fix --ignore ARG001,ARG002,F841 generators/bank_statement.py tests/test_bank_statement.py
conda run -n du ruff format generators/bank_statement.py tests/test_bank_statement.py
git add generators/bank_statement.py tests/test_bank_statement.py
git commit -m "feat: add ANZ renderer with DR/CR suffixes and totals row"
```

---

### Task 7: Update seed_ground_truth.py

**Files:**
- Modify: `scripts/seed_ground_truth.py:25-38,253-324`
- Test: `tests/test_seed_ground_truth.py`

- [ ] **Step 1: Write failing test for bank entry generation**

Create `tests/test_seed_ground_truth.py`:

```python
"""Tests for seed_ground_truth.py bank statement generation changes."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.seed_ground_truth import _generate_bank_entries

_NEW_BANK_LAYOUTS = [
    "cba_standard",
    "cba_date_grouped",
    "westpac_standard",
    "westpac_premium",
    "nab_classic",
    "nab_dense",
    "anz_standard",
    "anz_modern",
]


def test_bank_entries_have_25_to_40_transactions():
    """Each bank statement should have 25-40 transactions."""
    rng = random.Random(42)
    entries = _generate_bank_entries(rng, 10)
    for case_id, entry in entries.items():
        dates = entry["fields"]["TRANSACTION_DATES"].split("|")
        count = len(dates)
        assert 25 <= count <= 40, (
            f"{case_id}: has {count} transactions, expected 25-40"
        )


def test_bank_entries_dates_within_statement_period():
    """All transaction dates must fall within the statement date range."""
    rng = random.Random(42)
    entries = _generate_bank_entries(rng, 10)
    for case_id, entry in entries.items():
        date_range = entry["fields"]["STATEMENT_DATE_RANGE"]
        start_str, end_str = date_range.split(" - ")
        start_parts = start_str.strip().split("/")
        end_parts = end_str.strip().split("/")
        start_day, start_month = int(start_parts[0]), int(start_parts[1])
        end_day, end_month = int(end_parts[0]), int(end_parts[1])

        dates = entry["fields"]["TRANSACTION_DATES"].split("|")
        for date_str in dates:
            d, m, _y = date_str.strip().split("/")
            day, month = int(d), int(m)
            assert month == start_month, (
                f"{case_id}: txn date {date_str} month {month} != statement month {start_month}"
            )
            assert start_day <= day <= end_day, (
                f"{case_id}: txn date {date_str} day {day} not in [{start_day}, {end_day}]"
            )


def test_bank_entries_dates_chronologically_sorted():
    """Transaction dates should be in ascending order."""
    rng = random.Random(42)
    entries = _generate_bank_entries(rng, 10)
    for case_id, entry in entries.items():
        dates_str = entry["fields"]["TRANSACTION_DATES"].split("|")
        days = []
        for ds in dates_str:
            d, _m, _y = ds.strip().split("/")
            days.append(int(d))
        assert days == sorted(days), f"{case_id}: dates not sorted: {days}"


def test_bank_entries_use_new_layout_names():
    """Bank entries should cycle through the 8 new layout names."""
    rng = random.Random(42)
    entries = _generate_bank_entries(rng, 16)
    used_layouts = {e["layout"] for e in entries.values()}
    assert used_layouts == set(_NEW_BANK_LAYOUTS), (
        f"Expected layouts {set(_NEW_BANK_LAYOUTS)}, got {used_layouts}"
    )


def test_bank_entries_pipe_delimited_fields_same_count():
    """All pipe-delimited fields must have the same count per entry."""
    rng = random.Random(42)
    entries = _generate_bank_entries(rng, 10)
    for case_id, entry in entries.items():
        fields = entry["fields"]
        dates = len(fields["TRANSACTION_DATES"].split("|"))
        descs = len(fields["TRANSACTION_DESCRIPTIONS"].split("|"))
        debits = len(fields["TRANSACTION_AMOUNTS_PAID"].split("|"))
        credits = len(fields["TRANSACTION_AMOUNTS_RECEIVED"].split("|"))
        assert dates == descs == debits == credits, (
            f"{case_id}: pipe count mismatch: dates={dates} descs={descs} debits={debits} credits={credits}"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n du pytest tests/test_seed_ground_truth.py -v`
Expected: FAIL — transaction count is 8-15 (not 25-40), dates are unsorted and out of range.

- [ ] **Step 3: Update _BANK_LAYOUTS and _generate_bank_entries in seed_ground_truth.py**

In `scripts/seed_ground_truth.py`, replace `_BANK_LAYOUTS` (lines 25-38):

```python
_BANK_LAYOUTS = [
    "cba_standard",
    "cba_date_grouped",
    "westpac_standard",
    "westpac_premium",
    "nab_classic",
    "nab_dense",
    "anz_standard",
    "anz_modern",
]
```

Replace the `_generate_bank_entries` function (lines 253-324):

```python
def _generate_bank_entries(rng: random.Random, count: int) -> dict:
    """Generate bank statement ground truth entries.

    Each entry has 25-40 transactions, chronologically sorted within the
    statement period month.
    """
    entries: dict = {}
    layouts = _BANK_LAYOUTS

    for i in range(count):
        case_id = f"CASEB{i + 1:03d}"
        layout = layouts[i % len(layouts)]

        bank_name, bank_code, bsb_prefix = _BANKS[i % len(_BANKS)]
        holder = _ACCOUNT_HOLDERS[i % len(_ACCOUNT_HOLDERS)]
        loc = _LOCATIONS[i % len(_LOCATIONS)]
        suburb, postcode, state = loc

        # Statement period: 1-month window
        _d, m, y = _rand_date(rng)
        period_start = _fmt_date(1, m, y)
        max_day = 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31
        period_end = _fmt_date(max_day, m, y)
        statement_range = f"{period_start} - {period_end}"

        # 25-40 transactions, sorted by day within the month
        n_txns = rng.randint(25, 40)
        txn_days = sorted(rng.randint(1, max_day) for _ in range(n_txns))

        txn_dates = []
        txn_descs = []
        txn_debits = []
        txn_credits = []

        closing_balance = _rand_amount(rng, 500, 15000)

        for txn_day in txn_days:
            txn_dates.append(_fmt_date(txn_day, m, y))

            is_debit = rng.random() < 0.80  # 80% debits
            template = rng.choice(_BANK_DESCS)
            desc = template.format(
                suburb=suburb,
                merchant=rng.choice(_RETAILERS)[0][:12],
                crn=rng.randint(100000000, 999999999),
                ref=f"REF{rng.randint(10000, 99999)}",
                name=rng.choice(_ACCOUNT_HOLDERS).split()[0],
            )
            txn_descs.append(desc)

            if is_debit:
                amt = _rand_amount(rng, 10, 600)
                txn_debits.append(_fmt_decimal(amt))
                txn_credits.append("NOT_FOUND")
            else:
                amt = _rand_amount(rng, 100, 5000)
                txn_debits.append("NOT_FOUND")
                txn_credits.append(_fmt_decimal(amt))

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "BANK_STATEMENT",
                "SUPPLIER_NAME": bank_name,
                "STATEMENT_DATE_RANGE": statement_range,
                "TRANSACTION_DATES": "|".join(txn_dates),
                "TRANSACTION_DESCRIPTIONS": "|".join(txn_descs),
                "TRANSACTION_AMOUNTS_PAID": "|".join(txn_debits),
                "TRANSACTION_AMOUNTS_RECEIVED": "|".join(txn_credits),
                "ACCOUNT_BALANCE": _fmt_decimal(closing_balance),
                "PAYER_NAME": holder,
            },
        }

    return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n du pytest tests/test_seed_ground_truth.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Lint and commit**

```bash
conda run -n du ruff check --fix --ignore ARG001,ARG002,F841 scripts/seed_ground_truth.py tests/test_seed_ground_truth.py
conda run -n du ruff format scripts/seed_ground_truth.py tests/test_seed_ground_truth.py
git add scripts/seed_ground_truth.py tests/test_seed_ground_truth.py
git commit -m "feat: bank statements now generate 25-40 sorted transactions with new layout names"
```

---

### Task 8: Regenerate Ground Truth and Transaction Links

**Files:**
- Regenerate: `ground_truth/bank_statements.yml`
- Regenerate: `ground_truth/transaction_links.yml`

- [ ] **Step 1: Regenerate bank statement ground truth**

Run: `cd /Users/tod/Desktop/LMM_POC-synthetic-benchmark && conda run -n du python scripts/seed_ground_truth.py`
Expected: `Wrote 55 entries to ground_truth/bank_statements.yml` (plus receipt/invoice/cc outputs).

- [ ] **Step 2: Verify regenerated ground truth**

Run: `conda run -n du python -c "import yaml; data=yaml.safe_load(open('ground_truth/bank_statements.yml')); e=list(data.values())[0]; print(len(e['fields']['TRANSACTION_DATES'].split('|')), 'transactions in first entry'); print('Layout:', e['layout'])"`
Expected: `25-40 transactions in first entry` and `Layout: cba_standard`.

- [ ] **Step 3: Reseed transaction links**

Run: `cd /Users/tod/Desktop/LMM_POC-synthetic-benchmark && conda run -n du python scripts/seed_transaction_links.py`
Expected: `Generated 110 transaction links: {easy: ~50, medium: ~30, hard: ~28}` (approximate counts).

- [ ] **Step 4: Validate regenerated data**

Run: `conda run -n du python -m generators.pipeline validate`
Expected: `Validation passed.`

- [ ] **Step 5: Commit regenerated data**

```bash
git add ground_truth/bank_statements.yml ground_truth/transaction_links.yml
git commit -m "data: regenerate bank statement ground truth (25-40 txns) and transaction links"
```

---

### Task 9: End-to-End Generate and Visual Inspection

**Files:**
- Output: `output/clean/bank_statements/*.png`, `output/degraded/bank_statements/*.png`

- [ ] **Step 1: Generate all bank statement images**

Run: `cd /Users/tod/Desktop/LMM_POC-synthetic-benchmark && conda run -n du python -m generators.pipeline generate --type bank_statements`
Expected: `bank_statements: generated 55 documents.`

- [ ] **Step 2: Verify output files exist for all 8 layouts**

Run: `ls output/clean/bank_statements/ | head -16`
Expected: Files named `CASEB001_cba_standard.png`, `CASEB002_cba_date_grouped.png`, `CASEB003_westpac_standard.png`, etc.

- [ ] **Step 3: Visual inspection of one per bank**

Open these files to verify visual quality:

```bash
open output/clean/bank_statements/CASEB001_cba_standard.png
open output/clean/bank_statements/CASEB003_westpac_standard.png
open output/clean/bank_statements/CASEB005_nab_classic.png
open output/clean/bank_statements/CASEB007_anz_standard.png
```

**Check for:**
- Column headers aligned with values (no systematic misalignment)
- 25-40 transaction rows filling a substantial portion of the page
- Bank-specific visual DNA (CBA navy name + rules, Westpac red logo, NAB blue bars, ANZ blue header)
- Amounts right-aligned and properly formatted with $

- [ ] **Step 4: Generate degraded variants**

Run: `cd /Users/tod/Desktop/LMM_POC-synthetic-benchmark && conda run -n du python -m generators.pipeline generate --type bank_statements`
Expected: Both clean and degraded directories populated.

- [ ] **Step 5: Regenerate derived outputs**

Run: `conda run -n du python -m generators.pipeline derive`
Expected: `CSV written: derived/ground_truth.csv` and `JSONL written: derived/ground_truth.jsonl`.

- [ ] **Step 6: Run full test suite**

Run: `conda run -n du pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 7: Lint everything**

```bash
conda run -n du ruff check --fix --ignore ARG001,ARG002,F841 generators/bank_statement.py generators/common.py scripts/seed_ground_truth.py
conda run -n du ruff format .
conda run -n du mypy . --ignore-missing-imports
```

- [ ] **Step 8: Final commit**

```bash
git add output/ derived/
git commit -m "chore: regenerate all bank statement images and derived outputs"
```
