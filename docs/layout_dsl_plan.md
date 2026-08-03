# Declarative Layout DSL — Implementation Plan (Stages 1–2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a declarative layout engine driven by eight structural primitives, and prove it by re-expressing all 8 bank-statement layouts in YAML with the four hardcoded per-bank Python renderers deleted.

**Architecture:** YAML owns arrangement; Python owns drawing and computation. A walker reads a layout's `body:` list, dispatches each block to a primitive drawer, and threads a y-cursor plus a `Region` (left edge + available width) so containers can nest. Table data that must be computed — running balances, opening rows — comes from named **row providers** registered in Python, so no arithmetic ever appears in YAML. Every existing mechanism (`fit_text`, `field_budget`, `BoxRecorder`) is called by the engine at the same points the renderers call it today.

**Tech Stack:** Python 3.12, Pillow 12.2.0 (pinned — FreeType metrics drive every fit decision), PyYAML, pytest. No new runtime dependencies.

**Source spec:** `docs/layout_dsl_design.md`

## Global Constraints

- Conda env `synthetic`. Run tooling as `conda run -n synthetic <command>`.
- Python 3.12 typing: `X | Y`, not `Union[X, Y]`. No `from __future__ import annotations`.
- **Never** use `TYPE_CHECKING` guards for types used in runtime signatures.
- Max line length 108.
- All file paths via `pathlib.Path`.
- Google-style docstrings on every public function and class.
- Every fail-fast diagnostic carries all four elements: **What** is wrong, **Where** to fix it (absolute path + dotted key path), **What it should look like** (concrete YAML example + allowed values), **How to recover** (one-line remediation).
- Tests for fail-fast paths assert all four elements using `assert_diagnostic_error` from `tests/conftest.py`.
- In `except` blocks always `raise ... from err` or `from None` (B904).
- YAML is the single source of truth. No Python-side defaults shadowing config. Missing key = fail fast.
- `tests/` is gitignored — local only, never committed. Commit source and config only.
- Pre-commit gates, all four must pass: `conda run -n synthetic pytest tests/`, `ruff check --fix --ignore ARG001,ARG002,F841 *.py`, `ruff format .`, `mypy . --ignore-missing-imports`. **Never** use `--no-verify`.
- Commit messages use gitmoji. **No Claude attribution, ever.**
- Import the shared test helper as `from conftest import assert_diagnostic_error` — bare, not `from tests.conftest import ...`. This is the repo's existing convention and works from test subdirectories (see `tests/exporters/test_config.py:8`).
- A `.git/hooks/pre-commit` hook runs `ruff check --fix` on staged Python files. Never bypass it.
- Never write the term "ATO" anywhere. Use "PROD".
- Branch: `feat/declarative-layouts`.

**Known pre-existing mypy failures** (not introduced by this work, do not fix here): 8 `call-overload` errors in `degrade_camera_scan.py`, 2 `return-value` errors in `tests/test_fitted_helpers.py` and `tests/test_fit_text.py`. mypy is green for the purposes of this plan if the count stays at 10 and none are in `generators/layout_dsl/`.

---

## File Structure

**New package — `generators/layout_dsl/`**

| File | Responsibility |
|---|---|
| `__init__.py` | Public API re-exports: `render_body`, `render_blocks`, `validate_body`, `validate_layout`, `row_provider`, `RenderContext`, `Region` |
| `context.py` | `Region` (horizontal geometry, nesting arithmetic) and `RenderContext` (draw surface, entry, layout, recorder) |
| `binding.py` | `{FIELD}` interpolation, field-reference extraction, `when:` presence tests |
| `providers.py` | Row-provider registry plus the two shipped providers |
| `schema.py` | Primitive schema validation with four-element diagnostics |
| `primitives_text.py` | `text`, `pair`, `block`, `rule`, `spacer` |
| `primitives_container.py` | `panel`, `split` |
| `primitives_table.py` | `table` and the four row styles |
| `engine.py` | The walker: dispatch table and `render_body` |

**Modified**

| File | Change |
|---|---|
| `config/layouts/bank_statements.yml` | Rewritten: YAML anchors for reuse, `body:` trees replacing `renderer`/`variant`/`show_*` flags |
| `generators/bank_statement.py` | Four per-bank renderers deleted; becomes a thin adapter over the engine |
| `generators/pipeline.py` | `validate` gains DSL validation |

**Tests (local only, mirror source)** — `tests/layout_dsl/test_context.py`, `test_binding.py`, `test_providers.py`, `test_schema.py`, `test_primitives_text.py`, `test_primitives_container.py`, `test_primitives_table.py`, `test_engine.py`, plus `tests/test_bank_dsl_equivalence.py`.

---

# STAGE 1 — Engine and schema

Nothing in the pipeline calls the engine during Stage 1. Fully revertible.

---

### Task 1: Region and RenderContext

**Files:**
- Create: `generators/layout_dsl/__init__.py`, `generators/layout_dsl/context.py`
- Test: `tests/layout_dsl/test_context.py`

**Interfaces:**
- Consumes: `BoxRecorder` from `generators.exporters.geometry`.
- Produces: `Region(x: int, width: int)` with `.right`, `.indent(left: int, right: int = 0) -> Region` and `.divide(n: int, gap: int) -> list[Region]`; `RenderContext` dataclass with fields `draw`, `entry`, `layout`, `layout_id`, `layout_path`, `region`, `recorder`, `render_children`, and a `.within(region) -> RenderContext` method. Every primitive has signature `(block: dict, ctx: RenderContext, y: int) -> int` returning the advanced y.

`render_children` is the walker, injected by the engine at render time. It exists so `panel` and `split` can render nested blocks without importing the engine — the engine's dispatch table imports *them*, so a direct import would be circular. Injection keeps the containers independently unit-testable with a stub.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_context.py
import pytest

from generators.layout_dsl.context import Region


def test_indent_narrows_and_shifts():
    region = Region(x=100, width=1600)
    inner = region.indent(20)
    assert inner.x == 120
    assert inner.width == 1580


def test_indent_applies_right_inset():
    inner = Region(x=100, width=1600).indent(20, 30)
    assert inner.x == 120
    assert inner.width == 1550


def test_divide_splits_evenly_with_gap():
    left, right = Region(x=100, width=1000).divide(2, gap=40)
    assert left.x == 100
    assert left.width == 480
    assert right.x == 620
    assert right.width == 480


def test_divide_rejects_gap_wider_than_region():
    with pytest.raises(ValueError, match="gap"):
        Region(x=0, width=50).divide(2, gap=100)


def test_right_edge():
    assert Region(x=100, width=1600).right == 1700
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.layout_dsl'`

- [ ] **Step 3: Write minimal implementation**

```python
# generators/layout_dsl/__init__.py
"""Declarative layout DSL — YAML owns arrangement, Python owns drawing."""
```

```python
# generators/layout_dsl/context.py
"""Horizontal geometry and per-render state for the layout engine.

`Region` is the only place nesting arithmetic lives: a container narrows or
divides its own region and hands the result to its children, so no primitive
needs to know how deeply it is nested.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PIL import ImageDraw

from generators.exporters.geometry import BoxRecorder


@dataclass(frozen=True)
class Region:
    """A horizontal slice of the page available to a block.

    Attributes:
        x: Absolute left edge in pixels.
        width: Usable content width in pixels.
    """

    x: int
    width: int

    @property
    def right(self) -> int:
        """Absolute right edge in pixels."""
        return self.x + self.width

    def indent(self, left: int, right: int = 0) -> "Region":
        """Return a narrowed region inset from this one.

        Args:
            left: Pixels to inset from the left edge.
            right: Pixels to inset from the right edge.

        Returns:
            A new Region shifted right by `left` and narrowed by `left + right`.

        Raises:
            ValueError: If the insets consume the whole region.
        """
        width = self.width - left - right
        if width < 1:
            msg = (
                f"Region.indent({left}, {right}) leaves width {width} from {self.width}. "
                f"Remediation: reduce the container's padding."
            )
            raise ValueError(msg)
        return Region(x=self.x + left, width=width)

    def divide(self, n: int, gap: int) -> list["Region"]:
        """Split this region into `n` equal columns separated by `gap` px.

        Args:
            n: Number of columns; must be at least 1.
            gap: Pixels between adjacent columns.

        Returns:
            `n` Regions, left to right.

        Raises:
            ValueError: If `n` < 1, or the gaps leave no usable column width.
        """
        if n < 1:
            msg = f"Region.divide needs n >= 1, got {n}. Remediation: pass a positive column count."
            raise ValueError(msg)
        total_gap = gap * (n - 1)
        column = (self.width - total_gap) // n
        if column < 1:
            msg = (
                f"Region.divide({n}, gap={gap}) leaves column width {column} "
                f"from {self.width}. Remediation: reduce the gap or the column count."
            )
            raise ValueError(msg)
        return [Region(x=self.x + i * (column + gap), width=column) for i in range(n)]


@dataclass
class RenderContext:
    """Everything a primitive needs besides its own block dict and the y-cursor.

    Attributes:
        draw: The PIL drawing surface.
        entry: The ground-truth entry being rendered.
        layout: The resolved layout dict.
        layout_id: Layout id, used in diagnostics.
        layout_path: Path to the layout YAML, used in diagnostics.
        region: The horizontal slice this block may draw into.
        recorder: Optional draw-time bounding-box capture.
        render_children: The walker, injected by the engine so containers can
            render nested blocks without importing the engine — which would be
            a circular import, since the engine's dispatch table imports them.
    """

    draw: ImageDraw.ImageDraw
    entry: dict
    layout: dict
    layout_id: str
    layout_path: str
    region: Region
    recorder: BoxRecorder | None = None
    render_children: "Callable[[list, RenderContext, int], int] | None" = None

    def within(self, region: Region) -> "RenderContext":
        """Return a copy of this context scoped to a different region.

        Args:
            region: The child region.

        Returns:
            A new RenderContext sharing all state but the region.
        """
        return RenderContext(
            draw=self.draw,
            entry=self.entry,
            layout=self.layout,
            layout_id=self.layout_id,
            layout_path=self.layout_path,
            region=region,
            recorder=self.recorder,
            render_children=self.render_children,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_context.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add generators/layout_dsl/__init__.py generators/layout_dsl/context.py
git commit -m ":sparkles: add layout DSL region and render context"
```

---

### Task 2: Field binding

**Files:**
- Create: `generators/layout_dsl/binding.py`
- Test: `tests/layout_dsl/test_binding.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `referenced_fields(template: str) -> list[str]`, `interpolate(template: str, fields: dict) -> str`, `is_present(fields: dict, field: str) -> bool`, and `BindingError(RuntimeError)`.

Binding is deliberately minimal: `{FIELD}` substitution and presence tests, nothing else. `referenced_fields` exists so validation can check every reference statically, before anything renders.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_binding.py
import pytest

from generators.layout_dsl.binding import BindingError, interpolate, is_present, referenced_fields


def test_referenced_fields_finds_all_placeholders():
    assert referenced_fields("From {SUPPLIER_NAME} to {PAYER_NAME}") == [
        "SUPPLIER_NAME",
        "PAYER_NAME",
    ]


def test_referenced_fields_ignores_lowercase_braces():
    assert referenced_fields("literal {not_a_field} text") == []


def test_referenced_fields_on_literal_returns_empty():
    assert referenced_fields("Tax Invoice") == []


def test_interpolate_substitutes_values():
    fields = {"PAYER_NAME": "Robin Wood"}
    assert interpolate("Account Holder: {PAYER_NAME}", fields) == "Account Holder: Robin Wood"


def test_interpolate_raises_on_unknown_field():
    with pytest.raises(BindingError) as exc_info:
        interpolate("{NOPE}", {"PAYER_NAME": "Robin Wood"})
    message = str(exc_info.value)
    assert "NOPE" in message
    assert "Remediation:" in message


def test_interpolate_renders_not_found_as_empty():
    assert interpolate("Balance: {ACCOUNT_BALANCE}", {"ACCOUNT_BALANCE": "NOT_FOUND"}) == "Balance: "


def test_is_present_false_for_missing_blank_and_not_found():
    assert is_present({}, "X") is False
    assert is_present({"X": ""}, "X") is False
    assert is_present({"X": "NOT_FOUND"}, "X") is False


def test_is_present_true_for_real_value():
    assert is_present({"X": "01/07/2024 - 29/07/2024"}, "X") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_binding.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.layout_dsl.binding'`

- [ ] **Step 3: Write minimal implementation**

```python
# generators/layout_dsl/binding.py
"""Field binding for the layout DSL.

Deliberately minimal: `{FIELD}` substitution and presence tests, nothing else.
No expressions, no arithmetic, no filters — everything a layout references must
be statically checkable before a single pixel is drawn.
"""

import re

_PLACEHOLDER = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")

_ABSENT = "NOT_FOUND"


class BindingError(RuntimeError):
    """Raised when a layout references a field the entry does not carry."""


def referenced_fields(template: str) -> list[str]:
    """Return every field name referenced by a template string, in order.

    Args:
        template: A string that may contain `{FIELD}` placeholders.

    Returns:
        Field names, in order of first appearance, without duplicates removed.
    """
    return _PLACEHOLDER.findall(template)


def interpolate(template: str, fields: dict) -> str:
    """Substitute `{FIELD}` placeholders with the entry's values.

    A field whose value is the corpus-wide `NOT_FOUND` sentinel renders as the
    empty string, matching how the existing renderers suppress absent values.

    Args:
        template: String containing zero or more `{FIELD}` placeholders.
        fields: The entry's `fields` mapping.

    Returns:
        The template with every placeholder replaced.

    Raises:
        BindingError: If a referenced field is absent from `fields`.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in fields:
            msg = (
                f"Layout references unknown field '{name}'.\n"
                f"  Template: {template!r}\n"
                f"  Available: {sorted(fields)}\n"
                f"  Remediation: fix the field name in the layout, or add "
                f"'{name}' to the entry in ground_truth/."
            )
            raise BindingError(msg)
        value = str(fields[name])
        return "" if value == _ABSENT else value

    return _PLACEHOLDER.sub(replace, template)


def is_present(fields: dict, field: str) -> bool:
    """Report whether a field carries a real value.

    Args:
        fields: The entry's `fields` mapping.
        field: The field name to test.

    Returns:
        False if the field is missing, empty, or the `NOT_FOUND` sentinel.
    """
    value = fields.get(field)
    return value is not None and str(value) not in ("", _ABSENT)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_binding.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add generators/layout_dsl/binding.py
git commit -m ":sparkles: add layout DSL field binding"
```

---

### Task 3: Row-provider registry and `pipe_fields`

