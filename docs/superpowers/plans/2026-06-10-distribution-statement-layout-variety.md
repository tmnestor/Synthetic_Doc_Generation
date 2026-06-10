# Distribution Statement Layout Variety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the trust Distribution Statement from one layout to six (three archetypes × two variants) with varied labels, reusing the existing ground-truth values unchanged, and regenerate the images.

**Architecture:** The pipeline is layout-driven: each ground-truth entry names a `layout:` and a section-walking renderer draws it. We add six layout definitions, extend the Distribution Statement renderer with new section types, lift the duplicated grid-drawing code into a shared `draw_table` helper, then reassign layouts across the existing 50 entries by a deterministic index rule (touching only `layout:` lines) and regenerate outputs.

**Tech Stack:** Python 3.12, Pillow (PIL), PyYAML, typer, pytest, ruff, mypy. Conda env `du`.

**Conventions (from repo CLAUDE.md):**
- Run all tooling in the `du` env: `conda run -n du <cmd>`.
- `tests/`, `output/`, `derived/` are **gitignored** — never `git add` them; commits stage only `config/`, `generators/`, `scripts/`, `docs/`.
- Pre-commit hooks run tests/ruff/mypy — **never** use `--no-verify`. No Claude attribution in commit messages.
- Domain term "ATO" is used as-is in this project.
- YAML is the single source of truth; no layout/label values hardcoded in Python.

---

## File Structure

- `generators/common.py` — add a presentation-only `draw_table` helper (shared by two renderers).
- `generators/trust_income_schedule.py` — refactor its inline grid code to call `draw_table` (behaviour-preserving).
- `config/layouts/distribution_statements.yml` — replace the single layout with six.
- `generators/distribution_statement.py` — rewrite the renderer to support the new section types.
- `scripts/migrate_distribution_layouts.py` — new; reassigns `layout:` lines in the ground truth.
- `scripts/seed_trust_distributions.py` — update the layout list + index-based assignment for future reseeds.
- `ground_truth/distribution_statements.yml` — `layout:` lines only (rewritten by the migration script).
- `tests/test_renderers_trust.py` — update the retired-id reference; add per-layout render tests.
- `tests/test_layout_assignment.py` — new; assignment balance + registry coverage.
- `tests/fixtures/` — new; holds the trust-income-schedule characterization reference PNG (local-only).

---

## Task 1: Feature branch + commit the spec

**Files:**
- Modify: git branch state
- Add: `docs/superpowers/specs/2026-06-10-distribution-statement-layout-variety-design.md` (already written)

- [ ] **Step 1: Create a feature branch off main**

Run:
```bash
cd /Users/tod/Desktop/Synthetic_Doc_Generation
git switch -c feat/distribution-layout-variety
```
Expected: `Switched to a new branch 'feat/distribution-layout-variety'`

- [ ] **Step 2: Commit only the spec (leave unrelated dirty files alone)**

Run:
```bash
git add docs/superpowers/specs/2026-06-10-distribution-statement-layout-variety-design.md
git commit -m "📝 docs: add distribution statement layout variety design spec"
```
Expected: one file committed. Do **not** stage `README.md`, `receipts.zip`, `degrade_camera_scan.py`, or `rectify_camera_scan.py` — they are pre-existing unrelated changes.

---

## Task 2: Shared `draw_table` helper + behaviour-preserving refactor of the trust income schedule

**Files:**
- Modify: `generators/common.py` (add `draw_table`)
- Modify: `generators/trust_income_schedule.py:120-171` (the `grid_section` branch)
- Test: `tests/test_renderers_trust.py` (characterization test), `tests/fixtures/tis_ref_CASE201.png`

- [ ] **Step 1: Capture the pre-refactor reference render (characterization fixture)**

Run:
```bash
cd /Users/tod/Desktop/Synthetic_Doc_Generation
mkdir -p tests/fixtures
conda run -n du python -c "
import yaml
from pathlib import Path
from generators.trust_income_schedule import render_trust_income_schedule
lay = yaml.safe_load(Path('config/layouts/trust_income_schedules.yml').read_text())['layouts']
gt = yaml.safe_load(Path('ground_truth/trust_income_schedules.yml').read_text())
img = render_trust_income_schedule(gt['CASE201'], lay['trust_income_schedule_standard'])
img.save('tests/fixtures/tis_ref_CASE201.png')
print('saved reference')
"
```
Expected: `saved reference` and a PNG at `tests/fixtures/tis_ref_CASE201.png`.

- [ ] **Step 2: Write the failing characterization test**

Add to `tests/test_renderers_trust.py` (append at end of file):

```python
class TestTrustIncomeScheduleCharacterization:
    def test_render_matches_reference(self):
        from PIL import ImageChops

        ref_path = Path(__file__).parent / "fixtures" / "tis_ref_CASE201.png"
        layouts = _load_layout("trust_income_schedules")
        gt = _load_gt("trust_income_schedules")
        img = render_trust_income_schedule(
            gt["CASE201"], layouts["trust_income_schedule_standard"]
        ).convert("RGB")
        ref = Image.open(ref_path).convert("RGB")
        assert img.size == ref.size
        diff = ImageChops.difference(img, ref)
        assert diff.getbbox() is None, "trust income schedule render drifted from reference"
```

- [ ] **Step 3: Run it to confirm it PASSES on current (pre-refactor) code**

Run: `conda run -n du pytest tests/test_renderers_trust.py::TestTrustIncomeScheduleCharacterization -v`
Expected: PASS (the renderer is unchanged, so it matches the reference). This locks current behaviour before we refactor.

- [ ] **Step 4: Add the `draw_table` helper to `generators/common.py`**

Append to `generators/common.py`:

