# Phase 1A — Trust/Tax Renderer Fit-Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 4 trust/tax renderers fit-safe (no silent clipping/truncation) so Phase 1B can widen their content safely — trust renderers MUST NOT clip.

**Architecture:** Reuse the fit-safety mechanism already on `main` (`fit_text`, `field_budgets` loader, fitted draw helpers, overflow backstop). The trust renderers are field-def-driven: every variable value flows through 1-2 generic draw paths, so a couple of role/column budgets per layout cover all fields. Route those paths through the fitted helpers; prove byte-identical output where current content fits.

**Tech Stack:** Python 3.12, Pillow 12.2.0, PyYAML, Typer, pytest. Conda env `synthetic`.

**Design spec:** `docs/content_variety_phase1_design.md` §3.

## Global Constraints

Copied from the spec and project CLAUDE.md — implicit in every task:

- **Line length** max 108; Python 3.12 type hints (`X | Y`, no `from __future__ import annotations`, no `TYPE_CHECKING` guards for runtime-signature types).
- **YAML single source of truth.** All `field_budgets` keys (`width`, `fit`, `min_font`, `max_lines`) are required — no silent Python defaults; missing key fails fast.
- **Fail-fast diagnostics — four elements** (what / where / dotted YAML key / how to recover); tests assert all four via the shared `assert_diagnostic_error` helper in `tests/conftest.py`.
- **B904:** in `except`, `raise ... from err`/`from None`.
- **Never silently truncate/ellipsize** — descriptions/text values **wrap** (never shrink) to keep font uniform; amounts/columns `shrink`.
- **Determinism:** measure with the bundled DejaVu font; `pillow==12.2.0` (PROD mirror); the bundled-font guard already fails loud on a system-font fallback.
- **Do NOT write the term "ATO"** anywhere (use "PROD"). Existing trust code/docstrings may contain it; do not copy those strings into new code.
- **Tests:** `conda run -n synthetic pytest tests/`; `tests/` is gitignored (local-only); ≥80% coverage. Baselines live under `tests/fixtures/` (local-only).
- **Gate before every commit:** `ruff check --fix --ignore ARG001,ARG002,F841 *.py generators/*.py` → `ruff format .` → `mypy . --ignore-missing-imports` → `pytest tests/`. Never bypass the pre-commit hook. No Claude attribution in commits.

## Reused interfaces (already on `main` — do not reimplement)

From `generators/common.py`:
- `fit_text(text, *, width, fit, min_font, max_lines, nominal_size, mono=False, bold=False) -> FitResult` (`FitResult.lines: list[str]`).
- `draw_fitted_left(draw, text, x, y, *, budget, nominal_size, mono=False, bold=False, fill="black", line_spacing=None) -> int` (returns advanced y). Single-line output is pixel-identical to a raw `draw.text((x,y),...)`; pass `line_spacing` = the renderer's existing y-advance so wrapped lines push content down correctly.
- `draw_fitted_right(draw, text, x_right, y, *, budget, nominal_size, ..., line_spacing=None) -> int` — right-aligned equivalent of `draw_text_right`.

From `generators/layout_budgets.py`:
- `field_budget(layout: dict, layout_id: str, field: str, *, layout_path: str) -> dict` — returns the validated budget or raises `LayoutBudgetError` (four-element diagnostic). `field` is any string key under the layout's `field_budgets:` — here we use **role keys** (`TEXT_VALUE`, `AMOUNT_VALUE`, `DESC_COL`), not GT field names, because the field-driven renderers draw every value through a shared path with shared geometry.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `config/layouts/trust_returns.yml` | role budgets for trust return | Modify |
| `config/layouts/beneficiary_itrs.yml` | role budgets | Modify |
| `config/layouts/distribution_statements.yml` | role budgets | Modify |
| `config/layouts/trust_income_schedules.yml` | column + role budgets | Modify |
| `generators/trust_return.py` | route value/amount draws through fit_text | Modify |
| `generators/beneficiary_itr.py` | same | Modify |
| `generators/distribution_statement.py` | same | Modify |
| `generators/trust_income_schedule.py` | same (table Description column) | Modify |
| `tests/test_trust_fit.py` | budgets present, no-overflow, byte-identical regression | Create |
| `tests/fixtures/trust_*_baseline_hashes.json` | pristine per-renderer baselines (local-only) | Create |

