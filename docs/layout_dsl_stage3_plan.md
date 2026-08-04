# Layout DSL Stage 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render receipts and invoices entirely from `body:` trees in YAML, with no pixel value, colour, printed string, or spacing constant decided by a Python literal, reproducing today's output byte-for-byte.

**Architecture:** Three preparatory layers land before any layout body is authored — the engine's 31 silent defaults move into a required per-layout `defaults:` block, the engine gains the three capabilities the bank migration never needed (monospace, text fit budgets, declared line advance), and a field-provider extension point carries derived values into `entry["fields"]` so `{FIELD}` binding reaches them. Only then are the receipt and invoice bodies written, gated by a pixel snapshot captured from the legacy renderers first.

**Tech Stack:** Python 3.12, Pillow 12.2.0 (pinned — font metrics are load-bearing), PyYAML `safe_load`, pytest, conda env `synthetic`.

**Spec:** `docs/layout_dsl_stage3_design.md`

## Global Constraints

- Conda env is `synthetic`. Run everything as `conda run -n synthetic <cmd>`.
- `tests/` is gitignored and local-only. Never `git add tests/`.
- Every commit must pass, in order: `pytest tests/`, `ruff check --fix --ignore ARG001,ARG002,F841 *.py`, `ruff format .`, `mypy . --ignore-missing-imports`. Never `--no-verify`.
- Line length 108. Google-style docstrings. `pathlib.Path` for paths. Python 3.12 types (`X | Y`, no `from __future__ import annotations`, no `TYPE_CHECKING` guards for runtime-evaluated annotations).
- In `except` blocks always `raise ... from err` or `from None` (B904).
- No commit attribution to Claude. Never write "ATO" — use "PROD".
- **Every config key is required.** No Python literal may supply a value YAML omitted. A missing key raises a four-element diagnostic: WHAT is wrong, WHERE (absolute path + dotted key), WHAT IT SHOULD LOOK LIKE (concrete YAML + allowed values), HOW TO RECOVER (one line).
- Every fail-fast test asserts all four elements via `assert_diagnostic_error` from `tests/conftest.py`.
- **`tests/test_bank_pixel_snapshot.py` must stay green on every task in this plan.** Bank output does not change. If a task turns it red, the task is wrong — do not re-bless the fixture.
- Re-blessing a snapshot requires `conda run -n synthetic python tests/regenerate_bank_pixel_snapshot.py --confirm` and is a deliberate act, permitted only where a task explicitly says so.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `generators/layout_dsl/defaults.py` | Resolve a primitive parameter as block key → layout `defaults:` → fail fast. Single place the resolution order lives. |
| `generators/layout_dsl/field_providers.py` | Registry + `emits` declarations for providers that return derived `entry["fields"]` entries. Deliberately separate from `providers.py`: row providers return `list[dict]` for tables, field providers return `dict[str, str]` for binding. |
| `tests/regenerate_doc_pixel_snapshot.py` | Generalised snapshot capture for receipts and invoices, modelled on `regenerate_bank_pixel_snapshot.py`. |
| `tests/test_receipt_pixel_snapshot.py` | Phase A parity gate for the 6 receipt layouts. |
| `tests/test_invoice_pixel_snapshot.py` | Phase A parity gate for the 4 invoice layouts. |
| `tests/layout_dsl/test_defaults.py` | `resolve_param` unit tests. |
| `tests/layout_dsl/test_field_providers.py` | Registry, `emits` declaration, and collision tests. |

**Modified:**

| File | Change |
|---|---|
| `generators/layout_dsl/primitives_text.py` | 14 default sites → `resolve_param`; `mono`; `line_advance`; `budget:` on `text`/`pair`; `value_align`, `min_gap` on `pair`; `fill_char` on `rule` |
| `generators/layout_dsl/primitives_table.py` | 12 default sites → `resolve_param`; `mono`; `capture:` |
| `generators/layout_dsl/primitives_container.py` | 4 default sites → `resolve_param`; `widths:` on `split` |
| `generators/layout_dsl/context.py` | `Region.divide` floor division; four-element diagnostics on `indent`/`divide`; `Region.divide_widths` |
| `generators/layout_dsl/schema.py` | `defaults:` coverage check; unbalanced-brace check; new primitive keys; `field_providers:` validation; emit/scored-column collision check |
| `generators/layout_dsl/providers.py` | `bank_transaction_totals` label → required param; `receipt_line_items` provider |
| `generators/layout_dsl/engine.py` | Merge field-provider output into `entry["fields"]` before walking `body:` |
| `generators/receipt.py` | 442 lines → a page-setup adapter (~80 lines) |
| `generators/invoice.py` | 482 lines → a page-setup adapter (~60 lines) |
| `generators/payment_block.py` | Delete `render_payment_block`; keep pools, `derive_payment`, `PaymentDetails`, `load_link_index` |
| `config/layouts/bank_statements.yml` | `defaults:` block on all 8 layouts (+ shared anchor) |
| `config/layouts/receipts.yml` | `sections:` → `body:`; `defaults:`; dead keys removed |
| `config/layouts/invoices.yml` | `sections:` → `body:`; `defaults:`; dead keys removed |
| `config/data_pools.yml` | New `pos_terminal` block; slip labels into `payment_terminal` |

---

## Task 0: The snapshot net for receipts and invoices
> **Execute this task first.** It captures the Phase A parity baseline from the
> legacy renderers at the branch's current HEAD, before any engine change lands.
> Tasks 1-12 should be inert to the legacy receipt and invoice paths, but the
> baseline must not depend on that being true.


**Files:**
- Create: `tests/regenerate_doc_pixel_snapshot.py`, `tests/test_receipt_pixel_snapshot.py`, `tests/test_invoice_pixel_snapshot.py`
- Create: `tests/fixtures/receipt_legacy_snapshot.json`, `tests/fixtures/invoice_legacy_snapshot.json`

**Interfaces:**
- Consumes: `render_receipt`, `render_invoice` — the legacy renderers, still intact.
- Produces: `_digest(image: Image.Image) -> str` (sha256 of `image.tobytes()`), `_entries(path: Path) -> list[dict]`, `_RECEIPT_SNAPSHOT_PATH`, `_INVOICE_SNAPSHOT_PATH` in `tests/regenerate_doc_pixel_snapshot.py`, plus the two fixture files. This is the Phase A parity gate — Tasks 14 and 15 are defined as done by these tests.

**Capture this before authoring a single body.** Once Tasks 14 and 15 delete the legacy renderers there is no oracle left, which is exactly the reasoning `tests/test_bank_pixel_snapshot.py`'s docstring records for the bank migration.

- [ ] **Step 1: Write the capture script**

Model it on `regenerate_bank_pixel_snapshot.py`. For each entry in `ground_truth/receipts.yml` and `ground_truth/invoices.yml`, render through the legacy renderer with `geometry_out={}` and record `{"hash": sha256 of image bytes, "size": [w, h], "boxes": geometry_out["boxes"]}` keyed `"{case_id}_{layout_id}"`. Require `--confirm` to write, exactly as the bank script does, so a bare run only prints a dry-run summary.

- [ ] **Step 2: Capture the baseline**

```bash
conda run -n synthetic python tests/regenerate_doc_pixel_snapshot.py --confirm
```

Expected: two fixture files written, 55 receipt entries and 55 invoice entries.

- [ ] **Step 3: Write the parity tests**

```python
# tests/test_receipt_pixel_snapshot.py
"""Phase A parity gate. Renders every receipt entry and asserts the page hash
and every recorded box match the baseline captured from the legacy renderer.

This does not retire with the legacy path the way the bank equivalence harness
did. After Task 14 it becomes the permanent regression guard for receipts, and
it is re-blessed only when Phase B intentionally changes the rendering.
"""

import json
from pathlib import Path

import pytest

from generators.loader import load_layout_registry
from generators.receipt import render_receipt
from regenerate_doc_pixel_snapshot import _digest, _entries

BASELINE = json.loads(Path("tests/fixtures/receipt_legacy_snapshot.json").read_text())
LAYOUTS = load_layout_registry(Path("config/layouts/receipts.yml"))
ENTRIES = _entries(Path("ground_truth/receipts.yml"))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: f"{e['case_id']}_{e['layout']}")
def test_receipt_render_matches_baseline(entry):
    key = f"{entry['case_id']}_{entry['layout']}"
    geometry: dict = {}
    image = render_receipt(entry, LAYOUTS[entry["layout"]], geometry_out=geometry)
    expected = BASELINE[key]

    assert [image.width, image.height] == expected["size"]
    assert _digest(image) == expected["hash"]
    assert geometry["boxes"] == expected["boxes"]
```

Write the invoice test identically against `render_invoice` and the invoice fixture.

- [ ] **Step 4: Confirm the net is green against the legacy path**

Run: `conda run -n synthetic pytest tests/test_receipt_pixel_snapshot.py tests/test_invoice_pixel_snapshot.py -v`
Expected: PASS, 110 cases. A failure here means the capture is non-deterministic — investigate before proceeding, because a flaky baseline is worse than none.

- [ ] **Step 5: Commit**

`tests/` is gitignored, so only note in the commit body that the net exists. There is nothing to stage; skip the commit and record completion in the plan checkbox.

---

## Task 1: Stage 3 prerequisites

The four items in `docs/layout_dsl_stage3_prerequisites.md`. All are inert against the 8 bank layouts and go live the moment a hand-authored body exists.

**Files:**
- Modify: `generators/layout_dsl/context.py:33-79`
- Modify: `generators/layout_dsl/schema.py` (`validate_body`)
- Modify: `generators/layout_dsl/primitives_table.py` (`rule_above` ordering)
- Test: `tests/layout_dsl/test_context.py`, `tests/test_bank_dsl_validation.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Region.divide(n, gap)` distributing remainder pixels so the last column reaches `region.right`; `validate_body` rejecting unbalanced `{`/`}`.