```python
def draw_table(
    draw: ImageDraw.ImageDraw,
    *,
    x_left: int,
    x_right: int,
    y: int,
    title: str,
    columns: list[dict],
    rows: list[dict],
    total: dict | None,
    font_sub: Font,
    font_body: Font,
    font_small: Font,
    font_label_code: Font,
    section_bg: str,
    header_row_bg: str,
    grid_line: str,
    label_code_color: str,
    row_h: int = 52,
) -> int:
    """Draw a bordered component table and return the new y coordinate.

    Presentation-only: callers pass pre-formatted string values.

    Args:
        columns: each {"header", "width", "kind"} where kind is one of
            "label_code" | "description" | "amount".
        rows: each {"label_code", "description", "value"} (value pre-formatted).
        total: optional {"description", "value"} drawn as a final row.

    Returns:
        The y coordinate below the table.
    """
    if title:
        draw.rectangle([(x_left, y), (x_right, y + 44)], fill=section_bg)
        draw.text((x_left + 12, y + 8), title, font=font_sub, fill="black")
        y += 56

    offsets: list[int] = []
    cx = x_left
    for col in columns:
        offsets.append(cx)
        cx += col.get("width", 400)

    draw.rectangle([(x_left, y), (x_right, y + row_h)], fill=header_row_bg)
    for col, ox in zip(columns, offsets, strict=True):
        draw.text((ox + 8, y + 12), col.get("header", ""), font=font_small, fill="black")
    y += row_h

    all_rows = list(rows)
    if total is not None:
        all_rows.append({"label_code": "", "description": total["description"], "value": total["value"]})

    for row in all_rows:
        draw_separator_line(draw, x_left, x_right, y, color=grid_line, width=1)
        for col, ox in zip(columns, offsets, strict=True):
            kind = col.get("kind", "description")
            if kind == "label_code":
                code = row.get("label_code", "")
                if code:
                    draw.text((ox + 30, y + 12), code, font=font_label_code, fill=label_code_color)
            elif kind == "amount":
                draw_text_right(draw, row.get("value", ""), x_right - 20, y + 14, font_body)
            else:
                draw.text((ox + 8, y + 14), row.get("description", ""), font=font_body, fill="black")
        y += row_h

    draw_separator_line(draw, x_left, x_right, y, color=grid_line, width=1)
    return y + 20
```

- [ ] **Step 5: Refactor the trust income schedule to call `draw_table`**

In `generators/trust_income_schedule.py`, update the import block (lines 12-18) to include `draw_table`:

```python
from generators.common import (
    draw_separator_line,
    draw_table,
    draw_text_center,
    draw_text_right,
    fmt_amount,
    load_font,
)
```

Then replace the entire `elif sec_type == "grid_section":` branch (currently lines 120-171) with:

```python
        elif sec_type == "grid_section":
            cols = section.get("columns", [])
            kinded: list[dict] = []
            for i, col in enumerate(cols):
                if i == 0:
                    kind = "label_code"
                elif i == len(cols) - 1:
                    kind = "amount"
                else:
                    kind = "description"
                kinded.append({**col, "kind": kind})

            table_rows: list[dict] = []
            for row in section.get("rows", []):
                raw = str(fields.get(row.get("field", ""), ""))
                try:
                    value = fmt_amount(Decimal(raw))
                except Exception:  # noqa: BLE001
                    value = f"${raw}"
                table_rows.append(
                    {
                        "label_code": row.get("label_code", ""),
                        "description": row.get("description", ""),
                        "value": value,
                    }
                )

            y = draw_table(
                draw,
                x_left=margin,
                x_right=right_edge,
                y=y,
                title=section.get("title", ""),
                columns=kinded,
                rows=table_rows,
                total=None,
                font_sub=font_sub,
                font_body=font_b,
                font_small=font_s,
                font_label_code=font_lc,
                section_bg=colors.get("section_bg", "#F0F0F0"),
                header_row_bg="#E8E8E8",
                grid_line=grid_line_color,
                label_code_color=label_code_color,
            )
```

- [ ] **Step 6: Run the characterization test — output must be byte-identical**

Run: `conda run -n du pytest tests/test_renderers_trust.py::TestTrustIncomeScheduleCharacterization -v`
Expected: PASS. If it FAILS, the `draw_table` offsets diverge from the original; adjust `draw_table` (the +30 label_code, +8 description, `x_right - 20` amount, and `y + 12/14` offsets must match the original inline code) until the reference matches.

- [ ] **Step 7: Run lint, format, type checks**

Run:
```bash
conda run -n du ruff check --fix generators/common.py generators/trust_income_schedule.py
conda run -n du ruff format generators/common.py generators/trust_income_schedule.py
conda run -n du mypy generators/common.py generators/trust_income_schedule.py --ignore-missing-imports
```
Expected: no errors.

- [ ] **Step 8: Run the full trust render + ground-truth test suites**

