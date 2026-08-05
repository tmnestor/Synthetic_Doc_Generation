# Receipt / Bank Payment-Method Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every linked receipt print the payment scheme its bank-statement row names, eliminating all 39 current mismatches.

**Architecture:** `ground_truth/transaction_links.yml` becomes an input to receipt rendering. `generators/payment_block.py` gains a link index and a description→scheme mapping; `derive_payment` accepts an optional `bank_description` that forces the scheme. Nothing scored changes — bank ground truth and renders are untouched.

**Tech Stack:** Python 3.12, PIL (Pillow 12.2.0), PyYAML, typer, pytest, conda env `synthetic`.

**Spec:** `docs/receipt_bank_payment_consistency_design.md`

## Global Constraints

- Conda env is `synthetic`. Run every tool as `conda run -n synthetic <cmd>`.
- `tests/` is gitignored — test files are written and run locally but never committed.
- YAML is the single source of truth. No config value may exist as a Python default or fallback. Every key is required; a missing key raises.
- Every fail-fast diagnostic must contain all four elements as literal labelled lines: `What:`, `Where:`, `Expected:`, `Recover:` (asserted by `tests/conftest.py::assert_diagnostic_error`).
- Line length max 108. Python 3.12 type hints (`X | Y`). Google-style docstrings. `pathlib.Path` for paths.
- In `except` blocks always `raise ... from err` or `from None` (B904); `raise typer.Exit(1) from None`.
- Never write the Australian tax authority's three-letter acronym; use "PROD".
- No Claude attribution in commit messages.
- Pre-commit gate, all four must pass before every commit:
  1. `conda run -n synthetic pytest tests/`
  2. `conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py`
  3. `conda run -n synthetic ruff format .`
  4. `conda run -n synthetic mypy . --ignore-missing-imports`
- mypy currently reports 10 pre-existing errors in `degrade_camera_scan.py`, `tests/test_fitted_helpers.py` and `tests/test_fit_text.py`. That count must not grow.
- Never bypass pre-commit hooks with `--no-verify`.

## File Structure

| File | Responsibility |
| --- | --- |
| `config/data_pools.yml` (modify) | `payment_terminal` gains `bank_description_methods`, two debit `schemes` entries, `wallet_presentation_weights`, and `Cash: 0` |
| `generators/payment_block.py` (modify) | Link index, description→scheme mapping, `bank_description` parameter on `derive_payment`, relaxed weight validation |
| `generators/receipt.py` (modify) | Look up the case's linked description and pass it through |
| `generators/pipeline.py` (modify) | `validate` gains the link-mapping check |
| `tests/test_payment_block.py` (modify) | Mapping, forced scheme, wallet presentation, fallback, the corpus invariant |
| `tests/fixtures/receipt_baseline_hashes.json` (regenerate) | Receipt renders change again |

Task order: config + mapping primitives → forced derivation → renderer wiring + baselines → validation guard.

---

### Task 1: Config additions and the description→scheme mapping

**Files:**
- Modify: `config/data_pools.yml` (the `payment_terminal:` block)
- Modify: `generators/payment_block.py`
- Test: `tests/test_payment_block.py`

**Interfaces:**
- Consumes: `load_terminal_pools(path) -> dict` (existing).
- Produces:
  - `method_from_bank_description(description: str, cfg: dict) -> str` — returns a `schemes` key by longest-prefix match; raises `ValueError` with a four-element diagnostic when nothing matches.
  - `load_link_index(path: Path = _LINKS_PATH) -> dict[str, str]` — maps image stem (`"CASE001_receipt_fuel"`, no `.png`) to that link's `bank_description`, receipt links only. `lru_cache`d. Raises `FileNotFoundError` if the file is absent.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_payment_block.py`:

```python
# --- Bank-link consistency -----------------------------------------------------

from generators.payment_block import load_link_index, method_from_bank_description

_LINKS_PATH = Path("ground_truth/transaction_links.yml")


def test_bank_description_maps_to_scheme():
    cfg = load_terminal_pools(_POOLS)
    assert method_from_bank_description("EFTPOS SQ *PRIME Alexandria AUS", cfg) == "EFTPOS"
    assert (
        method_from_bank_description("VISA DEBIT PURCHASE SQ *RAVENSDALE AU", cfg) == "Visa Debit"
    )
    assert (
        method_from_bank_description("MASTERCARD DEBIT HARROWGATE L AU", cfg)
        == "Mastercard Debit"
    )


def test_longest_prefix_wins():
    """A longer, more specific prefix must beat a shorter one."""
    cfg = dict(load_terminal_pools(_POOLS))
    cfg["bank_description_methods"] = {"MASTERCARD": "Mastercard", "MASTERCARD DEBIT": "Mastercard Debit"}
    assert method_from_bank_description("MASTERCARD DEBIT FOO", cfg) == "Mastercard Debit"
    assert method_from_bank_description("MASTERCARD FOO", cfg) == "Mastercard"


def test_unmapped_description_is_four_element_diagnostic():
    cfg = load_terminal_pools(_POOLS)
    with pytest.raises(ValueError) as exc_info:
        method_from_bank_description("BITCOIN TRANSFER SATOSHI", cfg)
    assert "BITCOIN TRANSFER SATOSHI" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_mapped_schemes_exist():
    cfg = load_terminal_pools(_POOLS)
    for scheme_name in cfg["bank_description_methods"].values():
        assert scheme_name in cfg["schemes"], f"{scheme_name} is not a configured scheme"


def test_debit_schemes_are_configured():
    schemes = load_terminal_pools(_POOLS)["schemes"]
    assert schemes["Visa Debit"]["display"] == "VISA DEBIT"
    assert schemes["Mastercard Debit"]["display"] == "MASTERCARD DEBIT"
    for name in ("Visa Debit", "Mastercard Debit"):
        assert set(schemes[name]["account_types"]) == {"CHQ", "SAV"}


def test_zero_weight_is_allowed_but_all_zero_is_not(tmp_path):
    """Cash: 0 must be accepted; a pool with no positive weight must not."""
    path = _write_pools(tmp_path, lambda pt: pt["receipt_method_weights"].update({"Cash": 0}))
    assert load_terminal_pools(path)["receipt_method_weights"]["Cash"] == 0

    def zero_all(pt):
        pt["receipt_method_weights"] = dict.fromkeys(pt["receipt_method_weights"], 0)

    second = tmp_path / "b"
    second.mkdir()  # _write_pools writes into this directory; it must exist first
    path2 = _write_pools(second, zero_all)
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path2)
    assert_diagnostic_error(exc_info.value)


def test_negative_weight_is_rejected(tmp_path):
    path = _write_pools(tmp_path, lambda pt: pt["receipt_method_weights"].update({"Cash": -1}))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert_diagnostic_error(exc_info.value)


def test_link_index_covers_every_receipt_stem():
    index = load_link_index(_LINKS_PATH)
    entries = load_ground_truth(Path("ground_truth/receipts.yml"))
    for case_id, entry in entries.items():
        assert f"{case_id}_{entry['layout']}" in index
    assert len(index) == 55, f"expected 55 receipt links, got {len(index)}"


def test_link_index_excludes_invoices():
    index = load_link_index(_LINKS_PATH)
    assert not [stem for stem in index if "invoice" in stem or "tax_" in stem]


def test_link_index_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_link_index(tmp_path / "nope.yml")
```

