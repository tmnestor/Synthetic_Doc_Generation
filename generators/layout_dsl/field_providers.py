"""Field providers -- the DSL's other sanctioned escape hatch.

Some values a receipt or invoice draws exist nowhere in ground truth: a
receipt number, POS time, register and staff name, and the seventeen EFTPOS
terminal-slip values -- today derived by SHA-256 inside `generators/receipt.py`
and `generators/payment_block.py`. A field provider is a registered Python
function returning a flat `dict[str, str]` that is merged into `entry["fields"]`
before a layout's body renders, so `{FIELD}` interpolation (`binding.py`) and
`when:` suppression (`engine.py`) reach these derived values with no change to
either.

Mirrors `providers.py`'s row-provider registry shape deliberately -- a reader
who knows one recognises the other. The one addition is `emits`, mandatory:
without it, `validate` could not resolve a `{FIELD}` naming a derived value,
and every placeholder check would degrade from a startup failure to a
render-time one.
"""

from collections.abc import Callable
from pathlib import Path

import yaml

FieldProvider = Callable[[dict, dict], dict[str, str]]

_REGISTRY: dict[str, FieldProvider] = {}
# Mirrors providers.py's _PARAM_KEYS: the top-level `params:` keys a provider
# reads, declared at registration time so schema.py can reject a typo'd
# params key (e.g. `terminl_id`) at validate time.
_PARAM_KEYS: dict[str, frozenset[str]] = {}
# The one addition over providers.py's registry: every `fields` key a
# provider may return. schema.py unions this into `known_fields` (per
# provider actually referenced by a layout) so a `{FIELD}` naming a derived
# value resolves at validate time, and `apply_field_providers` uses it below
# to reject a provider that returns a key it never declared.
_EMITS: dict[str, tuple[str, ...]] = {}

_FIELD_DEFINITIONS_PATH = Path("config/field_definitions.yml")

# Loaded once, on first registration -- see _scored_columns().
_SCORED_COLUMNS: set[str] | None = None


class FieldProviderError(RuntimeError):
    """Raised when a field provider is unknown, misregistered, or misbehaves."""


def _scored_columns() -> set[str]:
    """Return every column name `config/field_definitions.yml` scores.

    Loaded once and cached: registration happens a handful of times, all at
    import time, so there is no render-time cost to worry about -- this just
    avoids re-reading and re-parsing the YAML on every `@field_provider` use.

    Returns:
        Every name in field_definitions.yml's `all_columns` list -- the same
        46-name schema `derive_outputs.py` uses as the CSV header, i.e. every
        column this corpus scores as extraction ground truth.

    Raises:
        FieldProviderError: If the file is missing or has no `all_columns` list.
    """
    global _SCORED_COLUMNS  # noqa: PLW0603
    if _SCORED_COLUMNS is not None:
        return _SCORED_COLUMNS

    path = _FIELD_DEFINITIONS_PATH
    if not path.exists():
        msg = (
            "Cannot check a field provider's emits against the scored-column schema.\n"
            f"  What:     field definitions file not found.\n"
            f"  Where:    {path.resolve()}\n"
            "  Expected: config/field_definitions.yml with an 'all_columns:' list.\n"
            "  Recover:  restore config/field_definitions.yml, or fix the path in "
            "generators/layout_dsl/field_providers.py's _FIELD_DEFINITIONS_PATH."
        )
        raise FieldProviderError(msg)

    data = yaml.safe_load(path.read_text())
    columns = data.get("all_columns") if isinstance(data, dict) else None
    if not isinstance(columns, list):
        msg = (
            "Cannot check a field provider's emits against the scored-column schema.\n"
            f"  What:     {path} has no 'all_columns:' list.\n"
            f"  Where:    {path.resolve()} -> all_columns\n"
            "  Expected: all_columns:\n              - DOCUMENT_TYPE\n              - ...\n"
            f"  Recover:  add an 'all_columns:' list to {path}."
        )
        raise FieldProviderError(msg)

    _SCORED_COLUMNS = set(columns)
    return _SCORED_COLUMNS