**Files:**
- Create: `generators/layout_dsl/providers.py`
- Test: `tests/layout_dsl/test_providers.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `row_provider(name: str)` decorator, `get_provider(name: str) -> RowProvider`, `provider_names() -> list[str]`, `ProviderError(RuntimeError)`. A `RowProvider` has signature `(entry: dict, params: dict) -> list[dict]`. The `pipe_fields` provider is registered here.

`pipe_fields` is what lets a future document type build tables with **no Python**: it zips pipe-delimited list fields into row dicts.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_providers.py
import pytest

from generators.layout_dsl.providers import ProviderError, get_provider, provider_names, row_provider


def test_pipe_fields_zips_list_fields_into_rows():
    entry = {
        "fields": {
            "LINE_ITEM_DESCRIPTIONS": "Coffee|Muffin|Juice",
            "LINE_ITEM_TOTAL_PRICES": "4.50|6.00|5.25",
        }
    }
    provider = get_provider("pipe_fields")
    rows = provider(entry, {"fields": {"desc": "LINE_ITEM_DESCRIPTIONS", "amount": "LINE_ITEM_TOTAL_PRICES"}})
    assert rows == [
        {"desc": "Coffee", "amount": "4.50"},
        {"desc": "Muffin", "amount": "6.00"},
        {"desc": "Juice", "amount": "5.25"},
    ]


def test_pipe_fields_rejects_ragged_lists():
    entry = {"fields": {"A": "1|2|3", "B": "1|2"}}
    provider = get_provider("pipe_fields")
    with pytest.raises(ProviderError) as exc_info:
        provider(entry, {"fields": {"a": "A", "b": "B"}})
    message = str(exc_info.value)
    assert "3" in message and "2" in message
    assert "Remediation:" in message


def test_get_provider_rejects_unknown_name_and_lists_known():
    with pytest.raises(ProviderError) as exc_info:
        get_provider("no_such_provider")
    message = str(exc_info.value)
    assert "no_such_provider" in message
    assert "pipe_fields" in message
    assert "Remediation:" in message


def test_provider_names_includes_registered():
    assert "pipe_fields" in provider_names()


def test_row_provider_rejects_duplicate_registration():
    with pytest.raises(ProviderError, match="already registered"):

        @row_provider("pipe_fields")
        def _duplicate(entry: dict, params: dict) -> list[dict]:
            return []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.layout_dsl.providers'`

- [ ] **Step 3: Write minimal implementation**

```python
# generators/layout_dsl/providers.py
"""Row providers — the DSL's one sanctioned escape hatch.

Some table data is computed rather than stored: a bank statement's running
balance and opening row exist nowhere in ground truth. Rather than put
arithmetic in YAML, a table names a provider registered here, and the provider
returns row dicts. Providers return data only — they never draw or position.
"""

from collections.abc import Callable

RowProvider = Callable[[dict, dict], list[dict]]

_REGISTRY: dict[str, RowProvider] = {}


class ProviderError(RuntimeError):
    """Raised when a provider is unknown, duplicated, or given bad input."""


def row_provider(name: str) -> Callable[[RowProvider], RowProvider]:
    """Register a row provider under `name`.

    Args:
        name: The name layouts use in a table's `rows:` key.

    Returns:
        A decorator that registers and returns the function unchanged.

    Raises:
        ProviderError: If `name` is already registered.
    """

    def decorate(func: RowProvider) -> RowProvider:
        if name in _REGISTRY:
            msg = (
                f"Row provider '{name}' is already registered.\n"
                f"  Remediation: pick a distinct provider name."
            )
            raise ProviderError(msg)
        _REGISTRY[name] = func
        return func

    return decorate


def get_provider(name: str) -> RowProvider:
    """Look up a registered row provider.

    Args:
        name: Provider name from a table's `rows:` key.

    Returns:
        The registered provider.

    Raises:
        ProviderError: If no provider is registered under `name`.
    """
    if name not in _REGISTRY:
        msg = (
            f"Unknown row provider.\n"
            f"  What:     no provider named '{name}' is registered.\n"
            f"  Where:    a table block's 'rows:' key.\n"
            f"  Expected: one of {sorted(_REGISTRY)}.\n"
            f"  Recover:  set rows: to a registered provider, or register a new "
            f"one with @row_provider in generators/layout_dsl/providers.py."
        )
        raise ProviderError(msg)
    return _REGISTRY[name]


def provider_names() -> list[str]:
    """Return the names of all registered providers, sorted."""
    return sorted(_REGISTRY)


@row_provider("pipe_fields")
def pipe_fields(entry: dict, params: dict) -> list[dict]:
    """Zip pipe-delimited list fields into row dicts.

    Lets a document type build a table from plain list fields with no Python.

    Args:
        entry: The ground-truth entry.
        params: Must carry `fields`, a mapping of row key to source field name.

    Returns:
        One dict per row, keyed by the `fields` mapping's keys.

    Raises:
        ProviderError: If `fields` is missing or the source lists differ in length.
    """
    mapping = params.get("fields")
    if not isinstance(mapping, dict) or not mapping:
        msg = (
            f"pipe_fields provider needs a 'fields' mapping.\n"
            f"  Expected: fields: {{row_key: SOURCE_FIELD, ...}}\n"
            f"  Remediation: add a fields: mapping under the table's params:."
        )
        raise ProviderError(msg)

    entry_fields = entry["fields"]
    columns: dict[str, list[str]] = {}
    for key, source in mapping.items():
        raw = str(entry_fields.get(source, ""))
        columns[key] = [part.strip() for part in raw.split("|")] if raw else []

    lengths = {key: len(values) for key, values in columns.items()}
    if len(set(lengths.values())) > 1:
        msg = (
            f"pipe_fields source lists differ in length: {lengths}.\n"
            f"  Remediation: every pipe-delimited field in one table must have "
            f"the same number of entries; fix the entry in ground_truth/."
        )
        raise ProviderError(msg)

    count = next(iter(lengths.values()), 0)
    return [{key: columns[key][i] for key in columns} for i in range(count)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_providers.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add generators/layout_dsl/providers.py
git commit -m ":sparkles: add row provider registry and pipe_fields provider"
```

---

### Task 4: `bank_transactions` provider

**Files:**
- Modify: `generators/layout_dsl/providers.py`
- Test: `tests/layout_dsl/test_providers.py` (append)

**Interfaces:**
- Consumes: `row_provider`, `ProviderError` from Task 3.
- Produces: a provider registered as `bank_transactions` emitting rows keyed `date`, `description`, `debit`, `credit`, `balance`, plus optional synthetic opening / brought-forward rows carrying `synthetic: True`.

This replicates `_parse_transactions` (`generators/bank_statement.py:80`) and `_compute_running_balances` (`:99`) exactly, and the opening-row arithmetic at `:221-229`. Balances are computed backwards from `ACCOUNT_BALANCE` using `Decimal`.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_providers.py  (append)
from decimal import Decimal


def _bank_entry() -> dict:
    return {
        "fields": {
            "TRANSACTION_DATES": "01/07/2024|02/07/2024",
            "TRANSACTION_DESCRIPTIONS": "ATM WITHDRAWAL|SALARY",
            "TRANSACTION_AMOUNTS_PAID": "100.00|NOT_FOUND",
            "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|500.00",
            "ACCOUNT_BALANCE": "1400.00",
        }
    }


def test_bank_transactions_computes_running_balances_backwards():
    rows = get_provider("bank_transactions")(_bank_entry(), {})
    assert [r["date"] for r in rows] == ["01/07/2024", "02/07/2024"]
    # Closing 1400.00; reversing the last row (credit 500) gives 900.00 for row 0.
    assert rows[0]["balance"] == Decimal("900.00")
    assert rows[1]["balance"] == Decimal("1400.00")


def test_bank_transactions_matches_legacy_helpers():
    from generators.bank_statement import _compute_running_balances, _parse_transactions

    entry = _bank_entry()
    legacy = _compute_running_balances(_parse_transactions(entry["fields"]), "1400.00")
    rows = get_provider("bank_transactions")(entry, {})
    assert [r["balance"] for r in rows] == [t["balance"] for t in legacy]
    assert [r["description"] for r in rows] == [t["description"] for t in legacy]


def test_bank_transactions_prepends_opening_row_when_requested():
    rows = get_provider("bank_transactions")(_bank_entry(), {"opening_balance": True})
    assert rows[0]["synthetic"] is True
    assert rows[0]["description"] == "Opening Balance"
    # Opening = first row balance - its credit + its debit = 900 - 0 + 100.
    assert rows[0]["balance"] == Decimal("1000.00")
    assert rows[0]["debit"] == "NOT_FOUND"
    assert len(rows) == 3


def test_bank_transactions_brought_forward_uses_its_own_label():
    rows = get_provider("bank_transactions")(_bank_entry(), {"brought_forward": True})
    assert rows[0]["description"] == "Balance Brought Forward"
    assert rows[0]["synthetic"] is True


def test_bank_transactions_rejects_both_synthetic_rows():
    with pytest.raises(ProviderError, match="mutually exclusive"):
        get_provider("bank_transactions")(_bank_entry(), {"opening_balance": True, "brought_forward": True})


def test_bank_transactions_without_synthetic_row_marks_all_real():
    rows = get_provider("bank_transactions")(_bank_entry(), {})
    assert all(row["synthetic"] is False for row in rows)


def test_malformed_amount_fails_loudly_rather_than_becoming_zero():
    entry = _bank_entry()
    entry["fields"]["TRANSACTION_AMOUNTS_PAID"] = "12.3.4|NOT_FOUND"
    with pytest.raises(ProviderError) as exc_info:
        get_provider("bank_transactions")(entry, {})
    message = str(exc_info.value)
    assert "12.3.4" in message
    assert "Remediation:" in message


def test_absent_value_sentinels_still_read_as_zero():
    from generators.layout_dsl.providers import _to_decimal

    assert _to_decimal("") == Decimal("0")
    assert _to_decimal("NOT_FOUND") == Decimal("0")
    assert _to_decimal("137.73") == Decimal("137.73")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_providers.py -k bank_transactions -v`
Expected: FAIL — `ProviderError: Unknown row provider ... 'bank_transactions'`

- [ ] **Step 3: Write minimal implementation**

Add to `generators/layout_dsl/providers.py` (and add `from decimal import Decimal` to its imports):

```python
_SYNTHETIC_LABELS = {"opening_balance": "Opening Balance", "brought_forward": "Balance Brought Forward"}


@row_provider("bank_transactions")
def bank_transactions(entry: dict, params: dict) -> list[dict]:
    """Build bank statement rows with running balances computed backwards.

    Mirrors the legacy `_parse_transactions` / `_compute_running_balances`
    helpers: balances are derived from ACCOUNT_BALANCE (the closing balance) by
    walking the transactions in reverse.

    Args:
        entry: The ground-truth entry.
        params: Optional `opening_balance` or `brought_forward` booleans, which
            prepend a synthetic balance row. They are mutually exclusive.

    Returns:
        One dict per row with keys `date`, `description`, `debit`, `credit`,
        `balance` (Decimal), and `synthetic` (bool).

    Raises:
        ProviderError: If both synthetic-row options are requested, or the
            transaction lists are ragged.
    """
    wants = [key for key in _SYNTHETIC_LABELS if params.get(key)]
    if len(wants) > 1:
        msg = (
            f"opening_balance and brought_forward are mutually exclusive; both were set.\n"
            f"  Remediation: keep exactly one synthetic balance row on the table block."
        )
        raise ProviderError(msg)

    rows = pipe_fields(
        entry,
        {
            "fields": {
                "date": "TRANSACTION_DATES",
                "description": "TRANSACTION_DESCRIPTIONS",
                "debit": "TRANSACTION_AMOUNTS_PAID",
                "credit": "TRANSACTION_AMOUNTS_RECEIVED",
            }
        },
    )

    balance = _to_decimal(entry["fields"].get("ACCOUNT_BALANCE", "0"))
    for row in reversed(rows):
        row["balance"] = balance
        row["synthetic"] = False
        balance = balance + _to_decimal(row["debit"]) - _to_decimal(row["credit"])
        # Coerce real amounts to Decimal so the table primitive formats them as currency
        # ("$100.00"), matching the legacy renderer. Leave the absent sentinel a string:
        # legacy draws nothing for it and _cell_text maps it to the empty string.
        for key in ("debit", "credit"):
            if row[key] != "NOT_FOUND":
                row[key] = _to_decimal(row[key])

    if wants and rows:
        first = rows[0]
        opening = first["balance"] - _to_decimal(first["credit"]) + _to_decimal(first["debit"])
        rows.insert(
            0,
            {
                "date": "",
                "description": _SYNTHETIC_LABELS[wants[0]],
                "debit": "NOT_FOUND",
                "credit": "NOT_FOUND",
                "balance": opening,
                "synthetic": True,
            },
        )
    return rows


def _to_decimal(value: str) -> Decimal:
    """Parse an amount, treating only the absent-value sentinels as zero.

    A malformed amount is a ground-truth defect and must fail loudly: coercing
    it to zero would corrupt every running balance below it and emit a
    plausible-looking but wrong statement.

    Args:
        value: An amount string from ground truth.

    Returns:
        The parsed Decimal, or Decimal("0") for the absent-value sentinels.

    Raises:
        ProviderError: If the value is neither a sentinel nor a valid amount.
    """
    if value in ("", "NOT_FOUND"):
        return Decimal("0")
    try:
        return Decimal(value)
    except ArithmeticError as err:
        msg = (
            f"Malformed amount {value!r} in a bank transaction.\n"
            f"  Remediation: fix the amount in ground_truth/bank_statements.yml; "
            f"amounts are decimal strings without a currency sign, e.g. '137.73'."
        )
        raise ProviderError(msg) from err
```

**Ruling (supersedes the original plan text):** an earlier draft of this task caught
`ArithmeticError` and returned `Decimal("0")`. Because `decimal.InvalidOperation` is an
`ArithmeticError`, that silently coerced malformed amounts to zero — corrupting every
balance below them — which contradicts CLAUDE.md's "NEVER use silent fallbacks" rule.
The legacy `_compute_running_balances` raised `InvalidOperation` on the same input, so
the silent version was also *quieter* than the code it replaces. Fail-fast governs.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_providers.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add generators/layout_dsl/providers.py
git commit -m ":sparkles: add bank_transactions row provider"
```

---

### Task 5: Primitive schema validation

**Files:**
- Create: `generators/layout_dsl/schema.py`
- Test: `tests/layout_dsl/test_schema.py`

**Interfaces:**
- Consumes: `referenced_fields` (Task 2), `provider_names` (Task 3).
- Produces: `LayoutSchemaError(RuntimeError)`, `validate_body(body: list, *, layout_id: str, layout_path: str, known_fields: set[str]) -> None`, and `validate_layout(layout: dict, *, layout_id: str, layout_path: str, known_fields: set[str]) -> None`.