Run: `conda run -n du pytest tests/test_renderers_trust.py tests/test_ground_truth_trust.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit (source only — tests are gitignored)**

```bash
git add generators/common.py generators/trust_income_schedule.py
git commit -m "♻️ refactor: extract shared draw_table helper used by grid renderers"
```

---

## Task 3: Define the six Distribution Statement layouts

**Files:**
- Modify: `config/layouts/distribution_statements.yml` (replace entire file)
- Test: `tests/test_layout_assignment.py` (new)

- [ ] **Step 1: Write the failing registry test**

Create `tests/test_layout_assignment.py`:

```python
"""Tests for distribution statement layout set and assignment."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

_LAYOUTS = Path(__file__).parent.parent / "config" / "layouts" / "distribution_statements.yml"

_EXPECTED_IDS = {
    "dist_software_navy",
    "dist_software_teal",
    "dist_table_plain",
    "dist_table_ruled",
    "dist_letter_formal",
    "dist_letter_compact",
}


def _registry() -> dict:
    return yaml.safe_load(_LAYOUTS.read_text())["layouts"]


class TestLayoutRegistry:
    def test_has_six_expected_layouts(self):
        assert set(_registry().keys()) == _EXPECTED_IDS

    def test_every_layout_has_required_keys(self):
        for name, layout in _registry().items():
            assert layout["format"] == "distribution_statement", name
            assert "page_dimensions" in layout, name
            assert "sections" in layout and layout["sections"], name
```

- [ ] **Step 2: Run it to verify it FAILS**

Run: `conda run -n du pytest tests/test_layout_assignment.py::TestLayoutRegistry -v`
Expected: FAIL (file still has only `distribution_statement_standard`).

- [ ] **Step 3: Replace `config/layouts/distribution_statements.yml` with the six layouts**

Overwrite the file with exactly:

```yaml
layouts:
  # ── Archetype 1: accounting-software statement ───────────────────────────
  dist_software_navy:
    format: distribution_statement
    page_dimensions:
      width: 1600
      height: 3508
    margin: 140
    font_sizes:
      header: 44
      subheader: 28
      body: 22
      small: 18
      label_code: 26
    colors:
      header_color: "#1A1A2E"
      accent_color: "#16213E"
      line_color: "#CCCCCC"
    sections:
      - type: letterhead
        title: "Statement of Distribution"
        subtitle: "Trust Distribution Advice"
        height: 120
      - type: spacer
        height: 30
      - type: section
        name: trust_details
        title: "Trust Details"
        fields:
          - label: "Trust name"
            field: TRUST_NAME
          - label: "ABN"
            field: TRUST_ABN
          - label: "Address"
            field: TRUST_ADDRESS
      - type: separator
        height: 20
      - type: section
        name: beneficiary_details
        title: "Beneficiary Details"
        fields:
          - label: "Beneficiary name"
            field: BENEFICIARY_NAME
          - label: "TFN"
            field: BENEFICIARY_TFN
          - label: "Address"
            field: BENEFICIARY_ADDRESS
      - type: separator
        height: 20
      - type: section
        name: period
        title: "Distribution Period"
        fields:
          - label: "Income year"
            field: INCOME_YEAR
          - label: "Date of distribution"
            field: DATE_OF_DISTRIBUTION
      - type: separator
        height: 20
      - type: section
        name: distribution_components
        title: "Distribution Components"
        fields:
          - label: "Share of net income"
            field: SHARE_OF_NET_INCOME
            format: amount
          - label: "Franking credit"
            field: FRANKING_CREDIT
            format: amount
          - label: "Capital gain component"
            field: CAPITAL_GAIN_COMPONENT
            format: amount
          - label: "Foreign income"
            field: FOREIGN_INCOME
            format: amount
          - label: "Tax-free amount"
            field: TAX_FREE_AMOUNT
            format: amount
          - label: "Tax-deferred amount"
            field: TAX_DEFERRED_AMOUNT
            format: amount
      - type: separator
        height: 30
      - type: declaration
        text: "This statement has been prepared by the trustee of the above trust and is provided to the beneficiary for inclusion in their individual income tax return."
        height: 80
      - type: footer
        text: "This is not a tax invoice"

  dist_software_teal:
    format: distribution_statement
    page_dimensions:
      width: 1600
      height: 3508
    margin: 140
    font_sizes:
      header: 40
      subheader: 26
      body: 22
      small: 18
      label_code: 26
    colors:
      header_bg: "#0B6E6E"
      header_text: "#FFFFFF"
      accent_color: "#0B6E6E"
      line_color: "#CCCCCC"
    sections:
      - type: header_bar
        text: "Trust Distribution Statement"
        subtext: "Beneficiary Tax Advice"
        height: 100
      - type: spacer
        height: 20
      - type: two_column
        left:
          title: "Trust"
          fields:
            - label: "Trust"
              field: TRUST_NAME
            - label: "Australian Business Number"
              field: TRUST_ABN
            - label: "Registered address"
              field: TRUST_ADDRESS
        right:
          title: "Beneficiary"
          fields:
            - label: "Name"
              field: BENEFICIARY_NAME
            - label: "Tax file number"
              field: BENEFICIARY_TFN
            - label: "Postal address"
              field: BENEFICIARY_ADDRESS
      - type: separator
        height: 20
      - type: section
        name: period
        title: "Financial Year"
        fields:
          - label: "Financial year"
            field: INCOME_YEAR
          - label: "Date prepared"
            field: DATE_OF_DISTRIBUTION
      - type: separator
        height: 20
      - type: section
        name: distribution_components
        title: "Your Distribution"
        fields:
          - label: "Net income distributed"
            field: SHARE_OF_NET_INCOME
            format: amount
          - label: "Franking credits attached"
            field: FRANKING_CREDIT
            format: amount
          - label: "Net capital gain"
            field: CAPITAL_GAIN_COMPONENT
            format: amount
          - label: "Foreign source income"
            field: FOREIGN_INCOME
            format: amount
          - label: "Tax-free distribution"
            field: TAX_FREE_AMOUNT
            format: amount
          - label: "Tax-deferred distribution"
            field: TAX_DEFERRED_AMOUNT
            format: amount
      - type: footer
        text: "Generated by trustee accounting software"

  # ── Archetype 2: tabular / grid statement ────────────────────────────────
  dist_table_plain:
    format: distribution_statement
    page_dimensions:
      width: 1600
      height: 3508
    margin: 140
    font_sizes:
      header: 42
      subheader: 26
      body: 22
      small: 18
      label_code: 26
    colors:
      header_color: "#222222"
      accent_color: "#444444"
      line_color: "#BBBBBB"
      section_bg: "#F4F4F4"
      header_row: "#ECECEC"
    sections:
      - type: letterhead
        title: "Distribution Statement"
        subtitle: ""
        height: 110
      - type: spacer
        height: 20
      - type: section
        name: trust_details
        title: "Trust"
        fields:
          - label: "Name of trust"
            field: TRUST_NAME
          - label: "ABN"
            field: TRUST_ABN
          - label: "Address"
            field: TRUST_ADDRESS
      - type: section
        name: beneficiary_details
        title: "Beneficiary"
        fields:
          - label: "Name"
            field: BENEFICIARY_NAME
          - label: "Tax file number"
            field: BENEFICIARY_TFN
          - label: "Income year"
            field: INCOME_YEAR
      - type: spacer
        height: 10
      - type: table
        title: "Distribution Components"
        columns:
          - header: "Component"
            width: 1000
            kind: description
          - header: "Amount $"
            width: 320
            kind: amount
        rows:
          - description: "Income entitlement"
            field: SHARE_OF_NET_INCOME
          - description: "Imputation credit"
            field: FRANKING_CREDIT
          - description: "Share of capital gains"
            field: CAPITAL_GAIN_COMPONENT
          - description: "Assessable foreign income"
            field: FOREIGN_INCOME
          - description: "Tax-free amount"
            field: TAX_FREE_AMOUNT
          - description: "Tax-deferred amount"
            field: TAX_DEFERRED_AMOUNT
      - type: footer
        text: "Retain for your records"

  dist_table_ruled:
    format: distribution_statement
    page_dimensions:
      width: 1600
      height: 3508
    margin: 140
    font_sizes:
      header: 40
      subheader: 26
      body: 22
      small: 18
      label_code: 26
    colors:
      header_bg: "#3A3A3A"
      header_text: "#FFFFFF"
      accent_color: "#3A3A3A"
      line_color: "#999999"
      section_bg: "#EDEDED"
      header_row: "#DDDDDD"
      label_code_color: "#0066CC"
    sections:
      - type: header_bar
        text: "Trust Income Distribution"
        subtext: "Annual Statement"
        height: 100
      - type: spacer
        height: 20
      - type: two_column
        left:
          title: "Trust"
          fields:
            - label: "Trust name"
              field: TRUST_NAME
            - label: "ABN"
              field: TRUST_ABN
        right:
          title: "Beneficiary"
          fields:
            - label: "Beneficiary"
              field: BENEFICIARY_NAME
            - label: "TFN"
              field: BENEFICIARY_TFN
      - type: section
        name: period
        title: "Period"
        fields:
          - label: "Year ended 30 June"
            field: INCOME_YEAR
      - type: spacer
        height: 10
      - type: table
        title: "Statement of Entitlement"
        columns:
          - header: "Code"
            width: 140
            kind: label_code
          - header: "Description"
            width: 860
            kind: description
          - header: "Amount $"
            width: 320
            kind: amount
        rows:
          - label_code: "Q"
            description: "Franking credit"
            field: FRANKING_CREDIT
          - label_code: "M"
            description: "Net capital gain"
            field: CAPITAL_GAIN_COMPONENT
          - label_code: "C"
            description: "Foreign income"
            field: FOREIGN_INCOME
          - label_code: "R"
            description: "Tax-free amount"
            field: TAX_FREE_AMOUNT
          - label_code: "T"
            description: "Tax-deferred amount"
            field: TAX_DEFERRED_AMOUNT
        total_row:
          label: "Net income share"
          field: SHARE_OF_NET_INCOME
      - type: footer
        text: "Sensitive (when completed)"

  # ── Archetype 3: simple trustee letter ───────────────────────────────────
  dist_letter_formal:
    format: distribution_statement
    page_dimensions:
      width: 1600
      height: 3508
    margin: 160
    font_sizes:
      header: 38
      subheader: 26
      body: 24
      small: 18
      label_code: 26
    colors:
      header_color: "#2B2B2B"
      accent_color: "#2B2B2B"
      line_color: "#CCCCCC"
    sections:
      - type: letterhead
        title: "Office of the Trustee"
        subtitle: "Trust Distribution Advice"
        height: 120
      - type: spacer
        height: 20
      - type: letter_meta
        date_field: DATE_OF_DISTRIBUTION
        addressee_fields:
          - BENEFICIARY_NAME
          - BENEFICIARY_ADDRESS
        salutation: "Dear {BENEFICIARY_NAME},"
      - type: letter_body
        paragraphs:
          - "We write to advise of your entitlement as a beneficiary of the {TRUST_NAME} for the income year {INCOME_YEAR}."
          - "The components of your distribution are set out below. Please retain this advice for inclusion in your individual income tax return."
      - type: spacer
        height: 10
      - type: section
        name: identity
        title: "Reference"
        fields:
          - label: "Trust ABN"
            field: TRUST_ABN
          - label: "Your tax file number"
            field: BENEFICIARY_TFN
      - type: section
        name: distribution_components
        title: "Distribution Components"
        fields:
          - label: "Share of net income"
            field: SHARE_OF_NET_INCOME
            format: amount
          - label: "Franking credit"
            field: FRANKING_CREDIT
            format: amount
          - label: "Capital gain component"
            field: CAPITAL_GAIN_COMPONENT
            format: amount
          - label: "Foreign income"
            field: FOREIGN_INCOME
            format: amount
          - label: "Tax-free amount"
            field: TAX_FREE_AMOUNT
            format: amount
          - label: "Tax-deferred amount"
            field: TAX_DEFERRED_AMOUNT
            format: amount
      - type: signature_block
        gap: 30
        lines:
          - "Yours faithfully,"
          - "Trustee, {TRUST_NAME}"
      - type: footer
        text: "This is not a tax invoice"

  dist_letter_compact:
    format: distribution_statement
    page_dimensions:
      width: 1600
      height: 3508
    margin: 160
    font_sizes:
      header: 34
      subheader: 24
      body: 24
      small: 18
      label_code: 26
    colors:
      header_color: "#333333"
      accent_color: "#555555"
      line_color: "#CCCCCC"
    sections:
      - type: letterhead
        title: "Trust Distribution Advice"
        subtitle: ""
        height: 100
      - type: letter_meta
        date_field: DATE_OF_DISTRIBUTION
        addressee_fields:
          - BENEFICIARY_NAME
        salutation: "Dear {BENEFICIARY_NAME},"
      - type: letter_body
        paragraphs:
          - "Your distribution from the {TRUST_NAME} for {INCOME_YEAR} is summarised below. Trust ABN: {TRUST_ABN}. Your TFN: {BENEFICIARY_TFN}."
      - type: spacer
        height: 10
      - type: section
        name: distribution_components
        title: "Summary"
        fields:
          - label: "Income entitlement"
            field: SHARE_OF_NET_INCOME
            format: amount
          - label: "Franking credit"
            field: FRANKING_CREDIT
            format: amount
          - label: "Capital gains"
            field: CAPITAL_GAIN_COMPONENT
            format: amount
          - label: "Foreign income"
            field: FOREIGN_INCOME
            format: amount
          - label: "Tax-free amount"
            field: TAX_FREE_AMOUNT
            format: amount
          - label: "Tax-deferred amount"
            field: TAX_DEFERRED_AMOUNT
            format: amount
      - type: signature_block
        gap: 20
        lines:
          - "Trustee, {TRUST_NAME}"
      - type: footer
        text: "Retain for your records"
```

- [ ] **Step 4: Run the registry test — now PASSES**

Run: `conda run -n du pytest tests/test_layout_assignment.py::TestLayoutRegistry -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/layouts/distribution_statements.yml
git commit -m "✨ feat: define six distribution statement layouts across three archetypes"
```

---

## Task 4: Rewrite the Distribution Statement renderer for the new section types

**Files:**
- Modify: `generators/distribution_statement.py` (replace entire file)
- Test: `tests/test_renderers_trust.py` (replace the `TestDistributionStatementRenderer` class)

- [ ] **Step 1: Write failing per-layout render tests**

In `tests/test_renderers_trust.py`, replace the existing `TestDistributionStatementRenderer` class (lines 53-61) with:

```python
class TestDistributionStatementRenderer:
    _LAYOUT_IDS = (
        "dist_software_navy",
        "dist_software_teal",
        "dist_table_plain",
        "dist_table_ruled",
        "dist_letter_formal",
        "dist_letter_compact",
    )

    def test_every_layout_renders_a4(self):
        layouts = _load_layout("distribution_statements")
        gt = _load_gt("distribution_statements")
        entry = gt["CASE201"]
        for layout_id in self._LAYOUT_IDS:
            img = render_distribution_statement(entry, layouts[layout_id])
            assert isinstance(img, Image.Image), layout_id
            assert img.size == (1600, 3508), layout_id

    def test_render_is_not_blank(self):
        layouts = _load_layout("distribution_statements")
        gt = _load_gt("distribution_statements")
        entry = gt["CASE201"]
        for layout_id in self._LAYOUT_IDS:
            img = render_distribution_statement(entry, layouts[layout_id]).convert("L")
            extrema = img.getextrema()
            assert extrema[0] < 128, f"{layout_id} appears blank (min={extrema[0]})"
```

- [ ] **Step 2: Run to verify it FAILS**

Run: `conda run -n du pytest tests/test_renderers_trust.py::TestDistributionStatementRenderer -v`
Expected: FAIL with `KeyError: 'dist_software_navy'`-style or rendering errors for unsupported section types (`header_bar`, `two_column`, `table`, `letter_meta`, `letter_body`, `signature_block`).

- [ ] **Step 3: Replace `generators/distribution_statement.py` in full**

Overwrite the file with:

```python
"""Distribution statement renderer — six trustee-produced layouts.