- [ ] **Step 1: Write the failing test for divide's lost pixels**

```python
# tests/layout_dsl/test_context.py
from generators.layout_dsl.context import Region


def test_divide_last_column_reaches_region_right():
    """Floor division drops up to n-1 px, so the last column never reaches the
    right edge. Westpac's only split is 1600 // 2 = 800 (exact), which is why
    this was never seen; any odd width or 3+ columns hits it."""
    columns = Region(x=100, width=1001).divide(3, gap=0)
    assert columns[-1].right == 1101
    assert sum(c.width for c in columns) == 1001
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_context.py::test_divide_last_column_reaches_region_right -v`
Expected: FAIL — last column right is 1100, widths sum to 999.

- [ ] **Step 3: Distribute the remainder**

```python
# generators/layout_dsl/context.py, in Region.divide, replacing the return
        total_gap = gap * (n - 1)
        usable = self.width - total_gap
        column = usable // n
        if column < 1:
            raise self._divide_error(n, gap, column)
        # Hand the remainder out one pixel at a time to the leftmost columns, so
        # the columns differ by at most 1px and the last one reaches self.right.
        remainder = usable - column * n
        regions: list[Region] = []
        x = self.x
        for i in range(n):
            width = column + (1 if i < remainder else 0)
            regions.append(Region(x=x, width=width))
            x += width + gap
        return regions
```

- [ ] **Step 4: Confirm it passes and bank output is unchanged**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_context.py tests/test_bank_pixel_snapshot.py -v`
Expected: PASS. Westpac's `1600 // 2 = 800` is exact, so remainder is 0 and no bank pixel moves.

- [ ] **Step 5: Write the failing test for unbalanced braces**

```python
# tests/test_bank_dsl_validation.py
import pytest

from generators.layout_dsl.schema import LayoutSchemaError, validate_body
from conftest import assert_diagnostic_error


def test_unclosed_placeholder_is_rejected():
    """An unclosed '{FIELD' renders as a silent literal today. Hand-authored
    receipt and invoice bodies are exactly where this typo happens."""
    body = [{"type": "text", "content": "Account: {PAYER_NAME"}]
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_body(body, layout_id="probe", layout_path="config/layouts/receipts.yml",
                      known_fields={"PAYER_NAME"})
    assert_diagnostic_error(exc_info.value)
    assert "PAYER_NAME" in str(exc_info.value)
```

- [ ] **Step 6: Run it and confirm it fails**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_validation.py::test_unclosed_placeholder_is_rejected -v`
Expected: FAIL — `validate_body` accepts the body, no exception raised.

- [ ] **Step 7: Add the brace-balance check**

Add to `schema.py` beside the existing `{FIELD}` resolution check. Run it on every string a block can interpolate — `content`, `label`, `value`, `heading`, and each entry of `lines`.

```python
_UNBALANCED = re.compile(r"\{[A-Z][A-Z0-9_]*(?![A-Z0-9_]*\})|(?<!\{)[A-Z][A-Z0-9_]*\}")


def _check_braces(template: str, *, layout_path: str, key_path: str) -> None:
    """Reject a placeholder missing its opening or closing brace.

    `referenced_fields` only matches well-formed `{FIELD}`, so a typo like
    `{PAYER_NAME` is invisible to it and draws as a literal.
    """
    if _UNBALANCED.search(template):
        raise _err(
            f"template {template!r} contains an unbalanced placeholder brace.",
            layout_path=layout_path,
            key_path=key_path,
            expected="every placeholder written as {FIELD_NAME}, e.g. "
            'content: "Account: {PAYER_NAME}".',
            recover=f"add the missing brace in {key_path}.",
        )
```

- [ ] **Step 8: Confirm it passes and every existing body still validates**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_validation.py -v && conda run -n synthetic python -m generators.pipeline validate`
Expected: PASS, and validate reports no errors across all 8 bank layouts.

- [ ] **Step 9: Move the rule_above draw below its bold validation**

In `primitives_table.py`, `rule_above` currently draws its separator before `_validate_bold_spec` runs, so an invalid bold collection marks the canvas before raising. Swap the two statements so validation precedes any drawing.

- [ ] **Step 10: Give Region.indent and Region.divide four-element diagnostics**

Both raise bare `ValueError`s naming only the arithmetic. Rewrite both to the four-element form, naming `config/layouts/*.yml`, the container's `padding` / `gap` key, a concrete valid value, and the remediation.

- [ ] **Step 11: Test both diagnostics**

```python
# tests/layout_dsl/test_context.py
import pytest

from generators.layout_dsl.context import Region
from conftest import assert_diagnostic_error


@pytest.mark.parametrize(
    "call",
    [lambda: Region(x=0, width=100).indent(60, 60), lambda: Region(x=0, width=10).divide(20, gap=5)],
)
def test_region_errors_are_diagnostic(call):
    with pytest.raises(ValueError) as exc_info:
        call()
    assert_diagnostic_error(exc_info.value)
```

- [ ] **Step 12: Run the full suite and commit**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_dsl/context.py generators/layout_dsl/schema.py generators/layout_dsl/primitives_table.py
git commit -m ":bug: clear the four Stage 3 prerequisites"
```

---

## Task 2: The `defaults:` resolution module

**Files:**
- Create: `generators/layout_dsl/defaults.py`
- Test: `tests/layout_dsl/test_defaults.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `resolve_param(block: dict, layout: dict, key: str, *, layout_id: str, layout_path: str) -> object` and `DefaultsError(RuntimeError)`, plus `PARAMETER_DEFAULTS: frozenset[str]` naming every parameter the `defaults:` block must cover. Tasks 3, 4, 6, 7, and 8 all call `resolve_param`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout_dsl/test_defaults.py
import pytest

from generators.layout_dsl.defaults import DefaultsError, resolve_param
from conftest import assert_diagnostic_error

LAYOUT = {"defaults": {"color": "#000000", "align": "left", "bold": False}}
KW = {"layout_id": "receipt_thermal_80mm", "layout_path": "config/layouts/receipts.yml"}


def test_block_key_wins_over_defaults():
    assert resolve_param({"color": "#12107D"}, LAYOUT, "color", **KW) == "#12107D"


def test_defaults_supply_an_absent_block_key():
    assert resolve_param({}, LAYOUT, "color", **KW) == "#000000"


def test_falsy_default_is_not_treated_as_absent():
    """`bold: false` is a real configured value, not a missing key. A truthiness
    test here would silently fall through to the fail-fast branch."""
    assert resolve_param({}, LAYOUT, "bold", **KW) is False


def test_missing_default_fails_with_a_four_element_diagnostic():
    with pytest.raises(DefaultsError) as exc_info:
        resolve_param({}, LAYOUT, "role", **KW)
    assert_diagnostic_error(exc_info.value)
    message = str(exc_info.value)
    assert "config/layouts/receipts.yml" in message
    assert "receipt_thermal_80mm.defaults.role" in message
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_defaults.py -v`
Expected: FAIL — `ModuleNotFoundError: generators.layout_dsl.defaults`.

- [ ] **Step 3: Write the module**

```python
"""Parameter resolution for layout primitives.

Resolution order is block key -> the layout's `defaults:` -> fail fast. There is
deliberately no fourth step: a Python literal supplying a value YAML omitted is
exactly what CLAUDE.md's "every config key is required" rule forbids, and it is
how `role`, `color`, `align` and 28 other pixel decisions came to live in Python
rather than in the layout files.
"""

# Every parameter a primitive may read. schema.py asserts a layout's `defaults:`
# covers all of them, so an omission fails at startup rather than at whichever
# block first happens to need it.
PARAMETER_DEFAULTS: frozenset[str] = frozenset(
    {
        "role", "color", "align", "bold", "line_advance", "mono",
        "rule_thickness", "rule_pad_above", "rule_pad_below", "rule_fill_char",
        "spacer_height", "pair_value_align", "pair_min_gap",
        "table_header", "table_header_rule_top", "table_header_rule_gap",
        "table_group_gap", "table_fill_inset", "table_dividers",
        "table_offset_y", "table_capture", "table_sub_line_height",
        "banner_text_color", "banner_role", "banner_text_y",
        "panel_padding", "panel_border_color", "split_gap", "split_divider_color",
    }
)


class DefaultsError(RuntimeError):
    """Raised when neither a block nor its layout supplies a parameter."""


_SENTINEL = object()


def resolve_param(
    block: dict,
    layout: dict,
    key: str,
    *,
    layout_id: str,
    layout_path: str,
    block_key: str | None = None,
) -> Any:
    """Resolve one primitive parameter.

    `key` names the `defaults:` entry; `block_key` names the block's own YAML
    key when the two differ. They differ whenever `PARAMETER_DEFAULTS`
    namespaces a short key two primitives share — a panel writes `padding:` but
    resolves against `panel_padding`, because one flat namespace cannot carry
    two primitives' defaults under the same short name. Without `block_key`
    the block lookup would search for the namespaced name, never find it, and
    silently discard every per-block override.

    Args:
        block: The block dict, whose own `block_key` (or `key`) wins if present.
        layout: The resolved layout dict, carrying a `defaults:` mapping.
        key: The `defaults:` parameter name, e.g. "panel_padding".
        block_key: The block's own literal YAML key, e.g. "padding". Defaults
            to `key` when the two are the same.
        layout_id: Layout id, used in the diagnostic.
        layout_path: Path to the layout YAML, used in the diagnostic.

    Returns:
        The block's value if it carries `key`, otherwise the layout default.

    Raises:
        DefaultsError: If neither supplies `key`.
    """
    value = block.get(key, _SENTINEL)
    if value is not _SENTINEL:
        return value

    default = layout.get("defaults", {}).get(key, _SENTINEL)
    if default is not _SENTINEL:
        return default

    raise DefaultsError(
        "Missing layout default.\n"
        f"  What:     no value for '{key}' on this block, and layout "
        f"'{layout_id}' declares no default for it.\n"
        f"  Where:    {layout_path} -> {layout_id}.defaults.{key}\n"
        f"  Expected: a defaults: mapping covering every parameter, e.g.\n"
        f"              defaults:\n"
        f"                {key}: <value>\n"
        f"  Recover:  add '{key}:' under {layout_id}.defaults, or set it on "
        f"the block itself when it varies block to block."
    )