This is the startup gate, implementing all five of the spec's new validation checks. `validate_body` walks the `body:` tree — unknown primitives, missing keys, unknown field references, unregistered providers. `validate_layout` wraps it and adds the two checks that need the surrounding layout: **column geometry versus declared budget width** (spec check 4, which closes the silent-drift hole where `TRANSACTION_DESC` widths are hand-computed to match column positions) and **nested children fitting their parent** (spec check 5). Each failure carries a four-element diagnostic.

Budget widths are validated, never derived — operator intent stays visible in the YAML, per CLAUDE.md.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_schema.py
import pytest

from generators.layout_dsl.schema import LayoutSchemaError, validate_body
from conftest import assert_diagnostic_error

FIELDS = {"PAYER_NAME", "SUPPLIER_NAME", "STATEMENT_DATE_RANGE"}


def _validate(body: list) -> None:
    validate_body(
        body,
        layout_id="cba_standard",
        layout_path="config/layouts/bank_statements.yml",
        known_fields=FIELDS,
    )


def test_accepts_a_minimal_valid_body():
    _validate([{"type": "text", "content": "{PAYER_NAME}"}, {"type": "rule"}])


def test_rejects_unknown_primitive_and_lists_allowed():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "hologram"}])
    message = str(exc_info.value)
    assert "hologram" in message
    assert "text" in message and "table" in message
    assert_diagnostic_error(message)


def test_rejects_block_without_type():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"content": "hi"}])
    assert_diagnostic_error(str(exc_info.value))


def test_rejects_missing_required_key():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "text"}])
    message = str(exc_info.value)
    assert "content" in message
    assert_diagnostic_error(message)


def test_rejects_unknown_field_reference():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "text", "content": "{NOT_A_FIELD}"}])
    message = str(exc_info.value)
    assert "NOT_A_FIELD" in message
    assert_diagnostic_error(message)


def test_rejects_unknown_when_field():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "rule", "when": "MYSTERY"}])
    assert "MYSTERY" in str(exc_info.value)


def test_rejects_unregistered_row_provider():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "table", "rows": "nope", "columns": [{"key": "a", "label": "A"}]}])
    message = str(exc_info.value)
    assert "nope" in message and "pipe_fields" in message
    assert_diagnostic_error(message)


def test_recurses_into_containers():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "panel", "children": [{"type": "text", "content": "{BAD}"}]}])
    message = str(exc_info.value)
    assert "BAD" in message
    assert "children[0]" in message


def test_recurses_into_split_columns():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(
            [{"type": "split", "children": [[{"type": "rule"}], [{"type": "text", "content": "{BAD}"}]]}]
        )
    assert "BAD" in str(exc_info.value)


def test_rejects_table_column_without_key():
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate([{"type": "table", "rows": "pipe_fields", "columns": [{"label": "A"}]}])
    assert_diagnostic_error(str(exc_info.value))


def test_rejects_unknown_row_style():
    body = [
        {
            "type": "table",
            "rows": "pipe_fields",
            "row_style": "sparkly",
            "columns": [{"key": "a", "label": "A"}],
        }
    ]
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate(body)
    message = str(exc_info.value)
    assert "sparkly" in message and "ruled" in message


# --- validate_layout: spec checks 4 and 5 ---

BUDGETED_LAYOUT = {
    "content_width": 1600,
    "field_budgets": {"DESC": {"width": 760, "fit": "wrap", "min_font": 10, "max_lines": 2}},
    "body": [
        {
            "type": "table",
            "rows": "pipe_fields",
            "columns": [
                {"key": "description", "label": "Description", "align": "left", "x": 200,
                 "budget": "DESC"},
                {"key": "debit", "label": "Debit", "align": "right", "x_right": -420},
            ],
        }
    ],
}


def _validate_layout(layout: dict) -> None:
    validate_layout(
        layout,
        layout_id="cba_standard",
        layout_path="config/layouts/bank_statements.yml",
        known_fields=FIELDS,
    )


def test_column_budget_matching_its_geometry_is_accepted():
    # Column spans x=200 to the next column's left edge at 1600-420=1180, so 980px
    # is available; the declared 760 fits within it.
    _validate_layout(BUDGETED_LAYOUT)


def test_column_budget_wider_than_its_geometry_is_rejected():
    layout = deepcopy(BUDGETED_LAYOUT)
    layout["field_budgets"]["DESC"]["width"] = 1400
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    message = str(exc_info.value)
    assert "1400" in message and "980" in message
    assert_diagnostic_error(message)


def test_column_naming_a_missing_budget_is_rejected():
    layout = deepcopy(BUDGETED_LAYOUT)
    layout["field_budgets"] = {}
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert "DESC" in str(exc_info.value)