Renders A4 distribution statements across accounting-software, tabular, and
trustee-letter archetypes. Every layout exposes the same scalar fields; only
structure, styling, and label wording differ. Section types are interpreted
from the layout YAML (the single source of truth).
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    Font,
    draw_separator_line,
    draw_table,
    draw_text_center,
    draw_text_right,
    fmt_amount,
    load_font,
)


def _subst(text: str, fields: dict) -> str:
    """Replace {FIELD_KEY} placeholders with field values (text/identity only)."""
    out = text
    for key, value in fields.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _fmt(value: str) -> str:
    """Format a raw decimal string as $X,XXX.XX, falling back gracefully."""
    try:
        return fmt_amount(Decimal(value))
    except Exception:  # noqa: BLE001
        return f"${value}"


def _draw_paragraph(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    x_left: int,
    x_right: int,
    font: Font,
    fill: str = "black",
) -> int:
    """Word-wrap and draw a paragraph; return the y below it."""
    line = ""
    for word in text.split():
        test = f"{line} {word}".strip()
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] > x_right - x_left and line:
            draw.text((x_left, y), line, font=font, fill=fill)
            y += 32
            line = word
        else:
            line = test
    if line:
        draw.text((x_left, y), line, font=font, fill=fill)
        y += 32
    return y


