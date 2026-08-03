"""Row providers — the DSL's one sanctioned escape hatch.

Some table data is computed rather than stored: a bank statement's running
balance and opening row exist nowhere in ground truth. Rather than put
arithmetic in YAML, a table names a provider registered here, and the provider
returns row dicts. Providers return data only — they never draw or position.
"""

from collections.abc import Callable
from decimal import Decimal

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
            f"  Remediation: set rows: to a registered provider, or register a new "
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
            "pipe_fields provider needs a 'fields' mapping.\n"
            "  Expected: fields: {row_key: SOURCE_FIELD, ...}\n"
            "  Remediation: add a fields: mapping under the table's params:."
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
            "opening_balance and brought_forward are mutually exclusive; both were set.\n"
            "  Remediation: keep exactly one synthetic balance row on the table block."
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
        # Coerce real amounts to Decimal so the table formats them as currency, matching
        # the legacy renderer. The absent sentinel is left alone: legacy draws nothing
        # for it, and _cell_text maps it to the empty string.
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
    except (ArithmeticError, TypeError) as err:
        msg = (
            f"Malformed amount {value!r} in a bank transaction.\n"
            f"  Remediation: fix the amount in ground_truth/bank_statements.yml; "
            f"amounts are decimal strings without a currency sign, e.g. '137.73'."
        )
        raise ProviderError(msg) from err
