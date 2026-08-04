"""Row providers — the DSL's one sanctioned escape hatch.

Some table data is computed rather than stored: a bank statement's running
balance and opening row exist nowhere in ground truth. Rather than put
arithmetic in YAML, a table names a provider registered here, and the provider
returns row dicts. Providers return data only — they never draw or position.
"""

import hashlib
from collections.abc import Callable
from decimal import Decimal

from generators.common import fmt_amount

RowProvider = Callable[[dict, dict], list[dict]]

_REGISTRY: dict[str, RowProvider] = {}
# Each provider declares the top-level `params:` keys it reads, at
# registration time, alongside the function itself — the provider is the one
# place that knowledge belongs, since only it knows what it accepts. schema.py
# reads this via `provider_param_keys()` to reject an unknown params key (e.g.
# a typo like `opening_balnce`) at validate time rather than have it silently
# do nothing, indistinguishable from a param that was never set.
_PARAM_KEYS: dict[str, frozenset[str]] = {}


class ProviderError(RuntimeError):
    """Raised when a provider is unknown, duplicated, or given bad input."""


def row_provider(
    name: str, *, params: frozenset[str] = frozenset()
) -> Callable[[RowProvider], RowProvider]:
    """Register a row provider under `name`.

    Args:
        name: The name layouts use in a table's `rows:` key.
        params: The top-level `params:` keys this provider reads. Combinations
            the provider itself further restricts (e.g. two keys being
            mutually exclusive) stay a render-time `ProviderError` raised by
            the provider — this only declares which key *names* are valid,
            for schema.py to catch a typo before any provider runs.

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
        _PARAM_KEYS[name] = params
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


def provider_param_keys(name: str) -> frozenset[str]:
    """Return the top-level `params:` keys a registered provider accepts.

    Args:
        name: A registered provider name (validate the name itself with
            `provider_names()`/`get_provider()` first; this returns an empty
            set for an unknown name rather than raising, since schema.py
            already reports the unknown-provider case with its own
            diagnostic before ever reaching a params check).

    Returns:
        The frozenset passed to this provider's `@row_provider(..., params=...)`.
    """
    return _PARAM_KEYS.get(name, frozenset())


@row_provider("pipe_fields", params=frozenset({"fields"}))
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


@row_provider(
    "bank_transactions",
    params=frozenset(
        {
            "opening_balance",
            "brought_forward",
            "opening_balance_label",
            "brought_forward_label",
            "opening_balance_bold",
            "brought_forward_bold",
            "carried_forward",
            "references",
            "balance_suffix",
        }
    ),
)
def bank_transactions(entry: dict, params: dict) -> list[dict]:
    """Build bank statement rows with running balances computed backwards.

    Mirrors the legacy `_parse_transactions` / `_compute_running_balances`
    helpers: balances are derived from ACCOUNT_BALANCE (the closing balance) by
    walking the transactions in reverse.

    Args:
        entry: The ground-truth entry.
        params: Optional `opening_balance` or `brought_forward` booleans, which
            prepend a synthetic leading balance row (mutually exclusive with
            each other). Each may be paired with `<key>_label` (e.g.
            `brought_forward_label`) to override the row's default
            description text — ANZ's leading row reads "BALANCE BROUGHT
            FORWARD" (all caps), unlike NAB's "Balance Brought Forward"; both
            share the same computed opening-balance value, only the label
            differs, so it is an override rather than a third label key. Each
            may also be paired with `<key>_bold` (e.g. `brought_forward_bold:
            ["description"]`), a collection of row keys to render bold on
            that one row — ANZ's leading row is the one legacy draws with
            mixed weight (its label bold, its balance value not); absent, the
            whole row stays regular, matching every other leading row. An
            independent optional `carried_forward` boolean appends a trailing
            synthetic closing-balance row — it may combine with either
            leading option, matching NAB's legacy renderer, which shows both
            a "Brought forward" row (under the first date-group header) and a
            "Carried forward" row (after every transaction).
            An independent optional `references` boolean adds a `reference`
            key to every real (non-synthetic) row — NAB's dotted-leader
            reference number, computed exactly as the legacy renderer does:
            sha256 of the description, taken mod 10**10, zero-padded to 10
            digits, prefixed "Ref: " and suffixed with 40 dots.
            An independent optional `balance_suffix` dict — `{debit: "DR",
            credit: "CR"}` — replaces every row's Decimal `balance` with an
            already-formatted string carrying the sign-dependent suffix ANZ's
            legacy renderer picks (`_format_balance`): the amount's absolute
            value plus `debit` when negative, or the amount plus `credit`
            otherwise. Applied last, to every row (real and synthetic) that
            still carries a Decimal `balance` — a fixed `currency_suffix` on
            the column, as NAB uses, cannot express a suffix that depends on
            the value itself, so the provider computes the final display
            string instead and the column just draws it verbatim.

    Returns:
        One dict per row with keys `date`, `description`, `debit`, `credit`,
        `balance` (Decimal, or a pre-formatted string when `balance_suffix`
        is set), `synthetic` (bool); `reference` only on real rows, and only
        when `references` is set; `bold` (True) only on the `carried_forward`
        row, which legacy draws in `font_body_bold` unlike its leading-row
        counterparts.

    Raises:
        ProviderError: If both leading synthetic-row options are requested, or
            the transaction lists are ragged.
    """
    wants = [key for key in _SYNTHETIC_LABELS if params.get(key)]
    if len(wants) > 1:
        msg = (
            "opening_balance and brought_forward are mutually exclusive; both were set.\n"
            "  Remediation: keep exactly one leading synthetic balance row on the table block."
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

    if params.get("references"):
        for row in rows:
            digest = hashlib.sha256(row["description"].encode()).hexdigest()
            ref_num = str(int(digest, 16) % 10**10).zfill(10)
            row["reference"] = f"Ref: {ref_num}" + "." * 40

    # The closing balance is exactly the last real row's own balance -- the
    # reversed loop above seeds it straight from ACCOUNT_BALANCE before any
    # adjustment -- captured now, before a leading synthetic row (if any)
    # shifts what rows[0] means, and before a trailing one is appended.
    closing_balance = rows[-1]["balance"] if rows else balance

    if wants and rows:
        key = wants[0]
        first = rows[0]
        opening = first["balance"] - _to_decimal(first["credit"]) + _to_decimal(first["debit"])
        rows.insert(
            0,
            {
                "date": "",
                "description": params.get(f"{key}_label", _SYNTHETIC_LABELS[key]),
                "debit": "NOT_FOUND",
                "credit": "NOT_FOUND",
                "balance": opening,
                "synthetic": True,
                # ANZ's "BALANCE BROUGHT FORWARD" is the one leading row
                # legacy draws with mixed weight -- its description bold, its
                # balance value not -- so `<key>_bold` names which columns
                # should render bold (see primitives_table._cell_bold);
                # absent, the whole row stays regular, matching every other
                # leading row (CBA's "Opening Balance", NAB's own "Brought
                # forward"), which legacy draws entirely unbolded.
                **({"bold": set(params[f"{key}_bold"])} if params.get(f"{key}_bold") else {}),
            },
        )

    if params.get("carried_forward") and rows:
        rows.append(
            {
                "date": "",
                "description": "Carried forward",
                "debit": "NOT_FOUND",
                "credit": "NOT_FOUND",
                "balance": closing_balance,
                "synthetic": True,
                # Legacy draws this row in font_body_bold, unlike the leading
                # Opening Balance / Brought Forward rows above, which stay
                # regular weight -- a fact about this specific row, not a
                # layout-level style choice, so it is set here rather than
                # exposed as a YAML key.
                "bold": True,
            }
        )

    suffix = params.get("balance_suffix")
    if suffix:
        for row in rows:
            bal = row.get("balance")
            if not isinstance(bal, Decimal):
                continue
            row["balance"] = (
                f"{fmt_amount(bal)} {suffix['credit']}"
                if bal >= 0
                else f"{fmt_amount(abs(bal))} {suffix['debit']}"
            )

    return rows


@row_provider("bank_transaction_totals", params=frozenset({"label"}))
def bank_transaction_totals(entry: dict, params: dict) -> list[dict]:
    """Build a single trailing row summing every transaction's debits and credits.

    ANZ draws a "Totals at end of period" row below its transaction table,
    after a fresh rule -- not as part of the same row run `bank_transactions`
    produces. Appending it there instead would move `last_row_field`'s "last
    row" off the real closing-balance row and onto this one, which never
    carries a balance in legacy. A second table block, using this provider
    and the same column geometry, keeps the two concerns apart.

    Args:
        entry: The ground-truth entry.
        params: Must carry `label`, the text printed in the row's description column.

    Returns:
        A single-row list: `date` and `balance` empty (legacy draws neither
        for this row), `description` the label, `debit`/`credit` the summed
        Decimal totals, `synthetic: True` (never recorded — this row has no
        ground-truth field of its own), `bold: True` (legacy draws it in
        `font_body_bold`), `rule_above: True` (legacy rules above it after a
        fresh 12px gap, unlike an ordinary continued row).

    Raises:
        ProviderError: If `label` is missing from params.
    """
    if "label" not in params:
        msg = (
            "bank_transaction_totals provider requires a 'label' param.\n"
            "  What:     the label param is missing from the table's params:\n"
            "  Where:    config/layouts/bank_statements.yml, the totals table's params: key.\n"
            '  Expected: params: {label: "Totals at end of period"}\n'
            '  Recover:  add label: "Totals at end of period" to the totals table\'s '
            "params: block."
        )
        raise ProviderError(msg) from None

    rows = pipe_fields(
        entry,
        {"fields": {"debit": "TRANSACTION_AMOUNTS_PAID", "credit": "TRANSACTION_AMOUNTS_RECEIVED"}},
    )
    total_debits = sum((_to_decimal(row["debit"]) for row in rows), Decimal("0"))
    total_credits = sum((_to_decimal(row["credit"]) for row in rows), Decimal("0"))
    return [
        {
            "date": "",
            "description": params["label"],
            "debit": total_debits,
            "credit": total_credits,
            "synthetic": True,
            "bold": True,
            "rule_above": True,
        }
    ]


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
