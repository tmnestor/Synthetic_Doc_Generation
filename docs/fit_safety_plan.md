# Phase 0 — Fit Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee every rendered image shows the exact full ground-truth string (no clipping, collision, or silent truncation) by fitting text losslessly at render time, with a fail-fast validation backstop — without changing the current 220 documents.

**Architecture:** Add per-field pixel budgets to `config/layouts/*.yml`. A new `fit_text()` in `generators/common.py` measures the full string with the bundled font and applies a per-field lossless strategy (`shrink` / `wrap` / `shrink_then_wrap`); it never truncates and raises a diagnostic only when geometry is genuinely impossible. Renderers draw through fitted helpers. `pipeline validate` (and `generate`) run the same measurement as a batch backstop. Budgets are derived from current renderer geometry so day-one output is byte-identical.

**Tech Stack:** Python 3.12, Pillow (PIL ImageFont/ImageDraw), PyYAML, Typer, pytest. Conda env `synthetic`.

**Design spec:** `docs/fit_safety_design.md`.

## Global Constraints

Copied verbatim from the spec and project CLAUDE.md — every task's requirements implicitly include these:

- **Line length:** max 108 chars. Type hints Python 3.12 (`X | Y`, no `from __future__ import annotations`, no `TYPE_CHECKING` guards for runtime-signature types).
- **YAML is the single source of truth.** All `field_budgets` keys (`width`, `fit`, `min_font`, `max_lines`) are **required** — never a silent Python default. Missing key ⇒ fail-fast at load.
- **Fail-fast diagnostics — four elements required:** (1) what is wrong, (2) where to fix it (absolute YAML path + dotted key), (3) what it should look like (valid example + allowed enum values), (4) how to recover (one-line remediation). Tests assert all four via a shared `assert_diagnostic_error` helper.
- **B904:** in `except` blocks, `raise ... from err` or `from None` — never bare re-raise.
- **Never silently truncate/ellipsize** rendered text. Only outcomes: fits losslessly, or fail loud.
- **Determinism:** measure only against the bundled DejaVu faces; identical Mac↔PROD.
- **Do NOT write the Australian tax authority's three-letter acronym** anywhere (use "PROD" if a substitute is ever needed). Some existing docstrings contain it; do not copy those strings into new code — refer to it as the "ABN checksum algorithm".
- **Tests:** `conda run -n synthetic pytest tests/`; `tests/` is gitignored (local-only); min 80% coverage. Mirror source layout under `tests/`.
- **Lint/type before every commit:** `conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py` → `ruff format .` → `mypy . --ignore-missing-imports`. Never bypass pre-commit hooks. No Claude attribution in commits.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `environment.yml` | Pin Pillow for reproducible FreeType metrics | Modify |
| `generators/common.py` | `FitResult`, `fit_text()`, bundled-font guard, fitted draw helpers | Modify |
| `generators/layout_budgets.py` | Load + fail-fast-validate `field_budgets` from a layout dict | Create |
| `config/layouts/receipt.yml` | `field_budgets` per receipt layout | Modify |
| `config/layouts/bank.yml` | `field_budgets` per bank layout | Modify |
| `config/layouts/invoice.yml` | `field_budgets` per invoice layout | Modify |
| `config/layouts/cc.yml` | `field_budgets` per CC layout | Modify |
| `generators/receipt.py` | Draw via fitted helpers | Modify |
| `generators/bank_statement.py` | Draw via fitted helpers | Modify |
| `generators/invoice.py` | Draw via fitted helpers | Modify |
| `generators/cc_statement.py` | Draw via fitted helpers | Modify |
| `generators/pipeline.py` | Overflow backstop in `validate` + `generate` | Modify |
| `tests/...` | Mirror of the above (local-only) | Create |

> Confirm the exact layout filenames first (Task 0). The table assumes `receipt.yml`, `bank.yml`, `invoice.yml`, `cc.yml`; adjust to whatever `config/layouts/` actually contains.

---

## Task 0: Confirm layout filenames and field inventory

**Files:** none changed (discovery only).

- [ ] **Step 1: List layout files and per-renderer variable fields**

Run:
```bash
ls config/layouts/
grep -n "draw_text_center\|draw_text_right\|draw_line_item\|draw.text" \
  generators/receipt.py generators/bank_statement.py \
  generators/invoice.py generators/cc_statement.py
```
Expected: the four layout YAML paths, and every text-draw call site per renderer. Record, for each renderer, the **variable** fields (content that changes per entry: supplier/account names, addresses, ABN lines, phone, line-item descriptions, amounts) versus **fixed** labels (`SUBTOTAL`, `GST`, `TOTAL` literals). Only variable fields get budgets.

- [ ] **Step 2: No commit** (discovery task).

---

## Task 1: Pin Pillow in environment.yml

**Files:**
- Modify: `environment.yml:23`
- Test: `tests/test_environment_pins.py`

**Interfaces:**
- Produces: a pinned `pillow==<version>` line. No code symbols.

- [ ] **Step 1: Capture the version currently in the env**

Run: `conda run -n synthetic python -c "import PIL; print(PIL.__version__)"`
Record the printed version (e.g. `11.3.0`). Use it as `<version>` below.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_environment_pins.py
from pathlib import Path

import yaml


def _pip_deps() -> list[str]:
    env = yaml.safe_load(Path("environment.yml").read_text())
    for dep in env["dependencies"]:
        if isinstance(dep, dict) and "pip" in dep:
            return dep["pip"]
    raise AssertionError("no pip section in environment.yml")


def test_pillow_is_pinned():
    pins = _pip_deps()
    assert any(d.startswith("pillow==") for d in pins), (
        f"pillow must be pinned for reproducible FreeType metrics; got {pins}"
    )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_environment_pins.py -v`
Expected: FAIL (current line is a bare `pillow`).

- [ ] **Step 4: Pin Pillow**

In `environment.yml`, replace the bare `- pillow` (line 23) with, mirroring the faker/opencv comment style:
```yaml
      # Pinned: Pillow's FreeType version drives font getbbox() metrics, which
      # drive every fit_text() shrink/wrap decision and the rendered pixels.
      # Pinning keeps images and fit results byte-stable across rebuilds / Mac<->PROD.
      - pillow==<version>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/test_environment_pins.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add environment.yml