```

- [ ] **Step 4: Run the tests**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_defaults.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_dsl/defaults.py
git commit -m ":sparkles: add layout-default parameter resolution"
```

---

## Task 3: Convert the 31 default sites; seed the bank layouts

**Files:**
- Modify: `generators/layout_dsl/primitives_text.py` (14 sites), `primitives_table.py` (12), `primitives_container.py` (4)
- Modify: `generators/layout_dsl/schema.py` (coverage check)
- Modify: `config/layouts/bank_statements.yml` (shared `defaults:` anchor + 8 layouts)
- Test: `tests/layout_dsl/test_defaults.py`, `tests/test_bank_pixel_snapshot.py`

**Interfaces:**
- Consumes: `resolve_param`, `PARAMETER_DEFAULTS`, `DefaultsError` from Task 2.
- Produces: every primitive resolving through `resolve_param`; `validate_layout` rejecting an incomplete `defaults:`.

**This task must not move a single bank pixel.** The seeded defaults are exactly today's Python literals.

- [ ] **Step 1: Write the failing coverage test**

```python
# tests/layout_dsl/test_defaults.py
import pytest

from generators.layout_dsl.defaults import PARAMETER_DEFAULTS
from generators.layout_dsl.schema import LayoutSchemaError, validate_layout
from conftest import assert_diagnostic_error


def test_incomplete_defaults_block_is_rejected():
    layout = {"defaults": {"color": "#000000"}, "body": [], "font_sizes": {"body": 32}}
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(layout, layout_id="probe", layout_path="config/layouts/receipts.yml",
                        known_fields=set())
    assert_diagnostic_error(exc_info.value)
    assert "align" in str(exc_info.value)


def test_bank_layouts_cover_every_parameter_name():
    """Guards against adding a parameter to PARAMETER_DEFAULTS and forgetting to
    seed it in the shipped layouts — validate would then fail only at render.

    Scoped to bank_statements.yml: receipts and invoices gain their defaults: in
    Tasks 14 and 15, and test_all_layouts_cover_every_parameter_name widens this
    to all three files there.
    """
    from pathlib import Path

    from generators.loader import load_layout_registry

    registry = load_layout_registry(Path("config/layouts/bank_statements.yml"))
    for layout_id, layout in registry.items():
        missing = PARAMETER_DEFAULTS - set(layout.get("defaults", {}))
        assert not missing, f"bank_statements.yml -> {layout_id} missing defaults: {sorted(missing)}"
```

Scoped to bank layouts deliberately — no `xfail`. A test that cannot fail yet is a test nobody trusts, and one whose removal depends on a later task remembering is a test that outlives its reason. Task 15 adds the widened version once all three files carry `defaults:`.

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_defaults.py -v`
Expected: FAIL on `test_incomplete_defaults_block_is_rejected` — no coverage check exists yet.

- [ ] **Step 3: Add the coverage check to `validate_layout`**

```python
# generators/layout_dsl/schema.py, inside validate_layout
    missing = sorted(PARAMETER_DEFAULTS - set(layout.get("defaults", {})))
    if missing:
        raise _err(
            f"layout '{layout_id}' declares no default for: {', '.join(missing)}.",
            layout_path=layout_path,
            key_path=f"{layout_id}.defaults",
            expected="a defaults: mapping covering every parameter a primitive can read: "
            f"{sorted(PARAMETER_DEFAULTS)}.",
            recover=f"add the missing keys under {layout_id}.defaults, sharing a common "
            "block through a YAML anchor as field_budgets already does.",
        )
```

- [ ] **Step 4: Seed the bank layouts**

Add one shared anchor in `config/layouts/bank_statements.yml`, merged into all 8 layouts. Values are today's Python literals verbatim — this is a transcription, not a design decision.

```yaml
_dsl_defaults: &dsl_defaults
  defaults:
    role: body
    color: "black"
    align: left
    bold: false
    rule_thickness: 1
    rule_pad_above: 0
    rule_pad_below: 0
    rule_fill_char: none
    spacer_height: 0
    pair_value_align: left
    pair_min_gap: 0
    table_header: true
    table_header_rule_top: true
    table_header_rule_gap: 16
    table_group_gap: 10
    table_fill_inset: 0
    table_dividers: []
    table_offset_y: 0
    table_capture: true
    table_sub_line_height: 0
    banner_text_color: "white"
    banner_text_y: 0
    banner_role: header
    panel_padding: 0
    panel_border_color: "black"
    split_gap: 0
    split_divider_color: "black"
```

`mono` and `line_advance` are in `PARAMETER_DEFAULTS` from Task 2, so the coverage check
demands them now even though no primitive reads them until Task 4. Seed them per layout in
this task with their real values — never a placeholder token. `mono: false` for every bank
layout (matching `load_font`'s current default), and `line_advance` as `int(font_sizes.body
* 1.4)` computed per layout, which is exactly what `line_height` returns today:

```yaml
  cba_standard:
    <<: *dsl_defaults
    defaults:
      <<: *dsl_defaults_values
      mono: false
      line_advance: 44        # int(32 * 1.4), the ratio line_height() hardcodes
```

- [ ] **Step 5: Convert all 31 sites**

Mechanical, one site at a time. Each `block.get("key", <literal>)` becomes:

```python
resolve_param(block, ctx.layout, "key", layout_id=ctx.layout_id, layout_path=ctx.layout_path)
```

The parameter name is the `PARAMETER_DEFAULTS` name, which is namespaced where two primitives share a short key — `rule_thickness` not `thickness`, `panel_padding` not `padding`. Cast at the call site exactly as today (`int(...)`, `bool(...)`, `str(...)`).

Do not work from a line-number list — Task 1 already shifted these, and each conversion shifts them again. Instead enumerate the sites yourself and convert every one:

```bash
conda run -n synthetic grep -rn '\.get("[a-z_]*", ' generators/layout_dsl/primitives_text.py generators/layout_dsl/primitives_table.py generators/layout_dsl/primitives_container.py
```

**The receiver decides, not the key name.** A `.get()` on `block` is a layout parameter; a `.get()` on `row` reads data the row provider produced, which has no business resolving against a layout's `defaults:`. These are NOT converted:

- `primitives_table.py`'s `block.get("params", {})` — a table's own params passthrough to its row provider, not a pixel decision.
- `primitives_table.py`'s `row.get("date", "")` — provider row data.
- `primitives_table.py`'s two `row.get("bold", False)` sites, reached via `_cell_bold` and `_validate_bold_spec` — provider row data, as that file's own docstrings state. A provider marks a row bold; the layout does not. Routing these through `defaults.bold` would mean a layout setting `bold: true` silently bolds every provider row, and would couple table row rendering to a typography default that exists for `text` and `banner` blocks.

Note `bold` is genuinely a layout parameter *for blocks* — `block.get("bold", False)` in `draw_text_block` and `draw_banner` both convert. Only the `row.` receiver is exempt. Any covering test must therefore key off the receiver, not the bare key name.

Every other hit converts. Two of them have parameter names that exist only because this task added them, so they are easy to miss: `draw_banner`'s `block.get("text_y", 0)` → `banner_text_y`, and the sub-line `sub_line.get("height", 0)` → `table_sub_line_height`. Note the latter is **not** `spacer_height` — a table sub-line's extra height and a spacer block's advance are different things that happened to share a short key.

When you finish, re-run the grep. Every remaining hit must be one of the two exclusions above; if anything else remains, you missed a site.

- [ ] **Step 6: Run the bank snapshot — the gate for this task**

Run: `conda run -n synthetic pytest tests/test_bank_pixel_snapshot.py tests/layout_dsl/ -v`
Expected: PASS. Any hash mismatch means a seeded default does not match the literal it replaced. Run `conda run -n synthetic python tests/bank_pixel_diagnostics.py` to localise it. **Do not re-bless the fixture.**

- [ ] **Step 7: Run the full suite and commit**

```bash
conda run -n synthetic pytest tests/ && conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_dsl/ config/layouts/bank_statements.yml
git commit -m ":recycle: resolve every primitive parameter through the layout"
```

---

## Task 4: Monospace and declared line advance

**Files:**
- Modify: `generators/layout_dsl/primitives_text.py:48-67, 127, 153, 261`, `primitives_table.py:269, 377, 485-486, 592`
- Modify: `config/layouts/bank_statements.yml` (`line_advance` per layout)
- Test: `tests/layout_dsl/test_text_primitives.py`

**Interfaces:**
- Consumes: `resolve_param` from Task 2.
- Produces: `line_advance(layout, block, *, layout_id, layout_path) -> int` in `primitives_text.py`, replacing the module-level `line_height(size)`. Tasks 6, 7, 14, and 15 depend on it.

Two of the three engine gaps from the spec. Bank output must not move: `mono: false` matches `load_font`'s default, and each bank layout's `line_advance` is seeded as `int(font_sizes.body * 1.4)` — the exact value `line_height` returns today.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout_dsl/test_text_primitives.py
from PIL import Image, ImageDraw

from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.primitives_text import draw_text_block

BASE = {
    "font_sizes": {"body": 18},
    "defaults": {"role": "body", "color": "black", "align": "left", "bold": False,
                 "mono": True, "line_advance": 20},
}


def _ctx(layout):
    image = Image.new("RGB", (420, 400), "white")
    return RenderContext(draw=ImageDraw.Draw(image), entry={"fields": {"SUPPLIER_NAME": "Woolworths"}},
                         layout=layout, layout_id="probe", layout_path="config/layouts/receipts.yml",
                         region=Region(x=12, width=396))


def test_line_advance_comes_from_the_layout_not_a_ratio():
    """Receipts declare line_height 20 against an 18pt font — a ratio of 1.11,
    not the 1.4 hardcoded in line_height(). Using the ratio retypesets every
    receipt."""
    end = draw_text_block({"type": "text", "content": "{SUPPLIER_NAME}"}, _ctx(BASE), 100)
    assert end == 120


def test_monospace_is_honoured():
    """All six receipt layouts are font_family: monospace. Every load_font call
    in this module omitted mono=, so they rendered in the sans face."""
    mono_ctx, sans_ctx = _ctx(BASE), _ctx({**BASE, "defaults": {**BASE["defaults"], "mono": False}})
    draw_text_block({"type": "text", "content": "{SUPPLIER_NAME}"}, mono_ctx, 10)
    draw_text_block({"type": "text", "content": "{SUPPLIER_NAME}"}, sans_ctx, 10)
    assert list(mono_ctx.draw._image.getdata()) != list(sans_ctx.draw._image.getdata())
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_text_primitives.py -v`
Expected: FAIL — advance is 25 (18 × 1.4), and both images are identical.