def _draw_column_block(
    draw: ImageDraw.ImageDraw,
    block: dict,
    fields: dict,
    y: int,
    x: int,
    font_sub: Font,
    font_b: Font,
    font_s: Font,
    accent: str,
) -> int:
    """Draw one column of a two_column section; return its bottom y."""
    title = block.get("title", "")
    if title:
        draw.text((x, y), title, font=font_sub, fill=accent)
        y += 40
    for fd in block.get("fields", []):
        draw.text((x, y), f"{fd.get('label', '')}:", font=font_s, fill="gray")
        y += 26
        draw.text((x + 20, y), str(fields.get(fd.get("field", ""), "")), font=font_b, fill="black")
        y += 38
    return y


def render_distribution_statement(entry: dict, layout: dict) -> Image.Image:
    """Render a distribution statement from ground truth and layout config.

    Args:
        entry: Ground truth YAML entry with a 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered distribution statement.
    """
    fields = entry["fields"]
    page_dims = layout.get("page_dimensions", {})
    width = page_dims.get("width", 1600)
    height = page_dims.get("height", 3508)
    margin = layout.get("margin", 140)
    right_edge = width - margin

    fs = layout.get("font_sizes", {})
    colors = layout.get("colors", {})

    font_h = load_font(fs.get("header", 44), bold=True)
    font_sub = load_font(fs.get("subheader", 28), bold=True)
    font_b = load_font(fs.get("body", 22))
    font_s = load_font(fs.get("small", 18))
    font_lc = load_font(fs.get("label_code", 26), bold=True)

    header_color = colors.get("header_color", "#1A1A2E")
    accent_color = colors.get("accent_color", "#16213E")
    line_color = colors.get("line_color", "#CCCCCC")

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    for section in layout.get("sections", []):
        st = section.get("type")

        if st == "letterhead":
            draw.text((margin, y), section.get("title", ""), font=font_h, fill=header_color)
            y += 60
            subtitle = section.get("subtitle", "")
            if subtitle:
                draw.text((margin, y), subtitle, font=font_sub, fill=accent_color)
                y += 44
            draw_separator_line(draw, margin, right_edge, y, color=header_color, width=3)
            y += section.get("height", 120) - 100

        elif st == "header_bar":
            bar_h = section.get("height", 100)
            bg = colors.get("header_bg", "#0B6E6E")
            fg = colors.get("header_text", "#FFFFFF")
            draw.rectangle([(0, y), (width, y + bar_h)], fill=bg)
            draw.text((margin, y + 15), section.get("text", ""), font=font_h, fill=fg)
            subtext = section.get("subtext", "")
            if subtext:
                draw_text_right(draw, subtext, right_edge, y + 22, font_sub, fill=fg)
            y += bar_h + 20

        elif st == "spacer":
            y += section.get("height", 30)

        elif st == "section":
            title = section.get("title", "")
            if title:
                draw.text((margin, y), title, font=font_sub, fill=accent_color)
                y += 40
            for fd in section.get("fields", []):
                label = fd.get("label", "")
                value = str(fields.get(fd.get("field", ""), ""))
                if fd.get("format") == "amount":
                    draw.text((margin + 20, y), label, font=font_b, fill="black")
                    draw_text_right(draw, _fmt(value), right_edge, y, font_b)
                    draw_separator_line(draw, margin + 20, right_edge, y + 34, color=line_color, width=1)
                    y += 52
                else:
                    draw.text((margin + 20, y), f"{label}:", font=font_s, fill="gray")
                    y += 26
                    draw.text((margin + 40, y), value, font=font_b, fill="black")
                    y += 38
            y += 16

        elif st == "two_column":
            mid = (margin + right_edge) // 2
            start_y = y
            y_left = _draw_column_block(
                draw, section.get("left", {}), fields, start_y, margin,
                font_sub, font_b, font_s, accent_color,
            )
            y_right = _draw_column_block(
                draw, section.get("right", {}), fields, start_y, mid + 20,
                font_sub, font_b, font_s, accent_color,
            )
            y = max(y_left, y_right) + 16

        elif st == "table":
            rows = [
                {
                    "label_code": r.get("label_code", ""),
                    "description": r.get("description", ""),
                    "value": _fmt(str(fields.get(r.get("field", ""), ""))),
                }
                for r in section.get("rows", [])
            ]
            total = None
            tr = section.get("total_row")
            if tr is not None:
                total = {
                    "description": tr.get("label", ""),
                    "value": _fmt(str(fields.get(tr.get("field", ""), ""))),
                }
            y = draw_table(
                draw,
                x_left=margin,
                x_right=right_edge,
                y=y,
                title=section.get("title", ""),
                columns=section.get("columns", []),
                rows=rows,
                total=total,
                font_sub=font_sub,
                font_body=font_b,
                font_small=font_s,
                font_label_code=font_lc,
                section_bg=colors.get("section_bg", "#F0F0F0"),
                header_row_bg=colors.get("header_row", "#E8E8E8"),
                grid_line=line_color,
                label_code_color=colors.get("label_code_color", "#0066CC"),
            )

        elif st == "letter_meta":
            date_field = section.get("date_field", "")
            if date_field:
                draw_text_right(draw, str(fields.get(date_field, "")), right_edge, y, font_b)
                y += 44
            for fkey in section.get("addressee_fields", []):
                draw.text((margin, y), str(fields.get(fkey, "")), font=font_b, fill="black")
                y += 34
            y += 16
            salutation = section.get("salutation", "")
            if salutation:
                draw.text((margin, y), _subst(salutation, fields), font=font_b, fill="black")
                y += 44

        elif st == "letter_body":
            for para in section.get("paragraphs", []):
                y = _draw_paragraph(draw, _subst(para, fields), y, margin, right_edge, font_b)
                y += 18

        elif st == "separator":
            draw_separator_line(draw, margin, right_edge, y + 8, color=line_color, width=1)
            y += section.get("height", 20)

        elif st == "declaration":
            text = section.get("text", "")
            if text:
                y = _draw_paragraph(draw, text, y, margin + 20, right_edge - 20, font_s, fill="#555555")
                y += 20

        elif st == "signature_block":
            y += section.get("gap", 30)
            for line in section.get("lines", []):
                draw.text((margin, y), _subst(line, fields), font=font_b, fill="black")
                y += 40

        elif st == "footer":
            draw_text_center(draw, section.get("text", ""), height - 60, width, font_s, fill="gray")

    return img