---

## Fit-wiring recipe (applied by every renderer task)

Each trust renderer has a module constant and a budget helper; then each variable
draw site is converted. The recipe is identical in shape across renderers — each
task below states its file's concrete edits.

**1. Imports + helper** (top of the renderer module):
```python
from generators.common import draw_fitted_left, draw_fitted_right  # add to existing import
from generators.layout_budgets import field_budget

_LAYOUT_PATH = "config/layouts/<this_layout_file>.yml"


def _budget(layout: dict, layout_id: str, role: str) -> dict:
    return field_budget(layout, layout_id, role, layout_path=_LAYOUT_PATH)
```
Add `layout_id = entry.get("layout", "")` near the top of the render function.

**2. Text value** — a left-aligned `draw.text((x, y), value, font=font_b, fill="black")`
followed by `y += N` becomes:
```python
y = draw_fitted_left(
    draw, value, x, y,
    budget=_budget(layout, layout_id, "TEXT_VALUE"),
    nominal_size=font_sizes.get("body", 22),
    line_spacing=N,
)
```
(Assign `y =` so a wrapped value advances by `N * lines`; single-line stays `y += N` → byte-identical.)

**3. Amount** — a `draw_text_right(draw, formatted, right_edge, y, font_amount)` becomes:
```python
draw_fitted_right(
    draw, formatted, right_edge, y,
    budget=_budget(layout, layout_id, "AMOUNT_VALUE"),
    nominal_size=font_sizes.get("body", 22),
)
```
(Amounts use `fit: shrink`, `max_lines: 1` — single line; keep the existing y-advance.)

**Fixed section titles / labels / header-bar text** come from the *layout*, not GT
`fields` — leave them as raw `draw.text` (constant, no overflow risk, out of scope).

**Budget derivation (per layout, committed to its YAML):**
- `TEXT_VALUE.width = (width - margin) - value_x - 8`, where `value_x` is the x the
  value is drawn at (`margin + 20` in the field-driven renderers). `fit: wrap`,
  `min_font: 12`, `max_lines: 2`.
- `AMOUNT_VALUE.width` = a currency-column width big enough for `"$9,999,999.99"`
  measured at body size + margin (use 500 for width 1600 layouts — verify with the
  no-overflow test). `fit: shrink`, `min_font: 12`, `max_lines: 1`.
- `DESC_COL.width` (schedule table only) = the Description column width − 8.
  `fit: wrap`, `min_font: 12`, `max_lines: 2`.

**Byte-identical guarantee:** widths are ≥ every current value's rendered width, so
`fit_text` takes the fits-as-is path and pixels are unchanged; the per-renderer
regression test proves it.

---

## Task 1: trust_return fit-safety (reference)

**Files:**
- Modify: `config/layouts/trust_returns.yml`, `generators/trust_return.py`
- Test: `tests/test_trust_fit.py`, `tests/fixtures/trust_return_baseline_hashes.json`

**Interfaces:**
- Consumes: `draw_fitted_left`, `draw_fitted_right`, `field_budget` (on `main`).
- Produces: `trust_returns.yml` with `TEXT_VALUE` + `AMOUNT_VALUE` budgets; `render_trust_return` routing its text-value draw (`generators/trust_return.py:155-159`) and `_draw_amount_field`'s amount draw (`:71`) through the fitted helpers.

- [ ] **Step 1: Capture pristine baseline hashes**

