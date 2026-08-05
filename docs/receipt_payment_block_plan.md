# Receipt Payment Block Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render a realistic Australian EFTPOS terminal block on every synthetic receipt, replacing the single bare payment line.

**Architecture:** A new module `generators/payment_block.py` owns terminal-slip config loading, deterministic derivation, and rendering. `generators/receipt.py`'s `payment` section branch becomes a call into it, and its hardcoded `_PAYMENT_METHODS` list is deleted in favour of a YAML-driven weighted pool. Nothing scored changes: no new columns, no reseed, no geometry capture.

**Tech Stack:** Python 3.12, PIL (Pillow 12.2.0), PyYAML, pytest, conda env `synthetic`.

**Spec:** `docs/receipt_payment_block_design.md`

## Global Constraints

- Conda env is `synthetic`, not the global default. Run every tool as `conda run -n synthetic <cmd>`.
- `tests/` is gitignored — test files are written and run locally but never appear in a commit.
- YAML is the single source of truth. No config value may exist as a Python default or fallback. Every key is required; a missing key raises.
- Every fail-fast diagnostic must contain all four elements as literal labelled lines: `What:`, `Where:`, `Expected:`, `Recover:` (asserted by `tests/conftest.py::assert_diagnostic_error`).
- Line length max 108. Type hints are Python 3.12 style (`X | Y`). Google-style docstrings. `pathlib.Path` for paths.
- In `except` blocks always `raise ... from err` or `from None` (B904).
- Never write the Australian tax authority's three-letter acronym anywhere; use "PROD".
- No Claude attribution in commit messages.
- Pre-commit gate, all four must pass before every commit:
  1. `conda run -n synthetic pytest tests/`
  2. `conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py`
  3. `conda run -n synthetic ruff format .`
  4. `conda run -n synthetic mypy . --ignore-missing-imports`
- Never bypass pre-commit hooks with `--no-verify`.

## File Structure

| File | Responsibility |
| --- | --- |
| `config/data_pools.yml` (modify) | New top-level `payment_terminal:` block — acquirers, schemes, wallets, entry modes, labels, method weights, cash labels |
| `generators/payment_block.py` (create) | Whole feature: `load_terminal_pools()`, `PaymentDetails`, `derive_payment()`, `render_payment_block()`. No knowledge of receipt layout sections |
| `generators/receipt.py` (modify) | Delete `_PAYMENT_METHODS`; drop `payment_method` from `_derive_receipt_details`; `payment` branch delegates to `render_payment_block()` |
| `config/layouts/receipts.yml` (modify) | Add `PAYMENT_ACQUIRER` and `PAYMENT_LINE` budgets to all 6 layouts |
| `tests/test_payment_block.py` (create) | Config validation, derivation determinism, block-variant dispatch, consistency with scored fields |
| `tests/test_receipt_fit.py` (modify) | Extend `_variable_strings` with payment lines; re-capture render baselines |
| `tests/fixtures/receipt_baseline_hashes.json` (regenerate) | Renders change intentionally — re-captured in Task 4 |

Task order is dependency order: config → derivation → rendering → corpus-wide verification.

---

### Task 1: `payment_terminal` config block and fail-fast loader

**Files:**
- Modify: `config/data_pools.yml` (append new top-level key)
- Create: `generators/payment_block.py`
- Test: `tests/test_payment_block.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `load_terminal_pools(path: Path = _DATA_POOLS_PATH) -> dict` returning the validated `payment_terminal` mapping. `lru_cache`d on `path`. Raises `ValueError` with a four-element diagnostic on any missing/invalid key, `FileNotFoundError` if the pools file is absent.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_payment_block.py`:

```python
"""Terminal-block config loading, derivation, and rendering (local-only)."""

import copy
from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error

from generators.payment_block import load_terminal_pools

_POOLS = Path("config/data_pools.yml")

_REQUIRED = [
    "receipt_method_weights",
    "acquirers",
    "schemes",
    "wallets",
    "entry_modes",
    "contactless_label",
    "customer_copy_text",
    "approved_text",
    "response_code",
    "retain_text",
    "cash",
]


def _write_pools(tmp_path: Path, mutate) -> Path:
    """Copy the real pools file, apply `mutate` to payment_terminal, write it out."""
    data = yaml.safe_load(_POOLS.read_text())
    mutate(data["payment_terminal"])
    out = tmp_path / "data_pools.yml"
    out.write_text(yaml.safe_dump(data))
    return out


def test_loads_real_pools_file():
    pools = load_terminal_pools(_POOLS)
    for key in _REQUIRED:
        assert key in pools, f"{key} missing from payment_terminal"


def test_every_scheme_has_required_subkeys():
    schemes = load_terminal_pools(_POOLS)["schemes"]
    assert schemes
    for name, scheme in schemes.items():
        for sub in ("display", "aid", "pan_digits", "account_types"):
            assert sub in scheme, f"scheme {name} missing {sub}"
        assert scheme["account_types"], f"scheme {name} has empty account_types"


def test_every_weighted_method_resolves():
    pools = load_terminal_pools(_POOLS)
    known = set(pools["schemes"]) | set(pools["wallets"]) | {"Cash"}
    assert set(pools["receipt_method_weights"]) <= known


@pytest.mark.parametrize("key", _REQUIRED)
def test_missing_required_key_is_four_element_diagnostic(tmp_path, key):
    path = _write_pools(tmp_path, lambda pt: pt.pop(key))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert key in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_missing_payment_terminal_block_is_diagnostic(tmp_path):
    data = yaml.safe_load(_POOLS.read_text())
    del data["payment_terminal"]
    path = tmp_path / "data_pools.yml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert_diagnostic_error(exc_info.value)


def test_scheme_missing_subkey_is_diagnostic(tmp_path):
    def drop_aid(pt):
        pt["schemes"] = copy.deepcopy(pt["schemes"])
        del pt["schemes"]["Visa"]["aid"]

    path = _write_pools(tmp_path, drop_aid)
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert "aid" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_unknown_weighted_method_is_diagnostic(tmp_path):
    path = _write_pools(tmp_path, lambda pt: pt["receipt_method_weights"].update({"Bitcoin": 5}))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert "Bitcoin" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_non_positive_weight_is_diagnostic(tmp_path):
    path = _write_pools(tmp_path, lambda pt: pt["receipt_method_weights"].update({"Cash": 0}))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert_diagnostic_error(exc_info.value)


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_terminal_pools(tmp_path / "nope.yml")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'generators.payment_block'`.

