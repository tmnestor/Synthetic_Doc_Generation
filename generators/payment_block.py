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