- [ ] **Step 3: Replace `line_height` with `line_advance`**

```python
def line_advance(layout: dict, block: dict, *, layout_id: str, layout_path: str) -> int:
    """Return the vertical advance for one line, in pixels.

    Replaces the former `line_height(size) = int(size * 1.4)`. The 1.4 ratio was
    a Python literal that receipts contradict: `receipts.yml` declares
    `line_height: 20` against `font_size: 18`, a ratio of 1.11.
    """
    return int(resolve_param(block, layout, "line_advance",
                             layout_id=layout_id, layout_path=layout_path))
```

Replace every `y + line_height(size)` with `y + line_advance(...)`. Delete `line_height`.

- [ ] **Step 4: Thread `mono` into every font load**

Add a module-level helper and route all eight `load_font` call sites in `primitives_text.py` and `primitives_table.py` through it:

```python
def font_for(layout: dict, block: dict, size: int, *, bold: bool, layout_id: str, layout_path: str) -> Font:
    """Load a font honouring the layout's declared face."""
    mono = bool(resolve_param(block, layout, "mono", layout_id=layout_id, layout_path=layout_path))
    return load_font(size, mono=mono, bold=bold)
```

- [ ] **Step 5: Verify the seeded values against the ratio they replace**

Task 3 already seeded `mono` and `line_advance`. Confirm each layout's `line_advance` equals `int(font_sizes.body * 1.4)` before running the snapshot — a transcription slip here is the single most likely cause of a Step 6 failure.

```bash
conda run -n synthetic python -c "
import yaml
d = yaml.safe_load(open('config/layouts/bank_statements.yml'))['layouts']
for k, v in d.items():
    want = int(v['font_sizes']['body'] * 1.4)
    got = v['defaults']['line_advance']
    print(('OK  ' if want == got else 'DIFF'), k, 'want', want, 'got', got)
"
```

Expected: `OK` on all 8 layouts.

- [ ] **Step 6: Run the bank snapshot — the gate for this task**

Run: `conda run -n synthetic pytest tests/test_bank_pixel_snapshot.py tests/layout_dsl/ -v`
Expected: PASS. A mismatch means a `line_advance` value does not equal `int(size * 1.4)` for that layout.

- [ ] **Step 7: Full suite and commit**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_dsl/ config/layouts/bank_statements.yml
git commit -m ":sparkles: honour the layout's font face and line advance"
```

---

## Task 5: The hardcoded provider label

**Files:**
- Modify: `generators/layout_dsl/providers.py:330-362`
- Modify: `config/layouts/bank_statements.yml` (ANZ totals table `params:`)
- Test: `tests/layout_dsl/test_providers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `bank_transaction_totals` requiring a `label` param.

`providers.py:362` defaults `label` to the printed string `"Totals at end of period"`. A string rendered onto the page has no business living in Python.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_providers.py
import pytest

from generators.layout_dsl.providers import ProviderError, get_provider
from conftest import assert_diagnostic_error

ENTRY = {"fields": {"TRANSACTION_AMOUNTS_PAID": "10.00|20.00",
                    "TRANSACTION_AMOUNTS_RECEIVED": "5.00|NOT_FOUND"}}


def test_totals_label_must_come_from_yaml():
    with pytest.raises(ProviderError) as exc_info:
        get_provider("bank_transaction_totals")(ENTRY, {})
    assert_diagnostic_error(exc_info.value)
    assert "label" in str(exc_info.value)
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_providers.py::test_totals_label_must_come_from_yaml -v`
Expected: FAIL — the provider returns a row labelled "Totals at end of period" and raises nothing.

- [ ] **Step 3: Make the param required**

Replace `params.get("label", "Totals at end of period")` with a presence check raising a four-element `ProviderError` naming `config/layouts/bank_statements.yml`, the table's `params.label` key, and a concrete example.

- [ ] **Step 4: Set the label in YAML**

Add `label: "Totals at end of period"` under the ANZ totals table's `params:` in `config/layouts/bank_statements.yml`.

- [ ] **Step 5: Confirm pass, snapshot green, and commit**

```bash
conda run -n synthetic pytest tests/layout_dsl/test_providers.py tests/test_bank_pixel_snapshot.py -v
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
git add generators/layout_dsl/providers.py config/layouts/bank_statements.yml
git commit -m ":bug: move the totals row label out of Python"
```

---

## Task 6: Fit budgets on `text` and `pair`

**Files:**
- Modify: `generators/layout_dsl/primitives_text.py` (`draw_text_block`, `draw_pair`)
- Modify: `generators/layout_dsl/schema.py` (allow `budget` on `text`/`pair`; extend `_validate_column_budgets`' sibling check)
- Test: `tests/layout_dsl/test_text_primitives.py`

**Interfaces:**
- Consumes: `resolve_param`, `line_advance`, `font_for` from Tasks 2 and 4.
- Produces: `text` and `pair` accepting `budget: <FIELD_BUDGET_NAME>`, dispatching to the `draw_fitted_*` helpers and returning their wrapped advance. Tasks 14 and 15 depend on it.

The third engine gap. Six receipt fields and four invoice fields are drawn through `draw_fitted_*` with `shrink_then_wrap` and `max_lines: 2`; a wrapped line advances the cursor twice.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_text_primitives.py
def test_budgeted_text_wraps_and_advances_by_the_wrapped_height():
    """shrink_then_wrap with max_lines 2 puts a long supplier name on two lines.
    The cursor must advance by both, or every block below it overlaps."""
    layout = {
        "font_sizes": {"body": 18},
        "defaults": {"role": "body", "color": "black", "align": "center", "bold": False,
                     "mono": True, "line_advance": 20},
        "field_budgets": {
            "SUPPLIER_NAME": {"width": 396, "fit": "shrink_then_wrap", "min_font": 10, "max_lines": 2}
        },
    }
    ctx = _ctx(layout)
    ctx.entry["fields"]["SUPPLIER_NAME"] = "Woolworths Group Limited Southbank Trading"
    end = draw_text_block(
        {"type": "text", "content": "{SUPPLIER_NAME}", "budget": "SUPPLIER_NAME"}, ctx, 100
    )
    assert end == 140


def test_budget_names_an_undeclared_field_budget():
    layout = {"font_sizes": {"body": 18},
              "defaults": {"role": "body", "color": "black", "align": "left", "bold": False,
                           "mono": True, "line_advance": 20},
              "field_budgets": {}}
    with pytest.raises(LayoutBudgetError) as exc_info:
        draw_text_block({"type": "text", "content": "x", "budget": "SUPPLIER_NAME"}, _ctx(layout), 0)
    assert_diagnostic_error(exc_info.value)
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_text_primitives.py -v`
Expected: FAIL — `budget` is ignored, the name draws on one line, advance is 20.

- [ ] **Step 3: Implement the budgeted path**

In `draw_text_block`, when `budget` is present, resolve it via `field_budget(ctx.layout, ctx.layout_id, name, layout_path=ctx.layout_path)` and dispatch on the resolved `align` to `draw_fitted_left`, `draw_fitted_center`, or `draw_fitted_right`, passing `nominal_size=size`, `mono`, `bold`, `fill=color`, `line_spacing=<line_advance>`, `recorder=ctx.recorder`, `field=block.get("field")`. Return the helper's own advance — those helpers already return the wrapped bottom. The unbudgeted path is unchanged.

`draw_fitted_center` centres in a canvas width, not a region: pass `ctx.region.x * 2 + ctx.region.width` so a symmetric margin centres identically to `receipt.py:161`. Assert this in a test rather than assuming it.

Apply the same treatment to `draw_pair`, budgeting the value only.

- [ ] **Step 4: Allow the key in the schema**

Add `"budget"` to the `text` and `pair` optional-key tuples in `PRIMITIVES`, and extend the existing budget validation so a `text`/`pair` budget name must exist in `field_budgets` and its width must not exceed the block's region width.