def field_provider(
    name: str, *, params: frozenset[str] = frozenset(), emits: tuple[str, ...]
) -> Callable[[FieldProvider], FieldProvider]:
    """Register a field provider under `name`.

    Args:
        name: The name a layout's `field_providers:` entry uses.
        params: The top-level `params:` keys this provider reads (see
            `row_provider`'s identical rationale in `providers.py`).
        emits: Every `fields` key this provider may return. Mandatory --
            without it, `validate` could not resolve a `{FIELD}` naming a
            derived value, and `apply_field_providers` could not catch a
            provider returning a key it never declared.

    Returns:
        A decorator that registers and returns the function unchanged.

    Raises:
        FieldProviderError: If `name` is already registered, or an emitted
            name collides with a scored column `config/field_definitions.yml` owns.
    """

    def decorate(func: FieldProvider) -> FieldProvider:
        if name in _REGISTRY:
            msg = (
                "Cannot register field provider.\n"
                f"  What:     field provider '{name}' is already registered.\n"
                "  Where:    generators/layout_dsl/field_providers.py, "
                f"@field_provider('{name}', ...)\n"
                "  Expected: a distinct provider name.\n"
                "  Recover:  pick a distinct provider name."
            )
            raise FieldProviderError(msg)

        collisions = sorted(set(emits) & _scored_columns())
        if collisions:
            msg = (
                "Cannot register field provider.\n"
                f"  What:     field provider '{name}' declares emits {collisions} that collide "
                "with scored column name(s) config/field_definitions.yml owns.\n"
                "  Where:    generators/layout_dsl/field_providers.py, "
                f"@field_provider('{name}', emits=...)\n"
                "  Expected: emits names distinct from every column in "
                "config/field_definitions.yml's all_columns list.\n"
                f"  Recover:  rename {collisions} in '{name}''s emits= to a name that is not "
                "a scored column, e.g. prefix it POS_ or TERMINAL_."
            )
            raise FieldProviderError(msg)

        _REGISTRY[name] = func
        _PARAM_KEYS[name] = params
        _EMITS[name] = emits
        return func

    return decorate


def get_field_provider(name: str) -> FieldProvider:
    """Look up a registered field provider.

    Args:
        name: Provider name from a layout's `field_providers:` list.

    Returns:
        The registered provider.

    Raises:
        FieldProviderError: If no provider is registered under `name`.
    """
    if name not in _REGISTRY:
        msg = (
            "Unknown field provider.\n"
            f"  What:     no field provider named '{name}' is registered.\n"
            "  Where:    a layout's 'field_providers:' list.\n"
            f"  Expected: one of {sorted(_REGISTRY)}.\n"
            "  Recover:  set the entry's name: to a registered field provider, or register a "
            "new one with @field_provider in generators/layout_dsl/field_providers.py."
        )
        raise FieldProviderError(msg)
    return _REGISTRY[name]


def field_provider_names() -> list[str]:
    """Return the names of all registered field providers, sorted."""
    return sorted(_REGISTRY)


def field_provider_emits(name: str) -> tuple[str, ...]:
    """Return the `fields` keys a registered field provider may emit.

    Args:
        name: A registered field provider name (validate the name itself with
            `field_provider_names()`/`get_field_provider()` first; this
            returns an empty tuple for an unknown name rather than raising,
            since schema.py already reports the unknown-provider case with
            its own diagnostic before ever reaching an emits check).

    Returns:
        The tuple passed to this provider's `@field_provider(..., emits=...)`.
    """
    return _EMITS.get(name, ())


def field_provider_param_keys(name: str) -> frozenset[str]:
    """Return the top-level `params:` keys a registered field provider accepts.

    Args:
        name: A registered field provider name (see `field_provider_emits`'s
            identical note on validating the name first).

    Returns:
        The frozenset passed to this provider's `@field_provider(..., params=...)`.
    """
    return _PARAM_KEYS.get(name, frozenset())


def apply_field_providers(layout: dict, entry: dict) -> dict:
    """Merge every field provider a layout declares into a copy of `entry`.

    Args:
        layout: The resolved layout dict, carrying `field_providers` -- a
            required key (see `validate_layout` in `generators/layout_dsl/
            schema.py`), so a layout deriving nothing declares
            `field_providers: []` explicitly rather than omitting the key.
        entry: The ground-truth entry.

    Returns:
        A new entry dict -- never a mutation of `entry` -- whose `fields` is
        `entry["fields"]` merged with every provider's derived output.
        `pipeline.generate` reuses entries across the clean and degraded
        passes, so mutating the caller's entry would leak derived values
        between the two.

    Raises:
        FieldProviderError: If a `field_providers:` entry names an unknown
            provider, or a provider returns a key it did not declare in its
            own `emits`.
    """
    derived: dict[str, str] = {}
    for spec in layout["field_providers"]:
        name = spec["name"]
        provider = get_field_provider(name)
        result = provider(entry, spec.get("params", {}))

        declared = set(field_provider_emits(name))
        undeclared = sorted(set(result) - declared)
        if undeclared:
            msg = (
                "Field provider emitted an undeclared key.\n"
                f"  What:     field provider '{name}' returned key(s) {undeclared} not listed "
                "in its own emits=.\n"
                "  Where:    generators/layout_dsl/field_providers.py, "
                f"@field_provider('{name}', emits=...)\n"
                f"  Expected: emits including {undeclared}.\n"
                f"  Recover:  add {undeclared} to '{name}''s emits= tuple, or stop returning "
                "them from the provider."
            )
            raise FieldProviderError(msg)

        derived.update(result)

    return {**entry, "fields": {**entry["fields"], **derived}}