```

- [ ] **Step 4: Run the per-layout render tests — now PASS**

Run: `conda run -n du pytest tests/test_renderers_trust.py::TestDistributionStatementRenderer -v`
Expected: both tests PASS.

- [ ] **Step 5: Lint, format, type-check**

Run:
```bash
conda run -n du ruff check --fix generators/distribution_statement.py
conda run -n du ruff format generators/distribution_statement.py
conda run -n du mypy generators/distribution_statement.py --ignore-missing-imports
```
Expected: no errors. (`Font` is exported from `generators.common`; confirm the import resolves.)

- [ ] **Step 6: Commit**

```bash
git add generators/distribution_statement.py
git commit -m "✨ feat: render distribution statements via header_bar, two_column, table, and letter sections"
```

---

## Task 5: Migration script — reassign layouts across the existing ground truth

**Files:**
- Create: `scripts/migrate_distribution_layouts.py`
- Test: `tests/test_layout_assignment.py` (add assignment tests)

- [ ] **Step 1: Write the failing assignment-function test**

Append to `tests/test_layout_assignment.py`:

```python
class TestAssignmentFunction:
    def test_round_robin_indices(self):
        from scripts.migrate_distribution_layouts import DISTRIBUTION_LAYOUTS, layout_for_index

        assert layout_for_index(0) == DISTRIBUTION_LAYOUTS[0]
        assert layout_for_index(5) == DISTRIBUTION_LAYOUTS[5]
        assert layout_for_index(6) == DISTRIBUTION_LAYOUTS[0]

    def test_layout_list_matches_registry(self):
        from scripts.migrate_distribution_layouts import DISTRIBUTION_LAYOUTS

        assert set(DISTRIBUTION_LAYOUTS) == _EXPECTED_IDS
        assert len(DISTRIBUTION_LAYOUTS) == 6