- [ ] **Step 5: Confirm pass, snapshot green, and commit**

```bash
conda run -n synthetic pytest tests/layout_dsl/ tests/test_bank_pixel_snapshot.py tests/test_fitted_helpers.py -v
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_dsl/
git commit -m ":sparkles: apply fit budgets to text and pair primitives"
```

---

## Task 7: Receipt primitives — `pair.value_align`, `pair.min_gap`, `rule.fill_char`

**Files:**
- Modify: `generators/layout_dsl/primitives_text.py` (`draw_pair`, `draw_rule`)
- Modify: `generators/layout_dsl/schema.py` (`PRIMITIVES`)
- Test: `tests/layout_dsl/test_text_primitives.py`

**Interfaces:**
- Consumes: `resolve_param`, `line_advance`, `font_for` from Tasks 2 and 4.
- Produces: `pair` supporting `value_align: right` and `min_gap: <px>`; `rule` supporting `fill_char: "-"`. Tasks 14 and 15 depend on both.

`pair` today draws `"{label}: {value}"` as one left-aligned string (`primitives_text.py:147`). Receipts and invoices need the label at the left edge and the amount right-aligned to the region — `draw_line_item`. Separately, `common.py:540`'s `draw_separator` fills the content width with `-` glyphs, which `rule`'s drawn line cannot reproduce.

`min_gap` covers `invoice.py:283-285`, where a long label is pushed left just enough to clear a right-aligned amount. YAML states the minimum gap; Python does the measuring.

- [ ] **Step 1: Write the failing tests**

```python
def test_pair_right_aligns_its_value_to_the_region():
    layout = {**BASE, "defaults": {**BASE["defaults"], "pair_value_align": "right", "pair_min_gap": 0}}
    ctx = _ctx(layout)
    draw_pair({"type": "pair", "label": "TOTAL", "value": "137.73"}, ctx, 50)
    columns = [x for x in range(396) if ctx.draw._image.getpixel((12 + x, 55)) != (255, 255, 255)]
    assert max(columns) > 340, "value should sit against the region's right edge"


def test_pair_min_gap_pushes_a_long_label_left():
    """invoice.py:283-285 computes label_x so 'GST included (10%):' never merges
    with the amount into one OCR token."""
    layout = {**BASE, "defaults": {**BASE["defaults"], "pair_value_align": "right", "pair_min_gap": 24}}
    ctx = _ctx(layout)
    draw_pair({"type": "pair", "label": "GST included (10%)", "value": "1,234,567.89"}, ctx, 50)
    row = [x for x in range(396) if ctx.draw._image.getpixel((12 + x, 55)) != (255, 255, 255)]
    gaps = [b - a for a, b in zip(row, row[1:]) if b - a > 1]
    assert max(gaps) >= 24


def test_rule_fill_char_draws_glyphs_not_a_line():
    ctx = _ctx({**BASE, "defaults": {**BASE["defaults"], "rule_fill_char": "-"}})
    end = draw_rule({"type": "rule"}, ctx, 50)
    assert end == 70, "a character separator advances a full line, not its thickness"
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_text_primitives.py -v`
Expected: FAIL on all three — the keys are ignored.

- [ ] **Step 3: Implement**

In `draw_pair`, when the resolved `pair_value_align` is `right`: draw the label at `ctx.region.x`, right-align the value at `ctx.region.right`, and place the label at `min(region.x, region.right - value_width - label_width - min_gap)`. Record the value's own box as today.

In `draw_rule`, when the resolved `rule_fill_char` is not the string `none`: compute the repeat count as `region.width // glyph_width` and draw the string, advancing by `line_advance` instead of `thickness`. This mirrors `common.py:548-553` exactly — reuse `draw_separator` rather than reimplementing the arithmetic.

- [ ] **Step 4: Confirm pass, snapshot green, and commit**

```bash
conda run -n synthetic pytest tests/layout_dsl/ tests/test_bank_pixel_snapshot.py -v
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
git add generators/layout_dsl/
git commit -m ":sparkles: add right-aligned pair values and character rules"
```

---

## Task 8: Invoice primitives — `split.widths`, `table.capture`

**Files:**
- Modify: `generators/layout_dsl/context.py` (`Region.divide_widths`), `primitives_container.py` (`draw_split`), `primitives_table.py` (`draw_table`)
- Modify: `generators/layout_dsl/schema.py`
- Test: `tests/layout_dsl/test_context.py`, `tests/layout_dsl/test_containers.py`

**Interfaces:**
- Consumes: `resolve_param` from Task 2.
- Produces: `Region.divide_widths(widths: list[int], gap: int) -> list[Region]`; `split` accepting `widths:`; `table` accepting `capture: false`. Task 15 depends on both.

`split` divides equally (`context.py:55`). Invoice totals occupy a fixed 400px column at `right_edge - 400` (`invoice.py:242`), which equal division cannot express. `capture: false` replaces the `line_item_tables_seen` counter at `invoice.py:412`: `tax_invoice_mixed` draws the same `LINE_ITEM_*` list into two tables, and a second recorded box for the same field would collide with the first.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout_dsl/test_context.py
def test_divide_widths_places_explicit_columns():
    left, right = Region(x=100, width=1700).divide_widths([1300, 400], gap=0)
    assert (left.x, left.width) == (100, 1300)
    assert (right.x, right.width) == (1400, 400)
    assert right.right == 1800


def test_divide_widths_rejects_a_sum_that_overflows_the_region():
    with pytest.raises(ValueError) as exc_info:
        Region(x=0, width=100).divide_widths([80, 80], gap=0)
    assert_diagnostic_error(exc_info.value)
```

```python
# tests/layout_dsl/test_containers.py
def test_capture_false_records_no_field_boxes():
    """tax_invoice_mixed renders the same line items twice. The second table
    must not record boxes — one ground-truth value has one box."""
    recorder = BoxRecorder(1900, 3508)
    ctx = _table_ctx(recorder=recorder)
    draw_table({**MIXED_TABLE, "capture": False}, ctx, 100)
    assert recorder.as_dict() == {}
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_context.py tests/layout_dsl/test_containers.py -v`
Expected: FAIL — `divide_widths` does not exist; `capture` is ignored and boxes are recorded.

- [ ] **Step 3: Implement `Region.divide_widths`**

Take an explicit width list plus gap, validate that `sum(widths) + gap * (n - 1) <= self.width` with a four-element diagnostic naming the layout's `split.widths` key, and return the regions left to right.

- [ ] **Step 4: Wire `widths:` into `draw_split` and `capture:` into `draw_table`**

`draw_split` uses `divide_widths` when the block carries `widths:` and `divide` otherwise. `draw_table` resolves `table_capture` and passes `None` instead of `ctx.recorder` into its cell drawing when false.

- [ ] **Step 5: Add both keys to the schema**

`widths` on `split`, `capture` on `table`, both validated: `widths` a non-empty list of positive ints whose length equals `len(children)`, `capture` a bool.

- [ ] **Step 6: Confirm pass, snapshot green, and commit**

```bash
conda run -n synthetic pytest tests/layout_dsl/ tests/test_bank_pixel_snapshot.py -v
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_dsl/
git commit -m ":sparkles: add explicit split widths and table capture control"
```

---

## Task 9: The field-provider registry

**Files:**
- Create: `generators/layout_dsl/field_providers.py`
- Modify: `generators/layout_dsl/engine.py` (`render_body`), `schema.py`
- Test: `tests/layout_dsl/test_field_providers.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `field_provider(name: str, *, params: frozenset[str], emits: tuple[str, ...])` decorator
  - `get_field_provider(name) -> FieldProvider` where `FieldProvider = Callable[[dict, dict], dict[str, str]]`
  - `field_provider_names() -> list[str]`, `field_provider_emits(name) -> tuple[str, ...]`, `field_provider_param_keys(name) -> frozenset[str]`
  - `apply_field_providers(layout: dict, entry: dict) -> dict` returning a new entry whose `fields` carries the merged derived values
  - `FieldProviderError(RuntimeError)`

  Tasks 10, 11, 14, and 15 depend on these.

Mirror `providers.py`'s registry shape deliberately — a reader who knows one knows the other. The one addition is `emits`, which is mandatory: without it `validate` could not resolve a `{FIELD}` naming a derived value, and every placeholder check would degrade to a render-time failure.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout_dsl/test_field_providers.py
import pytest

from generators.layout_dsl.field_providers import (
    FieldProviderError, apply_field_providers, field_provider, field_provider_emits,
)
from conftest import assert_diagnostic_error


def test_provider_output_is_merged_into_entry_fields():
    layout = {"field_providers": [{"name": "probe_pos", "params": {}}]}
    entry = {"fields": {"TOTAL_AMOUNT": "137.73"}}
    merged = apply_field_providers(layout, entry)
    assert merged["fields"]["POS_STAFF"] == "Sarah"
    assert merged["fields"]["TOTAL_AMOUNT"] == "137.73"
    assert entry["fields"] == {"TOTAL_AMOUNT": "137.73"}, "the caller's entry must not be mutated"


def test_provider_emitting_an_undeclared_key_fails():
    """`emits` is the contract validate checks placeholders against. A provider
    returning a key it never declared makes that check a lie."""
    layout = {"field_providers": [{"name": "probe_undeclared", "params": {}}]}
    with pytest.raises(FieldProviderError) as exc_info:
        apply_field_providers(layout, {"fields": {}})
    assert_diagnostic_error(exc_info.value)
    assert "POS_SURPRISE" in str(exc_info.value)