git commit -m "📌 deps: pin pillow for reproducible font metrics (fit-safety)"
```

---

## Task 2: Bundled-font guard

Ensure `fit_text` can only measure against a bundled DejaVu face; fail loud if `load_font` fell back to a system font.

**Files:**
- Modify: `generators/common.py` (near `load_font`, ~L45-97)
- Test: `tests/generators/test_font_guard.py`

**Interfaces:**
- Produces: `font_source_path(font: Font) -> Path | None` returns the file a font was loaded from, or `None` if unknown. `assert_bundled_font(font: Font) -> None` raises `FontSourceError` (a `RuntimeError` subclass) with a four-element diagnostic if the font is not under `_BUNDLED_FONTS_DIR`.
- Consumes (later tasks): `fit_text` calls `assert_bundled_font` on the font it measures.

- [ ] **Step 1: Write the failing test**

```python
# tests/generators/test_font_guard.py
from pathlib import Path

import pytest
from PIL import ImageFont

from generators.common import (
    FontSourceError,
    assert_bundled_font,
    load_font,
)


def test_bundled_font_passes_guard():
    assert_bundled_font(load_font(20))  # bundled DejaVuSans -> no raise


def test_system_font_fails_guard():
    system = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
    with pytest.raises(FontSourceError) as exc:
        assert_bundled_font(system)
    msg = str(exc.value)
    assert "not a bundled font" in msg          # what
    assert "fonts/" in msg                        # where
    assert "DejaVuSans" in msg                    # what it should look like
    assert "reinstall" in msg or "restore" in msg # how to recover
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/generators/test_font_guard.py -v`
Expected: FAIL — `ImportError: cannot import name 'FontSourceError'`.

- [ ] **Step 3: Implement the guard**

In `generators/common.py`, record each font's source path when loading and add the guard:

```python
class FontSourceError(RuntimeError):
    """Raised when a font used for measurement is not the bundled DejaVu face."""


# Maps id(font) -> Path it was loaded from (bundled or system).
_FONT_SOURCE: dict[int, Path] = {}
```

In `load_font`, immediately after `font = ImageFont.truetype(str(p), size)`, record the source:
```python
                font = ImageFont.truetype(str(p), size)
                _FONT_SOURCE[id(font)] = p
                break
```

Then add:
```python
def font_source_path(font: Font) -> Path | None:
    """Return the file a font was loaded from, or None if unknown."""
    return _FONT_SOURCE.get(id(font))