```

- [ ] **Step 2: Run to verify it FAILS**

Run: `conda run -n du pytest tests/test_layout_assignment.py::TestAssignmentFunction -v`
Expected: FAIL with `ModuleNotFoundError: scripts.migrate_distribution_layouts`.

- [ ] **Step 3: Create `scripts/migrate_distribution_layouts.py`**

```python
"""Reassign Distribution Statement layouts across the existing ground truth.

Rewrites ONLY each entry's `layout:` line in
ground_truth/distribution_statements.yml, mapping the 50 entries (in file order)
onto the six layouts round-robin by index. Field values, CASE ids, and
degradation seeds are left byte-for-byte unchanged. The script aborts without
writing if any field value would change.

Usage:
    python scripts/migrate_distribution_layouts.py
"""

import re
import sys
from pathlib import Path

import yaml

_GT = Path(__file__).parent.parent / "ground_truth" / "distribution_statements.yml"

DISTRIBUTION_LAYOUTS = [
    "dist_software_navy",
    "dist_software_teal",
    "dist_table_plain",
    "dist_table_ruled",
    "dist_letter_formal",
    "dist_letter_compact",
]

_CASE_RE = re.compile(r"^CASE\d+:\s*$")
_LAYOUT_RE = re.compile(r"^(\s*layout:\s*).*$")


def layout_for_index(index: int) -> str:
    """Deterministic round-robin layout for the Nth entry (0-based)."""
    return DISTRIBUTION_LAYOUTS[index % len(DISTRIBUTION_LAYOUTS)]


def migrate(path: Path = _GT) -> dict[str, str]:
    """Rewrite layout lines in place. Returns {case_id: new_layout}.

    Raises:
        SystemExit: if any field value would change (nothing is written).
    """
    original_text = path.read_text()
    before = yaml.safe_load(original_text)
    before_fields = {cid: e["fields"] for cid, e in before.items()}

    assignments: dict[str, str] = {}
    replaced: set[str] = set()
    current_case: str | None = None
    index = -1
    out: list[str] = []

    for line in original_text.splitlines(keepends=True):
        if _CASE_RE.match(line):
            current_case = line.split(":", 1)[0]
            index += 1
            assignments[current_case] = layout_for_index(index)
            out.append(line)
            continue
        m = _LAYOUT_RE.match(line)
        if m and current_case is not None and current_case not in replaced:
            out.append(f"{m.group(1)}{assignments[current_case]}\n")
            replaced.add(current_case)
            continue
        out.append(line)

    new_text = "".join(out)
    after = yaml.safe_load(new_text)
    after_fields = {cid: e["fields"] for cid, e in after.items()}

    if before_fields != after_fields:
        raise SystemExit("ABORT: field values would change; nothing written.")
    if set(replaced) != set(assignments):
        missing = set(assignments) - set(replaced)
        raise SystemExit(f"ABORT: no layout line found for {sorted(missing)}; nothing written.")

    path.write_text(new_text)
    return assignments