def test_emit_colliding_with_a_scored_column_is_rejected():
    """A derived presentation value must never be mistaken for extraction
    ground truth — config/field_definitions.yml owns those 23 names."""
    with pytest.raises(FieldProviderError) as exc_info:

        @field_provider("probe_collision", params=frozenset(), emits=("TOTAL_AMOUNT",))
        def _collide(entry, params):
            return {"TOTAL_AMOUNT": "0.00"}

    assert_diagnostic_error(exc_info.value)
```

Register `probe_pos` and `probe_undeclared` as module-level fixtures in the test file.

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_field_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: generators.layout_dsl.field_providers`.

- [ ] **Step 3: Write the module**

Registry, decorator, lookups, and `apply_field_providers` returning `{**entry, "fields": {**entry["fields"], **derived}}` — a copy, never a mutation, since `pipeline.generate` reuses entries across the clean and degraded passes. The decorator loads `config/field_definitions.yml`'s column names once and rejects a colliding emit at import time. Every error is four-element.

- [ ] **Step 4: Call it from `render_body`**

In `engine.py`, before constructing the `RenderContext`, replace `entry` with `apply_field_providers(layout, entry)`. A layout with no `field_providers:` key gets an empty list — but that key is **required**, so add it explicitly as `field_providers: []` to all 8 bank layouts rather than defaulting it.

- [ ] **Step 5: Extend `validate`**

Three checks, each four-element:
1. Every `field_providers:` entry names a registered provider.
2. Its `params` keys are a subset of the provider's declared `params`.
3. `known_fields` passed to `validate_body` is the union of `field_definitions.yml`'s columns and every declared `emits` name, so a `{FIELD}` naming a derived value resolves and a typo still fails.

- [ ] **Step 6: Confirm pass, snapshot green, and commit**

```bash
conda run -n synthetic pytest tests/ && conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_dsl/ config/layouts/bank_statements.yml
git commit -m ":sparkles: add the field-provider extension point"
```

---

## Task 10: `pos_terminal` config and the POS providers

**Files:**
- Modify: `config/data_pools.yml` (new `pos_terminal` block)
- Modify: `generators/payment_block.py` (`load_pos_pools` + validation)
- Modify: `generators/layout_dsl/field_providers.py` (`receipt_pos`, `computed_totals`)
- Test: `tests/test_data_pools_core.py`, `tests/layout_dsl/test_field_providers.py`

**Interfaces:**
- Consumes: `field_provider` from Task 9.
- Produces: `receipt_pos` emitting `POS_TIME`, `POS_REGISTER`, `POS_STAFF`, `RECEIPT_NUMBER`; `computed_totals` emitting `SUBTOTAL_AMOUNT`. Tasks 14 and 15 bind these.

**The digest slicing must not change.** `receipt.py:100-113` consumes hex chars 0–8 of `sha256(f"{case_id}:pos:{invoice_date}")`; `payment_block.py:384` consumes 10–40. Phase A parity depends on both staying exact.

- [ ] **Step 1: Write the failing parity test**

```python
# tests/layout_dsl/test_field_providers.py
import pytest

from pathlib import Path

from generators.layout_dsl.field_providers import get_field_provider

# Task 0's capture script. `load_ground_truth` returns a flat case_id -> entry
# mapping with no "documents" key; `_entries` is the helper that flattens it to
# the list of entries these tests iterate, each carrying its own `case_id`.
from regenerate_doc_pixel_snapshot import _entries


@pytest.mark.parametrize("entry", _entries(Path("ground_truth/receipts.yml")))
def test_receipt_pos_matches_the_legacy_derivation(entry):
    """Phase A parity: the provider must reproduce receipt.py's values exactly
    for every entry in the corpus, not just a sample."""
    from generators.receipt import _derive_receipt_details, _derive_receipt_number

    case_id, date = entry["case_id"], entry["fields"]["INVOICE_DATE"]
    legacy = _derive_receipt_details(case_id, date)
    derived = get_field_provider("receipt_pos")(entry, {"pools_key": "pos_terminal"})

    assert derived["POS_TIME"] == legacy["time"]
    assert derived["POS_REGISTER"] == legacy["register"]
    assert derived["POS_STAFF"] == legacy["staff"]
    assert derived["RECEIPT_NUMBER"] == _derive_receipt_number(case_id, date)
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_field_providers.py -k receipt_pos -v`
Expected: FAIL — no `receipt_pos` provider is registered.

- [ ] **Step 3: Add the `pos_terminal` block**

```yaml
# config/data_pools.yml
pos_terminal:
  # Deterministic POS values, derived from sha256("{case_id}:pos:{invoice_date}").
  # Hex slices 0-8 belong to this block; payment_terminal consumes 10-40.
  staff_names: [Sarah, James, Emma, Liam, Olivia, Noah, Chloe, Jack,
                Mia, Ethan, Ava, Will, Sophie, Ben, Isla, Tom]
  hour_min: 8
  hour_span: 12          # 08:00-19:59
  register_min: 1
  register_span: 8       # 01-08
  receipt_number_prefix: "R-"
  receipt_number_digest_length: 6
```

- [ ] **Step 4: Add `load_pos_pools` with four-element validation**

Follow `load_terminal_pools`' shape exactly (`payment_block.py:68-210`): `@lru_cache`, a `_REQUIRED_KEYS` mapping of key to expected-shape description, and a presence-and-type check per key.

- [ ] **Step 5: Write the two providers**

`receipt_pos` moves the arithmetic from `receipt.py:100-119` verbatim, reading its pools from `load_pos_pools()` instead of `_STAFF_NAMES` and the inline ranges. `computed_totals` emits `SUBTOTAL_AMOUNT` as `str(Decimal(TOTAL_AMOUNT) - Decimal(GST_AMOUNT))`, matching `receipt.py:303`, and emits nothing when either field is absent or `NOT_FOUND`.

- [ ] **Step 6: Confirm parity across all 55 receipt entries**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_field_providers.py tests/test_data_pools_core.py -v`
Expected: PASS — 55 parametrised cases plus the pools validation tests.

- [ ] **Step 7: Commit**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add config/data_pools.yml generators/payment_block.py generators/layout_dsl/field_providers.py
git commit -m ":sparkles: add the POS and computed-totals field providers"
```

---

## Task 11: The `receipt_payment` provider and slip labels

**Files:**
- Modify: `config/data_pools.yml` (`payment_terminal.slip_labels`)
- Modify: `generators/payment_block.py` (validation for the new keys)
- Modify: `generators/layout_dsl/field_providers.py` (`receipt_payment`)
- Test: `tests/test_payment_block.py`, `tests/layout_dsl/test_field_providers.py`

**Interfaces:**
- Consumes: `field_provider` from Task 9; `derive_payment`, `load_terminal_pools`, `load_link_index` from `payment_block.py`.
- Produces: `receipt_payment` emitting `PAYMENT_KIND`, `PAYMENT_METHOD`, `PAYMENT_SCHEME_DISPLAY`, `PAYMENT_ACCOUNT_TYPE`, `PAYMENT_ACQUIRER`, `PAYMENT_AID`, `PAYMENT_MASKED_PAN`, `PAYMENT_ENTRY_MODE`, `PAYMENT_PSN`, `PAYMENT_ATC`, `PAYMENT_TERMINAL_ID`, `PAYMENT_TRANSACTION_REF`, `PAYMENT_TIMESTAMP`, `PAYMENT_WALLET_LABEL`, `PAYMENT_TENDERED`, `PAYMENT_CHANGE`. Task 14 binds these.

**It deliberately does not emit a purchase total.** The slip's `Purchase   AUD` line binds `{TOTAL_AMOUNT}` directly, so it cannot drift from the scored field — the invariant `payment_block.py:300-303` documents.

The three block variants are selected by `when:` on emitted keys, not by a Python branch: a cash payment emits `NOT_FOUND` for the card keys, a card payment emits `NOT_FOUND` for `PAYMENT_WALLET_LABEL`, `PAYMENT_TENDERED`, and `PAYMENT_CHANGE`. `is_present` already treats `NOT_FOUND` as absent (`binding.py:76`).

- [ ] **Step 1: Write the failing parity test**

Add to the same file as Task 10's tests, which already imports `_entries` from
`regenerate_doc_pixel_snapshot` (see Task 10 Step 1 — `load_ground_truth` returns a flat
case_id mapping, not a list).

```python
@pytest.mark.parametrize("entry", _entries(Path("ground_truth/receipts.yml")))
def test_receipt_payment_matches_derive_payment(entry):
    from generators.payment_block import derive_payment, load_link_index
    from generators.receipt import _derive_receipt_details

    case_id, date = entry["case_id"], entry["fields"]["INVOICE_DATE"]
    legacy = derive_payment(
        case_id, date, entry["fields"]["TOTAL_AMOUNT"],
        _derive_receipt_details(case_id, date)["time"],
        bank_description=load_link_index().get(f"{case_id}_{entry['layout']}"),
    )
    derived = get_field_provider("receipt_payment")(entry, {"pools_key": "payment_terminal"})

    assert derived["PAYMENT_SCHEME_DISPLAY"] == (legacy.scheme_display or "NOT_FOUND")
    assert derived["PAYMENT_AID"] == (legacy.aid or "NOT_FOUND")
    assert derived["PAYMENT_TIMESTAMP"] == legacy.timestamp
    assert derived["PAYMENT_KIND"] == legacy.kind


def test_cash_receipts_suppress_the_card_keys():
    """The three slip variants are selected by when:, so a cash payment must
    emit NOT_FOUND for every card key rather than an empty string."""
    cash = [e for e in _entries(Path("ground_truth/receipts.yml"))
            if get_field_provider("receipt_payment")(e, {"pools_key": "payment_terminal"})
            ["PAYMENT_KIND"] == "cash"]
    assert cash, "the corpus must contain at least one cash receipt for this test to mean anything"
    derived = get_field_provider("receipt_payment")(cash[0], {"pools_key": "payment_terminal"})
    assert derived["PAYMENT_AID"] == "NOT_FOUND"
    assert derived["PAYMENT_TENDERED"] != "NOT_FOUND"
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_field_providers.py -k receipt_payment -v`
Expected: FAIL — no `receipt_payment` provider registered.