def assert_bundled_font(font: Font) -> None:
    """Fail loud if `font` was not loaded from the bundled fonts/ directory.

    load_font() silently falls back to system fonts when a bundled file is
    missing; measuring against a system font would diverge Mac<->PROD.
    """
    src = font_source_path(font)
    if src is not None and _BUNDLED_FONTS_DIR in src.parents:
        return
    raise FontSourceError(
        "Font used for measurement is not a bundled font.\n"
        f"  What:  fit measurement requires a bundled DejaVu face; got {src}.\n"
        f"  Where: bundled fonts directory {_BUNDLED_FONTS_DIR}\n"
        "  Expected: fonts/DejaVuSans.ttf (and -Bold / Mono variants) present so\n"
        "            load_font() resolves bundled-first, not a system fallback.\n"
        "  Recover: restore/reinstall the fonts/ directory from the repo, then rerun."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/generators/test_font_guard.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type, commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/common.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/common.py
git commit -m "✨ feat: add bundled-font guard for deterministic fit measurement"
```

---

## Task 3: `FitResult` + `fit_text` measurement and `shrink` strategy

**Files:**
- Modify: `generators/common.py`
- Test: `tests/generators/test_fit_text.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class FitResult: lines: list[str]; size: int; line_height: int` — the lossless render plan (one entry per line, the chosen font size, and per-line vertical advance).
  - `FitError(RuntimeError)` — raised when the full string cannot fit.
  - `fit_text(text, *, width, fit, min_font, max_lines, nominal_size, mono=False, bold=False) -> FitResult`. Measures with the bundled font (calls `assert_bundled_font`). This task implements the `fit`=`"shrink"` path and the fits-as-is path; `wrap` / `shrink_then_wrap` are added in Tasks 4–5.
- Consumes: `load_font`, `assert_bundled_font` (Task 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/generators/test_fit_text.py
import pytest

from generators.common import FitError, FitResult, fit_text, load_font


def _measure(text: str, size: int) -> int:
    bbox = load_font(size).getbbox(text)
    return bbox[2] - bbox[0]


def test_fits_as_is_returns_nominal_single_line():
    text = "Coles"
    width = _measure(text, 20) + 50
    r = fit_text(text, width=width, fit="shrink", min_font=12,
                 max_lines=1, nominal_size=20)
    assert r == FitResult(lines=[text], size=20, line_height=load_font(20).size)


def test_shrink_reduces_size_until_it_fits():
    text = "Nguyen & Associates Chartered Accountants"
    tight = _measure(text, 20) - 40           # too wide at 20
    r = fit_text(text, width=tight, fit="shrink", min_font=8,
                 max_lines=1, nominal_size=20)
    assert r.lines == [text]                  # lossless: full string, one line
    assert r.size < 20                        # shrunk
    assert _measure(text, r.size) <= tight    # actually fits


def test_shrink_raises_fiterror_below_floor():
    text = "Nguyen & Associates Chartered Accountants Pty Ltd"
    impossible = _measure(text, 8) - 5        # cannot fit even at floor 8
    with pytest.raises(FitError):
        fit_text(text, width=impossible, fit="shrink", min_font=8,
                 max_lines=1, nominal_size=20)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/generators/test_fit_text.py -v`
Expected: FAIL — `cannot import name 'fit_text'`.

- [ ] **Step 3: Implement `FitResult`, `FitError`, and `fit_text` (shrink + fits-as-is)**

Add to `generators/common.py`:
```python
from dataclasses import dataclass

FitStrategy = str  # one of: "shrink", "wrap", "shrink_then_wrap"
_FIT_STRATEGIES = ("shrink", "wrap", "shrink_then_wrap")


@dataclass(frozen=True)
class FitResult:
    """Lossless render plan for a field: the full string laid out to fit its box."""

    lines: list[str]
    size: int
    line_height: int


class FitError(RuntimeError):
    """Raised when a string cannot fit its box even at the font floor / max lines."""


def _text_width(text: str, size: int, *, mono: bool, bold: bool) -> int:
    font = load_font(size, mono=mono, bold=bold)
    assert_bundled_font(font)
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def fit_text(
    text: str,
    *,
    width: int,
    fit: FitStrategy,
    min_font: int,
    max_lines: int,
    nominal_size: int,
    mono: bool = False,
    bold: bool = False,
) -> FitResult:
    """Compute a lossless layout of `text` fitting within `width` px.

    Never truncates. Raises FitError if the full string cannot fit.
    """
    if fit not in _FIT_STRATEGIES:
        raise ValueError(f"unknown fit strategy {fit!r}; allowed: {_FIT_STRATEGIES}")

    def line_height(size: int) -> int:
        return load_font(size, mono=mono, bold=bold).size

    # Fits as-is at nominal size on one line -> unchanged (day-one path).
    if _text_width(text, nominal_size, mono=mono, bold=bold) <= width:
        return FitResult(lines=[text], size=nominal_size, line_height=line_height(nominal_size))

    if fit == "shrink":
        for size in range(nominal_size - 1, min_font - 1, -1):
            if _text_width(text, size, mono=mono, bold=bold) <= width:
                return FitResult(lines=[text], size=size, line_height=line_height(size))
        raise FitError(
            _fit_error_message(text, width=width, min_font=min_font,
                               max_lines=max_lines, fit=fit)
        )

    # wrap / shrink_then_wrap added in Tasks 4-5.
    raise NotImplementedError(fit)


def _fit_error_message(text: str, *, width: int, min_font: int,
                       max_lines: int, fit: str) -> str:
    """Four-element diagnostic body (caller prepends entry/field context)."""
    return (
        f"string cannot fit its box losslessly.\n"
        f"  What:     {text!r} exceeds width {width}px at min_font {min_font} "
        f"across max_lines {max_lines} (fit={fit}).\n"
        "  Where:    the field's `field_budgets` entry in its config/layouts/*.yml.\n"
        "  Expected: width >= measured, or larger max_lines, or lower min_font; "
        f"fit one of shrink|wrap|shrink_then_wrap.\n"
        "  Recover:  raise `width` (or `max_lines`) for this field in the layout YAML; "
        "never truncate the string."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/generators/test_fit_text.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint, type, commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/common.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/common.py tests/generators/test_fit_text.py
git commit -m "✨ feat: add fit_text with shrink strategy and FitResult"
```

---

## Task 4: `wrap` strategy

**Files:**
- Modify: `generators/common.py` (`fit_text`)
- Test: `tests/generators/test_fit_text.py` (add cases)

**Interfaces:**
- Consumes: `fit_text` from Task 3.
- Produces: `fit="wrap"` returns a `FitResult` whose `lines` are the full string word-wrapped to ≤ `max_lines`, each ≤ `width`, at `nominal_size`; raises `FitError` if it needs more than `max_lines`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/generators/test_fit_text.py
def test_wrap_splits_into_allowed_lines():
    text = "Nguyen and Associates Chartered Accountants"
    width = _measure("Nguyen and Associates", 20) + 10
    r = fit_text(text, width=width, fit="wrap", min_font=20,
                 max_lines=3, nominal_size=20)
    assert " ".join(r.lines) == text          # lossless: words preserved in order
    assert len(r.lines) <= 3
    assert all(_measure(line, 20) <= width for line in r.lines)


def test_wrap_raises_when_exceeds_max_lines():
    text = "Nguyen and Associates Chartered Accountants Group"
    width = _measure("Nguyen", 20) + 5
    with pytest.raises(FitError):
        fit_text(text, width=width, fit="wrap", min_font=20,
                 max_lines=2, nominal_size=20)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/generators/test_fit_text.py -k wrap -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement wrap**

In `fit_text`, replace the `raise NotImplementedError(fit)` tail with a wrap helper and dispatch:
```python
    if fit == "wrap":
        lines = _wrap_to_width(text, width=width, size=nominal_size, mono=mono, bold=bold)
        if lines is None or len(lines) > max_lines:
            raise FitError(
                _fit_error_message(text, width=width, min_font=min_font,
                                   max_lines=max_lines, fit=fit)
            )
        return FitResult(lines=lines, size=nominal_size, line_height=line_height(nominal_size))

    raise NotImplementedError(fit)  # shrink_then_wrap -> Task 5
```

Add module-level:
```python
def _wrap_to_width(text: str, *, width: int, size: int,
                  mono: bool, bold: bool) -> list[str] | None:
    """Greedy word-wrap. Returns lines each within `width`, or None if a single
    word cannot fit (caller treats None as unfittable)."""
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        if _text_width(word, size, mono=mono, bold=bold) > width:
            return None  # unbreakable word wider than the box
        candidate = word if not current else f"{current} {word}"
        if _text_width(candidate, size, mono=mono, bold=bold) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/generators/test_fit_text.py -v`
Expected: PASS (all fit_text tests).

- [ ] **Step 5: Lint, type, commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/common.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/common.py tests/generators/test_fit_text.py
git commit -m "✨ feat: add wrap strategy to fit_text"
```

---

## Task 5: `shrink_then_wrap` strategy + impossible-fit diagnostic

**Files:**
- Modify: `generators/common.py` (`fit_text`)
- Test: `tests/generators/test_fit_text.py` (add cases), `tests/conftest.py` (shared helper)

**Interfaces:**
- Consumes: `fit_text`, `_wrap_to_width` (Tasks 3–4).
- Produces: `fit="shrink_then_wrap"` shrinks toward `min_font`; at each size tries single-line, then wrap to ≤ `max_lines`; returns the first fitting `FitResult`; raises `FitError` if none fit. `assert_diagnostic_error` shared test helper.

- [ ] **Step 1: Add the shared diagnostic assertion helper**

```python
# tests/conftest.py
def assert_diagnostic_error(message: str) -> None:
    """Assert an error message carries all four fail-fast elements."""
    low = message.lower()
    assert "what:" in low, f"missing WHAT in: {message}"
    assert "where:" in low, f"missing WHERE in: {message}"
    assert "expected:" in low, f"missing EXPECTED in: {message}"
    assert "recover:" in low, f"missing RECOVER in: {message}"
```

- [ ] **Step 2: Write the failing tests**

```python
# add to tests/generators/test_fit_text.py
from tests.conftest import assert_diagnostic_error


def test_shrink_then_wrap_prefers_shrink_then_wraps():
    text = "Nguyen and Associates Chartered Accountants"
    width = _measure("Nguyen and Associates", 20) + 10
    r = fit_text(text, width=width, fit="shrink_then_wrap", min_font=10,
                 max_lines=2, nominal_size=20)
    assert " ".join(r.lines) == text
    assert len(r.lines) <= 2


def test_impossible_fit_raises_four_element_diagnostic():
    text = "Nguyen and Associates Chartered Accountants Group Pty Limited"
    width = _measure("Ng", 10)
    with pytest.raises(FitError) as exc:
        fit_text(text, width=width, fit="shrink_then_wrap", min_font=10,
                 max_lines=2, nominal_size=20)
    assert_diagnostic_error(str(exc.value))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/generators/test_fit_text.py -k "shrink_then_wrap or impossible" -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 4: Implement shrink_then_wrap**

Replace the final `raise NotImplementedError(fit)` in `fit_text` with:
```python
    if fit == "shrink_then_wrap":
        for size in range(nominal_size, min_font - 1, -1):
            if _text_width(text, size, mono=mono, bold=bold) <= width:
                return FitResult(lines=[text], size=size, line_height=line_height(size))
            wrapped = _wrap_to_width(text, width=width, size=size, mono=mono, bold=bold)
            if wrapped is not None and len(wrapped) <= max_lines:
                return FitResult(lines=wrapped, size=size, line_height=line_height(size))
        raise FitError(
            _fit_error_message(text, width=width, min_font=min_font,
                               max_lines=max_lines, fit=fit)
        )

    raise ValueError(f"unhandled fit strategy {fit!r}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/generators/test_fit_text.py -v`
Expected: PASS (all fit_text tests).

- [ ] **Step 6: Lint, type, commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/common.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/common.py tests/generators/test_fit_text.py tests/conftest.py
git commit -m "✨ feat: add shrink_then_wrap strategy and four-element fit diagnostic"
```

---

## Task 6: Fitted draw helpers

Give renderers one-line, fit-aware replacements for `draw_text_center` / `draw_text_right` / left `draw.text`, so per-renderer wiring is a call-site swap. Each helper fits the string then draws every line, returning the y-advance.

**Files:**
- Modify: `generators/common.py`
- Test: `tests/generators/test_fitted_helpers.py`

**Interfaces:**
- Consumes: `fit_text`, `FitResult`, `load_font`.
- Produces (all return the new `y` after drawing all lines):
  - `draw_fitted_left(draw, text, x, y, *, budget, nominal_size, mono=False, bold=False, fill="black") -> int`
  - `draw_fitted_center(draw, text, y, canvas_width, *, budget, nominal_size, mono=False, bold=False, fill="black") -> int`
  - `draw_fitted_right(draw, text, x_right, y, *, budget, nominal_size, mono=False, bold=False, fill="black") -> int`
  - `budget` is a `FieldBudget` mapping with keys `width`, `fit`, `min_font`, `max_lines` (loaded in Task 7).

- [ ] **Step 1: Write the failing test**

```python
# tests/generators/test_fitted_helpers.py
from PIL import Image, ImageDraw

from generators.common import draw_fitted_center, draw_fitted_left, draw_fitted_right

BUDGET = {"width": 300, "fit": "shrink", "min_font": 8, "max_lines": 1}


def _draw():
    img = Image.new("RGB", (400, 200), "white")
    return img, ImageDraw.Draw(img)


def test_fitted_left_returns_advanced_y():
    _, d = _draw()
    y = draw_fitted_left(d, "Coles", x=10, y=20, budget=BUDGET, nominal_size=20)
    assert y > 20


def test_fitted_center_wraps_and_advances_more_for_two_lines():
    _, d = _draw()
    wide = {"width": 120, "fit": "wrap", "min_font": 20, "max_lines": 2}
    y1 = draw_fitted_center(d, "Short", y=0, canvas_width=400, budget=BUDGET, nominal_size=20)
    y2 = draw_fitted_center(d, "Nguyen and Associates Accountants", y=0,
                            canvas_width=400, budget=wide, nominal_size=20)
    assert y2 > y1  # two wrapped lines advance further than one


def test_fitted_right_draws_within_canvas():
    _, d = _draw()
    y = draw_fitted_right(d, "$1,234.56", x_right=390, y=30, budget=BUDGET, nominal_size=20)
    assert y > 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/generators/test_fitted_helpers.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement the helpers**

Add to `generators/common.py`:
```python
def _fit_from_budget(text: str, budget: dict, nominal_size: int,
                    *, mono: bool, bold: bool) -> FitResult:
    return fit_text(
        text,
        width=budget["width"],
        fit=budget["fit"],
        min_font=budget["min_font"],
        max_lines=budget["max_lines"],
        nominal_size=nominal_size,
        mono=mono,
        bold=bold,
    )


def draw_fitted_left(draw, text, x, y, *, budget, nominal_size,
                    mono=False, bold=False, fill="black") -> int:
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    for line in r.lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += r.line_height
    return y


def draw_fitted_center(draw, text, y, canvas_width, *, budget, nominal_size,
                      mono=False, bold=False, fill="black") -> int:
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    for line in r.lines:
        w = font.getbbox(line)[2] - font.getbbox(line)[0]
        draw.text(((canvas_width - w) // 2, y), line, font=font, fill=fill)
        y += r.line_height
    return y


def draw_fitted_right(draw, text, x_right, y, *, budget, nominal_size,
                     mono=False, bold=False, fill="black") -> int:
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    for line in r.lines:
        w = font.getbbox(line)[2] - font.getbbox(line)[0]
        draw.text((x_right - w, y), line, font=font, fill=fill)
        y += r.line_height
    return y
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/generators/test_fitted_helpers.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type, commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/common.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/common.py tests/generators/test_fitted_helpers.py
git commit -m "✨ feat: add fitted draw helpers (left/center/right)"
```

---

## Task 7: `field_budgets` schema loader with fail-fast validation

**Files:**
- Create: `generators/layout_budgets.py`
- Test: `tests/generators/test_layout_budgets.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure YAML validation).
- Produces:
  - `REQUIRED_BUDGET_KEYS = ("width", "fit", "min_font", "max_lines")`, `ALLOWED_FITS = ("shrink", "wrap", "shrink_then_wrap")`.
  - `class LayoutBudgetError(RuntimeError)`.
  - `field_budget(layout: dict, layout_id: str, field: str, *, layout_path: str) -> dict` — returns the validated budget dict for one field; raises `LayoutBudgetError` (four-element diagnostic) if `field_budgets`, the field, or any required key is missing, or `fit`/numeric values are invalid.

- [ ] **Step 1: Write the failing tests**

```python
# tests/generators/test_layout_budgets.py
import pytest

from generators.layout_budgets import LayoutBudgetError, field_budget
from tests.conftest import assert_diagnostic_error

GOOD = {
    "field_budgets": {
        "SUPPLIER_NAME": {"width": 360, "fit": "shrink_then_wrap",
                          "min_font": 12, "max_lines": 2},
    }
}


def test_returns_valid_budget():
    b = field_budget(GOOD, "receipt_thermal_80mm", "SUPPLIER_NAME",
                     layout_path="config/layouts/receipt.yml")
    assert b == GOOD["field_budgets"]["SUPPLIER_NAME"]


def test_missing_field_budgets_block_is_diagnostic():
    with pytest.raises(LayoutBudgetError) as exc:
        field_budget({}, "receipt_thermal_80mm", "SUPPLIER_NAME",
                     layout_path="config/layouts/receipt.yml")
    assert_diagnostic_error(str(exc.value))


def test_missing_required_key_is_diagnostic():
    bad = {"field_budgets": {"SUPPLIER_NAME": {"width": 360, "fit": "shrink"}}}
    with pytest.raises(LayoutBudgetError) as exc:
        field_budget(bad, "receipt_thermal_80mm", "SUPPLIER_NAME",
                     layout_path="config/layouts/receipt.yml")
    msg = str(exc.value)
    assert_diagnostic_error(msg)
    assert "min_font" in msg and "max_lines" in msg


def test_invalid_fit_enum_is_diagnostic():
    bad = {"field_budgets": {"X": {"width": 1, "fit": "chop",
                                   "min_font": 8, "max_lines": 1}}}
    with pytest.raises(LayoutBudgetError) as exc:
        field_budget(bad, "L", "X", layout_path="config/layouts/receipt.yml")
    assert_diagnostic_error(str(exc.value))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/generators/test_layout_budgets.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the loader**

```python
# generators/layout_budgets.py
"""Load and fail-fast-validate per-field pixel budgets from a layout dict.

Budgets are the single source of truth for how a variable field is allowed to
fit its box. Every key is required — no silent defaults.
"""

REQUIRED_BUDGET_KEYS = ("width", "fit", "min_font", "max_lines")
ALLOWED_FITS = ("shrink", "wrap", "shrink_then_wrap")


class LayoutBudgetError(RuntimeError):
    """Raised when a layout's field_budgets block is missing or malformed."""


def _err(what: str, *, layout_path: str, key_path: str, expected: str,
        recover: str) -> "LayoutBudgetError":
    return LayoutBudgetError(
        f"Invalid field_budgets.\n"
        f"  What:     {what}\n"
        f"  Where:    {layout_path} -> {key_path}\n"
        f"  Expected: {expected}\n"
        f"  Recover:  {recover}"
    )


def field_budget(layout: dict, layout_id: str, field: str, *, layout_path: str) -> dict:
    """Return the validated budget dict for `field` in `layout`."""
    budgets = layout.get("field_budgets")
    if not isinstance(budgets, dict):
        raise _err(
            f"layout '{layout_id}' has no field_budgets block.",
            layout_path=layout_path, key_path=f"{layout_id}.field_budgets",
            expected="a mapping of FIELD -> {width, fit, min_font, max_lines}.",
            recover=f"add a field_budgets block under {layout_id}.",
        )
    entry = budgets.get(field)
    if not isinstance(entry, dict):
        raise _err(
            f"field '{field}' has no budget in layout '{layout_id}'.",
            layout_path=layout_path,
            key_path=f"{layout_id}.field_budgets.{field}",
            expected="width (int px), fit (shrink|wrap|shrink_then_wrap), "
                     "min_font (int), max_lines (int >= 1).",
            recover=f"add {field}: {{width, fit, min_font, max_lines}}.",
        )
    missing = [k for k in REQUIRED_BUDGET_KEYS if k not in entry]
    if missing:
        raise _err(
            f"field '{field}' budget missing key(s): {missing}.",
            layout_path=layout_path,
            key_path=f"{layout_id}.field_budgets.{field}",
            expected=f"all of {list(REQUIRED_BUDGET_KEYS)} present.",
            recover=f"add {missing} to {field}.",
        )
    if entry["fit"] not in ALLOWED_FITS:
        raise _err(
            f"field '{field}' has invalid fit {entry['fit']!r}.",
            layout_path=layout_path,
            key_path=f"{layout_id}.field_budgets.{field}.fit",
            expected=f"one of {list(ALLOWED_FITS)}.",
            recover="set fit to an allowed value.",
        )
    for k in ("width", "min_font", "max_lines"):
        if not isinstance(entry[k], int) or entry[k] < 1:
            raise _err(
                f"field '{field}' has invalid {k}={entry[k]!r}.",
                layout_path=layout_path,
                key_path=f"{layout_id}.field_budgets.{field}.{k}",
                expected=f"{k} must be a positive int.",
                recover=f"set {k} to a positive integer.",
            )
    return entry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/generators/test_layout_budgets.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint, type, commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/layout_budgets.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/layout_budgets.py tests/generators/test_layout_budgets.py
git commit -m "✨ feat: add fail-fast field_budgets loader"
```

---

## Task 8: Receipt — derive budgets, wire renderer, prove byte-identical output

This is the reference wiring task; Tasks 9–11 repeat the same procedure with each renderer's own field table.

**Files:**
- Modify: `config/layouts/receipt.yml`, `generators/receipt.py`
- Test: `tests/generators/test_receipt_fit.py`, `tests/fixtures/receipt_baseline_hashes.json`

**Interfaces:**
- Consumes: `draw_fitted_left/center/right` (Task 6), `field_budget` (Task 7).
- Produces: receipt layouts carrying `field_budgets`; `receipt.py` drawing all variable fields through fitted helpers.

- [ ] **Step 1: Capture baseline PNG hashes from CURRENT code (before any change)**

```bash
conda run -n synthetic python -m generators.pipeline generate --type receipts --clean-only
conda run -n synthetic python - <<'PY'
import hashlib, json, pathlib
out = {}
for p in sorted(pathlib.Path("output/clean").glob("*receipt*.png")):
    out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
pathlib.Path("tests/fixtures").mkdir(parents=True, exist_ok=True)
pathlib.Path("tests/fixtures/receipt_baseline_hashes.json").write_text(json.dumps(out, indent=2))
print("captured", len(out), "baselines")
PY
```
> NOTE: this `<<'PY'` heredoc is being pasted directly into a terminal by the human executor, NOT run through an agent Bash tool. Agentic workers must instead write a throwaway script file with the Write tool and run it — never send a heredoc through the Bash tool (it hangs).
Expected: `tests/fixtures/receipt_baseline_hashes.json` with 55 entries.

- [ ] **Step 2: Derive budget widths and add `field_budgets` to `config/layouts/receipt.yml`**

For each receipt layout, using its `width` and `margin`, compute:
- **Centered header fields** (`SUPPLIER_NAME`, `ADDRESS`, `ABN_LINE`, `PHONE`): `width_budget = layout.width - 2 * margin`.
- **Line-item description** (`LINE_ITEM_DESC`): reserve the amount column. Measure the widest realistic amount `"$99,999.99"` at the body font size; `amount_reserve = ceil(that width)`; `desc_budget = layout.width - 2*margin - amount_reserve - 12` (12px gap).
- **Amount** (`LINE_ITEM_AMOUNT`): `width_budget = amount_reserve`.

Add per layout (numbers are the derived values for that layout):
```yaml
  receipt_thermal_80mm:
    # ...existing keys...
    field_budgets:
      SUPPLIER_NAME:    {width: 560, fit: shrink_then_wrap, min_font: 14, max_lines: 2}
      ADDRESS:          {width: 560, fit: shrink_then_wrap, min_font: 12, max_lines: 2}
      ABN_LINE:         {width: 560, fit: shrink,           min_font: 12, max_lines: 1}
      PHONE:            {width: 560, fit: shrink,           min_font: 12, max_lines: 1}
      LINE_ITEM_DESC:   {width: 430, fit: shrink,           min_font: 12, max_lines: 1}
      LINE_ITEM_AMOUNT: {width: 118, fit: shrink,           min_font: 12, max_lines: 1}
```
Repeat for `receipt_thermal_57mm`, `receipt_retail_tax`, `receipt_fuel`, `receipt_professional`, `receipt_hospitality`, substituting each layout's own `width`/`margin` into the formulas above. Header fields use `shrink_then_wrap` (they have vertical room); columns use `shrink` (`max_lines: 1`).

- [ ] **Step 3: Write the failing regression + overflow tests**

```python
# tests/generators/test_receipt_fit.py
import hashlib
import json
from pathlib import Path

import yaml

from generators.layout_budgets import field_budget
from generators.receipt import render_receipt


def _layouts() -> dict:
    return yaml.safe_load(Path("config/layouts/receipt.yml").read_text())


def test_every_receipt_layout_has_budgets_for_variable_fields():
    layouts = _layouts()
    for lid in layouts:
        for field in ("SUPPLIER_NAME", "LINE_ITEM_DESC", "LINE_ITEM_AMOUNT"):
            field_budget(layouts, lid, field, layout_path="config/layouts/receipt.yml")


def test_receipts_render_byte_identical_to_baseline():
    baseline = json.loads(Path("tests/fixtures/receipt_baseline_hashes.json").read_text())
    entries = yaml.safe_load(Path("ground_truth/receipts.yml").read_text())
    layouts = _layouts()
    seen = 0
    for entry in entries:
        layout = layouts[entry["layout"]]
        img = render_receipt(entry, layout)
        name = f"{entry['CASE_ID']}_{entry['layout']}.png"
        if name in baseline:
            digest = hashlib.sha256(img.tobytes()).hexdigest()
            # compare pixel content deterministically
            assert digest == baseline_pixel_hash(name, baseline), name
            seen += 1
    assert seen > 0
```
> Adjust the baseline comparison to hash the same bytes both times: capture the baseline in Step 1 from `img.tobytes()` via a small render loop rather than the on-disk PNG if PNG encoding is not deterministic in your Pillow build. Use `render_receipt(entry, layout).tobytes()` on both sides so the test compares raw pixels. Confirm the ground-truth field name (`CASE_ID` vs `case_id`) from `ground_truth/receipts.yml` and the exact `render_receipt` signature before finalizing.

- [ ] **Step 4: Run tests to verify they fail**

Run: `conda run -n synthetic pytest tests/generators/test_receipt_fit.py -v`
Expected: FAIL — budgets/wiring not present yet.

- [ ] **Step 5: Wire `generators/receipt.py` to fitted helpers**

Load budgets once at the top of `render_receipt`:
```python
from generators.layout_budgets import field_budget

_LP = "config/layouts/receipt.yml"

def _b(layout, layout_id, field):
    return field_budget({layout_id: layout, "field_budgets": layout.get("field_budgets", {})},
                        layout_id, field, layout_path=_LP)
```
> Simpler: pass the full layout dict that already contains `field_budgets`; call `field_budget(layout, layout_id, field, layout_path=_LP)` where `layout` is the single-layout dict. Match whatever shape `load_layout_registry` returns (confirm in `generators/schema.py`).

Then replace call sites (from Task 0's grep) — examples:
```python
# was: draw_text_center(draw, fields.get("SUPPLIER_NAME", ""), y, width, font_bold)
y = draw_fitted_center(draw, fields.get("SUPPLIER_NAME", ""), y, width,
                       budget=_b(layout, layout_id, "SUPPLIER_NAME"),
                       nominal_size=font_size, mono=is_mono, bold=True)

# was: draw_line_item(draw, desc, amount_str, y, font, margin, width)
draw_fitted_left(draw, desc, margin, y,
                 budget=_b(layout, layout_id, "LINE_ITEM_DESC"),
                 nominal_size=font_size, mono=is_mono)
draw_fitted_right(draw, amount_str, width - margin, y,
                  budget=_b(layout, layout_id, "LINE_ITEM_AMOUNT"),
                  nominal_size=font_size, mono=is_mono)
```
Keep the existing `y += ...` advances for fixed-label rows unchanged. Fixed labels (`SUBTOTAL`, `GST`, `TOTAL`) keep their current `draw_line_item` calls — they are constant and need no budget.

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n synthetic pytest tests/generators/test_receipt_fit.py -v`
Expected: PASS — byte-identical (derived widths match current geometry, so `fit_text` takes the fits-as-is path).

- [ ] **Step 7: Lint, type, commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 generators/receipt.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add config/layouts/receipt.yml generators/receipt.py
git commit -m "✨ feat: fit-safe receipt rendering with derived field_budgets"
```

---

## Task 9: Bank statement — derive budgets, wire renderer, byte-identical

**Files:**
- Modify: `config/layouts/bank.yml`, `generators/bank_statement.py`
- Test: `tests/generators/test_bank_fit.py`, `tests/fixtures/bank_baseline_hashes.json`

**Interfaces:** same helpers as Task 8.

- [ ] **Step 1: Capture baseline pixel hashes from current code** — same procedure as Task 8 Step 1, writing `tests/fixtures/bank_baseline_hashes.json` via a Write-tool script (`render` each bank entry, hash `img.tobytes()`).
- [ ] **Step 2: Enumerate bank variable fields** from Task 0's grep (e.g. `ACCOUNT_HOLDER`, `ACCOUNT_ADDRESS`, `BANK_NAME`, `TXN_DESCRIPTION`, `TXN_AMOUNT`, `BALANCE`). For the wide bank canvas (~1800px), transaction description and the amount/balance columns are the collision risk: reserve amount and balance columns by measuring `"$999,999.99"`, and set `TXN_DESCRIPTION.width = column_x_of_amount - left_margin - gap`. Header fields use `shrink_then_wrap`; columns use `shrink`, `max_lines: 1`.
- [ ] **Step 3: Add `field_budgets` to each of the 8 bank layouts** using the same formulas (Task 8 Step 2), substituting each layout's geometry.
- [ ] **Step 4: Write failing regression + budget-presence tests** (copy the Task 8 Step 3 structure, pointing at `bank.yml`, `ground_truth/bank_statements.yml`, `render_bank_statement`).
- [ ] **Step 5: Run to verify they fail.**
- [ ] **Step 6: Wire `generators/bank_statement.py`** call sites to `draw_fitted_left/center/right` (same swap pattern as Task 8 Step 5).
- [ ] **Step 7: Run tests — expect byte-identical PASS.**
- [ ] **Step 8: Lint, type, commit** `git commit -m "✨ feat: fit-safe bank statement rendering with derived field_budgets"`

---

## Task 10: Invoice — derive budgets, wire renderer, byte-identical

**Files:**
- Modify: `config/layouts/invoice.yml`, `generators/invoice.py`
- Test: `tests/generators/test_invoice_fit.py`, `tests/fixtures/invoice_baseline_hashes.json`

- [ ] **Step 1: Capture baseline pixel hashes** for the 4 invoice layouts (Task 8 Step 1 procedure, Write-tool script).
- [ ] **Step 2: Enumerate invoice variable fields** (e.g. `SUPPLIER_NAME`, `SUPPLIER_ABN`, `BILL_TO_NAME`, `BILL_TO_ADDRESS`, `LINE_ITEM_DESC`, `LINE_ITEM_QTY`, `LINE_ITEM_PRICE`, `LINE_ITEM_TOTAL`). Line-item table has multiple numeric columns — reserve each by measuring its widest realistic value; description width = remaining space to the first numeric column minus gap.
- [ ] **Step 3: Add `field_budgets` to the 4 invoice layouts** using Task 8 formulas.
- [ ] **Step 4: Write failing regression + budget-presence tests** pointing at `invoice.yml`, `ground_truth/invoices.yml`, `render_invoice`.
- [ ] **Step 5: Run to verify they fail.**
- [ ] **Step 6: Wire `generators/invoice.py`** call sites to fitted helpers.
- [ ] **Step 7: Run tests — expect byte-identical PASS.**
- [ ] **Step 8: Lint, type, commit** `git commit -m "✨ feat: fit-safe invoice rendering with derived field_budgets"`

---

## Task 11: CC statement — derive budgets, wire renderer, byte-identical

**Files:**
- Modify: `config/layouts/cc.yml`, `generators/cc_statement.py`
- Test: `tests/generators/test_cc_fit.py`, `tests/fixtures/cc_baseline_hashes.json`

- [ ] **Step 1: Capture baseline pixel hashes** for the 8 CC layouts (Task 8 Step 1 procedure).
- [ ] **Step 2: Enumerate CC variable fields** (e.g. `CARDHOLDER_NAME`, `CARD_ADDRESS`, `BANK_NAME`, `TXN_DESCRIPTION`, `TXN_AMOUNT`). Same column-reservation approach as bank statements.
- [ ] **Step 3: Add `field_budgets` to the 8 CC layouts** using Task 8 formulas.
- [ ] **Step 4: Write failing regression + budget-presence tests** pointing at `cc.yml`, `ground_truth/cc_statements.yml`, `render_cc_statement`.
- [ ] **Step 5: Run to verify they fail.**
- [ ] **Step 6: Wire `generators/cc_statement.py`** call sites to fitted helpers.
- [ ] **Step 7: Run tests — expect byte-identical PASS.**
- [ ] **Step 8: Lint, type, commit** `git commit -m "✨ feat: fit-safe CC statement rendering with derived field_budgets"`

---

## Task 12: Overflow validation backstop in `pipeline validate` and `generate`

**Files:**
- Modify: `generators/pipeline.py` (`validate` ~L47, `generate` ~L117)
- Create: `generators/overflow_check.py`
- Test: `tests/test_overflow_backstop.py`

**Interfaces:**
- Consumes: `fit_text` + `FitError` (Tasks 3–5), `field_budget` (Task 7), layout registry loader (existing `load_layout_registry`).
- Produces:
  - `check_overflow(entries, layouts, *, layout_path, variable_fields) -> list[str]` — returns a list of human-readable violation lines (empty if all fit). Each entry/field is measured with its budget; a `FitError` becomes one violation line (entry id, field, measured vs budget). **Collects all**, never raises mid-scan.
  - `variable_fields`: the per-doc-type field list established in Tasks 8–11.
  - `class OverflowError_(RuntimeError)` raised by callers with the aggregated report (four-element diagnostic).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_overflow_backstop.py
import pytest

from generators.overflow_check import check_overflow
from tests.conftest import assert_diagnostic_error, aggregated_overflow_error

LAYOUTS = {
    "L": {"field_budgets": {
        "NAME": {"width": 5, "fit": "shrink", "min_font": 8, "max_lines": 1}}}
}
ENTRIES = [{"CASE_ID": "CASE001", "layout": "L",
            "NAME": "A Very Long Unfittable Supplier Name"}]


def test_collects_all_violations_without_raising():
    violations = check_overflow(ENTRIES, LAYOUTS,
                                layout_path="config/layouts/receipt.yml",
                                variable_fields=["NAME"])
    assert len(violations) == 1
    assert "CASE001" in violations[0] and "NAME" in violations[0]


def test_no_violations_when_everything_fits():
    layouts = {"L": {"field_budgets": {
        "NAME": {"width": 9999, "fit": "shrink", "min_font": 8, "max_lines": 1}}}}
    violations = check_overflow(ENTRIES, layouts,
                                layout_path="config/layouts/receipt.yml",
                                variable_fields=["NAME"])
    assert violations == []


def test_aggregated_error_is_four_element_diagnostic():
    violations = ["CASE001 / NAME: 40px > 5px"]
    assert_diagnostic_error(str(aggregated_overflow_error(violations,
                            layout_path="config/layouts/receipt.yml")))
```
Add to `tests/conftest.py`:
```python
def aggregated_overflow_error(violations, *, layout_path):
    from generators.overflow_check import build_overflow_error
    return build_overflow_error(violations, layout_path=layout_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n synthetic pytest tests/test_overflow_backstop.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `generators/overflow_check.py`**

```python
"""Batch overflow backstop: measure every variable field against its budget.

Collects ALL genuinely-unfittable violations into one report so a reseed
surfaces every problem in a single pass. Routine length variation is handled
losslessly at render time by fit_text and does not appear here.
"""

from generators.common import FitError, fit_text
from generators.layout_budgets import field_budget

_NOMINAL = 20  # measurement reference size; render uses each layout's own font size


class OverflowError_(RuntimeError):
    """Aggregated render-overflow report across a ground-truth file."""


def check_overflow(entries, layouts, *, layout_path, variable_fields) -> list[str]:
    violations: list[str] = []
    for entry in entries:
        layout_id = entry.get("layout", "")
        layout = layouts.get(layout_id, {})
        for field in variable_fields:
            value = str(entry.get(field, ""))
            if not value:
                continue
            budget = field_budget(layout, layout_id, field, layout_path=layout_path)
            try:
                fit_text(value, width=budget["width"], fit=budget["fit"],
                         min_font=budget["min_font"], max_lines=budget["max_lines"],
                         nominal_size=_NOMINAL)
            except FitError:
                cid = entry.get("CASE_ID", "?")
                violations.append(f"{cid} / {layout_id} / {field}: "
                                  f"{value!r} exceeds width {budget['width']}px")
    return violations


def build_overflow_error(violations, *, layout_path) -> "OverflowError_":
    listing = "\n    ".join(violations)
    return OverflowError_(
        "Content overflow: fields cannot fit their boxes losslessly.\n"
        f"  What:     {len(violations)} field(s) overflow:\n    {listing}\n"
        f"  Where:    field_budgets entries in {layout_path}.\n"
        "  Expected: each listed field's rendered string <= its budget width, or a\n"
        "            larger max_lines / lower min_font.\n"
        "  Recover:  widen `width` (or `max_lines`) for the listed fields in the "
        "layout YAML, or shorten the source strings; never truncate."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n synthetic pytest tests/test_overflow_backstop.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into `pipeline.py` `validate` and `generate`**

In `validate`, after the existing layout-reference check, for each doc type call `check_overflow(entries, layouts, layout_path=doc_cfg["layouts"], variable_fields=VARIABLE_FIELDS[doc_type])`; accumulate across all types; if any, `raise build_overflow_error(all_violations, layout_path=...) from None` (B904) and exit non-zero. In `generate`, run the same check before the render loop and refuse (raise) if non-empty, so no clipped image is produced. Define `VARIABLE_FIELDS` (per doc type) in `generators/overflow_check.py` from Tasks 8–11's field lists.

- [ ] **Step 6: Add integration tests for the CLI gate**

```python
# tests/test_overflow_backstop.py (add)
def test_validate_passes_on_current_ground_truth():
    # The 220 shipped docs all fit; validate must not raise.
    from typer.testing import CliRunner
    from generators.pipeline import app
    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 0, result.output
```

- [ ] **Step 7: Run the full suite**

Run: `conda run -n synthetic pytest tests/ -v`
Expected: PASS. Then confirm real CLI: `conda run -n synthetic python -m generators.pipeline validate` exits 0.

- [ ] **Step 8: Lint, type, commit**

```bash
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py generators/*.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
git add generators/overflow_check.py generators/pipeline.py
git commit -m "✨ feat: add fail-fast overflow backstop to validate and generate"
```

---

## Final verification

- [ ] `conda run -n synthetic pytest tests/ --cov=generators` — all pass, ≥80% coverage.
- [ ] `conda run -n synthetic python -m generators.pipeline validate` — exits 0 on the shipped 220 docs.
- [ ] `conda run -n synthetic python -m generators.pipeline generate --clean-only` — regenerates; spot-check that output is unchanged (baseline hashes still match).
- [ ] Confirm no rendered field is ever truncated: every fit path returns the full string or raises.

---

## Self-review notes (author)

- **Spec coverage:** §2 schema → Tasks 7–11; §3 fit_text → Tasks 3–6; §4 backstop → Task 12; §5 derive-from-geometry → Tasks 8–11; §6 determinism (bundled font guard + Pillow pin) → Tasks 1–2; §7 testing → per-task TDD + regression; §8 non-goals respected (no content widening, no generation-time regeneration, no full geometry migration).
- **Assumptions to confirm during Task 0 / Task 8:** exact layout YAML filenames; ground-truth field key casing (`CASE_ID` vs `case_id`); `render_*` signatures and the dict shape returned by `load_layout_registry`; whether PNG encoding is deterministic (else hash `img.tobytes()` on both sides). These are verification steps inside the tasks, not open design questions.
