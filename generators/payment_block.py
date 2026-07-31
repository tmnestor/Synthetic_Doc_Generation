"""EFTPOS terminal-slip block for synthetic receipts.

Owns the `payment_terminal` config in config/data_pools.yml, the deterministic
derivation of per-case terminal values, and the rendering of the three block
variants (card, wallet, cash). generators/receipt.py delegates its `payment`
section here and holds no terminal knowledge of its own.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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
        f"  Recover:  {recover} in {path}."
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
            recover=f"add a '{_ROOT_KEY}:' block",
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
                    expected="display (str), aid (str), pan_digits (int), account_types (non-empty list).",
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