def test_panel_padding_wider_than_the_page_is_rejected():
    layout = {
        "content_width": 100,
        "field_budgets": {},
        "body": [{"type": "panel", "padding": 80, "children": [{"type": "rule"}]}],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert_diagnostic_error(str(exc_info.value))


def test_validate_layout_reports_a_missing_key_diagnostically():
    # A layout not yet migrated to the DSL lacks these keys; the gate must say so
    # rather than surface a bare KeyError traceback.
    for missing in ("body", "content_width"):
        layout = {"content_width": 1600, "field_budgets": {}, "body": []}
        del layout[missing]
        with pytest.raises(LayoutSchemaError) as exc_info:
            _validate_layout(layout)
        message = str(exc_info.value)
        assert missing in message
        assert_diagnostic_error(message)


def test_budgeted_table_nested_in_a_panel_uses_the_narrowed_width():
    # Panel padding narrows the region; the nested table's column arithmetic must use
    # the narrowed width, not the layout's full content_width. This is the interaction
    # Stage 2's Westpac rewards panel (a panel containing a split) depends on.
    layout = {
        "content_width": 1600,
        "field_budgets": {"DESC": {"width": 1200, "fit": "wrap", "min_font": 10, "max_lines": 2}},
        "body": [
            {
                "type": "panel",
                "padding": 100,
                "children": [
                    {
                        "type": "table",
                        "rows": "pipe_fields",
                        "columns": [
                            {"key": "d", "label": "D", "align": "left", "x": 0, "budget": "DESC"},
                            {"key": "x", "label": "X", "align": "right", "x_right": -400},
                        ],
                    }
                ],
            }
        ],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert_diagnostic_error(str(exc_info.value))


def test_split_with_too_large_a_gap_is_rejected():
    layout = {
        "content_width": 100,
        "field_budgets": {},
        "body": [
            {"type": "split", "gap": 200, "children": [[{"type": "rule"}], [{"type": "rule"}]]}
        ],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        _validate_layout(layout)
    assert_diagnostic_error(str(exc_info.value))
```

Add `from copy import deepcopy` and `validate_layout` to the test module's imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.layout_dsl.schema'`

- [ ] **Step 3: Write minimal implementation**

```python
# generators/layout_dsl/schema.py
"""Startup validation for a layout's `body:` tree.

Every layout is fully checked before any rendering begins, per CLAUDE.md's
fail-fast rule: unknown primitives, missing keys, unknown field references and
unregistered row providers all fail here with a four-element diagnostic.
"""

from generators.layout_dsl.binding import referenced_fields
from generators.layout_dsl.providers import provider_names

ROW_STYLES = ("ruled", "bordered", "grouped", "plain")

# primitive -> (required keys, optional keys)
PRIMITIVES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "text": (("content",), ("role", "align", "color", "field")),
    # No "gap": draw_pair renders "label: value" as one string and never reads it.
    "pair": (("label", "value"), ("role", "color", "field")),
    "block": (("lines",), ("role", "color", "heading")),
    "rule": ((), ("color", "thickness", "pad_above", "pad_below")),
    "spacer": ((), ("height",)),
    "panel": (("children",), ("border_color", "padding", "height")),
    "split": (("children",), ("gap",)),
    # No block-level "budget": budgets are declared per column, and advertising an
    # unread block-level key would be silently accepted and silently ignored.
    "table": (("rows", "columns"), ("row_style", "params", "row_height", "header")),
}

_CONTAINERS = ("panel", "split")


class LayoutSchemaError(RuntimeError):
    """Raised when a layout body fails structural validation."""


def _err(what: str, *, layout_path: str, key_path: str, expected: str, recover: str) -> LayoutSchemaError:
    """Build a four-element fail-fast diagnostic error.

    Args:
        what: What is wrong.
        layout_path: Path to the offending layout YAML.
        key_path: Dotted path to the offending key inside that file.
        expected: What a valid value looks like.
        recover: One-line remediation.

    Returns:
        The constructed error.
    """
    return LayoutSchemaError(
        "Invalid layout body.\n"
        f"  What:     {what}\n"
        f"  Where:    {layout_path} -> {key_path}\n"
        f"  Expected: {expected}\n"
        f"  Recover:  {recover}"
    )


def validate_body(
    body: list,
    *,
    layout_id: str,
    layout_path: str,
    known_fields: set[str],
) -> None:
    """Validate a layout's body tree, recursing into containers.

    Args:
        body: The layout's `body:` list of block dicts.
        layout_id: Layout id, used in diagnostics.
        layout_path: Path to the layout YAML, used in diagnostics.
        known_fields: Field names the document type may reference.

    Raises:
        LayoutSchemaError: On any structural or reference problem.
    """
    if not isinstance(body, list):
        raise _err(
            f"layout '{layout_id}' body is {type(body).__name__}, not a list.",
            layout_path=layout_path,
            key_path=f"{layout_id}.body",
            expected="a list of block mappings, each with a 'type' key.",
            recover=f"make {layout_id}.body a YAML list.",
        )
    _validate_blocks(body, layout_id=layout_id, layout_path=layout_path, known_fields=known_fields,
                     key_path=f"{layout_id}.body")


def _validate_blocks(
    blocks: list, *, layout_id: str, layout_path: str, known_fields: set[str], key_path: str
) -> None:
    """Validate a list of blocks at one nesting level."""
    for index, block in enumerate(blocks):
        here = f"{key_path}[{index}]"
        if not isinstance(block, dict):
            raise _err(
                f"block is {type(block).__name__}, not a mapping.",
                layout_path=layout_path,
                key_path=here,
                expected="a mapping such as {type: text, content: \"{PAYER_NAME}\"}.",
                recover="replace the entry with a block mapping.",
            )
        _validate_block(block, layout_id=layout_id, layout_path=layout_path,
                        known_fields=known_fields, key_path=here)


def _validate_block(
    block: dict, *, layout_id: str, layout_path: str, known_fields: set[str], key_path: str
) -> None:
    """Validate one block and recurse into any children."""
    kind = block.get("type")
    if kind is None:
        raise _err(
            "block has no 'type' key.",
            layout_path=layout_path,
            key_path=key_path,
            expected=f"type: one of {sorted(PRIMITIVES)}.",
            recover="add a type: key naming the primitive to render.",
        )
    if kind not in PRIMITIVES:
        raise _err(
            f"unknown primitive '{kind}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.type",
            expected=f"one of {sorted(PRIMITIVES)}.",
            recover="use a supported primitive, or add one to PRIMITIVES in "
            "generators/layout_dsl/schema.py.",
        )

    required, optional = PRIMITIVES[kind]
    missing = [key for key in required if key not in block]
    if missing:
        raise _err(
            f"'{kind}' block missing required key(s): {missing}.",
            layout_path=layout_path,
            key_path=key_path,
            expected=f"required {list(required)}; optional {list(optional)}.",
            recover=f"add {missing} to the {kind} block.",
        )
    allowed = set(required) | set(optional) | {"type", "when"}
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise _err(
            f"'{kind}' block has unknown key(s): {unknown}.",
            layout_path=layout_path,
            key_path=key_path,
            expected=f"only {sorted(allowed)}.",
            recover=f"remove {unknown}, or add them to PRIMITIVES in "
            "generators/layout_dsl/schema.py.",
        )

    _validate_references(block, layout_path=layout_path, known_fields=known_fields, key_path=key_path)

    if kind == "table":
        _validate_table(block, layout_path=layout_path, key_path=key_path)
    if kind in _CONTAINERS:
        _validate_children(block, layout_id=layout_id, layout_path=layout_path,
                           known_fields=known_fields, key_path=key_path)


def _validate_references(
    block: dict, *, layout_path: str, known_fields: set[str], key_path: str
) -> None:
    """Check every {FIELD} placeholder and `when:` field is a known field."""
    texts: list[str] = []
    for key in ("content", "label", "value", "heading"):
        if isinstance(block.get(key), str):
            texts.append(block[key])
    for line in block.get("lines", []) or []:
        if isinstance(line, str):
            texts.append(line)

    for text in texts:
        for name in referenced_fields(text):
            if name not in known_fields:
                raise _err(
                    f"unknown field reference '{{{name}}}'.",
                    layout_path=layout_path,
                    key_path=key_path,
                    expected=f"a field defined for this document type: {sorted(known_fields)}.",
                    recover=f"fix the field name, or add '{name}' to "
                    "config/field_definitions.yml.",
                )

    when = block.get("when")
    if when is not None and when not in known_fields:
        raise _err(
            f"'when' references unknown field '{when}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.when",
            expected=f"a field defined for this document type: {sorted(known_fields)}.",
            recover=f"fix the field name, or add '{when}' to config/field_definitions.yml.",
        )


def _validate_table(block: dict, *, layout_path: str, key_path: str) -> None:
    """Check a table's provider, row style, and column definitions."""
    rows = block["rows"]
    if rows not in provider_names():
        raise _err(
            f"unknown row provider '{rows}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.rows",
            expected=f"one of {provider_names()}.",
            recover="set rows: to a registered provider, or register one with "
            "@row_provider in generators/layout_dsl/providers.py.",
        )

    style = block.get("row_style", "plain")
    if style not in ROW_STYLES:
        raise _err(
            f"unknown row_style '{style}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.row_style",
            expected=f"one of {list(ROW_STYLES)}.",
            recover="set row_style to a supported style.",
        )

    columns = block["columns"]
    if not isinstance(columns, list) or not columns:
        raise _err(
            "table has no columns.",
            layout_path=layout_path,
            key_path=f"{key_path}.columns",
            expected="a non-empty list of {key, label, align, x|x_right} mappings.",
            recover="add at least one column.",
        )
    for index, column in enumerate(columns):
        for required in ("key", "label"):
            if not isinstance(column, dict) or required not in column:
                raise _err(
                    f"column {index} missing '{required}'.",
                    layout_path=layout_path,
                    key_path=f"{key_path}.columns[{index}]",
                    expected="{key: date, label: Date, align: left, x: 0}.",
                    recover=f"add {required}: to the column.",
                )
        if "x" not in column and "x_right" not in column:
            raise _err(
                f"column {index} has neither 'x' nor 'x_right'.",
                layout_path=layout_path,
                key_path=f"{key_path}.columns[{index}]",
                expected="x: <offset from region left> or x_right: <offset from region right>.",
                recover="add x: or x_right: to position the column.",
            )


def _validate_children(
    block: dict, *, layout_id: str, layout_path: str, known_fields: set[str], key_path: str
) -> None:
    """Recurse into a container's children.

    `panel` takes a flat list of blocks; `split` takes a list of such lists,
    one per column.
    """
    children = block["children"]
    if block["type"] == "split":
        if not isinstance(children, list) or len(children) < 2:
            raise _err(
                "split needs at least two child columns.",
                layout_path=layout_path,
                key_path=f"{key_path}.children",
                expected="a list of at least two lists of blocks.",
                recover="add a second column, or use panel for a single column.",
            )
        for index, column in enumerate(children):
            _validate_blocks(column, layout_id=layout_id, layout_path=layout_path,
                             known_fields=known_fields, key_path=f"{key_path}.children[{index}]")
    else:
        _validate_blocks(children, layout_id=layout_id, layout_path=layout_path,
                         known_fields=known_fields, key_path=f"{key_path}.children")


def validate_layout(
    layout: dict, *, layout_id: str, layout_path: str, known_fields: set[str]
) -> None:
    """Validate a whole layout: its body tree plus geometry-dependent checks.

    Adds the two checks that need the surrounding layout and cannot be made
    from the body alone — column budgets against column geometry, and nested
    container widths against their parent.

    Args:
        layout: The resolved layout dict, carrying `body`, `content_width`,
            and `field_budgets`.
        layout_id: Layout id, used in diagnostics.
        layout_path: Path to the layout YAML, used in diagnostics.
        known_fields: Field names the document type may reference.

    Raises:
        LayoutSchemaError: On any structural, reference, or geometry problem, or if
            the layout lacks a key this function needs.
    """
    for key, example in (("body", "a list of block mappings"), ("content_width", "1600")):
        if key not in layout:
            raise _err(
                f"layout '{layout_id}' has no '{key}' key.",
                layout_path=layout_path,
                key_path=f"{layout_id}.{key}",
                expected=f"{key}: {example}.",
                recover=f"add a '{key}:' key to {layout_id}, or do not pass this layout "
                f"to validate_layout.",
            )
    validate_body(
        layout["body"], layout_id=layout_id, layout_path=layout_path, known_fields=known_fields
    )
    content_width = int(layout["content_width"])
    _validate_geometry(
        layout["body"],
        layout=layout,
        layout_path=layout_path,
        width=content_width,
        key_path=f"{layout_id}.body",
    )


def _column_anchor(column: dict, width: int) -> int:
    """Resolve a column's anchor as an offset from the region's left edge."""
    return int(column["x"]) if "x" in column else width + int(column["x_right"])


def _validate_geometry(
    blocks: list, *, layout: dict, layout_path: str, width: int, key_path: str
) -> None:
    """Recursively check budgets and container widths against available space."""
    for index, block in enumerate(blocks):
        here = f"{key_path}[{index}]"
        kind = block["type"]

        if kind == "table":
            _validate_column_budgets(block, layout=layout, layout_path=layout_path,
                                     width=width, key_path=here)
        elif kind == "panel":
            padding = int(block.get("padding", 0))
            inner = width - 2 * padding
            if inner < 1:
                raise _err(
                    f"panel padding {padding} leaves width {inner} inside a {width}px region.",
                    layout_path=layout_path,
                    key_path=f"{here}.padding",
                    expected=f"padding below {width // 2}, e.g. padding: 10.",
                    recover="reduce the panel's padding, or widen content_width.",
                )
            declared = block.get("height")
            if declared is not None and int(declared) < 2 * padding:
                raise _err(
                    f"panel declares height {int(declared)} but its padding alone needs "
                    f"{2 * padding}px.",
                    layout_path=layout_path,
                    key_path=f"{here}.height",
                    expected=f"height >= {2 * padding}, or padding <= {int(declared) // 2}.",
                    recover="raise the panel's height, or reduce its padding.",
                )
            _validate_geometry(block["children"], layout=layout, layout_path=layout_path,
                               width=inner, key_path=f"{here}.children")
        elif kind == "split":
            columns = block["children"]
            gap = int(block.get("gap", 0))
            inner = (width - gap * (len(columns) - 1)) // len(columns)
            if inner < 1:
                raise _err(
                    f"split of {len(columns)} columns with gap {gap} leaves column "
                    f"width {inner} inside a {width}px region.",
                    layout_path=layout_path,
                    key_path=f"{here}.gap",
                    expected=f"gap below {width // max(len(columns) - 1, 1)}, e.g. gap: 30.",
                    recover="reduce the gap or the column count.",
                )
            for column_index, child_blocks in enumerate(columns):
                _validate_geometry(child_blocks, layout=layout, layout_path=layout_path,
                                   width=inner, key_path=f"{here}.children[{column_index}]")


def _validate_column_budgets(
    block: dict, *, layout: dict, layout_path: str, width: int, key_path: str
) -> None:
    """Check each budgeted column's declared width fits its column geometry.

    The budget is validated, never derived: a mismatch is an authoring error the
    operator must fix in YAML, so the intended width stays visible in the file.
    """
    budgets = layout.get("field_budgets", {})
    columns = block["columns"]
    anchors = sorted(_column_anchor(column, width) for column in columns)

    for index, column in enumerate(columns):
        name = column.get("budget")
        if name is None:
            continue
        if name not in budgets:
            raise _err(
                f"column {index} names budget '{name}', which the layout does not define.",
                layout_path=layout_path,
                key_path=f"{key_path}.columns[{index}].budget",
                expected=f"a key present in field_budgets: {sorted(budgets)}.",
                recover=f"add '{name}: {{width, fit, min_font, max_lines}}' to field_budgets.",
            )

        anchor = _column_anchor(column, width)
        following = [value for value in anchors if value > anchor]
        available = (min(following) if following else width) - anchor
        declared = int(budgets[name]["width"])
        if declared > available:
            raise _err(
                f"column {index} budget '{name}' declares width {declared}px but only "
                f"{available}px is available before the next column.",
                layout_path=layout_path,
                key_path=f"{key_path}.columns[{index}]",
                expected=f"field_budgets.{name}.width <= {available}.",
                recover=f"set field_budgets.{name}.width to {available} or less, or move "
                f"the following column right.",
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_schema.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add generators/layout_dsl/schema.py
git commit -m ":sparkles: add layout DSL primitive schema validation"
```

---

### Task 6: Text primitives

**Files:**
- Create: `generators/layout_dsl/primitives_text.py`
- Test: `tests/layout_dsl/test_primitives_text.py`

**Interfaces:**
- Consumes: `Region`, `RenderContext` (Task 1); `interpolate`, `is_present` (Task 2).
- Produces: `draw_text_block`, `draw_pair`, `draw_block`, `draw_rule`, `draw_spacer`, each with signature `(block: dict, ctx: RenderContext, y: int) -> int`. Also `resolve_role(layout: dict, role: str) -> int` returning the font size for a role.

Roles map to `layout["font_sizes"]`. A missing role fails fast rather than defaulting, per CLAUDE.md.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_primitives_text.py
import pytest
from PIL import Image, ImageDraw

from generators.exporters.geometry import BoxRecorder
from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.primitives_text import (
    RoleError,
    draw_block,
    draw_pair,
    draw_rule,
    draw_spacer,
    draw_text_block,
    resolve_role,
)
from conftest import assert_diagnostic_error

LAYOUT = {"font_sizes": {"header": 48, "body": 32, "footer": 18}, "margin": 100}


def _ctx(recorder: BoxRecorder | None = None) -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry={"fields": {"PAYER_NAME": "Robin Wood", "STATEMENT_DATE_RANGE": "01/07/2024 - 29/07/2024"}},
        layout=LAYOUT,
        layout_id="cba_standard",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        recorder=recorder,
    )


def test_resolve_role_returns_font_size():
    assert resolve_role(LAYOUT, "body") == 32


def test_resolve_role_fails_fast_on_unknown_role():
    with pytest.raises(RoleError) as exc_info:
        resolve_role(LAYOUT, "mystery")
    message = str(exc_info.value)
    assert "mystery" in message and "header" in message
    assert_diagnostic_error(message)


def test_text_advances_y():
    end = draw_text_block({"type": "text", "content": "{PAYER_NAME}", "role": "body"}, _ctx(), 200)
    assert end > 200


def test_text_records_geometry_when_field_given():
    recorder = BoxRecorder(1800, 3508)
    draw_text_block(
        {"type": "text", "content": "{PAYER_NAME}", "role": "body", "field": "PAYER_NAME"},
        _ctx(recorder),
        200,
    )
    assert "PAYER_NAME" in recorder.as_dict()


def test_text_without_field_records_nothing():
    recorder = BoxRecorder(1800, 3508)
    draw_text_block({"type": "text", "content": "{PAYER_NAME}", "role": "body"}, _ctx(recorder), 200)
    assert recorder.as_dict() == {}


def test_pair_renders_label_and_value():
    end = draw_pair(
        {"type": "pair", "label": "Account Holder", "value": "{PAYER_NAME}", "role": "body"},
        _ctx(),
        200,
    )
    assert end > 200


def test_block_advances_once_per_line():
    ctx = _ctx()
    one = draw_block({"type": "block", "lines": ["a"], "role": "footer"}, ctx, 0)
    three = draw_block({"type": "block", "lines": ["a", "b", "c"], "role": "footer"}, ctx, 0)
    assert three == one * 3


def test_spacer_advances_by_height():
    assert draw_spacer({"type": "spacer", "height": 40}, _ctx(), 200) == 240


def test_rule_advances_by_padding():
    end = draw_rule({"type": "rule", "pad_above": 10, "pad_below": 20}, _ctx(), 200)
    assert end == 231  # 10 above + 1px line + 20 below
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_primitives_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.layout_dsl.primitives_text'`

- [ ] **Step 3: Write minimal implementation**

```python
# generators/layout_dsl/primitives_text.py
"""Text-bearing primitives: text, pair, block, rule, spacer.

Each takes (block, ctx, y) and returns the advanced y-cursor, matching the
convention the existing renderers already use.
"""

from generators.common import draw_separator_line, load_font
from generators.layout_dsl.binding import interpolate
from generators.layout_dsl.context import RenderContext

_ALIGNMENTS = ("left", "center", "right")


class RoleError(RuntimeError):
    """Raised when a block names a typographic role the layout does not define."""


def resolve_role(layout: dict, role: str) -> int:
    """Return the font size a role maps to.

    Args:
        layout: The resolved layout dict, carrying a `font_sizes` mapping.
        role: The role name, e.g. "body".

    Returns:
        The font size in points.

    Raises:
        RoleError: If the layout defines no such role.
    """
    sizes = layout.get("font_sizes")
    if not isinstance(sizes, dict) or role not in sizes:
        available = sorted(sizes) if isinstance(sizes, dict) else []
        raise RoleError(
            "Unknown typographic role.\n"
            f"  What:     role '{role}' is not defined by this layout.\n"
            f"  Where:    config/layouts/*.yml -> <layout>.font_sizes.{role}\n"
            f"  Expected: one of {available}, e.g. font_sizes: {{body: 32}}.\n"
            f"  Recover:  add '{role}:' under the layout's font_sizes, or use "
            f"an existing role."
        )
    return int(sizes[role])


def _line_height(size: int) -> int:
    """Return the vertical advance for a font size."""
    return int(size * 1.4)


def _draw_line(ctx: RenderContext, text: str, y: int, *, size: int, align: str, color: str,
               bold: bool = False) -> tuple[int, int]:
    """Draw one line honouring alignment; return (left, right) pixel extent."""
    font = load_font(size, bold=bold)
    bbox = font.getbbox(text)
    text_width = int(bbox[2] - bbox[0])
    if align == "right":
        x = ctx.region.right - text_width
    elif align == "center":
        x = ctx.region.x + (ctx.region.width - text_width) // 2
    else:
        x = ctx.region.x
    ctx.draw.text((x, y), text, font=font, fill=color)
    return x, x + text_width


def draw_text_block(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a single line of text.

    Args:
        block: The `text` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    size = resolve_role(ctx.layout, block.get("role", "body"))
    text = interpolate(block["content"], ctx.entry["fields"])
    left, right = _draw_line(
        ctx, text, y,
        size=size,
        align=block.get("align", "left"),
        color=block.get("color", "black"),
    )
    end = y + _line_height(size)
    field = block.get("field")
    if ctx.recorder is not None and field is not None:
        ctx.recorder.record(field, (left, y, right, end))
    return end


def draw_pair(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a label and value on one line, separated by a colon and gap.

    Args:
        block: The `pair` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    size = resolve_role(ctx.layout, block.get("role", "body"))
    label = interpolate(block["label"], ctx.entry["fields"])
    value = interpolate(block["value"], ctx.entry["fields"])
    text = f"{label}: {value}"
    left, right = _draw_line(ctx, text, y, size=size, align="left", color=block.get("color", "black"))
    end = y + _line_height(size)
    field = block.get("field")
    if ctx.recorder is not None and field is not None:
        # Record the value's own extent, not the label's. Measure the label with
        # textlength (glyph advance) to match generators/common.py:482 _record_paired,
        # the existing helper that solves exactly this problem; getbbox (ink extent)
        # would place the left edge 0-2px right of where the rest of the corpus puts it.
        font = load_font(size)
        label_width = int(ctx.draw.textlength(f"{label}: ", font=font))
        ctx.recorder.record(field, (left + label_width, y, right, end))
    return end


def draw_block(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a group of lines, optionally under a heading.

    Args:
        block: The `block` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    size = resolve_role(ctx.layout, block.get("role", "body"))
    color = block.get("color", "black")
    heading = block.get("heading")
    if heading is not None:
        _draw_line(ctx, interpolate(heading, ctx.entry["fields"]), y, size=size, align="left",
                   color=color, bold=True)
        y += _line_height(size)
    for line in block["lines"]:
        _draw_line(ctx, interpolate(line, ctx.entry["fields"]), y, size=size, align="left", color=color)
        y += _line_height(size)
    return y


def draw_rule(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a horizontal separator across the region.

    Args:
        block: The `rule` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    thickness = int(block.get("thickness", 1))
    y += int(block.get("pad_above", 0))
    # Pass thickness through: it must change the drawn line, not only the space
    # reserved for it, or a layout setting thickness: 3 silently draws 1px.
    draw_separator_line(
        ctx.draw,
        ctx.region.x,
        ctx.region.right,
        y,
        color=block.get("color", "black"),
        width=thickness,
    )
    y += thickness + int(block.get("pad_below", 0))
    return y


def draw_spacer(block: dict, ctx: RenderContext, y: int) -> int:
    """Advance the cursor by a fixed height.

    Args:
        block: The `spacer` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    return y + int(block.get("height", 0))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_primitives_text.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add generators/layout_dsl/primitives_text.py
git commit -m ":sparkles: add layout DSL text primitives"
```

---

### Task 7: Container primitives

**Files:**
- Create: `generators/layout_dsl/primitives_container.py`
- Test: `tests/layout_dsl/test_primitives_container.py`

**Interfaces:**
- Consumes: `Region`, `RenderContext`, and its injected `render_children` (Task 1).
- Produces: `draw_panel(block, ctx, y) -> int`, `draw_split(block, ctx, y) -> int`, and `ContainerError(RuntimeError)`. Both containers render their children through `ctx.render_children`, so this module has no dependency on the engine and is testable with a stub walker.

`panel` draws a border and indents its children by `padding`. `split` divides the region into equal columns and renders each child list independently, returning the tallest column's y.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_primitives_container.py
from PIL import Image, ImageDraw

import pytest

from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.primitives_container import ContainerError, draw_panel, draw_split


def _stub_walker(blocks: list, ctx: RenderContext, y: int) -> int:
    """Minimal stand-in for the engine: advance by each spacer's height."""
    for block in blocks:
        y += int(block.get("height", 0))
    return y


def _ctx(render_children=_stub_walker) -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry={"fields": {"PAYER_NAME": "Robin Wood"}},
        layout={"font_sizes": {"body": 32, "footer": 18}},
        layout_id="test",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        render_children=render_children,
    )


def test_container_without_injected_walker_fails_loudly():
    block = {"type": "panel", "children": [{"type": "spacer", "height": 10}]}
    with pytest.raises(ContainerError, match="render_children"):
        draw_panel(block, _ctx(render_children=None), 0)


def test_panel_advances_past_its_children():
    block = {
        "type": "panel",
        "padding": 10,
        "children": [{"type": "spacer", "height": 50}, {"type": "spacer", "height": 30}],
    }
    assert draw_panel(block, _ctx(), 200) == 200 + 10 + 80 + 10


def test_panel_honours_fixed_height():
    block = {"type": "panel", "height": 260, "children": [{"type": "spacer", "height": 10}]}
    assert draw_panel(block, _ctx(), 200) == 460


def test_split_returns_tallest_column():
    block = {
        "type": "split",
        "gap": 40,
        "children": [
            [{"type": "spacer", "height": 100}],
            [{"type": "spacer", "height": 250}],
        ],
    }
    assert draw_split(block, _ctx(), 200) == 450


def test_split_gives_each_column_its_own_non_overlapping_region():
    seen: list[Region] = []

    def recording_walker(blocks: list, ctx: RenderContext, y: int) -> int:
        seen.append(ctx.region)
        return _stub_walker(blocks, ctx, y)

    block = {
        "type": "split",
        "gap": 40,
        "children": [[{"type": "spacer", "height": 10}], [{"type": "spacer", "height": 10}]],
    }
    draw_split(block, _ctx(render_children=recording_walker), 0)

    left, right = seen
    assert left.right < right.x
    assert left.width == right.width == 780
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_primitives_container.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.layout_dsl.primitives_container'`

- [ ] **Step 3: Write minimal implementation**

```python
# generators/layout_dsl/primitives_container.py
"""Nesting containers: panel and split.

These are the only primitives that create child regions, which is why all the
region arithmetic lives in `Region` rather than being duplicated here. Children
render through `ctx.render_children` — injected by the engine — so this module
never imports the engine, which imports it.
"""

from generators.layout_dsl.context import RenderContext


class ContainerError(RuntimeError):
    """Raised when a container is asked to render without a walker."""


def _walker(ctx: RenderContext):
    """Return the injected child renderer, or fail with a diagnostic.

    Args:
        ctx: The render context.

    Returns:
        The injected `render_children` callable.

    Raises:
        ContainerError: If no walker was injected.
    """
    if ctx.render_children is None:
        raise ContainerError(
            "Container cannot render its children.\n"
            "  What:     RenderContext.render_children is None.\n"
            f"  Where:    {ctx.layout_path} -> {ctx.layout_id}.body\n"
            "  Expected: the engine injects render_children before rendering.\n"
            "  Recover:  render through generators.layout_dsl.engine.render_body, "
            "which sets it, rather than constructing a RenderContext by hand."
        )
    return ctx.render_children


def draw_panel(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a bordered container around a nested list of blocks.

    Args:
        block: The `panel` block, carrying `children` and optional `padding`,
            `border_color`, and a fixed `height`.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor: past the panel's border and padding.
    """
    render_children = _walker(ctx)
    padding = int(block.get("padding", 0))
    inner_ctx = ctx.within(ctx.region.indent(padding, padding))
    inner_end = render_children(block["children"], inner_ctx, y + padding)

    fixed = block.get("height")
    if fixed is not None:
        # A fixed height must not silently let children draw outside their own box:
        # the border would be short, the return value wrong, and following blocks
        # would overlap the spilled content. Fail with the numbers needed to fix it.
        natural = inner_end + padding
        if natural > y + int(fixed):
            raise ContainerError(
                "Panel content overflows its fixed height.\n"
                f"  What:     children need {natural - y}px but the panel declares "
                f"height: {int(fixed)}.\n"
                f"  Where:    {ctx.layout_path} -> {ctx.layout_id}.body (a panel block)\n"
                f"  Expected: height >= {natural - y}, or fewer/smaller children.\n"
                f"  Recover:  raise the panel's height: to at least {natural - y}, or "
                f"reduce its children."
            )
    bottom = y + int(fixed) if fixed is not None else inner_end + padding

    ctx.draw.rectangle(
        [(ctx.region.x, y), (ctx.region.right, bottom)],
        outline=block.get("border_color", "black"),
    )
    return bottom


def draw_split(block: dict, ctx: RenderContext, y: int) -> int:
    """Render child block lists side by side in equal columns.

    Args:
        block: The `split` block, carrying `children` (a list of block lists,
            one per column) and an optional `gap`.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor: the bottom of the tallest column.
    """
    render_children = _walker(ctx)
    columns = block["children"]
    regions = ctx.region.divide(len(columns), gap=int(block.get("gap", 0)))
    ends = [
        render_children(child_blocks, ctx.within(region), y)
        for child_blocks, region in zip(columns, regions, strict=True)
    ]
    return max(ends)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_primitives_container.py -v`
Expected: PASS (5 tests). No dependency on the engine — the stub walker stands in for it.

- [ ] **Step 5: Commit**

```bash
git add generators/layout_dsl/primitives_container.py
git commit -m ":sparkles: add layout DSL container primitives"
```

---

### Task 8: Table primitive

**Files:**
- Create: `generators/layout_dsl/primitives_table.py`
- Test: `tests/layout_dsl/test_primitives_table.py`

**Interfaces:**
- Consumes: `RenderContext` (Task 1), `get_provider` (Tasks 3–4), `resolve_role` (Task 6), `field_budget` from `generators.layout_budgets`, `draw_fitted_left` / `draw_text_right` / `draw_separator_line` / `fmt_amount` from `generators.common`.
- Produces: `draw_table(block: dict, ctx: RenderContext, y: int) -> int` and `column_x(column: dict, ctx: RenderContext) -> int`.

Column positions resolve against the region: `x` is an offset from the region's left edge, `x_right` an offset from its right edge (normally negative). Amount-valued cells (`Decimal`) format through `fmt_amount`. Description cells honour the layout's `field_budgets` entry named by the column's `budget` key, so `fit_text` behaviour is identical to today's renderers.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_primitives_table.py
from decimal import Decimal

import pytest
from PIL import Image, ImageDraw

from generators.exporters.geometry import BoxRecorder
from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.primitives_table import column_x, draw_table

LAYOUT = {
    "font_sizes": {"body": 32, "footer": 18},
    "row_height": 72,
    "field_budgets": {
        "TRANSACTION_DESC": {"width": 760, "fit": "wrap", "min_font": 10, "max_lines": 2},
    },
}

ENTRY = {
    "fields": {
        "TRANSACTION_DATES": "01/07/2024|02/07/2024",
        "TRANSACTION_DESCRIPTIONS": "ATM WITHDRAWAL|SALARY",
        "TRANSACTION_AMOUNTS_PAID": "100.00|NOT_FOUND",
        "TRANSACTION_AMOUNTS_RECEIVED": "NOT_FOUND|500.00",
        "ACCOUNT_BALANCE": "1400.00",
    }
}

COLUMNS = [
    {"key": "date", "label": "Date", "align": "left", "x": 0},
    {"key": "description", "label": "Description", "align": "left", "x": 200,
     "budget": "TRANSACTION_DESC", "field": "TRANSACTION_DESCRIPTIONS"},
    {"key": "debit", "label": "Withdrawal", "align": "right", "x_right": -420},
    {"key": "balance", "label": "Balance", "align": "right", "x_right": 0},
]


def _ctx(recorder: BoxRecorder | None = None) -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry=ENTRY,
        layout=LAYOUT,
        layout_id="cba_standard",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        recorder=recorder,
    )