`_write_pools`, `_POOLS`, `assert_diagnostic_error`, `load_ground_truth` and `pytest` are already imported or defined at the top of `tests/test_payment_block.py` from the earlier payment-block work; only `load_link_index` and `method_from_bank_description` are new imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -k "bank_description or link_index or weight or debit" -v`
Expected: collection error — `cannot import name 'load_link_index'`.

- [ ] **Step 3: Add the config**

In `config/data_pools.yml`, inside `payment_terminal:`:

Set the cash weight to zero, keeping the key visible:
```yaml
  receipt_method_weights:
    EFTPOS: 30
    Visa: 25
    Mastercard: 20
    AMEX: 5
    Cash: 0            # every receipt in this corpus is linked to a bank transaction
    Apple Pay: 5
    Google Pay: 3
```

Add two debit schemes to `schemes:` (alongside the existing four):
```yaml
    Visa Debit:
      display: VISA DEBIT
      aid: A0000000031010
      pan_digits: 16
      account_types: [CHQ, SAV]
    Mastercard Debit:
      display: MASTERCARD DEBIT
      aid: A0000000041010
      pan_digits: 16
      account_types: [CHQ, SAV]
```

Add the mapping and the wallet presentation weights as new keys of `payment_terminal:`:
```yaml
  # A linked receipt's scheme is fixed by its bank row, not by the weighted pool.
  # Longest matching prefix wins. `validate` fails if a linked description matches none.
  bank_description_methods:
    MASTERCARD DEBIT: Mastercard Debit
    VISA DEBIT: Visa Debit
    EFTPOS: EFTPOS
  # A linked receipt's scheme is fixed; this decides how often that payment is
  # presented as a phone wallet over the same scheme. 'none' means plain card.
  wallet_presentation_weights:
    none: 90
    Apple Pay: 6
    Google Pay: 4
```

- [ ] **Step 4: Implement the mapping, the index, and the relaxed weight rule**

In `generators/payment_block.py`:

Add `bank_description_methods` and `wallet_presentation_weights` to `_REQUIRED_KEYS`:
```python
    "bank_description_methods": "a mapping of bank-description prefix -> schemes key",
    "wallet_presentation_weights": "a mapping of 'none' plus wallet names -> non-negative weights",
```

Add the links path constant next to `_DATA_POOLS_PATH`:
```python
_LINKS_PATH = Path(__file__).resolve().parent.parent / "ground_truth" / "transaction_links.yml"
```

Replace the weight check inside `load_terminal_pools` (the `if not isinstance(weight, int) or weight <= 0:` branch) with a non-negative rule, and add an at-least-one-positive check after the loop:
```python
        if not isinstance(weight, int) or weight < 0:
            raise _err(
                f"weight for '{method}' is not a non-negative integer (got {weight!r}).",
                path=path,
                key_path=f"{_ROOT_KEY}.receipt_method_weights.{method}",
                expected="a non-negative integer, e.g. 'EFTPOS: 30'. Use 0 to disable a "
                "method explicitly rather than deleting its key.",
                recover=f"set a non-negative integer weight for '{method}'",
            )

    if not any(pools["receipt_method_weights"].values()):
        raise _err(
            "every receipt_method_weights entry is zero, so no method can be picked.",
            path=path,
            key_path=f"{_ROOT_KEY}.receipt_method_weights",
            expected="at least one positive weight.",
            recover="give at least one method a positive weight",
        )
```

Validate the mapping and the wallet weights, after the existing `receipt_method_weights` loop:
```python
    for prefix, scheme_name in pools["bank_description_methods"].items():
        if scheme_name not in pools["schemes"]:
            raise _err(
                f"bank_description_methods['{prefix}'] names scheme '{scheme_name}', "
                "which is not configured.",
                path=path,
                key_path=f"{_ROOT_KEY}.bank_description_methods.{prefix}",
                expected=f"a key of 'schemes': {sorted(pools['schemes'])}.",
                recover=f"point '{prefix}' at a configured scheme",
            )

    for name, weight in pools["wallet_presentation_weights"].items():
        if name != "none" and name not in pools["wallets"]:
            raise _err(
                f"wallet_presentation_weights['{name}'] is not a configured wallet.",
                path=path,
                key_path=f"{_ROOT_KEY}.wallet_presentation_weights.{name}",
                expected=f"'none' or a key of 'wallets': {sorted(pools['wallets'])}.",
                recover=f"remove '{name}' or add it to {_ROOT_KEY}.wallets",
            )
        if not isinstance(weight, int) or weight < 0:
            raise _err(
                f"wallet presentation weight for '{name}' is not a non-negative integer "
                f"(got {weight!r}).",
                path=path,
                key_path=f"{_ROOT_KEY}.wallet_presentation_weights.{name}",
                expected="a non-negative integer, e.g. 'none: 90'.",
                recover=f"set a non-negative integer weight for '{name}'",
            )