- [ ] **Step 3: Move the slip labels into YAML**

```yaml
# config/data_pools.yml, under payment_terminal
  slip_labels:
    aid: "AID: "
    card: "Card: "
    psn_atc: "PSN: {PAYMENT_PSN}, ATC: {PAYMENT_ATC}"
    purchase: "Purchase   AUD"
    terminal_id: "Terminal ID: "
    transaction_ref: "Transaction Ref: "
  cash_tender_step: 5
  cash_extra_notes: 3
```

Add `slip_labels`, `cash_tender_step`, and `cash_extra_notes` to `_REQUIRED_KEYS` in `payment_block.py:38` with their expected-shape descriptions, and add a sub-key check for `slip_labels` mirroring the existing `schemes` check at `payment_block.py:120-129`.

- [ ] **Step 4: Write the provider**

Wrap `derive_payment`, reading the linked bank description exactly as `receipt.py:334-340` does. Map each `PaymentDetails` attribute to its emit name, substituting `"NOT_FOUND"` for every empty string and `None`.

- [ ] **Step 5: Confirm parity across all 55 entries and commit**

```bash
conda run -n synthetic pytest tests/layout_dsl/test_field_providers.py tests/test_payment_block.py -v
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add config/data_pools.yml generators/payment_block.py generators/layout_dsl/field_providers.py
git commit -m ":sparkles: add the EFTPOS terminal field provider"
```

---

## Task 12: The `receipt_line_items` row provider

**Files:**
- Modify: `generators/layout_dsl/providers.py`
- Test: `tests/layout_dsl/test_providers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: row provider `receipt_line_items`, params `{"fields", "quantity_prefix_format"}`, returning rows keyed `description`, `quantity`, `price`, `total`. Task 14 binds it.

`receipt.py:265-268` prefixes a description with its quantity when the quantity is not `1` — `"2x Coffee"`. `pipe_fields` zips columns and cannot join them, and the join is arithmetic on row data, so it belongs in a provider.

- [ ] **Step 1: Write the failing test**

```python
def test_quantity_prefix_is_applied_only_above_one():
    entry = {"fields": {
        "LINE_ITEM_DESCRIPTIONS": "Coffee|Muffin",
        "LINE_ITEM_QUANTITIES": "2|1",
        "LINE_ITEM_PRICES": "4.50|3.20",
        "LINE_ITEM_TOTAL_PRICES": "9.00|3.20",
    }}
    rows = get_provider("receipt_line_items")(entry, {
        "fields": {"description": "LINE_ITEM_DESCRIPTIONS", "quantity": "LINE_ITEM_QUANTITIES",
                   "price": "LINE_ITEM_PRICES", "total": "LINE_ITEM_TOTAL_PRICES"},
        "quantity_prefix_format": "{quantity}x ",
    })
    assert rows[0]["description"] == "2x Coffee"
    assert rows[1]["description"] == "Muffin"


def test_missing_prefix_format_fails_diagnostically():
    with pytest.raises(ProviderError) as exc_info:
        get_provider("receipt_line_items")({"fields": {}}, {"fields": {"description": "X"}})
    assert_diagnostic_error(exc_info.value)
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_providers.py -k line_items -v`
Expected: FAIL — no `receipt_line_items` provider registered.

- [ ] **Step 3: Implement it**

Delegate the zip to `pipe_fields`, then apply the prefix. `quantity_prefix_format` is required — a four-element `ProviderError` when absent, never a Python literal.

- [ ] **Step 4: Confirm pass and commit**

```bash
conda run -n synthetic pytest tests/layout_dsl/test_providers.py -v
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
git add generators/layout_dsl/providers.py
git commit -m ":sparkles: add the receipt line-item row provider"
```

---

## Task 14: Receipt bodies and adapter

**Files:**
- Modify: `config/layouts/receipts.yml` (all 6 layouts)
- Modify: `generators/receipt.py` (442 lines → ~80)
- Modify: `generators/payment_block.py` (delete `render_payment_block`)
- Test: `tests/test_receipt_pixel_snapshot.py`, `tests/test_receipt_fit.py`

**Interfaces:**
- Consumes: everything from Tasks 0–12.
- Produces: `render_receipt(entry, layout, *, geometry_out=None) -> Image.Image` — unchanged signature, so `pipeline.py:51` needs no edit.

Work **one layout at a time**, running the snapshot after each. Six small failures are diagnosable; one large one is not.

- [ ] **Step 1: Write the adapter**

Mirror `bank_statement.py:39-76`, with the variable-height handling receipts need:

```python
def render_receipt(entry: dict, layout: dict, *, geometry_out: dict | None = None) -> Image.Image:
    """Render a receipt through the declarative layout engine.

    Receipts are variable-height: the body is drawn onto a tall canvas, then
    cropped to the y the engine returns. `render_body` is canvas-agnostic, so
    this needs no engine support — it is the same crop-and-rescale the legacy
    renderer did at receipt.py:431-440.
    """
    layout_id = str(entry.get("layout", ""))
    width = layout["width"]
    ceiling = layout["canvas_ceiling"]
    margin = layout["margin"]

    image = Image.new("RGB", (width, ceiling), "white")
    draw = ImageDraw.Draw(image)
    recorder = BoxRecorder(width, ceiling) if geometry_out is not None else None

    end_y = render_body(
        layout, entry, layout_id=layout_id, layout_path=_LAYOUT_PATH, draw=draw,
        region=Region(x=margin, width=width - 2 * margin), y=margin, recorder=recorder,
    )

    height = min(end_y + margin, ceiling)
    image = image.crop((0, 0, width, height))

    if recorder is not None and geometry_out is not None:
        geometry_out["width"] = width
        geometry_out["height"] = height
        geometry_out["boxes"] = rescale_vertical(recorder.as_dict(), old_height=ceiling, new_height=height)
    return image
```

`canvas_ceiling` replaces the `max_h = 4000` literal and is declared per layout.

- [ ] **Step 2: Author `receipt_thermal_80mm`'s body**

Translate the eleven sections. The header's four fitted centre lines become budgeted `text` blocks; `receipt_meta`'s two lines become `split` blocks with a left and a right `text`; each `separator` becomes a `rule` with `fill_char: "-"`; `itemized` becomes a `table` on `receipt_line_items`; `totals` becomes three `pair` blocks with `value_align: right`, the first two under `when: GST_AMOUNT`; `payment` becomes the slip blocks bound to `receipt_payment`'s emits with `when:` selecting the variant; `footer` becomes a centred `text`.

Every label that was a Python string — `"Date: "`, `"Time: "`, `"Reg: "`, `"Staff: "`, `"SUBTOTAL"`, `"GST"`, `"TOTAL"` — is written in the YAML. Every `line_h // 4` becomes an explicit `spacer` with its computed pixel height (`20 // 4 = 5` for the 80mm layout).

```yaml
    body:
      - {type: text, content: "{SUPPLIER_NAME}", align: center, bold: true,
         budget: SUPPLIER_NAME, field: SUPPLIER_NAME}
      - {type: text, content: "{BUSINESS_ADDRESS}", align: center,
         budget: BUSINESS_ADDRESS, field: BUSINESS_ADDRESS,
         when: BUSINESS_ADDRESS}
      - {type: text, content: "ABN: {BUSINESS_ABN}", align: center,
         budget: ABN_LINE, field: BUSINESS_ABN, when: BUSINESS_ABN}
      - {type: text, content: "Ph: {BUSINESS_PHONE}", align: center,
         budget: PHONE, when: BUSINESS_PHONE}
      - {type: spacer, height: 5}          # was line_h // 4
      - {type: rule, fill_char: "-"}
      - type: split
        children:
          - [{type: text, content: "Date: {INVOICE_DATE}", field: INVOICE_DATE}]
          - [{type: text, content: "Time: {POS_TIME}", align: right}]
      - type: split
        children:
          - [{type: text, content: "Reg: {POS_REGISTER}  Staff: {POS_STAFF}"}]
          - [{type: text, content: "#{RECEIPT_NUMBER}", align: right}]
      - {type: rule, fill_char: "-"}
      - type: table
        rows: receipt_line_items
        frame: plain
        grouping: none
        header: false
        params:
          fields: {description: LINE_ITEM_DESCRIPTIONS, quantity: LINE_ITEM_QUANTITIES,
                   price: LINE_ITEM_PRICES, total: LINE_ITEM_TOTAL_PRICES}
          quantity_prefix_format: "{quantity}x "
        columns:
          - {key: description, align: left, x: 0, budget: LINE_ITEM_DESC,
             field: LINE_ITEM_DESCRIPTIONS}
          - {key: total, align: right, x_right: 0, budget: LINE_ITEM_AMOUNT,
             currency: true, field: LINE_ITEM_TOTAL_PRICES}
      - {type: rule, fill_char: "-"}
      - {type: pair, label: "SUBTOTAL", value: "{SUBTOTAL_AMOUNT}",
         value_align: right, when: GST_AMOUNT}
      - {type: pair, label: "GST", value: "{GST_AMOUNT}", value_align: right,
         field: GST_AMOUNT, when: GST_AMOUNT}
      - {type: pair, label: "TOTAL", value: "{TOTAL_AMOUNT}", value_align: right,
         bold: true, field: TOTAL_AMOUNT}
```