def test_column_x_resolves_left_offset():
    assert column_x({"x": 200}, _ctx()) == 300


def test_column_x_resolves_right_offset():
    assert column_x({"x_right": -420}, _ctx()) == 1280


def test_table_advances_by_header_plus_rows():
    block = {"type": "table", "rows": "bank_transactions", "row_style": "plain", "columns": COLUMNS}
    end = draw_table(block, _ctx(), 500)
    assert end > 500 + 2 * LAYOUT["row_height"]


def test_table_records_each_row_description():
    recorder = BoxRecorder(1800, 3508)
    block = {"type": "table", "rows": "bank_transactions", "row_style": "plain", "columns": COLUMNS}
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    assert "TRANSACTION_DESCRIPTIONS[0]" in boxes
    assert "TRANSACTION_DESCRIPTIONS[1]" in boxes


def test_synthetic_opening_row_is_not_recorded():
    recorder = BoxRecorder(1800, 3508)
    block = {
        "type": "table",
        "rows": "bank_transactions",
        "row_style": "plain",
        "params": {"opening_balance": True},
        "columns": COLUMNS,
    }
    draw_table(block, _ctx(recorder), 500)
    boxes = recorder.as_dict()
    # Two real transactions only; the synthetic row has no ground-truth identity.
    assert sorted(k for k in boxes if k.startswith("TRANSACTION_DESCRIPTIONS")) == [
        "TRANSACTION_DESCRIPTIONS[0]",
        "TRANSACTION_DESCRIPTIONS[1]",
    ]


def test_decimal_cells_format_as_amounts():
    from generators.common import fmt_amount

    assert fmt_amount(Decimal("1400.00")) == fmt_amount(Decimal("1400.0"))


@pytest.mark.parametrize("style", ["ruled", "bordered", "grouped", "plain"])
def test_every_row_style_renders(style: str):
    block = {"type": "table", "rows": "bank_transactions", "row_style": style, "columns": COLUMNS}
    assert draw_table(block, _ctx(), 500) > 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_primitives_table.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.layout_dsl.primitives_table'`

- [ ] **Step 3: Write minimal implementation**

```python
# generators/layout_dsl/primitives_table.py
"""The table primitive and its four row styles.

Row data comes from a named provider; this module only lays it out. Column
positions resolve against the current region, so a table nested inside a
container positions correctly without knowing it is nested.
"""

from decimal import Decimal

from generators.common import (
    draw_fitted_left,
    draw_separator_line,
    draw_text_left,
    draw_text_right,
    fmt_amount,
    load_font,
)
from generators.layout_budgets import field_budget
from generators.layout_dsl.context import RenderContext
from generators.layout_dsl.primitives_text import resolve_role
from generators.layout_dsl.providers import get_provider

_ABSENT = "NOT_FOUND"


def column_x(column: dict, ctx: RenderContext) -> int:
    """Resolve a column's anchor x-coordinate against the current region.

    Args:
        column: The column spec, carrying `x` or `x_right`.
        ctx: Render context supplying the region.

    Returns:
        The absolute pixel x: an anchor's left edge for `align: left`, or its
        right edge for `align: right`.
    """
    if "x" in column:
        return ctx.region.x + int(column["x"])
    return ctx.region.right + int(column["x_right"])


def _cell_text(row: dict, key: str) -> str:
    """Render one cell's value as display text."""
    value = row.get(key, "")
    if isinstance(value, Decimal):
        return fmt_amount(value)
    text = str(value)
    return "" if text == _ABSENT else text


def draw_table(block: dict, ctx: RenderContext, y: int) -> int:
    """Draw a table's header and rows.

    Args:
        block: The `table` block.
        ctx: Render context.
        y: Current y-cursor.

    Returns:
        The advanced y-cursor.
    """
    style = block.get("row_style", "plain")
    columns = block["columns"]
    row_height = int(block.get("row_height", ctx.layout["row_height"]))
    body_size = resolve_role(ctx.layout, "body")
    rows = get_provider(block["rows"])(ctx.entry, block.get("params", {}))

    if block.get("header", True):
        y = _draw_header(columns, ctx, y, size=body_size, style=style, row_height=row_height)

    index = 0
    previous_date = None
    for row in rows:
        if style == "grouped" and not row.get("synthetic") and row.get("date") != previous_date:
            draw_text_left(ctx.draw, str(row.get("date", "")), ctx.region.x, y,
                           load_font(body_size, bold=True))
            previous_date = row.get("date")
            y += row_height

        y = _draw_row(row, columns, ctx, y, size=body_size, style=style,
                      row_height=row_height, index=None if row.get("synthetic") else index)
        if not row.get("synthetic"):
            index += 1

    return y


def _draw_header(columns: list, ctx: RenderContext, y: int, *, size: int, style: str,
                 row_height: int) -> int:
    """Draw the column-header row in the table's style."""
    font = load_font(size, bold=True)
    if style == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, y, color="black")
        y += 12

    for column in columns:
        x = column_x(column, ctx)
        if column.get("align") == "right":
            draw_text_right(ctx.draw, column["label"], x_right=x, y=y, font=font)
        else:
            draw_text_left(ctx.draw, column["label"], x, y, font)

    y += row_height
    if style == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, y, color="black")
        y += 16
    return y


def _draw_row(row: dict, columns: list, ctx: RenderContext, y: int, *, size: int, style: str,
              row_height: int, index: int | None, is_last_real: bool = False) -> int:
    """Draw one row.

    Args:
        row: The row dict from the provider.
        columns: The table's column specs.
        ctx: Render context.
        y: Current y-cursor.
        size: Body font size.
        style: One of the four row styles.
        row_height: Vertical advance for this row.
        index: The real-row index, or None for synthetic rows, which are never recorded.
        is_last_real: True on the final real row, enabling any column's
            `last_row_field` capture.

    Returns:
        The advanced y-cursor.
    """
    font = load_font(size)
    bottom = y + row_height

    for column in columns:
        x = column_x(column, ctx)
        text = _cell_text(row, column["key"])
        if not text:
            continue

        # Alignment picks the helper; recording happens on EVERY path. The legacy
        # renderer records the right-aligned amount columns too, so omitting them here
        # would fail Stage 2's equivalence assertion on every case.
        right = column.get("align") == "right"
        recorder = ctx.recorder if index is not None else None
        budget_name = column.get("budget")

        # A column records either per-row (`field` -> FIELD[i]) or once on the final
        # real row (`last_row_field` -> FIELD, unindexed). Legacy's balance column uses
        # the latter: it records ACCOUNT_BALANCE on the last row and nothing elsewhere
        # (bank_statement.py:290-299). Synthetic rows have index None and record nothing.
        field = column.get("field")
        if field is not None and index is not None:
            record_field = f"{field}[{index}]"
        elif column.get("last_row_field") and is_last_real:
            record_field = column["last_row_field"]
        else:
            record_field = None

        if budget_name is not None:
            budget = field_budget(ctx.layout, ctx.layout_id, budget_name,
                                  layout_path=ctx.layout_path)
            fitted = draw_fitted_right if right else draw_fitted_left
            fitted(ctx.draw, text, x, y, budget=budget, nominal_size=size,
                   line_spacing=row_height, recorder=recorder, field=record_field)
        elif right:
            draw_text_right(ctx.draw, text, x_right=x, y=y, font=font,
                            recorder=recorder, field=record_field)
        else:
            draw_text_left(ctx.draw, text, x, y, font, recorder=recorder, field=record_field)

    if style == "bordered":
        ctx.draw.rectangle([(ctx.region.x, y), (ctx.region.right, bottom)], outline="#999999")
    elif style == "ruled":
        draw_separator_line(ctx.draw, ctx.region.x, ctx.region.right, bottom, color="#CCCCCC")

    return bottom
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_primitives_table.py -v`
Expected: PASS (10 tests, including 4 parametrised row styles)