```

Add the two new public functions after `load_terminal_pools`:
```python
def method_from_bank_description(description: str, cfg: dict) -> str:
    """Resolve a bank-statement description to the scheme the receipt must print.

    Longest matching prefix wins, so 'MASTERCARD DEBIT' beats 'MASTERCARD'.

    Args:
        description: The linked row's bank_description.
        cfg: The validated payment_terminal mapping.

    Returns:
        A key of cfg['schemes'].

    Raises:
        ValueError: no configured prefix matches the description.
    """
    mapping = cfg["bank_description_methods"]
    for prefix in sorted(mapping, key=len, reverse=True):
        if description.startswith(prefix):
            return mapping[prefix]

    raise _err(
        f"bank description '{description}' matches no configured prefix.",
        path=_DATA_POOLS_PATH,
        key_path=f"{_ROOT_KEY}.bank_description_methods",
        expected=f"a description starting with one of: {sorted(mapping)}.",
        recover="add a prefix mapping for this description shape",
    )


@lru_cache(maxsize=None)
def load_link_index(path: Path = _LINKS_PATH) -> dict[str, str]:
    """Map each linked receipt's image stem to its bank_description.

    Invoice links are skipped: invoices render no payment block. Where a stem
    carries several links the first is used; the seed script emits one per
    receipt.

    Args:
        path: Path to transaction_links.yml.

    Returns:
        {"CASE001_receipt_fuel": "VISA DEBIT PURCHASE ...", ...}

    Raises:
        FileNotFoundError: `path` does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(
            "transaction links file not found.\n"
            f"  What:     {path} does not exist.\n"
            f"  Where:    {path}\n"
            "  Expected: the receipt/invoice -> bank statement link ground truth.\n"
            f"  Recover:  restore {path} or run scripts/seed_transaction_links.py."
        )

    data = yaml.safe_load(path.read_text()) or {}
    index: dict[str, str] = {}
    for image_name, links in data.items():
        stem = str(image_name).removesuffix(".png")
        if "_receipt" not in stem or not links:
            continue
        index[stem] = links[0]["bank_description"]
    return index
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: all PASS. The corpus still renders the old methods — that is Task 2's job.

- [ ] **Step 6: Run the pre-commit gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all pass; mypy still at 10 pre-existing errors.

- [ ] **Step 7: Commit**

```bash
git add config/data_pools.yml generators/payment_block.py
git commit -m ":sparkles: map bank descriptions to receipt card schemes"
```

---

### Task 2: Force the scheme from the bank description

**Files:**
- Modify: `generators/payment_block.py` (`derive_payment`)
- Test: `tests/test_payment_block.py`

**Interfaces:**
- Consumes: `method_from_bank_description(description, cfg) -> str` and `load_link_index()` from Task 1.
- Produces: `derive_payment(case_id, invoice_date, total, time_str, *, pools=None, bank_description: str | None = None) -> PaymentDetails`. With `bank_description`, `scheme_name` is the mapped scheme and `wallet_presentation_weights` decides `kind`; with `None`, behaviour is byte-identical to today.

Digest slices stay as they are, with one addition: chars 10:14 pick the wallet presentation when a description is supplied (they pick the method otherwise), and 16:18 still choose the account type within the scheme.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_payment_block.py`:

```python
def test_bank_description_forces_the_scheme():
    d = derive_payment(
        "CASE001", "07/07/2024", "137.73", "10:33",
        bank_description="VISA DEBIT PURCHASE SQ *RAVENSDALE Alexandria AU",
    )
    assert d.scheme_name == "Visa Debit"
    assert d.scheme_display == "VISA DEBIT"
    assert d.kind in ("card", "wallet")
    assert d.kind != "cash", "a linked receipt can never be cash"


def test_forced_scheme_keeps_hash_derived_values():
    """Only the scheme changes; the rest of the slip stays hash-derived."""
    plain = derive_payment("CASE007", "07/07/2024", "137.73", "10:33")
    forced = derive_payment(
        "CASE007", "07/07/2024", "137.73", "10:33", bank_description="EFTPOS FOO AUS"
    )
    assert forced.psn == plain.psn
    assert forced.atc == plain.atc
    assert forced.terminal_id == plain.terminal_id
    assert forced.transaction_ref == plain.transaction_ref
    assert forced.timestamp == plain.timestamp
    assert forced.acquirer == plain.acquirer


def test_account_type_belongs_to_the_forced_scheme():
    cfg = load_terminal_pools(_POOLS)
    for i in range(1, 60):
        d = derive_payment(
            f"CASE{i:03d}", "07/07/2024", "137.73", "10:33",
            bank_description="VISA DEBIT PURCHASE FOO AU",
        )
        assert d.account_type in cfg["schemes"]["Visa Debit"]["account_types"]


def test_wallet_presentation_keeps_the_bank_scheme():
    """A wallet presentation must not change the scheme the bank row names."""
    wallets = [
        derive_payment(
            f"CASE{i:03d}", "07/07/2024", "137.73", "10:33",
            bank_description="VISA DEBIT PURCHASE FOO AU",
        )
        for i in range(1, 200)
    ]
    presented = [d for d in wallets if d.kind == "wallet"]
    assert presented, "no wallet presentation occurred across 199 cases"
    for d in presented:
        assert d.scheme_name == "Visa Debit"
        assert d.scheme_display == "VISA DEBIT"
        assert d.wallet_label
        assert d.entry_mode == load_terminal_pools(_POOLS)["entry_modes"]["wallet"]
    assert len(presented) < len(wallets) / 2, "wallets must stay a minority presentation"


def test_unlinked_receipt_falls_back_to_the_weighted_pick():
    """Without a description the derivation is byte-identical to before."""
    d = derive_payment("CASE001", "07/07/2024", "137.73", "10:33")
    assert d.method in load_terminal_pools(_POOLS)["receipt_method_weights"]


def test_cash_never_appears_now_that_its_weight_is_zero():
    for i in range(1, 200):
        d = derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33")
        assert d.method != "Cash", "Cash weight is 0, so it must never be picked"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -k "forces or forced or wallet_presentation or unlinked or cash_never" -v`
Expected: FAIL — `derive_payment() got an unexpected keyword argument 'bank_description'`.

- [ ] **Step 3: Implement the forced path**

In `generators/payment_block.py`, change the signature and docstring of `derive_payment`:

```python
def derive_payment(
    case_id: str,
    invoice_date: str,
    total: str,
    time_str: str,
    *,
    pools: dict | None = None,
    bank_description: str | None = None,
) -> PaymentDetails:
```

Add to its Args section:
```
        bank_description: The linked bank row's description. When given, the
            scheme is taken from it (the bank statement is the source of truth
            for a linked receipt) and wallet_presentation_weights decides
            whether the payment is presented as a phone wallet over that same
            scheme. When None, the weighted pool picks the method.
```

Replace the method pick and the cash branch guard. The current lines

```python
    method_pool = _weighted_pool(cfg["receipt_method_weights"])
    method = method_pool[int(digest[10:14], 16) % len(method_pool)]
```

become:

```python
    if bank_description is None:
        method_pool = _weighted_pool(cfg["receipt_method_weights"])
        method = method_pool[int(digest[10:14], 16) % len(method_pool)]
        forced_scheme = None
    else:
        # A linked receipt's scheme is fixed by its bank row; the same hash slice
        # that would have picked a method now picks the wallet presentation.
        forced_scheme = method_from_bank_description(bank_description, cfg)
        presentation_pool = _weighted_pool(cfg["wallet_presentation_weights"])
        presentation = presentation_pool[int(digest[10:14], 16) % len(presentation_pool)]
        method = forced_scheme if presentation == "none" else presentation
```

Then replace the scheme resolution below the cash branch. The current lines

```python
    wallets = cfg["wallets"]
    is_wallet = method in wallets
    scheme_names = sorted(cfg["schemes"])
    # A wallet transaction still runs over a card scheme; pick one by hash.
    scheme_name = scheme_names[int(digest[16:18], 16) % len(scheme_names)] if is_wallet else method
```

become:

```python
    wallets = cfg["wallets"]
    is_wallet = method in wallets
    if forced_scheme is not None:
        scheme_name = forced_scheme
    elif is_wallet:
        # A wallet transaction still runs over a card scheme; pick one by hash.
        scheme_names = sorted(cfg["schemes"])
        scheme_name = scheme_names[int(digest[16:18], 16) % len(scheme_names)]
    else:
        scheme_name = method
```

The cash branch is unreachable for a linked receipt because `Cash` is never a value of
`bank_description_methods`; no guard is needed, and `test_bank_description_forces_the_scheme`
asserts it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the pre-commit gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all pass. `tests/test_receipt_fit.py::test_unchanged_docs_byte_identical` is still green — the renderer does not pass a description yet.

- [ ] **Step 6: Commit**

```bash
git add generators/payment_block.py
git commit -m ":sparkles: force receipt scheme from the linked bank description"
```

---

### Task 3: Wire the renderer and prove the corpus invariant

**Files:**
- Modify: `generators/receipt.py` (the `payment` section branch)
- Modify: `tests/fixtures/receipt_baseline_hashes.json` (re-capture)
- Test: `tests/test_payment_block.py`

**Interfaces:**
- Consumes: `derive_payment(..., bank_description=...)` and `load_link_index()` from Tasks 1-2.
- Produces: receipts whose rendered scheme always matches their linked bank row.

- [ ] **Step 1: Write the failing invariant test**

Append to `tests/test_payment_block.py`. This is the proof of the fix — it fails 39 times today:

```python
def test_every_linked_receipt_matches_its_bank_row():
    """The invariant this whole change exists to establish."""
    from generators.receipt import _derive_receipt_details

    cfg = load_terminal_pools(_POOLS)
    index = load_link_index(_LINKS_PATH)
    entries = load_ground_truth(Path("ground_truth/receipts.yml"))

    mismatches = []
    for case_id, entry in entries.items():
        fields = entry["fields"]
        stem = f"{case_id}_{entry['layout']}"
        description = index[stem]
        pos = _derive_receipt_details(case_id, fields["INVOICE_DATE"])
        d = derive_payment(
            case_id,
            fields["INVOICE_DATE"],
            fields["TOTAL_AMOUNT"],
            pos["time"],
            bank_description=description,
        )
        expected = method_from_bank_description(description, cfg)
        if d.scheme_name != expected:
            mismatches.append(f"{stem}: bank={expected} receipt={d.scheme_name}")

    assert not mismatches, f"{len(mismatches)} receipts disagree with their bank row: {mismatches[:5]}"


def test_no_linked_receipt_is_cash():
    from generators.receipt import _derive_receipt_details

    index = load_link_index(_LINKS_PATH)
    for case_id, entry in load_ground_truth(Path("ground_truth/receipts.yml")).items():
        fields = entry["fields"]
        pos = _derive_receipt_details(case_id, fields["INVOICE_DATE"])
        d = derive_payment(
            case_id,
            fields["INVOICE_DATE"],
            fields["TOTAL_AMOUNT"],
            pos["time"],
            bank_description=index[f"{case_id}_{entry['layout']}"],
        )
        assert d.kind != "cash"


def test_rendered_receipt_prints_the_bank_scheme():
    """End-to-end: the scheme reaches the page, not just the dataclass."""
    from generators.receipt import _derive_receipt_details

    cfg = load_terminal_pools(_POOLS)
    index = load_link_index(_LINKS_PATH)
    layouts = load_layout_registry(_LAYOUTS_PATH)
    entries = load_ground_truth(Path("ground_truth/receipts.yml"))

    case_id = "CASE001"
    entry = dict(entries[case_id])
    entry["case_id"] = case_id
    fields = entry["fields"]
    expected_display = cfg["schemes"][
        method_from_bank_description(index[f"{case_id}_{entry['layout']}"], cfg)
    ]["display"]

    pos = _derive_receipt_details(case_id, fields["INVOICE_DATE"])
    details = derive_payment(
        case_id,
        fields["INVOICE_DATE"],
        fields["TOTAL_AMOUNT"],
        pos["time"],
        bank_description=index[f"{case_id}_{entry['layout']}"],
    )
    assert details.scheme_display == expected_display

    # The render must not raise, and must be taller than a two-line cash block.
    layout = layouts[entry["layout"]]
    stripped = dict(layout)
    stripped["sections"] = [s for s in layout["sections"] if s.get("type") != "payment"]
    grew = render_receipt(entry, layout).height - render_receipt(entry, stripped).height
    assert grew >= 12 * layout["line_height"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -k "linked_receipt or bank_scheme" -v`
Expected: `test_rendered_receipt_prints_the_bank_scheme` FAILS — CASE001 renders a two-line cash block today, so `grew` is 2 line heights, not 12. The other two pass already, because they call `derive_payment` with the description directly rather than through the renderer.

- [ ] **Step 3: Wire the renderer**

In `generators/receipt.py`, add to the imports:
```python
from generators.payment_block import derive_payment, load_link_index, render_payment_block
```

Replace the `derive_payment` call in the `payment` branch:
```python
        elif sec_type == "payment":
            details = derive_payment(
                case_id,
                inv_date,
                fields.get("TOTAL_AMOUNT", "0"),
                pos_details["time"],
                bank_description=load_link_index().get(f"{case_id}_{layout_id}"),
            )
```

`.get` rather than `[...]`: an unlinked receipt yields `None` and falls back to the weighted
pick, which is the documented behaviour for receipts with no bank match.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -v`
Expected: all PASS, including the invariant.

- [ ] **Step 5: Re-capture the render baselines**

Every receipt render changes again:

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

Then update the comment in `tests/test_receipt_fit.py::test_unchanged_docs_byte_identical` to
record that the baselines were re-captured after the bank-consistency change.

- [ ] **Step 6: Confirm bank and CC renders did NOT change**

Run: `conda run -n synthetic pytest tests/test_bank_fit.py tests/test_cc_fit.py tests/test_bank_supplier_header.py tests/test_cc_supplier_header.py -v`
Expected: all PASS with no re-capture. Bank ground truth is untouched by this change; if any of
these fail, stop — something reached beyond receipts.

- [ ] **Step 7: Run the pre-commit gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add generators/receipt.py
git commit -m ":sparkles: derive receipt payment from its linked bank transaction"
```

---

### Task 4: Validation guard against future drift

**Files:**
- Modify: `generators/pipeline.py` (the `validate` command)
- Test: `tests/test_payment_block.py`

**Interfaces:**
- Consumes: `load_link_index()`, `method_from_bank_description()`, `load_terminal_pools()`.
- Produces: `validate` exits 1 listing every receipt link whose `bank_description` maps to no scheme.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_payment_block.py`:

```python
def test_validate_passes_on_the_shipped_corpus():
    from typer.testing import CliRunner

    from generators.pipeline import app

    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 0, result.output


def test_validate_reports_unmapped_bank_descriptions(monkeypatch):
    """A link the mapping cannot resolve must fail validation, not render wrongly."""
    from typer.testing import CliRunner

    import generators.pipeline as pipeline_mod
    from generators.pipeline import app

    monkeypatch.setattr(
        pipeline_mod,
        "load_link_index",
        lambda: {"CASE001_receipt_fuel": "BITCOIN TRANSFER SATOSHI"},
    )
    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "CASE001_receipt_fuel" in result.output
    assert "BITCOIN TRANSFER SATOSHI" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -k validate -v`
Expected: `test_validate_reports_unmapped_bank_descriptions` FAILS with
`AttributeError: <module 'generators.pipeline'> has no attribute 'load_link_index'`.

- [ ] **Step 3: Add the check**

In `generators/pipeline.py`, add to the imports:
```python
from generators.payment_block import load_link_index, load_terminal_pools, method_from_bank_description
```

In `validate`, after the per-document-type loop and before the `if all_errors:` block:
```python
    # Every linked receipt's bank description must resolve to a card scheme, so a
    # reseed introducing a new description shape fails here rather than silently
    # rendering a receipt that contradicts its bank statement.
    terminal_cfg = load_terminal_pools()
    for stem, description in sorted(load_link_index().items()):
        try:
            method_from_bank_description(description, terminal_cfg)
        except ValueError:
            all_errors.append(
                f"{stem}: bank description '{description}' maps to no card scheme. "
                f"Add a prefix to payment_terminal.bank_description_methods in "
                f"config/data_pools.yml. Known prefixes: "
                f"{sorted(terminal_cfg['bank_description_methods'])}."
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `conda run -n synthetic pytest tests/test_payment_block.py -k validate -v`
Expected: both PASS.

- [ ] **Step 5: Run the whole pipeline end to end**

```bash
conda run -n synthetic python -m generators.pipeline validate
conda run -n synthetic python -m generators.pipeline generate --type receipts --clean-only
```
Expected: `Validation passed.` then `receipts: generated 55 documents.`

Open two rendered receipts from `output/clean/receipts/` and confirm against their links in
`ground_truth/transaction_links.yml`: a receipt whose bank row starts `VISA DEBIT` prints
`VISA DEBIT`, and one whose row starts `EFTPOS` prints `eftpos` with a `SAV`/`CHQ` account
type. No receipt shows `CASH TENDERED`.

- [ ] **Step 6: Run the pre-commit gate**

```bash
conda run -n synthetic pytest tests/
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add generators/pipeline.py
git commit -m ":white_check_mark: fail validation on unmapped bank descriptions"
```

- [ ] **Step 8: Update the earlier design doc's known follow-up**

`docs/receipt_payment_block_design.md` ends with a "Known follow-up" section describing this
mismatch as unresolved. Replace that section's body with a pointer to the fix:

```markdown
## Known follow-up

Resolved by `docs/receipt_bank_payment_consistency_design.md`: a linked receipt's scheme is
now derived from its bank row, and `validate` fails on any bank description the mapping cannot
resolve.
```

```bash
git add docs/receipt_payment_block_design.md
git commit -m ":memo: mark payment-method mismatch as resolved"
```

---

## Out of Scope (do not implement)

- `match_status: NOT_FOUND` receipt links so cash receipts can exist again. That changes the linking benchmark's 110-link, three-difficulty distribution and needs its own design.
- Any change to bank or CC statement ground truth, rendering, or baselines. Those staying green without re-capture is a verification step in Task 3.
- Invoice payment presentation: invoices render no payment block.
- Re-exporting the LMM_POC evaluation set. Re-run `python -m generators.pipeline eval-set --out <dir>` afterwards if you want the exported receipts refreshed.