def main() -> None:
    assignments = migrate()
    counts: dict[str, int] = {}
    for layout in assignments.values():
        counts[layout] = counts.get(layout, 0) + 1
    print(f"Reassigned {len(assignments)} entries:")
    for layout in DISTRIBUTION_LAYOUTS:
        print(f"  {layout}: {counts.get(layout, 0)}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the assignment-function test — now PASSES**

Run: `conda run -n du pytest tests/test_layout_assignment.py::TestAssignmentFunction -v`
Expected: PASS.

- [ ] **Step 5: Snapshot field values, run the migration, verify only layout lines changed**

Run:
```bash
cd /Users/tod/Desktop/Synthetic_Doc_Generation
conda run -n du python scripts/migrate_distribution_layouts.py
git diff --stat ground_truth/distribution_statements.yml
git diff ground_truth/distribution_statements.yml | grep -E '^[+-]' | grep -vE '^[+-]\s*layout:' | grep -vE '^(\+\+\+|---)'
```
Expected: the migration prints a balanced spread (eight layouts with 8, two with 9 — `dist_software_navy` and `dist_software_teal` get 9). The final `grep` prints **nothing** (no non-`layout:` line changed). If it prints anything, STOP — the migration altered a value.

- [ ] **Step 6: Add the live-ground-truth assignment test**

Append to `tests/test_layout_assignment.py`:

```python
class TestGroundTruthAssignment:
    def test_every_entry_uses_a_known_layout(self):
        import yaml as _yaml

        gt_path = Path(__file__).parent.parent / "ground_truth" / "distribution_statements.yml"
        gt = _yaml.safe_load(gt_path.read_text())
        for case_id, entry in gt.items():
            assert entry["layout"] in _EXPECTED_IDS, f"{case_id} -> {entry['layout']}"

    def test_assignment_is_balanced(self):
        import yaml as _yaml

        gt_path = Path(__file__).parent.parent / "ground_truth" / "distribution_statements.yml"
        gt = _yaml.safe_load(gt_path.read_text())
        counts: dict[str, int] = {}
        for entry in gt.values():
            counts[entry["layout"]] = counts.get(entry["layout"], 0) + 1
        assert set(counts) == _EXPECTED_IDS
        assert all(8 <= n <= 9 for n in counts.values()), counts
        assert sum(counts.values()) == 50
```

- [ ] **Step 7: Run the full layout-assignment + ground-truth suites**

Run: `conda run -n du pytest tests/test_layout_assignment.py tests/test_ground_truth_trust.py -v`
Expected: all PASS (ground-truth cross-quad value tests confirm the 5 linking fields are intact).

- [ ] **Step 8: Lint, format, type-check the new script**

Run:
```bash
conda run -n du ruff check --fix scripts/migrate_distribution_layouts.py
conda run -n du ruff format scripts/migrate_distribution_layouts.py
conda run -n du mypy scripts/migrate_distribution_layouts.py --ignore-missing-imports
```
Expected: no errors.

- [ ] **Step 9: Commit (script + migrated ground truth; tests are gitignored)**

```bash
git add scripts/migrate_distribution_layouts.py ground_truth/distribution_statements.yml
git commit -m "✨ feat: reassign distribution statements across six layouts (values unchanged)"
```

---

## Task 6: Keep the seed script consistent

**Files:**
- Modify: `scripts/seed_trust_distributions.py:40` and its distribution-layout assignment

- [ ] **Step 1: Confirm the existing assignment is already index-based**

Run: `conda run -n du grep -n "_DISTRIBUTION_STATEMENT_LAYOUTS\|ds_layout" scripts/seed_trust_distributions.py`
Expected: line 40 defines the constant; line 380 is `ds_layout = _DISTRIBUTION_STATEMENT_LAYOUTS[i % len(_DISTRIBUTION_STATEMENT_LAYOUTS)]` where `i` runs `range(_TOTAL_CASES)` with `case_num = 201 + i`. The assignment is **already** `i % len(...)` in ascending case order — identical to `migrate.layout_for_index`. So **only the constant at line 40 changes**; the assignment logic (line 380) needs no edit.

- [ ] **Step 2: Update the layout constant (line 40) — the only edit in this task**

Replace:
```python
_DISTRIBUTION_STATEMENT_LAYOUTS = ["distribution_statement_standard"]
```
with:
```python
_DISTRIBUTION_STATEMENT_LAYOUTS = [
    "dist_software_navy",
    "dist_software_teal",
    "dist_table_plain",
    "dist_table_ruled",
    "dist_letter_formal",
    "dist_letter_compact",
]
```
The other three layout constants (`_TRUST_RETURN_LAYOUTS`, `_TRUST_INCOME_SCHEDULE_LAYOUTS`, `_BENEFICIARY_ITR_LAYOUTS`) are unchanged. Because line 380 already uses `i % len(...)` (no `random.*` call), re-running the seed at `_SEED = 42` would reproduce identical field values with the new layouts — confirming the seed and the migration agree.

- [ ] **Step 3: Do NOT re-run the seed.** The migration (Task 5) is the regeneration path. Re-running the full seed would rewrite all four ground-truth files; we only updated the constant for future consistency.

- [ ] **Step 4: Lint, format, type-check**

Run:
```bash
conda run -n du ruff check --fix scripts/seed_trust_distributions.py
conda run -n du ruff format scripts/seed_trust_distributions.py
conda run -n du mypy scripts/seed_trust_distributions.py --ignore-missing-imports
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_trust_distributions.py
git commit -m "🔧 chore: align seed script with six distribution layouts (index-based)"
```

---

## Task 7: Regenerate images, validate, and final verification

**Files:**
- Regenerate: `output/clean/distribution_statements/`, `output/degraded/distribution_statements/` (gitignored)

- [ ] **Step 1: Validate all ground truth against the registry**

Run: `conda run -n du python -m generators.pipeline validate`
Expected: `Validation passed.` (all 50 distribution entries reference one of the six known layouts).

- [ ] **Step 2: Delete stale Distribution Statement outputs**

Old filenames embed `_distribution_statement_standard` and would orphan. Run:
```bash
cd /Users/tod/Desktop/Synthetic_Doc_Generation
rm -rf output/clean/distribution_statements output/degraded/distribution_statements
```

- [ ] **Step 3: Regenerate Distribution Statement images (clean + degraded)**

Run: `conda run -n du python -m generators.pipeline generate --type distribution_statements`
Expected: `distribution_statements: generated 50 documents.`

- [ ] **Step 4: Confirm the new spread of rendered files**

Run:
```bash
ls output/clean/distribution_statements | sed -E 's/^CASE[0-9]+_//; s/\.png$//' | sort | uniq -c
```
Expected: six layout suffixes, each appearing 8–9 times (50 total). No `distribution_statement_standard` entries remain.

- [ ] **Step 5: Spot-check one render per archetype visually**

Open these and confirm they look right (letterhead/table/letter structure, labels vary, amounts present and right-aligned):
```bash
open output/clean/distribution_statements/CASE201_dist_software_navy.png
open output/clean/distribution_statements/CASE203_dist_table_plain.png
open output/clean/distribution_statements/CASE204_dist_table_ruled.png
open output/clean/distribution_statements/CASE205_dist_letter_formal.png
```
(CASE→layout follows `index % 6`: CASE201→navy, 202→teal, 203→table_plain, 204→table_ruled, 205→letter_formal, 206→letter_compact.)

- [ ] **Step 6: Regenerate derived exports (values unchanged; run for consistency)**

Run: `conda run -n du python -m generators.pipeline derive`
Expected: CSV and JSONL written without error.

- [ ] **Step 7: Run the entire test suite with coverage**

Run: `conda run -n du pytest --cov=generators tests/ -v`
Expected: all PASS, `generators/` coverage ≥ 80%. (Coverage is measured on `generators/` — the `scripts/` data-seed generators are not import-covered and would skew the number; their logic is exercised functionally by `test_layout_assignment.py`.) Linking tests (`test_linking_trust.py`) and ground-truth tests confirm the flow still reconciles.

- [ ] **Step 8: Full lint / format / type gate**

Run:
```bash
conda run -n du ruff check --fix --ignore ARG001,ARG002,F841 generators/ scripts/
conda run -n du ruff format generators/ scripts/
conda run -n du mypy generators/ scripts/ --ignore-missing-imports
```
Expected: no errors.

- [ ] **Step 9: Final commit (if Step 8 changed anything; outputs/derived are gitignored)**

```bash
git add generators/ scripts/
git commit -m "✅ test: finalize distribution layout variety; full suite green" || echo "nothing to commit"
```

---

## Verification Checklist (run at the end)

- [ ] `conda run -n du python -m generators.pipeline validate` → `Validation passed.`
- [ ] `conda run -n du pytest --cov=generators --cov=scripts tests/` → all green, ≥80%.
- [ ] `git diff main --stat` shows changes only in `config/layouts/distribution_statements.yml`, `generators/{common,distribution_statement,trust_income_schedule}.py`, `scripts/{migrate_distribution_layouts,seed_trust_distributions}.py`, `ground_truth/distribution_statements.yml`, and `docs/`.
- [ ] `git diff main -- ground_truth/distribution_statements.yml` shows **only** `layout:` lines changed.
- [ ] `output/clean/distribution_statements/` contains 50 PNGs across six layout suffixes (8–9 each).

## Definition of Done

Six distribution-statement layouts render across three archetypes with varied labels; all 50 ground-truth entries reassigned by deterministic index with **zero** field-value changes; clean + degraded images regenerated; trust-income-schedule output unchanged (characterization test); linking unaffected; full test suite green at ≥80% coverage; lint/format/type gates clean.