- [ ] **Step 5: Commit**

```bash
git add generators/layout_dsl/primitives_table.py
git commit -m ":sparkles: add layout DSL table primitive with four row styles"
```

---

### Task 9: The walker

**Files:**
- Create: `generators/layout_dsl/engine.py`
- Modify: `generators/layout_dsl/__init__.py`
- Test: `tests/layout_dsl/test_engine.py`

**Interfaces:**
- Consumes: every primitive from Tasks 6–8; `is_present` (Task 2).
- Produces: `render_blocks(blocks: list, ctx: RenderContext, y: int) -> int`, `render_body(layout: dict, entry: dict, *, layout_id: str, layout_path: str, draw, region, recorder) -> int`, and the `PRIMITIVE_DRAWERS` dispatch table. Re-exported from `generators.layout_dsl`.

**Note:** the containers (Task 7) render children through the injected `ctx.render_children` rather than importing this module, so there is no import cycle and no ordering constraint between them.

**Error location.** Validate-time errors carry a precise `key_path` (`cba_standard.body[2].children[1]`); runtime errors must too, or an author hitting a failure three levels inside `panel > split > panel` is told only "some block in this layout failed". The walker accumulates the location on the exception as it unwinds — each `render_blocks` level prepends its own `[index](type)` segment — and `render_body` surfaces it as a trailing `At:` line. This keeps every primitive ignorant of how deeply it is nested. The error types are imported into `engine.py` for the `except` clause; verified no cycle, since `layout_budgets.py` imports nothing and `binding.py` imports only `re`.

- [ ] **Step 1: Write the failing test**

```python
# tests/layout_dsl/test_engine.py
import pytest
from PIL import Image, ImageDraw

from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.engine import PRIMITIVE_DRAWERS, EngineError, render_blocks
from generators.layout_dsl.schema import PRIMITIVES
from conftest import assert_diagnostic_error


def _ctx() -> RenderContext:
    image = Image.new("RGB", (1800, 3508), "white")
    return RenderContext(
        draw=ImageDraw.Draw(image),
        entry={"fields": {"PAYER_NAME": "Robin Wood", "STATEMENT_DATE_RANGE": "NOT_FOUND"}},
        layout={"font_sizes": {"body": 32}, "row_height": 72},
        layout_id="test",
        layout_path="config/layouts/bank_statements.yml",
        region=Region(x=100, width=1600),
        render_children=render_blocks,
    )


def test_every_schema_primitive_has_a_drawer():
    assert set(PRIMITIVES) == set(PRIMITIVE_DRAWERS)


def test_render_blocks_advances_through_the_list():
    end = render_blocks([{"type": "spacer", "height": 40}, {"type": "spacer", "height": 60}], _ctx(), 0)
    assert end == 100


def test_when_suppresses_a_block_whose_field_is_absent():
    body = [{"type": "spacer", "height": 40, "when": "STATEMENT_DATE_RANGE"}]
    assert render_blocks(body, _ctx(), 0) == 0


def test_when_admits_a_block_whose_field_is_present():
    body = [{"type": "spacer", "height": 40, "when": "PAYER_NAME"}]
    assert render_blocks(body, _ctx(), 0) == 40


def test_unknown_primitive_fails_with_diagnostic():
    with pytest.raises(EngineError) as exc_info:
        render_blocks([{"type": "hologram"}], _ctx(), 0)
    assert_diagnostic_error(str(exc_info.value))


def test_nested_panel_renders_through_the_walker():
    body = [{"type": "panel", "padding": 10, "children": [{"type": "spacer", "height": 50}]}]
    assert render_blocks(body, _ctx(), 0) == 70
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/layout_dsl/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generators.layout_dsl.engine'`

- [ ] **Step 3: Write minimal implementation**

```python
# generators/layout_dsl/engine.py
"""The walker: dispatch each block in a layout body to its primitive drawer."""

from collections.abc import Callable

from PIL import ImageDraw

from generators.exporters.geometry import BoxRecorder
from generators.layout_dsl.binding import is_present
from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.primitives_container import draw_panel, draw_split
from generators.layout_dsl.primitives_table import draw_table
from generators.layout_dsl.primitives_text import (
    draw_block,
    draw_pair,
    draw_rule,
    draw_spacer,
    draw_text_block,
)

Drawer = Callable[[dict, RenderContext, int], int]

PRIMITIVE_DRAWERS: dict[str, Drawer] = {
    "text": draw_text_block,
    "pair": draw_pair,
    "block": draw_block,
    "rule": draw_rule,
    "spacer": draw_spacer,
    "panel": draw_panel,
    "split": draw_split,
    "table": draw_table,
}


class EngineError(RuntimeError):
    """Raised when a block cannot be dispatched at render time."""


def render_blocks(blocks: list, ctx: RenderContext, y: int) -> int:
    """Render a list of blocks in order, threading the y-cursor.

    Args:
        blocks: Block dicts to render.
        ctx: Render context, already scoped to the right region.
        y: Starting y-cursor.

    Returns:
        The y-cursor after the last block.

    Raises:
        EngineError: If a block names a primitive with no registered drawer.
    """
    for block in blocks:
        when = block.get("when")
        if when is not None and not is_present(ctx.entry["fields"], when):
            continue

        kind = block.get("type")
        drawer = PRIMITIVE_DRAWERS.get(str(kind))
        if drawer is None:
            raise EngineError(
                "Cannot render layout block.\n"
                f"  What:     no drawer registered for primitive '{kind}'.\n"
                f"  Where:    {ctx.layout_path} -> {ctx.layout_id}.body\n"
                f"  Expected: one of {sorted(PRIMITIVE_DRAWERS)}.\n"
                f"  Recover:  use a supported primitive, or register a drawer in "
                f"PRIMITIVE_DRAWERS in generators/layout_dsl/engine.py."
            )
        y = drawer(block, ctx, y)
    return y


def render_body(
    layout: dict,
    entry: dict,
    *,
    layout_id: str,
    layout_path: str,
    draw: ImageDraw.ImageDraw,
    region: Region,
    y: int,
    recorder: BoxRecorder | None = None,
) -> int:
    """Render a layout's whole body onto a drawing surface.

    Args:
        layout: The resolved layout dict, carrying `body`.
        entry: The ground-truth entry.
        layout_id: Layout id, used in diagnostics.
        layout_path: Path to the layout YAML, used in diagnostics.
        draw: The PIL drawing surface.
        region: The page's content region.
        y: Starting y-cursor, normally the layout's top margin.
        recorder: Optional draw-time bounding-box capture.

    Returns:
        The y-cursor after the last block.

    Raises:
        EngineError: If the layout has no `body` key. `validate_layout` guards this,
            but nothing forces validation to run first — `generate` and `validate` are
            independent CLI subcommands — so the engine must diagnose it itself rather
            than surface a bare KeyError.
    """
    if "body" not in layout:
        raise EngineError(
            "Cannot render layout.\n"
            f"  What:     layout '{layout_id}' has no 'body' key.\n"
            f"  Where:    {layout_path} -> {layout_id}.body\n"
            "  Expected: body: a list of block mappings, each with a 'type' key.\n"
            f"  Recover:  add a 'body:' list to {layout_id}, or run "
            "`python -m generators.pipeline validate` to see the full diagnostic."
        )
    ctx = RenderContext(
        draw=draw,
        entry=entry,
        layout=layout,
        layout_id=layout_id,
        layout_path=layout_path,
        region=region,
        recorder=recorder,
        render_children=render_blocks,
    )
    return render_blocks(layout["body"], ctx, y)
```

```python
# generators/layout_dsl/__init__.py
"""Declarative layout DSL — YAML owns arrangement, Python owns drawing."""

from generators.layout_dsl.context import Region, RenderContext
from generators.layout_dsl.engine import render_blocks, render_body
from generators.layout_dsl.providers import row_provider
from generators.layout_dsl.schema import validate_body, validate_layout

__all__ = [
    "Region",
    "RenderContext",
    "render_blocks",
    "render_body",
    "row_provider",
    "validate_body",
    "validate_layout",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/layout_dsl/ -v`
Expected: PASS — all of Tasks 1–9 including the previously blocked container tests.

- [ ] **Step 5: Run the full gate and commit**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_dsl/
git commit -m ":sparkles: add layout DSL walker and public API"
```

Expected: full suite green; mypy error count unchanged at 10, none in `generators/layout_dsl/`.

---

# STAGE 2 — Migrate bank statements (GO / NO-GO)

Stage 2 proves the vocabulary against the hardest document type in the corpus. **If the primitives cannot express all 8 bank layouts cleanly, stop and reconsider the design** rather than proceeding to Stage 3.

Tasks 10–13 add DSL layouts alongside the existing ones and prove equivalence per bank. The old renderers stay live until Task 14.

---

### Task 10: Equivalence harness and CBA layouts

**Files:**
- Modify: `generators/loader.py` (unwrap `layouts:` alongside anchor siblings)
- Modify: `config/layouts/bank_statements.yml`
- Test: `tests/test_bank_dsl_equivalence.py`, `tests/test_loader_anchors.py`

**Interfaces:**
- Consumes: `render_body` (Task 9); `render_cba` from `generators.bank_statement`.

### Step 0 (prerequisite): let the loader see anchor siblings

`load_layout_registry` currently unwraps `layouts:` only when it is the sole top-level
key:

```python
if "layouts" in data and isinstance(data["layouts"], dict) and len(data) == 1:
    return data["layouts"]
```

The de-duplication scheme puts anchor definitions (`_bank_base`, `_cba`, …) at top level
as siblings of `layouts:`, so `len(data)` becomes 2+ and the loader returns the whole
dict — making `_bank_base` look like a layout id and hiding every real layout. Fix this
before touching the YAML, or every subsequent step fails for the wrong reason.

Anchor keys are distinguished by a leading underscore. A non-underscore sibling is a
genuine authoring error (a mis-indented layout) and must fail fast rather than be
silently swallowed:

```python
    if "layouts" in data and isinstance(data["layouts"], dict):
        stray = sorted(k for k in data if k != "layouts" and not str(k).startswith("_"))
        if stray:
            msg = (
                f"Unexpected top-level key(s) {stray} in {path.resolve()}.\n"
                f"  What:     only 'layouts:' and underscore-prefixed anchor "
                f"definitions may sit at the top level.\n"
                f"  Where:    {path.resolve()}\n"
                f"  Expected: layouts:\\n  <layout_id>: ...   plus optional "
                f"_anchor: &anchor blocks.\n"
                f"  Recover:  indent {stray} under 'layouts:', or rename to "
                f"'_{stray[0]}' if it is an anchor definition."
            )
            raise ValueError(msg)
        return data["layouts"]
```

Covering test:

```python
# tests/test_loader_anchors.py
from pathlib import Path

import pytest

from generators.loader import load_layout_registry


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "layouts.yml"
    path.write_text(text)
    return path


def test_anchor_siblings_are_not_mistaken_for_layouts(tmp_path: Path):
    path = _write(tmp_path, """
_base: &base
  page_dimensions: {width: 1800, height: 3508}
  content_width: 1600
layouts:
  cba_standard:
    <<: *base
    row_height: 72
""")
    registry = load_layout_registry(path)
    assert list(registry) == ["cba_standard"]
    assert registry["cba_standard"]["content_width"] == 1600
    assert registry["cba_standard"]["row_height"] == 72


def test_a_non_anchor_top_level_key_fails_fast(tmp_path: Path):
    path = _write(tmp_path, """
cba_standard:
  row_height: 72
layouts:
  westpac_standard:
    row_height: 62
""")
    with pytest.raises(ValueError) as exc_info:
        load_layout_registry(path)
    message = str(exc_info.value)
    assert "cba_standard" in message
    assert "Recover:" in message


def test_a_file_with_only_layouts_still_unwraps(tmp_path: Path):
    path = _write(tmp_path, "layouts:\n  a:\n    row_height: 10\n")
    assert list(load_layout_registry(path)) == ["a"]