Write `/private/tmp/.../scratchpad/trust_return_capture.py` (Write tool — NOT a heredoc, which hangs the Bash tool):
```python
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from generators.trust_return import render_trust_return
from generators.loader import load_ground_truth, load_layout_registry
layouts = load_layout_registry(Path("config/layouts/trust_returns.yml"))
entries = load_ground_truth(Path("ground_truth/trust_returns.yml"))
h = {}
for cid, e in entries.items():
    e["case_id"] = str(cid)
    img = render_trust_return(e, layouts[e["layout"]])
    h[f"{cid}_{e['layout']}"] = hashlib.sha256(img.tobytes()).hexdigest()
Path("tests/fixtures").mkdir(parents=True, exist_ok=True)
Path("tests/fixtures/trust_return_baseline_hashes.json").write_text(json.dumps(h, indent=2))
print("captured", len(h))
```
Run: `conda run -n synthetic python /private/tmp/.../scratchpad/trust_return_capture.py`
Expected: `captured 50`.

- [ ] **Step 2: Add role budgets to `config/layouts/trust_returns.yml`**

Under `trust_return_standard:` (and any other trust_return layout), add — width 1600, margin 120 → value drawn at `margin+20=140`, `TEXT_VALUE.width = (1600-120) - 140 - 8 = 1332`:
```yaml
    field_budgets:
      TEXT_VALUE: {width: 1332, fit: wrap, min_font: 12, max_lines: 2}
      AMOUNT_VALUE: {width: 500, fit: shrink, min_font: 12, max_lines: 1}
```

- [ ] **Step 3: Write the failing tests** (`tests/test_trust_fit.py`)

```python
import hashlib, json
from pathlib import Path
from conftest import assert_diagnostic_error  # noqa: F401  (used by later trust tasks)
from generators.common import fit_text, load_font
from generators.layout_budgets import field_budget
from generators.loader import load_ground_truth, load_layout_registry
from generators.trust_return import render_trust_return

_LP = "config/layouts/trust_returns.yml"


def _text_fields(fields: dict) -> list[str]:
    # Every value the field-driven renderer draws as text (non-amount, non-digit).
    return [str(v) for v in fields.values() if v is not None]


def test_trust_return_layouts_have_role_budgets():
    layouts = load_layout_registry(Path(_LP))
    for lid, layout in layouts.items():
        for role in ("TEXT_VALUE", "AMOUNT_VALUE"):
            field_budget(layout, lid, role, layout_path=_LP)


def test_trust_return_no_text_overflow():
    layouts = load_layout_registry(Path(_LP))
    for entry in load_ground_truth(Path("ground_truth/trust_returns.yml")).values():
        layout = layouts[entry["layout"]]
        b = field_budget(layout, entry["layout"], "TEXT_VALUE", layout_path=_LP)
        for value in _text_fields(entry["fields"]):
            fit_text(value, width=b["width"], fit=b["fit"], min_font=b["min_font"],
                     max_lines=b["max_lines"], nominal_size=layout["font_sizes"]["body"])  # must not raise


def test_trust_return_byte_identical():
    layouts = load_layout_registry(Path(_LP))
    baseline = json.loads(Path("tests/fixtures/trust_return_baseline_hashes.json").read_text())
    for cid, entry in load_ground_truth(Path("ground_truth/trust_returns.yml")).items():
        entry["case_id"] = str(cid)
        layout = layouts[entry["layout"]]
        digest = hashlib.sha256(render_trust_return(entry, layout).tobytes()).hexdigest()
        assert digest == baseline[f"{cid}_{entry['layout']}"], f"{cid} changed"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_trust_fit.py -v`
Expected: FAIL — `LayoutBudgetError`/no budgets, or byte mismatch (renderer not yet routed).

- [ ] **Step 5: Wire `generators/trust_return.py`**

Apply the recipe: add imports, `_LAYOUT_PATH = "config/layouts/trust_returns.yml"`, `_budget(...)`, and `layout_id = entry.get("layout", "")` in `render_trust_return`.

Convert the text-value draw (currently `generators/trust_return.py:155-159`):
```python
                else:
                    draw.text((margin, y), label, font=font_s, fill="gray")
                    y += 28
                    y = draw_fitted_left(
                        draw, value, margin + 20, y,
                        budget=_budget(layout, layout_id, "TEXT_VALUE"),
                        nominal_size=font_sizes.get("body", 22),
                        line_spacing=40,
                    )
```