Note the receipt `table` carries `header: false` — the legacy renderer draws no column
header row for line items (`receipt.py:259-296`), unlike every bank table.

- [ ] **Step 3: Run the snapshot for that one layout**

Run: `conda run -n synthetic pytest tests/test_receipt_pixel_snapshot.py -k thermal_80mm -v`
Expected: PASS. A hash mismatch with a matching size is a drawing difference; a size mismatch is a cursor-advance difference — check `line_advance` and the `spacer` heights first.

- [ ] **Step 4: Repeat Steps 2–3 for the remaining five layouts**

`receipt_thermal_57mm`, `receipt_retail_tax`, `receipt_fuel`, `receipt_professional`, `receipt_hospitality`. All six share a body; hoist it into a YAML anchor and let each layout override only `width`, `margin`, `line_advance`, `font_sizes`, `canvas_ceiling`, `field_budgets`, and the footer text. Commit after each layout goes green.

- [ ] **Step 5: Delete the legacy code**

From `receipt.py`: `_parse_line_items`, `_derive_receipt_number`, `_derive_receipt_details`, `_STAFF_NAMES`, and the whole section loop. From `payment_block.py`: `render_payment_block`. Keep `load_terminal_pools`, `method_from_bank_description`, `load_link_index`, `derive_payment`, and `PaymentDetails` — the field providers call all five.

`tests/test_receipt_fit.py` imports `_parse_line_items`; repoint it at the `receipt_line_items` provider.

- [ ] **Step 6: Full suite and commit**

```bash
conda run -n synthetic pytest tests/ && conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add config/layouts/receipts.yml generators/receipt.py generators/payment_block.py
git commit -m ":fire: replace the receipt renderer with declarative layouts"
```

---

## Task 15: Invoice bodies and adapter

**Files:**
- Modify: `config/layouts/invoices.yml` (all 4 layouts)
- Modify: `generators/invoice.py` (482 lines → ~60)
- Test: `tests/test_invoice_pixel_snapshot.py`, `tests/test_invoice_fit.py`, `tests/layout_dsl/test_defaults.py`

**Interfaces:**
- Consumes: everything from Tasks 0–12.
- Produces: `render_invoice(entry, layout, *, geometry_out=None) -> Image.Image` — unchanged signature.

Invoices are fixed-page, so the adapter is `bank_statement.py:39-76` almost verbatim. `_normalize_layout` (`invoice.py:47-73`) is deleted outright: it exists only to supply defaults for keys the YAML should state, and every one of its `.get(key, literal)` fallbacks is the pattern this plan removes.

- [ ] **Step 1: Write the adapter and delete `_normalize_layout`**

Flatten `page_dimensions` and `font_sizes` in the YAML instead of in Python. The layouts already declare both.

- [ ] **Step 2: Author `tax_invoice_standard`'s body**

The title becomes a `text` with `role: header`. Seller and buyer details become budgeted `text` blocks, with `"Bill To:"` written in the YAML and coloured `gray` explicitly. The metadata line becomes a `pair`. The table becomes a `table` on `pipe_fields` with `frame: filled`, `fill_color: "#F0F0F0"`, and the four columns at their current offsets — `x: 0`, `x: 900`, `x: 1050`, `x: 1550` relative to the region — with `header_text` values written in the YAML. The totals become a `split` with `widths: [1300, 400]`, the right child holding three `pair` blocks with `value_align: right`.

The `20` and `28`px trailing gaps become explicit `spacer` blocks.

- [ ] **Step 3: Run the snapshot for that one layout**

Run: `conda run -n synthetic pytest tests/test_invoice_pixel_snapshot.py -k tax_invoice_standard -v`
Expected: PASS.

- [ ] **Step 4: Author the remaining three**

- `tax_invoice_gst_inclusive` — the GST `pair` moves below the total and takes `min_gap: 24`, reproducing `invoice.py:283-296`.
- `tax_invoice_high_value` — adds the `delivery_details` label block.
- `tax_invoice_mixed` — two `label` texts and two tables over the same `LINE_ITEM_*` fields, the second carrying `capture: false`. Add a YAML comment recording that both tables intentionally render the identical list today, and that Phase B splits them for real.

Commit after each.

- [ ] **Step 5: Delete the legacy code**

The whole section loop, `_parse_line_items`, and `_normalize_layout`. Repoint `tests/test_invoice_fit.py`'s `_parse_line_items` import at `pipe_fields`.

- [ ] **Step 6: Widen the defaults-coverage test to all three layout files**

All three now carry `defaults:`. Add the widened test beside Task 3's bank-scoped one:

```python
# tests/layout_dsl/test_defaults.py
def test_all_layouts_cover_every_parameter_name():
    """The Task 3 version was scoped to bank_statements.yml because receipts and
    invoices had no defaults: yet. All three carry it now."""
    from pathlib import Path

    from generators.loader import load_layout_registry

    for name in ("bank_statements", "receipts", "invoices"):
        registry = load_layout_registry(Path(f"config/layouts/{name}.yml"))
        for layout_id, layout in registry.items():
            missing = PARAMETER_DEFAULTS - set(layout.get("defaults", {}))
            assert not missing, f"{name}.yml -> {layout_id} missing defaults: {sorted(missing)}"
```

Run: `conda run -n synthetic pytest tests/layout_dsl/test_defaults.py -v`
Expected: PASS, both the bank-scoped and widened tests.

- [ ] **Step 7: Full suite and commit**

```bash
conda run -n synthetic pytest tests/ && conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add config/layouts/invoices.yml generators/invoice.py
git commit -m ":fire: replace the invoice renderer with declarative layouts"
```

---

## Task 16: Dead-key sweep and final verification

**Files:**
- Modify: `config/layouts/receipts.yml`, `config/layouts/invoices.yml`
- Modify: `generators/layout_dsl/schema.py` (unknown top-level layout key rejection)
- Test: `tests/test_layout_assignment.py`, all snapshots

**Interfaces:**
- Consumes: everything.
- Produces: `known_layout_keys(layout: dict) -> frozenset[str]` in `schema.py`; layout files carrying only keys the engine reads.

- [ ] **Step 1: Write the failing test**

```python
def test_layout_carries_no_key_the_engine_never_reads():
    """The invoice YAML shipped six-column table specs, table_start_y, and per-
    section font sizes that no code path read. A layout key that does nothing is
    worse than no key: it tells an operator the document is configured a way it
    is not."""
    from generators.layout_dsl.schema import known_layout_keys
    from generators.loader import load_layout_registry
    from pathlib import Path

    for name in ("bank_statements", "receipts", "invoices"):
        registry = load_layout_registry(Path(f"config/layouts/{name}.yml"))
        for layout_id, layout in registry.items():
            unknown = set(layout) - known_layout_keys(layout)
            assert not unknown, f"{name}.yml -> {layout_id} carries unread keys: {sorted(unknown)}"
```

- [ ] **Step 2: Run and confirm failure**

Run: `conda run -n synthetic pytest tests/test_layout_assignment.py -k unread -v`
Expected: FAIL — `minimum_amount`, `mixed_tax_mode`, `format`, and any leftover `sections` are reported.

- [ ] **Step 3: Define `KNOWN_LAYOUT_KEYS` and enforce it in `validate_layout`**

Build the set from two sources rather than hand-listing it, so it cannot drift:

```python
# generators/layout_dsl/schema.py
# Keys every layout may carry, read by the engine or the page adapters.
_ENGINE_LAYOUT_KEYS = frozenset({
    "defaults", "body", "field_providers", "field_budgets", "font_sizes",
    "margin", "content_width", "page_dimensions", "width", "canvas_ceiling",
})


def known_layout_keys(layout: dict) -> frozenset[str]:
    """Return the keys this layout is permitted to carry.

    `from_layout` lets a text or banner block name an arbitrary layout key as
    its content (`primitives_text.py:100`), so the permitted set is not fixed:
    it is the engine's own keys plus whatever this layout's body actually
    references. Hand-listing them would drift the moment a layout adds one.
    """
    return _ENGINE_LAYOUT_KEYS | _from_layout_targets(layout.get("body", []))
```

`_from_layout_targets` walks the body (recursing into `panel` and `split` children) and collects every `from_layout` value. Reject any remaining unknown key with a four-element diagnostic naming it, the layout, and the file.

- [ ] **Step 4: Delete the dead keys**

From `invoices.yml`: `columns:` with its `header_text`/`width`/`font_size` sub-keys, `table_start_y`, `row_height`, the `fields:` name lists, per-section `height`/`font_size`/`alignment`/`font_weight`, `minimum_amount`, `mixed_tax_mode`, `format`, `font_family`. From `receipts.yml`: `format`, `font_family` (superseded by `defaults.mono`), `line_height` (superseded by `defaults.line_advance`), `font_size` (superseded by `font_sizes`), and the section `name:` values that were never read.

- [ ] **Step 5: Full verification**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic python -m generators.pipeline generate --clean-only
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py && conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```

Expected: all tests pass, validate reports no errors, and generation completes for all three document types.

- [ ] **Step 6: Commit**

```bash
git add config/layouts/ generators/layout_dsl/schema.py
git commit -m ":fire: delete layout keys no code path reads"
```

---

## Out of scope for this plan

**Phase B** — the six-column invoice table, rendered payment terms and delivery details, the genuine taxable / GST-free split, and distinct per-format receipt headers. It is YAML-only by construction and re-baselines both document types, so it gets its own plan once Phase A is merged and the parity gate has proven the migration.

**Stage 4** — corpus narrowing to three document types, transaction-linking removal, and the re-export of `/Users/tod/Desktop/evaluation_data/synthetic_20260731/`.