- [ ] **Step 3: Add the config block**

Append to `config/data_pools.yml` (top level, after the existing `payment_methods:` line — leave `payment_methods:` untouched, other document types use it):

```yaml
# EFTPOS terminal-slip constants for the receipt payment block. Every key is
# required; generators/payment_block.py fails fast on any omission.
payment_terminal:
  # Weighted method pool for receipts. POS-plausible only — deliberately
  # excludes BPAY / PayPal / Bank Transfer, which never print a terminal slip.
  receipt_method_weights:
    EFTPOS: 30
    Visa: 25
    Mastercard: 20
    AMEX: 5
    Cash: 12
    Apple Pay: 5
    Google Pay: 3
  acquirers:
    - Tyro Payments EFTPOS
    - Westpac EFTPOS
    - CBA Smart EFTPOS
    - ANZ Worldline EFTPOS
    - Smartpay EFTPOS
    - NAB EFTPOS
  schemes:
    EFTPOS:
      display: eftpos
      aid: A0000003841001
      pan_digits: 16
      account_types: [SAV, CHQ]
    Visa:
      display: VISA CREDIT
      aid: A0000000031010
      pan_digits: 16
      account_types: [CR]
    Mastercard:
      display: MASTERCARD
      aid: A0000000041010
      pan_digits: 16
      account_types: [CR]
    AMEX:
      display: AMERICAN EXPRESS
      aid: A00000002501
      pan_digits: 15
      account_types: [CR]
  wallets:
    Apple Pay: APPLE PAY
    Google Pay: GOOGLE PAY
  entry_modes:
    card: (c)
    wallet: (t)
  contactless_label: CONTACTLESS
  customer_copy_text: CUSTOMER COPY
  approved_text: APPROVED
  response_code: '00'
  retain_text: Retain copy for your records
  cash:
    tendered_label: CASH TENDERED
    change_label: CHANGE
```

- [ ] **Step 4: Write the loader**

Create `generators/payment_block.py`:

```python
"""EFTPOS terminal-slip block for synthetic receipts.

Owns the `payment_terminal` config in config/data_pools.yml, the deterministic
derivation of per-case terminal values, and the rendering of the three block
variants (card, wallet, cash). generators/receipt.py delegates its `payment`
section here and holds no terminal knowledge of its own.
"""

from functools import lru_cache
from pathlib import Path

import yaml

_DATA_POOLS_PATH = Path(__file__).resolve().parent.parent / "config" / "data_pools.yml"

_ROOT_KEY = "payment_terminal"

# Required sub-keys of payment_terminal, each mapped to a short description of
# the expected shape used in the fail-fast diagnostic.
_REQUIRED_KEYS: dict[str, str] = {
    "receipt_method_weights": "a mapping of method name -> positive integer weight",
    "acquirers": "a non-empty list of acquirer display names",
    "schemes": "a mapping of scheme name -> {display, aid, pan_digits, account_types}",
    "wallets": "a mapping of wallet method name -> printed wallet label",
    "entry_modes": "a mapping with 'card' and 'wallet' entry-mode markers",
    "contactless_label": "the printed contactless label, e.g. 'CONTACTLESS'",
    "customer_copy_text": "the printed header text, e.g. 'CUSTOMER COPY'",
    "approved_text": "the printed approval word, e.g. 'APPROVED'",
    "response_code": "the printed response code as a string, e.g. '00'",
    "retain_text": "the printed footer, e.g. 'Retain copy for your records'",
    "cash": "a mapping with 'tendered_label' and 'change_label'",
}

_REQUIRED_SCHEME_KEYS = ("display", "aid", "pan_digits", "account_types")


def _err(what: str, *, path: Path, key_path: str, expected: str, recover: str) -> ValueError:
    """Build a four-element fail-fast diagnostic (what / where / expected / recover)."""
    return ValueError(
        f"{what}\n"
        f"  What:     {what}\n"
        f"  Where:    {path} -> '{key_path}'.\n"
        f"  Expected: {expected}\n"
        f"  Recover:  set '{key_path}' in {path} to a valid value."
    )


@lru_cache(maxsize=None)
def load_terminal_pools(path: Path = _DATA_POOLS_PATH) -> dict:
    """Load and validate the `payment_terminal` block of the data pools file.

    Args:
        path: Path to the data pools YAML file.

    Returns:
        The validated `payment_terminal` mapping.

    Raises:
        FileNotFoundError: `path` does not exist.
        ValueError: the block or any required key is missing or malformed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"data pools file not found.\n"
            f"  What:     {path} does not exist.\n"
            f"  Where:    {path}\n"
            f"  Expected: a YAML file with a top-level '{_ROOT_KEY}' mapping.\n"
            f"  Recover:  create {path} (see config/data_pools.yml in the repo)."
        )

    data = yaml.safe_load(path.read_text())
    pools = data.get(_ROOT_KEY) if isinstance(data, dict) else None
    if not isinstance(pools, dict):
        raise _err(
            f"'{_ROOT_KEY}' block is missing or not a mapping in {path}.",
            path=path,
            key_path=_ROOT_KEY,
            expected="a mapping with keys " + ", ".join(_REQUIRED_KEYS) + ".",
            recover=f"add a '{_ROOT_KEY}:' block to {path}",
        )

    for key, expected in _REQUIRED_KEYS.items():
        if key not in pools:
            raise _err(
                f"'{_ROOT_KEY}.{key}' is missing.",
                path=path,
                key_path=f"{_ROOT_KEY}.{key}",
                expected=expected + ".",
                recover=f"add '{key}' under {_ROOT_KEY}",
            )
        if not pools[key]:
            raise _err(
                f"'{_ROOT_KEY}.{key}' is empty.",
                path=path,
                key_path=f"{_ROOT_KEY}.{key}",
                expected=expected + ".",
                recover=f"populate '{key}' under {_ROOT_KEY}",
            )

    for name, scheme in pools["schemes"].items():
        for sub in _REQUIRED_SCHEME_KEYS:
            if not isinstance(scheme, dict) or sub not in scheme or not scheme[sub]:
                raise _err(
                    f"scheme '{name}' is missing '{sub}'.",
                    path=path,
                    key_path=f"{_ROOT_KEY}.schemes.{name}.{sub}",
                    expected="display (str), aid (str), pan_digits (int), "
                    "account_types (non-empty list).",
                    recover=f"add '{sub}' to scheme '{name}'",
                )

    for mode in ("card", "wallet"):
        if mode not in pools["entry_modes"]:
            raise _err(
                f"entry_modes is missing '{mode}'.",
                path=path,
                key_path=f"{_ROOT_KEY}.entry_modes.{mode}",
                expected="a marker string, e.g. card: (c) and wallet: (t).",
                recover=f"add '{mode}' under {_ROOT_KEY}.entry_modes",
            )

    for label in ("tendered_label", "change_label"):
        if label not in pools["cash"]:
            raise _err(
                f"cash block is missing '{label}'.",
                path=path,
                key_path=f"{_ROOT_KEY}.cash.{label}",
                expected="a printed label, e.g. tendered_label: CASH TENDERED.",
                recover=f"add '{label}' under {_ROOT_KEY}.cash",
            )

    known = set(pools["schemes"]) | set(pools["wallets"]) | {"Cash"}
    for method, weight in pools["receipt_method_weights"].items():
        if method not in known:
            raise _err(
                f"weighted method '{method}' resolves to no scheme, wallet, or Cash.",
                path=path,
                key_path=f"{_ROOT_KEY}.receipt_method_weights.{method}",
                expected="a key of 'schemes', a key of 'wallets', or the literal 'Cash'. "
                f"Known: {sorted(known)}.",
                recover=f"remove '{method}' or add a matching scheme/wallet entry",
            )
        if not isinstance(weight, int) or weight <= 0:
            raise _err(
                f"weight for '{method}' is not a positive integer (got {weight!r}).",
                path=path,
                key_path=f"{_ROOT_KEY}.receipt_method_weights.{method}",
                expected="a positive integer, e.g. 'EFTPOS: 30'.",
                recover=f"set a positive integer weight for '{method}'",
            )

    return pools
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full pre-commit gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all pass. (`tests/test_receipt_fit.py` is still green — nothing renders differently yet.)

- [ ] **Step 7: Commit**

```bash
git add config/data_pools.yml generators/payment_block.py
git commit -m ":sparkles: add payment_terminal config block and fail-fast loader"
```

---

### Task 2: Deterministic derivation — `PaymentDetails` and `derive_payment()`

**Files:**
- Modify: `generators/payment_block.py`
- Test: `tests/test_payment_block.py`

**Interfaces:**
- Consumes: `load_terminal_pools() -> dict` from Task 1.
- Produces:
  - `PaymentDetails` — frozen dataclass with fields `method: str`, `kind: str` (one of `"card"`, `"wallet"`, `"cash"`), `scheme_name: str` (the `schemes` key, e.g. `"Visa"`, empty for cash), `scheme_display: str` (the printed text, e.g. `"VISA CREDIT"`), `account_type: str`, `acquirer: str`, `aid: str`, `masked_pan: str`, `entry_mode: str`, `psn: str`, `atc: str`, `terminal_id: str`, `transaction_ref: str`, `timestamp: str`, `wallet_label: str` (empty for non-wallet), `tendered: Decimal | None`, `change: Decimal | None`, `purchase_total: Decimal`.
  - `derive_payment(case_id: str, invoice_date: str, total: str, time_str: str, *, pools: dict | None = None) -> PaymentDetails`. `pools` defaults to `load_terminal_pools()`; the parameter exists so tests can inject a pool without touching the real file.

Derivation reuses the digest `sha256(f"{case_id}:pos:{invoice_date}")` that `generators/receipt.py::_derive_receipt_details` already computes, consuming hex characters 10–40 (that function consumes 0–10). Slice assignment:

| Hex chars | Value |
| --- | --- |
| 10:14 | method index into the expanded weight pool |
| 14:16 | acquirer index |
| 16:18 | account type index within the scheme |
| 18:22 | PAN last four (`% 10000`, zero-padded) |
| 22:24 | PSN (`% 100`, zero-padded) |
| 24:28 | ATC (four hex chars, uppercased) |
| 28:32 | terminal ID (`% 99 + 1`) |
| 32:38 | transaction ref (`% 1000000`, zero-padded to 6) |
| 38:40 | cash extra-note index |

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_payment_block.py`:

```python
from decimal import Decimal

from generators.payment_block import PaymentDetails, derive_payment


def _details(case="CASE001", date="07/07/2024", total="137.73", time_str="10:33"):
    return derive_payment(case, date, total, time_str)


def test_derivation_is_deterministic():
    assert _details() == _details()


def test_different_cases_differ():
    assert _details(case="CASE001") != _details(case="CASE002")


def test_kind_matches_method():
    pools = load_terminal_pools(_POOLS)
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.method == "Cash":
            assert d.kind == "cash"
        elif d.method in pools["wallets"]:
            assert d.kind == "wallet"
        else:
            assert d.kind == "card"
            assert d.method in pools["schemes"]


def test_all_methods_appear_across_the_corpus():
    """The weighted pool must actually produce every configured method."""
    pools = load_terminal_pools(_POOLS)
    seen = {
        derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33").method
        for i in range(1, 56)
    }
    assert seen <= set(pools["receipt_method_weights"])
    assert len(seen) >= 4, f"weighted pool produced too little variety: {seen}"


def test_masked_pan_width_matches_scheme_pan_digits():
    pools = load_terminal_pools(_POOLS)
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.kind == "cash":
            assert d.masked_pan == ""
            continue
        expected_digits = pools["schemes"][d.scheme_name]["pan_digits"]
        assert len(d.masked_pan) == expected_digits
        assert d.masked_pan[-4:].isdigit()
        assert set(d.masked_pan[:-4]) == {"x"}


def test_account_type_comes_from_its_own_scheme():
    pools = load_terminal_pools(_POOLS)
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.kind == "cash":
            continue
        assert d.account_type in pools["schemes"][d.scheme_name]["account_types"]


def test_timestamp_is_twelve_hour_rendering_of_receipt_meta_time():
    d = derive_payment("CASE001", "07/07/2024", "137.73", "13:33")
    assert d.timestamp == "07 Jul 2024 at 01:33 PM"
    d_am = derive_payment("CASE001", "07/07/2024", "137.73", "09:05")
    assert d_am.timestamp == "07 Jul 2024 at 09:05 AM"


def test_cash_change_is_tendered_minus_total_and_tender_exceeds_total():
    for case in [f"CASE{i:03d}" for i in range(1, 200)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.kind != "cash":
            continue
        assert d.tendered > Decimal("137.73")
        assert d.change == d.tendered - Decimal("137.73")
        assert d.tendered % Decimal("5") == 0


def test_exact_multiple_of_five_still_gives_change():
    """A total that is already a round note must never render CHANGE 0.00."""
    for case in [f"CASE{i:03d}" for i in range(1, 200)]:
        d = derive_payment(case, "07/07/2024", "25.00", "10:33")
        if d.kind == "cash":
            assert d.change > 0


def test_card_details_have_no_cash_values():
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.kind != "cash":
            assert d.tendered is None and d.change is None
            assert d.aid and d.psn and d.atc and d.terminal_id and d.transaction_ref


def test_purchase_total_is_the_scored_total_verbatim():
    """The printed 'Purchase AUD $x' must never diverge from TOTAL_AMOUNT."""
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        assert d.purchase_total == Decimal("137.73")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: FAIL — `ImportError: cannot import name 'PaymentDetails' from 'generators.payment_block'`.

- [ ] **Step 3: Implement the derivation**

Add to `generators/payment_block.py` (imports at top: `import hashlib`, `from dataclasses import dataclass`, `from datetime import datetime`, `from decimal import Decimal`):

```python
@dataclass(frozen=True)
class PaymentDetails:
    """Deterministic terminal-slip values for one receipt.

    Attributes:
        method: The pool method name, e.g. "Visa", "Cash", "Apple Pay".
        kind: Block variant — "card", "wallet", or "cash".
        scheme_name: The `schemes` key backing this payment ("" for cash).
        scheme_display: Printed scheme text, e.g. "VISA CREDIT".
        account_type: Printed account suffix, e.g. "SAV" or "CR".
        acquirer: Printed acquirer line, e.g. "Tyro Payments EFTPOS".
        aid: Printed EMV application identifier.
        masked_pan: Masked card number, e.g. "xxxxxxxxxxxx3218".
        entry_mode: Entry-mode marker, "(c)" for card or "(t)" for wallet.
        psn: Two-digit PAN sequence number.
        atc: Four-hex-character application transaction counter.
        terminal_id: Printed terminal number.
        transaction_ref: Six-digit transaction reference.
        timestamp: "DD Mon YYYY at hh:mm AM/PM".
        wallet_label: Printed wallet name, "" unless kind == "wallet".
        tendered: Cash tendered, None unless kind == "cash".
        change: Cash change, None unless kind == "cash".
        purchase_total: TOTAL_AMOUNT as a Decimal, printed verbatim as the
            'Purchase AUD $x' line so the block never diverges from the
            scored field.
    """

    method: str
    kind: str
    scheme_name: str
    scheme_display: str
    account_type: str
    acquirer: str
    aid: str
    masked_pan: str
    entry_mode: str
    psn: str
    atc: str
    terminal_id: str
    transaction_ref: str
    timestamp: str
    wallet_label: str
    tendered: Decimal | None
    change: Decimal | None
    purchase_total: Decimal


def _weighted_pool(weights: dict[str, int]) -> list[str]:
    """Expand a method -> weight mapping into a deterministic flat pool."""
    pool: list[str] = []
    for method in sorted(weights):
        pool.extend([method] * weights[method])
    return pool


def _format_timestamp(invoice_date: str, time_str: str) -> str:
    """Render 'DD/MM/YYYY' + 'HH:MM' as 'DD Mon YYYY at hh:mm AM/PM'."""
    stamp = datetime.strptime(f"{invoice_date} {time_str}", "%d/%m/%Y %H:%M")
    return stamp.strftime("%d %b %Y at %I:%M %p")