```

- Produces: `render_via_dsl(entry: dict, layout: dict, layout_id: str, *, geometry_out: dict | None) -> Image.Image` in `generators/bank_statement.py`, and a reusable `assert_geometry_equivalent` helper in the test module.

Equivalence is checked on **geometry**, not pixels: the spec permits re-baselining, so fields must land in the same places but need not be byte-identical. Tolerance is 1.5% of page dimension.

Add to `config/layouts/bank_statements.yml`, keeping the existing keys intact for now:

```yaml
_bank_base: &bank_base
  page_dimensions: {width: 1800, height: 3508}
  content_width: 1600

_cba: &cba
  <<: *bank_base
  bank: Commonwealth Bank of Australia
  logo_text: Commonwealth Bank
  bank_code: CBA
  margin: 100
  bank_name_color: "#12107D"
  field_budgets:
    TRANSACTION_DESC: {width: 760, fit: wrap, min_font: 10, max_lines: 2}
    SUPPLIER_NAME: {width: 1600, fit: shrink, min_font: 12, max_lines: 1}
```

and give `cba_standard` a `body:`:

```yaml
  cba_standard:
    <<: *cba
    font_sizes: {header: 48, body: 32, footer: 18}
    row_height: 72
    date_format: "DD/MM/YYYY"
    body:
      - {type: text, content: "{SUPPLIER_NAME}", role: header, color: "#12107D",
         field: SUPPLIER_NAME}
      - type: block
        role: footer
        color: "#666666"
        lines:
          - Commonwealth Bank of Australia
          - ABN 48 123 456 789 AFSL and
          - Australian credit licence 234567
      - {type: spacer, height: 40}
      - {type: pair, label: "Account Holder", value: "{PAYER_NAME}", role: body,
         field: PAYER_NAME}
      - {type: pair, label: "Statement Period", value: "{STATEMENT_DATE_RANGE}", role: body,
         when: STATEMENT_DATE_RANGE, field: STATEMENT_DATE_RANGE}
      - {type: spacer, height: 28}
      - type: table
        rows: bank_transactions
        row_style: ruled
        params: {opening_balance: true}
        columns:
          - {key: date, label: Date, align: left, x: 0}
          - {key: description, label: Description, align: left, x: 200,
             budget: TRANSACTION_DESC, field: TRANSACTION_DESCRIPTIONS}
          - {key: debit, label: Withdrawal, align: right, x_right: -420}
          - {key: credit, label: Deposit, align: right, x_right: -210}
          - {key: balance, label: Balance, align: right, x_right: 0}
      - {type: spacer, height: 40}
      - {type: text, role: footer, color: "#666666",
         content: "Transaction types: EFTPOS, ATM, Direct Debit, Direct Credit, Transfer"}
```

Repeat for `cba_date_grouped`, merging `*cba` and setting `row_style: grouped`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bank_dsl_equivalence.py
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from generators.bank_statement import render_bank_statement
from generators.layout_dsl.context import Region
from generators.layout_dsl.engine import render_body
from generators.loader import load_ground_truth, load_layout_registry

LAYOUT_PATH = Path("config/layouts/bank_statements.yml")
TOLERANCE = 0.015


def _entries_for(layout_id: str) -> list[tuple[str, dict]]:
    """Return (case_id, entry) pairs using the given layout.

    Entries carry only `fields`, `layout` and `degradation_seed` — the case id
    is the ground-truth mapping's key, not a field on the entry.
    """
    gt = load_ground_truth(Path("ground_truth/bank_statements.yml"))
    return [(str(case_id), entry) for case_id, entry in gt.items() if entry.get("layout") == layout_id]


def _dsl_geometry(entry: dict, layout: dict, layout_id: str) -> dict:
    from generators.exporters.geometry import BoxRecorder

    dims = layout["page_dimensions"]
    image = Image.new("RGB", (dims["width"], dims["height"]), "white")
    recorder = BoxRecorder(dims["width"], dims["height"])
    render_body(
        layout,
        entry,
        layout_id=layout_id,
        layout_path=str(LAYOUT_PATH),
        draw=ImageDraw.Draw(image),
        region=Region(x=layout["margin"], width=layout["content_width"]),
        y=layout["margin"],
        recorder=recorder,
    )
    return recorder.as_dict()


def assert_geometry_equivalent(legacy: dict, dsl: dict, case_id: str) -> None:
    """Assert both renderers place the same fields in the same places."""
    missing = sorted(set(legacy) - set(dsl))
    assert not missing, f"{case_id}: DSL did not record {missing}"
    for field, legacy_box in legacy.items():
        for axis, (want, got) in enumerate(zip(legacy_box, dsl[field], strict=True)):
            assert abs(want - got) <= TOLERANCE, (
                f"{case_id}: {field} coordinate {axis} moved {abs(want - got):.4f} "
                f"(legacy {want:.4f} vs DSL {got:.4f}, tolerance {TOLERANCE})"
            )


@pytest.mark.parametrize("layout_id", ["cba_standard", "cba_date_grouped"])
def test_cba_dsl_matches_legacy_geometry(layout_id: str):
    layouts = load_layout_registry(LAYOUT_PATH)
    layout = layouts[layout_id]
    entries = _entries_for(layout_id)
    assert entries, f"no ground truth entries use layout {layout_id}"

    for case_id, entry in entries[:5]:
        legacy: dict = {}
        render_bank_statement(entry, layout, geometry_out=legacy)
        assert_geometry_equivalent(legacy["boxes"], _dsl_geometry(entry, layout, layout_id), case_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_equivalence.py -v`
Expected: FAIL — `KeyError: 'body'`, because the layouts have no `body:` yet.

- [ ] **Step 3: Add the CBA anchors and `body:` trees**

Edit `config/layouts/bank_statements.yml` exactly as shown in the Interfaces section above, for both `cba_standard` and `cba_date_grouped`. Leave `renderer:`, `variant:` and the `show_*` keys in place — they still drive the legacy path this test compares against.

- [ ] **Step 4: Run test and tune offsets until it passes**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_equivalence.py -v`
Expected: PASS. If a field is off by more than the tolerance, adjust the `spacer` heights and column `x` offsets in the YAML — **not** the tolerance.

- [ ] **Step 5: Commit**

```bash
git add config/layouts/bank_statements.yml
git commit -m ":sparkles: express CBA bank layouts in the declarative DSL"
```

---

### Task 11: Westpac layouts

**Files:**
- Modify: `config/layouts/bank_statements.yml`
- Test: `tests/test_bank_dsl_equivalence.py` (extend the parametrise list)

**Interfaces:**
- Consumes: `assert_geometry_equivalent` and `_dsl_geometry` from Task 10.
- Produces: `westpac_standard` and `westpac_premium` layouts with `body:` trees.

Westpac exercises two things CBA does not: `row_style: bordered`, and the rewards panel — a `panel` containing a `split`, replacing `show_rewards_section`. The figures hardcoded at `bank_statement.py:399-407` move into YAML.

- [ ] **Step 1: Extend the failing test**

```python
# tests/test_bank_dsl_equivalence.py — replace the parametrise decorator
@pytest.mark.parametrize(
    "layout_id",
    ["cba_standard", "cba_date_grouped", "westpac_standard", "westpac_premium"],
)
def test_cba_dsl_matches_legacy_geometry(layout_id: str):
    ...  # body unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_equivalence.py -v`
Expected: FAIL on the two Westpac ids with `KeyError: 'body'`.

- [ ] **Step 3: Add the Westpac layouts**

```yaml
_westpac: &westpac
  <<: *bank_base
  bank: Westpac Banking Corporation
  logo_text: Westpac
  bank_code: WBC
  margin: 80
  logo_color: "#C41E3A"
  field_budgets:
    TRANSACTION_DESC: {width: 1064, fit: wrap, min_font: 10, max_lines: 2}
    SUPPLIER_NAME: {width: 1600, fit: shrink, min_font: 12, max_lines: 1}

_westpac_txn_columns: &westpac_txn_columns
  - {key: date, label: "Date of Transaction", align: left, x: 0}
  - {key: description, label: Description, align: left, x: 240,
     budget: TRANSACTION_DESC, field: TRANSACTION_DESCRIPTIONS}
  - {key: debit, label: Debits, align: right, x_right: -420}
  - {key: credit, label: "Credits (-)", align: right, x_right: -210}
  - {key: balance, label: Balance, align: right, x_right: 0}
```

```yaml
  westpac_standard:
    <<: *westpac
    font_sizes: {header: 44, body: 28, sub_description: 22, footer: 16}
    row_height: 62
    date_format: "DD MMM YY"
    body:
      - {type: text, content: "{SUPPLIER_NAME}", role: header, color: "#C41E3A",
         field: SUPPLIER_NAME}
      - {type: text, content: "Page 1 of 1", role: footer, align: right, color: "#666666"}
      - {type: spacer, height: 72}
      - {type: pair, label: "Account Holder", value: "{PAYER_NAME}", role: body,
         field: PAYER_NAME}
      - {type: pair, label: "Statement Period", value: "{STATEMENT_DATE_RANGE}", role: body,
         when: STATEMENT_DATE_RANGE, field: STATEMENT_DATE_RANGE}
      - {type: spacer, height: 28}
      - type: table
        rows: bank_transactions
        row_style: bordered
        columns: *westpac_txn_columns

  westpac_premium:
    <<: *westpac
    font_sizes: {header: 44, body: 28, sub_description: 22, footer: 16}
    row_height: 62
    date_format: "DD MMM YY"
    body:
      - {type: text, content: "{SUPPLIER_NAME}", role: header, color: "#C41E3A",
         field: SUPPLIER_NAME}
      - {type: text, content: "Page 1 of 1", role: footer, align: right, color: "#666666"}
      - {type: spacer, height: 82}
      - type: panel
        height: 260
        padding: 10
        children:
          - type: split
            gap: 30
            children:
              - - type: block
                  role: sub_description
                  heading: "Rewards Points Balance Summary"
                  lines:
                    - "Opening Balance          345,678"
                    - "Points Earned             12,456"
                    - "Bonus Points Earned            0"
                    - "Points Redeemed                0"
                    - "Closing Balance          358,134"
                    - "Points Status          Available"
              - - type: block
                  role: sub_description
                  heading: "A message from Rewards"
                  lines:
                    - "Your points are ready to redeem."
      - {type: spacer, height: 20}
      - {type: pair, label: "Account Holder", value: "{PAYER_NAME}", role: body,
         field: PAYER_NAME}
      - {type: pair, label: "Statement Period", value: "{STATEMENT_DATE_RANGE}", role: body,
         when: STATEMENT_DATE_RANGE, field: STATEMENT_DATE_RANGE}
      - {type: spacer, height: 28}
      - type: table
        rows: bank_transactions
        row_style: grouped
        columns: *westpac_txn_columns
```

- [ ] **Step 4: Run test and tune until it passes**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_equivalence.py -v`
Expected: PASS for all four layout ids.

- [ ] **Step 5: Commit**

```bash
git add config/layouts/bank_statements.yml
git commit -m ":sparkles: express Westpac bank layouts in the declarative DSL"
```

---

### Task 12: NAB layouts

**Files:**
- Modify: `config/layouts/bank_statements.yml`
- Test: `tests/test_bank_dsl_equivalence.py` (extend the parametrise list)

**Interfaces:**
- Consumes: Task 10's helpers.
- Produces: `nab_classic` and `nab_dense` layouts with `body:` trees.

NAB is the case that proves the within-type variation rule: `references` differs between its two layouts (`nab_classic` true, `nab_dense` false), so it stays a table parameter, while `brought_forward` is constant for the bank and becomes a provider param.

- [ ] **Step 1: Extend the failing test**

Add `"nab_classic", "nab_dense"` to the parametrise list in `tests/test_bank_dsl_equivalence.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_equivalence.py -v`
Expected: FAIL on the two NAB ids with `KeyError: 'body'`.

- [ ] **Step 3: Add the NAB layouts**

```yaml
_nab: &nab
  <<: *bank_base
  bank: National Australia Bank
  logo_text: NAB Classic Banking
  bank_code: NAB
  margin: 80
  header_bar_color: "#E8F0FE"
  balance_suffix: "Cr"
  field_budgets:
    TRANSACTION_DESC: {width: 860, fit: wrap, min_font: 10, max_lines: 2}
    SUPPLIER_NAME: {width: 1600, fit: shrink, min_font: 12, max_lines: 1}

_nab_txn_columns: &nab_txn_columns
  - {key: date, label: Date, align: left, x: 0}
  - {key: description, label: Particulars, align: left, x: 220,
     budget: TRANSACTION_DESC, field: TRANSACTION_DESCRIPTIONS}
  - {key: debit, label: Debit, align: right, x_right: -420}
  - {key: credit, label: Credit, align: right, x_right: -210}
  - {key: balance, label: Balance, align: right, x_right: 0}
```

```yaml
  nab_classic:
    <<: *nab
    font_sizes: {header: 44, body: 28, sub_description: 22, footer: 16}
    row_height: 66
    date_format: "DD MMM YYYY"
    body:
      - {type: text, content: "{SUPPLIER_NAME}", role: header, field: SUPPLIER_NAME}
      - {type: spacer, height: 60}
      - {type: pair, label: "Account Holder", value: "{PAYER_NAME}", role: body,
         field: PAYER_NAME}
      - {type: pair, label: "Statement Period", value: "{STATEMENT_DATE_RANGE}", role: body,
         when: STATEMENT_DATE_RANGE, field: STATEMENT_DATE_RANGE}
      - {type: spacer, height: 28}
      - type: table
        rows: bank_transactions
        row_style: grouped
        params: {brought_forward: true, references: true}
        columns: *nab_txn_columns

  nab_dense:
    <<: *nab
    font_sizes: {header: 40, body: 24, sub_description: 20, footer: 14}
    row_height: 52
    date_format: "DD MMM YY"
    body:
      - {type: text, content: "{SUPPLIER_NAME}", role: header, field: SUPPLIER_NAME}
      - {type: spacer, height: 56}
      - {type: pair, label: "Account Holder", value: "{PAYER_NAME}", role: body,
         field: PAYER_NAME}
      - {type: pair, label: "Statement Period", value: "{STATEMENT_DATE_RANGE}", role: body,
         when: STATEMENT_DATE_RANGE, field: STATEMENT_DATE_RANGE}
      - {type: spacer, height: 28}
      - type: table
        rows: bank_transactions
        row_style: grouped
        params: {brought_forward: true, references: false}
        columns: *nab_txn_columns
```

**Note:** `references` is accepted by `bank_transactions` but currently ignored — it renders a sub-line beneath each description in the legacy NAB renderer (`bank_statement.py:693`). If the equivalence test fails on row spacing because of it, add a `sub_line` key to the provider's rows and render it in `_draw_row` under `row_style: grouped`. Do this only if the test demands it; do not add it speculatively.

- [ ] **Step 4: Run test and tune until it passes**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_equivalence.py -v`
Expected: PASS for all six layout ids.