Convert the amount draw in `_draw_amount_field` — thread `layout`/`layout_id` in
(add them as parameters and pass at the call site `:143-153`), then replace `:71`:
```python
    draw_fitted_right(
        draw, formatted, right_edge, y + 2,
        budget=field_budget(layout, layout_id, "AMOUNT_VALUE", layout_path=_LAYOUT_PATH),
        nominal_size=font_amount.size if isinstance(font_amount, ImageFont.FreeTypeFont) else 22,
    )
```
(Simpler: pass `nominal_size=font_sizes.get("body", 22)` from the caller instead of reading `font_amount.size`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_trust_fit.py -v`
Expected: PASS — byte-identical (derived widths ≥ current content, fits-as-is).

- [ ] **Step 7: Gate + commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/trust_return.py
conda run -n synthetic ruff format generators/trust_return.py config/layouts/trust_returns.yml
conda run -n synthetic mypy generators/trust_return.py --ignore-missing-imports
git add config/layouts/trust_returns.yml generators/trust_return.py
git commit -m "✨ feat: fit-safe trust return rendering with role budgets"
```

---

## Task 2: beneficiary_itr fit-safety

**Files:** Modify `config/layouts/beneficiary_itrs.yml`, `generators/beneficiary_itr.py`; add to `tests/test_trust_fit.py`; `tests/fixtures/beneficiary_itr_baseline_hashes.json`.

**Interfaces:** same helpers. `beneficiary_itrs.yml` gains `TEXT_VALUE` + `AMOUNT_VALUE`; `render_beneficiary_itr` routed through fitted helpers.

- [ ] **Step 1: Discover the variable draw sites**

Run: `grep -n "draw.text\|draw_text_right\|fields.get\|field_def\|value\|margin" generators/beneficiary_itr.py`
Record: the x each text value is drawn at, its y-advance `N`, and each amount draw. (This renderer is field-driven like trust_return; expect a shared text-value path + an amount path.)

- [ ] **Step 2: Capture pristine baseline** — copy Task 1 Step 1's capture script, changing the renderer to `render_beneficiary_itr`, the layout path to `config/layouts/beneficiary_itrs.yml`, GT to `ground_truth/beneficiary_itrs.yml`, and output to `tests/fixtures/beneficiary_itr_baseline_hashes.json`. Run; expect `captured 50`.

- [ ] **Step 3: Add role budgets to `config/layouts/beneficiary_itrs.yml`** — width 1600, margin 120 → `TEXT_VALUE.width = 1332`:
```yaml
    field_budgets:
      TEXT_VALUE: {width: 1332, fit: wrap, min_font: 12, max_lines: 2}
      AMOUNT_VALUE: {width: 500, fit: shrink, min_font: 12, max_lines: 1}
```
(If Step 1 shows a different `value_x`, recompute `width = (1600-120) - value_x - 8`.)

- [ ] **Step 4: Write failing tests** — append `test_beneficiary_itr_layouts_have_role_budgets`, `test_beneficiary_itr_no_text_overflow`, `test_beneficiary_itr_byte_identical` to `tests/test_trust_fit.py`, mirroring Task 1 Step 3 with `_LP_BI = "config/layouts/beneficiary_itrs.yml"`, `render_beneficiary_itr`, and the beneficiary baseline file.

- [ ] **Step 5: Run to verify they fail.** `conda run -n synthetic pytest tests/test_trust_fit.py -k beneficiary -v` → FAIL.

- [ ] **Step 6: Wire `generators/beneficiary_itr.py`** — apply the Fit-wiring recipe to the draw sites found in Step 1 (`_LAYOUT_PATH` = beneficiary layout; `_budget` helper; `layout_id`; text-value → `draw_fitted_left` with `line_spacing=N`; amount → `draw_fitted_right`).

- [ ] **Step 7: Run tests — expect byte-identical PASS.**

- [ ] **Step 8: Gate + commit** `git commit -m "✨ feat: fit-safe beneficiary ITR rendering with role budgets"`

---

## Task 3: distribution_statement fit-safety

**Files:** Modify `config/layouts/distribution_statements.yml`, `generators/distribution_statement.py`; add to `tests/test_trust_fit.py`; `tests/fixtures/distribution_statement_baseline_hashes.json`.

- [ ] **Step 1: Discover the variable draw sites** — this renderer has ~21 draw calls; run `grep -n "draw.text\|draw_text_right\|draw_text_center\|fields.get\|value\|margin\|right_edge" generators/distribution_statement.py`. Identify every draw of a GT `fields[...]` value (text vs amount) and its x / y-advance. Fixed layout text (titles, labels) is out of scope.

- [ ] **Step 2: Capture pristine baseline** — capture script per Task 1 Step 1 with `render_distribution_statement`, `config/layouts/distribution_statements.yml`, `ground_truth/distribution_statements.yml`, `tests/fixtures/distribution_statement_baseline_hashes.json`. Expect `captured 50`.

- [ ] **Step 3: Add role budgets** to each distribution layout (`dist_software_navy`, `dist_software_teal`, and any others) — width 1600, margin 140 → value at `margin+20=160`, `TEXT_VALUE.width = (1600-140) - 160 - 8 = 1292`:
```yaml
    field_budgets:
      TEXT_VALUE: {width: 1292, fit: wrap, min_font: 12, max_lines: 2}
      AMOUNT_VALUE: {width: 500, fit: shrink, min_font: 12, max_lines: 1}
```
Adjust `value_x` per what Step 1 finds if it differs.

- [ ] **Step 4: Write failing tests** — append `*_distribution_*` tests to `tests/test_trust_fit.py` mirroring Task 1 Step 3 (`_LP_DS`, `render_distribution_statement`, distribution baseline).

- [ ] **Step 5: Run to verify they fail.**

- [ ] **Step 6: Wire `generators/distribution_statement.py`** — apply the recipe to every value/amount draw found in Step 1.

- [ ] **Step 7: Run tests — expect byte-identical PASS.**

- [ ] **Step 8: Gate + commit** `git commit -m "✨ feat: fit-safe distribution statement rendering with role budgets"`

---

## Task 4: trust_income_schedule fit-safety (table)

**Files:** Modify `config/layouts/trust_income_schedules.yml`, `generators/trust_income_schedule.py`; add to `tests/test_trust_fit.py`; `tests/fixtures/trust_income_schedule_baseline_hashes.json`.

This renderer draws a **table** with columns `Label (100)`, `Description (800)`, `Amount $ (460)`. The Description column is the overflow-prone field (like a line-item description) → wrap within its column with row growth.

- [ ] **Step 1: Discover the table draw** — `grep -n "draw.text\|draw_text_right\|columns\|Description\|Amount\|row\|width" generators/trust_income_schedule.py`. Record the Description column's x and width, the Amount column's right edge, the per-row y-advance, and any non-table text/amount value draws.

- [ ] **Step 2: Capture pristine baseline** — capture script per Task 1 Step 1 with `render_trust_income_schedule`, `config/layouts/trust_income_schedules.yml`, `ground_truth/trust_income_schedules.yml`, `tests/fixtures/trust_income_schedule_baseline_hashes.json`. Expect `captured 50`.

- [ ] **Step 3: Add budgets** — Description column width 800 → `DESC_COL.width = 792`; plus `AMOUNT_VALUE` and (if there are non-table text values) `TEXT_VALUE`:
```yaml
    field_budgets:
      DESC_COL: {width: 792, fit: wrap, min_font: 12, max_lines: 2}
      AMOUNT_VALUE: {width: 452, fit: shrink, min_font: 12, max_lines: 1}
      TEXT_VALUE: {width: 1332, fit: wrap, min_font: 12, max_lines: 2}
```

- [ ] **Step 4: Write failing tests** — append `*_schedule_*` tests to `tests/test_trust_fit.py` mirroring Task 1 Step 3 (`_LP_TIS`, `render_trust_income_schedule`, schedule baseline).

- [ ] **Step 5: Run to verify they fail.**

- [ ] **Step 6: Wire `generators/trust_income_schedule.py`** — Description-cell draw → `draw_fitted_left(..., budget=_budget(layout, layout_id, "DESC_COL"), line_spacing=row_h)`; grow the row by `len(fit_text(desc, ...).lines)` exactly as the bank/CC pattern on `main` (`generators/cc_statement.py:_draw_transactions`); amount → `draw_fitted_right` with `AMOUNT_VALUE`; any non-table text value → `TEXT_VALUE`.

- [ ] **Step 7: Run tests — expect byte-identical PASS** (descriptions currently fit within 792px, so single-line, unchanged).

- [ ] **Step 8: Gate + commit** `git commit -m "✨ feat: fit-safe trust income schedule rendering with column budgets"`

---

## Task 5: Confirm the backstop now covers all 8 doc types

**Files:** add to `tests/test_trust_fit.py`.

Now that the 4 trust renderers call `fit_text`, the existing overflow backstop
(`generators/overflow_check.py`, wired into `pipeline validate`/`generate`) catches
their impossible-fit as `FitError` — the same as the core types. Verify it.

- [ ] **Step 1: Write the tests**

```python
def test_validate_still_passes_on_all_current_docs():
    from typer.testing import CliRunner
    from generators.pipeline import app
    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 0, result.output


def test_backstop_catches_impossible_trust_fit():
    # A budget too small to fit any real value makes check_overflow report it.
    from generators.overflow_check import check_overflow
    from generators.trust_return import render_trust_return
    from generators.loader import load_ground_truth, load_layout_registry
    from pathlib import Path
    layouts = load_layout_registry(Path("config/layouts/trust_returns.yml"))
    for layout in layouts.values():
        layout.setdefault("field_budgets", {})["TEXT_VALUE"] = {
            "width": 1, "fit": "wrap", "min_font": 12, "max_lines": 1
        }
    gt = load_ground_truth(Path("ground_truth/trust_returns.yml"))
    violations = check_overflow(gt, layouts, render_trust_return)
    assert violations, "backstop must catch impossible trust fit"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_trust_fit.py::test_validate_still_passes_on_all_current_docs tests/test_trust_fit.py::test_backstop_catches_impossible_trust_fit -v`
Expected: PASS. (The second test mutates in-memory layout dicts only — it does not touch YAML.)

- [ ] **Step 3: Full suite + real CLI**

Run: `conda run -n synthetic pytest tests/ -q` → all pass.
Run: `conda run -n synthetic python -m generators.pipeline validate` → `Validation passed.`

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_fit.py
git commit -m "✅ test: confirm overflow backstop covers all 8 doc types"
```
(Note: `tests/` is gitignored, so this commit may be empty on tracked files — that's expected; the real deliverable is the passing gate. If nothing is staged, skip the commit.)

---

## Final verification

- [ ] `conda run -n synthetic pytest tests/ -q` — all pass.
- [ ] `conda run -n synthetic python -m generators.pipeline validate` — exits 0 across all 8 doc types with the backstop active.
- [ ] Spot-check: all 4 trust renderers render byte-identically to their pristine baselines (regression tests green).
- [ ] Every trust/tax variable value now flows through `fit_text` — a widened value can only wrap/shrink losslessly or raise `FitError`, never clip.

---

## Self-review notes (author)

- **Spec coverage:** §3 (1A) items → Tasks 1-4 (budgets + wiring + byte-identical per renderer) and Task 5 (backstop coverage). Determinism preconditions are inherited from `main` (Pillow pin + bundled-font guard) — no new work.
- **Discovery-in-task:** Tasks 2-4 begin with a grep discovery step because each renderer's exact draw x/y-advances must be read at implementation time (same approach the Phase 0 plan used successfully for bank/CC/invoice). Task 1 is fully worked as the reference from the read of `generators/trust_return.py`.
- **Role vs per-field budgets:** trust renderers draw all values through shared paths with shared geometry, so budgets are keyed by role (`TEXT_VALUE`/`AMOUNT_VALUE`/`DESC_COL`), not GT field names — fewer, non-duplicated budgets that still cover every field. This is a deliberate, documented deviation from the core-renderer per-field scheme.
- **Assumptions to confirm at implementation:** each renderer's `value_x` (recompute `TEXT_VALUE.width` if not `margin+20`); whether distribution/schedule have additional value draws beyond the shared path (Step 1 discovery catches these).