def _cash_tender(total: Decimal, extra_index: int) -> tuple[Decimal, Decimal]:
    """Return (tendered, change): next $5 note above `total`, plus 0/$5/$10.

    Tendered always strictly exceeds the total, so a total that is already a
    round note never renders 'CHANGE 0.00'.
    """
    base = (total // Decimal("5")) * Decimal("5")
    if base <= total:
        base += Decimal("5")
    tendered = base + Decimal("5") * extra_index
    return tendered, tendered - total


def derive_payment(
    case_id: str,
    invoice_date: str,
    total: str,
    time_str: str,
    *,
    pools: dict | None = None,
) -> PaymentDetails:
    """Derive deterministic terminal-slip values for one receipt.

    Reuses the digest of f"{case_id}:pos:{invoice_date}" that
    generators/receipt.py::_derive_receipt_details computes for time/register/
    staff (hex chars 0-10); this function consumes hex chars 10-40, so the two
    never collide.

    Args:
        case_id: Case identifier, e.g. "CASE001".
        invoice_date: Receipt date as DD/MM/YYYY.
        total: TOTAL_AMOUNT as a decimal string, e.g. "137.73".
        time_str: 24-hour HH:MM already printed by the receipt_meta header.
        pools: Validated payment_terminal mapping; loaded from YAML if omitted.

    Returns:
        The derived PaymentDetails.
    """
    cfg = pools if pools is not None else load_terminal_pools()
    digest = hashlib.sha256(f"{case_id}:pos:{invoice_date}".encode()).hexdigest()

    method_pool = _weighted_pool(cfg["receipt_method_weights"])
    method = method_pool[int(digest[10:14], 16) % len(method_pool)]

    acquirers = cfg["acquirers"]
    acquirer = acquirers[int(digest[14:16], 16) % len(acquirers)]
    timestamp = _format_timestamp(invoice_date, time_str)
    total_dec = Decimal(total)

    if method == "Cash":
        tendered, change = _cash_tender(total_dec, int(digest[38:40], 16) % 3)
        return PaymentDetails(
            method=method,
            kind="cash",
            scheme_name="",
            scheme_display="",
            account_type="",
            acquirer=acquirer,
            aid="",
            masked_pan="",
            entry_mode="",
            psn="",
            atc="",
            terminal_id="",
            transaction_ref="",
            timestamp=timestamp,
            wallet_label="",
            tendered=tendered,
            change=change,
            purchase_total=total_dec,
        )

    wallets = cfg["wallets"]
    is_wallet = method in wallets
    scheme_names = sorted(cfg["schemes"])
    # A wallet transaction still runs over a card scheme; pick one by hash.
    scheme_name = scheme_names[int(digest[16:18], 16) % len(scheme_names)] if is_wallet else method
    scheme = cfg["schemes"][scheme_name]
    account_types = scheme["account_types"]

    last4 = f"{int(digest[18:22], 16) % 10000:04d}"
    masked_pan = "x" * (int(scheme["pan_digits"]) - 4) + last4

    return PaymentDetails(
        method=method,
        kind="wallet" if is_wallet else "card",
        scheme_name=scheme_name,
        scheme_display=scheme["display"],
        account_type=account_types[int(digest[16:18], 16) % len(account_types)],
        acquirer=acquirer,
        aid=scheme["aid"],
        masked_pan=masked_pan,
        entry_mode=cfg["entry_modes"]["wallet" if is_wallet else "card"],
        psn=f"{int(digest[22:24], 16) % 100:02d}",
        atc=digest[24:28].upper(),
        terminal_id=str(int(digest[28:32], 16) % 99 + 1),
        transaction_ref=f"{int(digest[32:38], 16) % 1000000:06d}",
        timestamp=timestamp,
        wallet_label=wallets[method] if is_wallet else "",
        tendered=None,
        change=None,
        purchase_total=total_dec,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: all PASS. If `test_all_methods_appear_across_the_corpus` fails on variety, do not weaken the assertion — check `_weighted_pool` expansion first.

- [ ] **Step 5: Run the pre-commit gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add generators/payment_block.py
git commit -m ":sparkles: derive deterministic EFTPOS terminal values per case"
```

---

### Task 3: Render the block and wire it into the receipt renderer

**Files:**
- Modify: `generators/payment_block.py` (add `render_payment_block`)
- Modify: `config/layouts/receipts.yml` (add 2 budgets to each of the 6 layouts)
- Modify: `generators/receipt.py:48` (delete `_PAYMENT_METHODS`), `:86-124` (`_derive_receipt_details`), `:335-338` (`payment` branch)
- Modify: `tests/fixtures/receipt_baseline_hashes.json` (re-capture — renders change by design)
- Test: `tests/test_payment_block.py`

**Interfaces:**
- Consumes: `PaymentDetails`, `derive_payment()` from Task 2; `field_budget(layout, layout_id, field, *, layout_path) -> dict` from `generators/layout_budgets`; `draw_fitted_center`, `draw_fitted_left`, `draw_line_item`, `draw_text_center`, `fmt_amount`, `load_font` from `generators.common`.
- Produces: `render_payment_block(draw, details, y, *, layout, layout_id, width, margin, line_h, font, font_bold, font_size, is_mono) -> int` — draws the block top-down from `y`, returns the y below the last line.

Layout budgets to add to **each** of the six layouts in `config/layouts/receipts.yml`, using that layout's existing content-box width (the same value its `SUPPLIER_NAME` budget uses — 396 for `receipt_thermal_80mm`/`receipt_retail_tax`/`receipt_fuel`, 294 for `receipt_thermal_57mm`, 416 for `receipt_professional`/`receipt_hospitality`):

```yaml
      PAYMENT_ACQUIRER: {width: <content_box>, fit: shrink, min_font: 8, max_lines: 1}
      PAYMENT_LINE: {width: <content_box>, fit: shrink, min_font: 8, max_lines: 1}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_payment_block.py`:

```python
from PIL import Image, ImageDraw

from generators.common import load_font
from generators.loader import load_layout_registry
from generators.payment_block import render_payment_block

_LAYOUTS_PATH = Path("config/layouts/receipts.yml")


def _render_lines(details, layout_id="receipt_thermal_80mm"):
    """Render a block onto a scratch canvas; return (rendered_text_probe, new_y)."""
    layouts = load_layout_registry(_LAYOUTS_PATH)
    layout = layouts[layout_id]
    img = Image.new("RGB", (layout["width"], 1200), "white")
    draw = ImageDraw.Draw(img)
    font = load_font(layout["font_size"], mono=True)
    font_bold = load_font(layout["font_size"], mono=True, bold=True)
    new_y = render_payment_block(
        draw,
        details,
        20,
        layout=layout,
        layout_id=layout_id,
        width=layout["width"],
        margin=layout["margin"],
        line_h=layout["line_height"],
        font=font,
        font_bold=font_bold,
        font_size=layout["font_size"],
        is_mono=True,
    )
    return img, new_y


def _ink_rows(img, from_y, to_y):
    """Count rows containing non-white pixels — a proxy for lines drawn."""
    px = img.load()
    rows = 0
    for y in range(from_y, to_y):
        if any(px[x, y] != (255, 255, 255) for x in range(img.width)):
            rows += 1
    return rows


def _card_details():
    for i in range(1, 200):
        d = derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33")
        if d.kind == "card":
            return d
    raise AssertionError("no card case found")


def _cash_details():
    for i in range(1, 200):
        d = derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33")
        if d.kind == "cash":
            return d
    raise AssertionError("no cash case found")


def test_card_block_is_taller_than_cash_block():
    _, card_y = _render_lines(_card_details())
    _, cash_y = _render_lines(_cash_details())
    assert card_y > cash_y, "card terminal block must print more lines than cash"


def test_cash_block_draws_only_two_lines():
    """Cash advances exactly two line heights (tendered + change), nothing more."""
    layout = load_layout_registry(_LAYOUTS_PATH)["receipt_thermal_80mm"]
    img, new_y = _render_lines(_cash_details())
    assert _ink_rows(img, 0, new_y) > 0
    assert new_y - 20 == 2 * layout["line_height"]


def test_block_renders_for_every_layout_and_method():
    """No layout/method combination may raise (FitError included)."""
    layouts = load_layout_registry(_LAYOUTS_PATH)
    for layout_id in layouts:
        for i in range(1, 60):
            d = derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33")
            _render_lines(d, layout_id=layout_id)


def test_every_layout_has_payment_budgets():
    from generators.layout_budgets import field_budget

    layouts = load_layout_registry(_LAYOUTS_PATH)
    for lid, layout in layouts.items():
        for field in ("PAYMENT_ACQUIRER", "PAYMENT_LINE"):
            field_budget(layout, lid, field, layout_path=str(_LAYOUTS_PATH))


def test_receipt_render_includes_terminal_block():
    """A full receipt render must grow by roughly the block's height."""
    from generators.loader import load_ground_truth
    from generators.receipt import render_receipt

    entry = dict(load_ground_truth(Path("ground_truth/receipts.yml"))["CASE001"])
    entry["case_id"] = "CASE001"
    layouts = load_layout_registry(_LAYOUTS_PATH)
    img = render_receipt(entry, layouts[entry["layout"]])
    assert img.height > 400, "receipt should include a multi-line payment block"


def test_receipt_module_has_no_hardcoded_methods():
    import generators.receipt as receipt_mod

    assert not hasattr(receipt_mod, "_PAYMENT_METHODS")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: FAIL — `cannot import name 'render_payment_block'`.

- [ ] **Step 3: Implement `render_payment_block`**

Add to `generators/payment_block.py` (imports: `from PIL import ImageDraw`; from `generators.common` import `Font`, `draw_fitted_center`, `draw_fitted_left`, `draw_line_item`, `fmt_amount` — `Font` is the font type alias `generators/common.py` already uses in `draw_line_item`; and `from generators.layout_budgets import field_budget`):

```python
_LAYOUT_PATH = "config/layouts/receipts.yml"


def render_payment_block(
    draw: ImageDraw.ImageDraw,
    details: PaymentDetails,
    y: int,
    *,
    layout: dict,
    layout_id: str,
    width: int,
    margin: int,
    line_h: int,
    font: Font,
    font_bold: Font,
    font_size: int,
    is_mono: bool,
    pools: dict | None = None,
) -> int:
    """Draw the terminal block for `details`, returning the y below it.

    Cash renders a two-line tender block; card and wallet render the full
    EFTPOS customer-copy slip, wallet adding a CONTACTLESS line.

    Args:
        draw: The PIL drawing context.
        details: Derived terminal values for this receipt.
        y: Top y to draw from.
        layout: The single-layout dict, for field budgets.
        layout_id: Layout id, used in budget diagnostics.
        width: Canvas width in pixels.
        margin: Layout margin in pixels.
        line_h: Layout line height in pixels.
        font: Regular font at nominal size.
        font_bold: Bold font at nominal size.
        font_size: Nominal font size, for fitted helpers.
        is_mono: Whether the layout font is monospace.
        pools: Validated payment_terminal mapping; loaded from YAML if omitted.

    Returns:
        The y coordinate below the last drawn line.
    """
    cfg = pools if pools is not None else load_terminal_pools()
    acquirer_budget = field_budget(layout, layout_id, "PAYMENT_ACQUIRER", layout_path=_LAYOUT_PATH)
    line_budget = field_budget(layout, layout_id, "PAYMENT_LINE", layout_path=_LAYOUT_PATH)

    def line(text: str) -> None:
        nonlocal y
        y = draw_fitted_left(
            draw,
            text,
            margin,
            y,
            budget=line_budget,
            nominal_size=font_size,
            mono=is_mono,
            line_spacing=line_h,
        )

    if details.kind == "cash":
        cash = cfg["cash"]
        draw_line_item(
            draw, cash["tendered_label"], fmt_amount(details.tendered), y, font, margin, width
        )
        y += line_h
        draw_line_item(
            draw, cash["change_label"], fmt_amount(details.change), y, font_bold, margin, width
        )
        return y + line_h

    y = draw_fitted_center(
        draw,
        cfg["customer_copy_text"],
        y,
        width,
        budget=acquirer_budget,
        nominal_size=font_size,
        mono=is_mono,
        bold=True,
        line_spacing=line_h,
    )
    y = draw_fitted_center(
        draw,
        details.acquirer,
        y,
        width,
        budget=acquirer_budget,
        nominal_size=font_size,
        mono=is_mono,
        line_spacing=line_h,
    )
    y += line_h // 4

    if details.kind == "wallet":
        line(f"{cfg['contactless_label']} - {details.wallet_label}")
    line(f"{details.scheme_display} {details.account_type}")
    line(f"AID: {details.aid}")
    line(f"Card: {details.masked_pan} {details.entry_mode}")
    line(f"PSN: {details.psn}, ATC: {details.atc}")
    y += line_h // 4

    draw_line_item(draw, "Purchase   AUD", fmt_amount(details.purchase_total), y, font, margin, width)
    y += line_h
    line(f"{cfg['approved_text']}   {cfg['response_code']}")
    y += line_h // 4

    line(f"Terminal ID: {details.terminal_id}")
    line(f"Transaction Ref: {details.transaction_ref}")
    line(details.timestamp)
    y += line_h // 4

    y = draw_fitted_center(
        draw,
        cfg["retain_text"],
        y,
        width,
        budget=acquirer_budget,
        nominal_size=font_size,
        mono=is_mono,
        line_spacing=line_h,
    )
    return y
```

`details.purchase_total` and `details.tendered`/`details.change` come straight from Task 2, so the renderer never re-parses `TOTAL_AMOUNT`.

- [ ] **Step 4: Add the layout budgets**

Edit `config/layouts/receipts.yml`. For each of the six layouts, add the two keys to its existing `field_budgets:` block, using that layout's content-box width:

Indentation is six spaces, matching the sibling `SUPPLIER_NAME:` entries. Per layout:

`receipt_thermal_80mm`, `receipt_retail_tax`, `receipt_fuel` — add to each:
```yaml
      PAYMENT_ACQUIRER: {width: 396, fit: shrink, min_font: 8, max_lines: 1}
      PAYMENT_LINE: {width: 396, fit: shrink, min_font: 8, max_lines: 1}
```

`receipt_thermal_57mm` — add:
```yaml
      PAYMENT_ACQUIRER: {width: 294, fit: shrink, min_font: 8, max_lines: 1}
      PAYMENT_LINE: {width: 294, fit: shrink, min_font: 8, max_lines: 1}
```

`receipt_professional`, `receipt_hospitality` — add to each:
```yaml
      PAYMENT_ACQUIRER: {width: 416, fit: shrink, min_font: 8, max_lines: 1}
      PAYMENT_LINE: {width: 416, fit: shrink, min_font: 8, max_lines: 1}
```

- [ ] **Step 5: Wire the renderer**

In `generators/receipt.py`:

1. Delete the `_PAYMENT_METHODS` list (line 48).
2. In `_derive_receipt_details`, delete the `pay_idx` / `payment_method` lines and the `"payment_method"` key from the returned dict; update the docstring to say the function returns time, register, and staff (payment values now come from `generators.payment_block.derive_payment`).
3. Add the import: `from generators.payment_block import derive_payment, render_payment_block`.
4. Replace the `payment` branch (lines 335-338) with:

```python
        elif sec_type == "payment":
            details = derive_payment(
                case_id, inv_date, fields.get("TOTAL_AMOUNT", "0"), pos_details["time"]
            )
            y = render_payment_block(
                draw,
                details,
                y,
                layout=layout,
                layout_id=layout_id,
                width=width,
                margin=margin,
                line_h=line_h,
                font=font,
                font_bold=font_bold,
                font_size=font_size,
                is_mono=is_mono,
            )
```

Note the old branch read `fields.get("PAYMENT_METHOD")` — no ground-truth entry defines that key (verified: zero matches in `ground_truth/*.yml`), and the spec adds no such column, so the lookup is dropped rather than carried forward.

- [ ] **Step 6: Run the payment tests**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: all PASS.

- [ ] **Step 7: Re-capture the render baselines**

`tests/test_receipt_fit.py::test_unchanged_docs_byte_identical` pins every receipt render against `tests/fixtures/receipt_baseline_hashes.json`. Renders change by design here, so re-capture:

```bash
conda run -n synthetic python -c "
import hashlib, json
from pathlib import Path
from generators.loader import load_ground_truth, load_layout_registry
from generators.receipt import render_receipt
layouts = load_layout_registry(Path('config/layouts/receipts.yml'))
entries = load_ground_truth(Path('ground_truth/receipts.yml'))
out = {}
for case_id, entry in entries.items():
    entry['case_id'] = str(case_id)
    layout = layouts[entry['layout']]
    digest = hashlib.sha256(render_receipt(entry, layout).tobytes()).hexdigest()
    out[f\"{case_id}_{entry['layout']}\"] = digest
Path('tests/fixtures/receipt_baseline_hashes.json').write_text(json.dumps(out, indent=2) + '\n')
print(f'recaptured {len(out)} baselines')
"
```
Expected: `recaptured 55 baselines`.

Then update the comment inside `test_unchanged_docs_byte_identical` to record why: baselines re-captured after the payment-block change; renders are pinned to the new block.

- [ ] **Step 8: Run the pre-commit gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all pass. `tests/test_geometry_capture.py` and `tests/test_task10b_geometry.py` must stay green — the block captures no boxes, so scored-field geometry is unchanged.

- [ ] **Step 9: Commit**

```bash
git add generators/payment_block.py generators/receipt.py config/layouts/receipts.yml
git commit -m ":sparkles: render EFTPOS terminal block on receipts"
```

---

### Task 4: Corpus-wide fit safety and visual verification

**Files:**
- Modify: `tests/test_receipt_fit.py`
- Verify: `output/clean/` renders

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: no new production code — this task proves the corpus renders cleanly at every layout/method combination.

- [ ] **Step 1: Extend the fit test to cover payment lines**

In `tests/test_receipt_fit.py`, add `"PAYMENT_ACQUIRER"` and `"PAYMENT_LINE"` to the `_FIELDS` tuple, and extend `_variable_strings` to append the payment strings for the entry. Add at the end of `_variable_strings`, before `return out`:

```python
    from generators.payment_block import derive_payment, load_terminal_pools

    cfg = load_terminal_pools(Path("config/data_pools.yml"))
    d = derive_payment(
        case_id, fields.get("INVOICE_DATE", ""), fields.get("TOTAL_AMOUNT", "0"), "10:33"
    )
    if d.kind == "cash":
        return out
    out.append(("PAYMENT_ACQUIRER", d.acquirer, False))
    out.append(("PAYMENT_ACQUIRER", cfg["customer_copy_text"], True))
    out.append(("PAYMENT_ACQUIRER", cfg["retain_text"], False))
    if d.kind == "wallet":
        out.append(("PAYMENT_LINE", f"{cfg['contactless_label']} - {d.wallet_label}", False))
    for text in (
        f"{d.scheme_display} {d.account_type}",
        f"AID: {d.aid}",
        f"Card: {d.masked_pan} {d.entry_mode}",
        f"PSN: {d.psn}, ATC: {d.atc}",
        f"{cfg['approved_text']}   {cfg['response_code']}",
        f"Terminal ID: {d.terminal_id}",
        f"Transaction Ref: {d.transaction_ref}",
        d.timestamp,
    ):
        out.append(("PAYMENT_LINE", text, False))
    return out
```

`_variable_strings(fields)` must become `_variable_strings(case_id, fields)` — update its signature, its docstring, and its one call site in `test_no_variable_field_overflows_after_fitting` (pass `case_id`, which that loop must now unpack: `for case_id, entry in _entries().items():`).

- [ ] **Step 2: Run the fit tests**

Run: `conda run -n synthetic pytest tests/test_receipt_fit.py -v`
Expected: all PASS. A `FitError` here means a payment line genuinely cannot fit a layout — fix by shortening the offending value in `config/data_pools.yml` (e.g. a long acquirer name), never by widening `min_font` below 8 or loosening the assertion.

- [ ] **Step 3: Run the overflow backstop and pipeline validation**

Run:
```bash
conda run -n synthetic pytest tests/test_overflow_backstop.py -v
conda run -n synthetic python -m generators.pipeline validate
```
Expected: tests PASS; `validate` exits 0.

- [ ] **Step 4: Generate receipts and check visually**

Run: `conda run -n synthetic python -m generators.pipeline generate --type receipts --clean-only`

Open three rendered receipts from `output/clean/` — one card, one wallet, one cash (find which is which via `derive_payment` for the case ids) — and confirm against `docs/receipt_payment_block_design.md`:
- The card block shows CUSTOMER COPY, acquirer, scheme + account type, AID, masked card with `(c)`, PSN/ATC, `Purchase AUD` matching the receipt's TOTAL, APPROVED 00, terminal ID, transaction ref, timestamp, retain-copy footer.
- The wallet block adds `CONTACTLESS - APPLE PAY` (or Google Pay) and uses `(t)`.
- The cash block shows only CASH TENDERED and CHANGE, with change > 0.
- The block's timestamp date and time agree with the `Date:` / `Time:` lines in the receipt header.
- Nothing is clipped at the right edge on `receipt_thermal_57mm` (the narrowest layout).

- [ ] **Step 5: Run the full pre-commit gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all pass.

- [ ] **Step 6: Commit**

Only `tests/fixtures/receipt_baseline_hashes.json` is committable from this task if it was not already committed in Task 3 (`tests/` is gitignored, but confirm with `git status` whether the fixtures path is tracked). If `git status` shows nothing to commit, skip this step and say so.

```bash
git status --short
```

---

## Out of Scope (do not implement)

- Payment-method consistency with `ground_truth/transaction_links.yml`. A receipt may render `Cash` while its linked bank row reads `VISA DEBIT PURCHASE …`. Recorded as a known follow-up in the design doc; fixing it is separate work against the linking ground truth.
- Any change to `config/field_definitions.yml`, `ground_truth/receipts.yml`, geometry capture, or the exporters. Nothing in the payment block is a scored field.
- The AU 5-cent cash-rounding line, deliberately omitted so no rendered total diverges from `TOTAL_AMOUNT`.