- [ ] **Step 5: Commit**

```bash
git add config/layouts/bank_statements.yml generators/layout_dsl/
git commit -m ":sparkles: express NAB bank layouts in the declarative DSL"
```

---

### Task 13: ANZ layouts and the GO/NO-GO review

**Files:**
- Modify: `config/layouts/bank_statements.yml`
- Test: `tests/test_bank_dsl_equivalence.py` (extend the parametrise list)

**Interfaces:**
- Consumes: Task 10's helpers.
- Produces: `anz_standard` and `anz_modern` layouts with `body:` trees. After this task all 8 bank layouts render through the DSL.

ANZ exercises the totals row — `show_totals_row` becomes a trailing `pair` block rather than a flag — and dual balance suffixes (`DR`/`CR`).

- [ ] **Step 1: Extend the failing test**

Add `"anz_standard", "anz_modern"` to the parametrise list.

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_equivalence.py -v`
Expected: FAIL on the two ANZ ids with `KeyError: 'body'`.

- [ ] **Step 3: Add the ANZ layouts**

```yaml
_anz: &anz
  <<: *bank_base
  bank: Australia and New Zealand Banking Group
  logo_text: ANZ
  bank_code: ANZ
  margin: 100
  header_color: "#0061B5"
  balance_suffix_debit: "DR"
  balance_suffix_credit: "CR"
  field_budgets:
    TRANSACTION_DESC: {width: 780, fit: wrap, min_font: 10, max_lines: 2}
    SUPPLIER_NAME: {width: 1600, fit: shrink, min_font: 12, max_lines: 1}

_anz_txn_columns: &anz_txn_columns
  - {key: date, label: Date, align: left, x: 0}
  - {key: description, label: Transaction, align: left, x: 200,
     budget: TRANSACTION_DESC, field: TRANSACTION_DESCRIPTIONS}
  - {key: debit, label: Withdrawals, align: right, x_right: -420}
  - {key: credit, label: Deposits, align: right, x_right: -210}
  - {key: balance, label: Balance, align: right, x_right: 0}
```

```yaml
  anz_standard:
    <<: *anz
    font_sizes: {header: 48, body: 32, sub_description: 24, footer: 18}
    row_height: 72
    date_format: "DD/MM/YY"
    body:
      - {type: text, content: "{SUPPLIER_NAME}", role: header, color: "#0061B5",
         field: SUPPLIER_NAME}
      - {type: spacer, height: 64}
      - {type: pair, label: "Account Holder", value: "{PAYER_NAME}", role: body,
         field: PAYER_NAME}
      - {type: pair, label: "Statement Period", value: "{STATEMENT_DATE_RANGE}", role: body,
         when: STATEMENT_DATE_RANGE, field: STATEMENT_DATE_RANGE}
      - {type: spacer, height: 28}
      - type: table
        rows: bank_transactions
        row_style: plain
        params: {brought_forward: true}
        columns: *anz_txn_columns
      - {type: rule, pad_above: 8, pad_below: 8}
      - {type: pair, label: "Closing Balance", value: "{ACCOUNT_BALANCE}", role: body,
         field: ACCOUNT_BALANCE}

  anz_modern:
    <<: *anz
    font_sizes: {header: 44, body: 28, sub_description: 22, footer: 16}
    row_height: 62
    date_format: "DD MMM YYYY"
    body:
      - {type: text, content: "{SUPPLIER_NAME}", role: header, color: "#0061B5",
         field: SUPPLIER_NAME}
      - {type: spacer, height: 58}
      - {type: pair, label: "Account Holder", value: "{PAYER_NAME}", role: body,
         field: PAYER_NAME}
      - {type: pair, label: "Statement Period", value: "{STATEMENT_DATE_RANGE}", role: body,
         when: STATEMENT_DATE_RANGE, field: STATEMENT_DATE_RANGE}
      - {type: spacer, height: 28}
      - type: table
        rows: bank_transactions
        row_style: plain
        params: {brought_forward: true}
        columns: *anz_txn_columns
      - {type: rule, pad_above: 8, pad_below: 8}
      - {type: pair, label: "Closing Balance", value: "{ACCOUNT_BALANCE}", role: body,
         field: ACCOUNT_BALANCE}
```

- [ ] **Step 4: Run test and tune until it passes**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_equivalence.py -v`
Expected: PASS for all eight layout ids.

- [ ] **Step 5: GO / NO-GO review — stop and report**

Do **not** proceed to Task 14 without an explicit decision. Report:

1. Did all 8 layouts express cleanly, or did any need a new primitive, a new row style, or a provider key added mid-task?
2. How many equivalence assertions needed offset tuning versus passing first time?
3. Were any of the four row styles unused, or did any need splitting?

**GO** if all 8 express within the existing vocabulary. **NO-GO** if two or more layouts needed vocabulary extensions — that indicates the primitives are under-powered and the design should be revisited before Stages 3–4.

- [ ] **Step 6: Commit**

```bash
git add config/layouts/bank_statements.yml
git commit -m ":sparkles: express ANZ bank layouts in the declarative DSL"
```

---

### Task 13b: Persisted pixel-snapshot test (prerequisite for Task 14)

**Files:**
- Test: `tests/test_bank_pixel_snapshot.py`
- Create: `tests/fixtures/bank_pixel_hashes.json` (checked in? No — `tests/` is gitignored; see note)

**Why this exists.** The equivalence harness compares recorded field geometry only. It
cannot see colour, font weight, rules, fills, or anything in a region carrying no
ground-truth field. Four consecutive banks passed it while rendering something visibly
wrong — Westpac's grey text rendering black, NAB's un-bolded Carried-forward row, ANZ's
brought-forward weight, and a stray `#CCCCCC` per-row rule that CBA shipped for four
tasks (53,217 spurious pixels against legacy's 386). Every one was caught by ad-hoc pixel
inspection; none by an assertion, and none of that evidence persists in `tests/`.

Task 14 deletes `generators/bank_statement.py`. After that there is no oracle to diff
against, so the snapshot must be captured **while legacy still exists**.

**What to capture.** For every bank ground-truth entry, render through the DSL and store
a hash of the full page. Assert on every run that the hash is unchanged. Capture the
legacy renderer's hash too, and record — as data, not as an assertion — which entries are
currently byte-identical between the two paths (today: ANZ 14/14; the other six differ,
CBA overwhelmingly by the known 2px offset, Westpac by disclosed content choices).

The DSL hash is the regression guard and must be asserted. The legacy hash is historical
evidence of what the migration changed, and retires with Task 14.

**Note on gitignored tests.** `tests/` is gitignored in this repo, so the snapshot file
cannot be committed. Write it under `tests/fixtures/` for local use, and additionally
emit the DSL hashes to a committed location the pipeline can verify against — decide
where with the same reasoning used for `derived/geometry.jsonl`, which is a regenerable
artefact kept out of `ground_truth/`.

---

### Task 14: Delete the legacy bank renderers

**Files:**
- Modify: `generators/bank_statement.py:122-962` (delete four renderers and the dispatch table)
- Modify: `config/layouts/bank_statements.yml` (remove now-dead keys)
- Modify: `generators/pipeline.py` (`validate` gains DSL validation)
- Test: `tests/test_bank_dsl_equivalence.py` (delete — it retires with the old path), `tests/test_bank_fit.py` (must still pass)

**Interfaces:**
- Consumes: `render_body` (Task 9), `validate_layout` (Task 5).
- Produces: `render_bank_statement(entry: dict, layout: dict, *, geometry_out: dict | None = None) -> Image.Image` — same public signature as today, so `generators/pipeline.py:49` needs no change.

Only run this task after a **GO**.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bank_dsl_validation.py
from pathlib import Path

import pytest

from generators.layout_dsl.schema import LayoutSchemaError, validate_layout
from generators.loader import load_layout_registry
from conftest import assert_diagnostic_error

LAYOUT_PATH = Path("config/layouts/bank_statements.yml")
BANK_FIELDS = {
    "DOCUMENT_TYPE", "SUPPLIER_NAME", "STATEMENT_DATE_RANGE", "TRANSACTION_DATES",
    "TRANSACTION_DESCRIPTIONS", "TRANSACTION_AMOUNTS_PAID", "TRANSACTION_AMOUNTS_RECEIVED",
    "ACCOUNT_BALANCE", "PAYER_NAME",
}


def test_every_bank_layout_validates():
    for layout_id, layout in load_layout_registry(LAYOUT_PATH).items():
        validate_layout(
            layout,
            layout_id=layout_id,
            layout_path=str(LAYOUT_PATH),
            known_fields=BANK_FIELDS,
        )


def test_no_bank_layout_retains_dead_dispatch_keys():
    dead = {"renderer", "variant", "column_headers", "show_opening_balance",
            "show_brought_forward", "show_references", "show_totals_row",
            "show_rewards_section", "show_footer_transaction_types", "date_grouping"}
    for layout_id, layout in load_layout_registry(LAYOUT_PATH).items():
        assert not (dead & set(layout)), f"{layout_id} still carries {sorted(dead & set(layout))}"


def test_bank_statement_module_no_longer_exposes_per_bank_renderers():
    import generators.bank_statement as module

    for name in ("render_cba", "render_westpac", "render_nab", "render_anz"):
        assert not hasattr(module, name), f"{name} should have been deleted"


def test_validation_rejects_a_broken_layout():
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            {
                "content_width": 1600,
                "field_budgets": {},
                "body": [{"type": "text", "content": "{NO_SUCH_FIELD}"}],
            },
            layout_id="broken",
            layout_path=str(LAYOUT_PATH),
            known_fields=BANK_FIELDS,
        )
    assert_diagnostic_error(str(exc_info.value))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_bank_dsl_validation.py -v`
Expected: FAIL — `test_no_bank_layout_retains_dead_dispatch_keys` and `test_bank_statement_module_no_longer_exposes_per_bank_renderers` both fail; the legacy keys and functions are still present.

- [ ] **Step 3: Replace the renderers with an engine adapter**

Delete `render_cba`, `render_westpac`, `render_nab`, `render_anz`, `_BANK_RENDERERS`, and the now-unused private helpers they alone used. Keep `_parse_transactions` and `_compute_running_balances` **only if** nothing else imports them — the provider in Task 4 has its own implementation, so delete them too and update `tests/layout_dsl/test_providers.py::test_bank_transactions_matches_legacy_helpers`, which was a migration aid and retires here.

```python
# generators/bank_statement.py — the whole rendering path becomes:
"""Bank statement renderer — a thin adapter over the declarative layout engine.

Visual DNA per bank now lives in config/layouts/bank_statements.yml as a `body:`
tree of layout primitives; this module only sets up the page and delegates.
"""

from PIL import Image, ImageDraw

from generators.exporters.geometry import BoxRecorder
from generators.layout_dsl.context import Region
from generators.layout_dsl.engine import render_body

_LAYOUT_PATH = "config/layouts/bank_statements.yml"


def render_bank_statement(
    entry: dict, layout: dict, *, geometry_out: dict | None = None
) -> Image.Image:
    """Render a bank statement from its layout's declarative body.

    Args:
        entry: Ground truth entry with a 'fields' dict.
        layout: Layout registry entry carrying 'body', 'page_dimensions',
            'margin', and 'content_width'.
        geometry_out: Optional dict (opt-in); when given, populated in place
            with {"width", "height", "boxes"}.

    Returns:
        PIL Image of the rendered bank statement.
    """
    dims = layout["page_dimensions"]
    width, height = dims["width"], dims["height"]
    image = Image.new("RGB", (width, height), "white")
    recorder = BoxRecorder(width, height) if geometry_out is not None else None

    render_body(
        layout,
        entry,
        layout_id=str(entry.get("layout", "")),
        layout_path=_LAYOUT_PATH,
        draw=ImageDraw.Draw(image),
        region=Region(x=layout["margin"], width=layout["content_width"]),
        y=layout["margin"],
        recorder=recorder,
    )

    if recorder is not None and geometry_out is not None:
        geometry_out["width"] = width
        geometry_out["height"] = height
        geometry_out["boxes"] = recorder.as_dict()
    return image
```

Then strip the dead keys from every layout in `config/layouts/bank_statements.yml`: `renderer`, `variant`, `column_headers`, and every `show_*` and `date_grouping` key.

- [ ] **Step 4: Wire DSL validation into the pipeline**

In `generators/pipeline.py`, inside `validate`'s per-document-type loop, after the layout registry is loaded and before the overflow backstop:

```python
        # Every layout body is structurally validated before any rendering, so a
        # malformed primitive or unknown field reference fails here rather than
        # part-way through a 330-image generate run.
        if layouts:
            known = set(field_names_for(doc_type))
            for layout_id, layout in layouts.items():
                if "body" not in layout:
                    continue
                try:
                    validate_layout(
                        layout,
                        layout_id=layout_id,
                        layout_path=str(doc_cfg["layouts"]),
                        known_fields=known,
                    )
                except LayoutSchemaError as err:
                    all_errors.append(str(err))
```

Add the imports `from generators.layout_dsl.schema import LayoutSchemaError, validate_layout` and a `field_names_for(doc_type: str) -> set[str]` helper in `generators/schema.py` that reads `config/field_definitions.yml` — reuse `_load_field_defs()` rather than re-reading the file.

- [ ] **Step 5: Run the full gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic python -m generators.pipeline generate --type bank_statements --clean-only
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```

Expected: full suite green including `tests/test_bank_fit.py` and `tests/test_bank_supplier_header.py`; `validate` reports no errors; 55 bank images generated; mypy error count still 10.

- [ ] **Step 6: Spot-check three rendered images**

Open `output/clean/bank_statements/` and confirm one CBA, one Westpac premium (rewards panel present and bordered), and one NAB dense image look like plausible bank statements. Geometry equivalence does not catch a missing border or a wrong colour.

- [ ] **Step 7: Commit**

```bash
git add generators/bank_statement.py generators/pipeline.py generators/schema.py \
        config/layouts/bank_statements.yml
git commit -m ":fire: replace per-bank renderers with the declarative layout engine"
```

---

## Stage 2 exit criteria

- All 8 bank layouts render through the DSL; `generators/bank_statement.py` is under 100 lines.
- `config/layouts/bank_statements.yml` carries no `renderer`, `variant`, or `show_*` keys.
- `python -m generators.pipeline validate` passes and rejects a deliberately broken layout body with a four-element diagnostic.
- Full test suite green; mypy error count unchanged at 10.
- GO/NO-GO reported in Task 13 Step 5.

**Stages 3–4** (migrate receipts and invoices; narrow the corpus to three document types, drop linking, re-baseline and re-export) are planned separately once Stage 2 returns GO.
