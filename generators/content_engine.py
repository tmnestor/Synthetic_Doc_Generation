"""Shared content-generation engine for seed scripts (core + trust).

Loads config/data_pools.yml once, owns a seeded Faker("en_AU"), and exposes
the primitives both scripts/seed_ground_truth.py and
scripts/seed_trust_distributions.py call in place of in-script constants and
`pool[i % len(pool)]` cycling: person/location/address (Faker + curated
locations), fictional_business / fictional_trust (invented AU entities
screened against a real-name blocklist), and sample / NonRepeatingSampler
(seeded pool draws). Every primitive is driven by an injected
`random.Random`, so a reseed is reproducible and diffable run-to-run.
"""

import random
from pathlib import Path

import yaml

_DATA_POOLS_PATH = Path(__file__).resolve().parent.parent / "config" / "data_pools.yml"

# Top-level keys load_pools() requires; each maps to the dotted sub-keys (if
# any) that must also be present, so a missing nested key fails fast too.
_REQUIRED_KEYS: dict[str, list[str]] = {
    "faker_config": ["locale", "seed_base"],
    "locations": [],
    "street_types": [],
    "business_name_parts": ["surnames", "suburb_prefixes", "category_nouns"],
    "product_catalog": [],
    "service_catalog": [],
    "payment_methods": [],
    "banks": [],
    "bank_descriptions": [],
    "retailers": [],
    "professional_services": [],
    "real_name_blocklist_extra": [],
}


def _missing_key_error(path: Path, dotted_key: str, subkeys: list[str]) -> str:
    """Build a four-element fail-fast diagnostic for a missing pool key."""
    example = f"a mapping with keys {subkeys}" if subkeys else "a non-empty value"
    return (
        "content pool is missing a required key.\n"
        f"  What:     '{dotted_key}' not found in {path}.\n"
        f"  Where:    {path} -> '{dotted_key}'.\n"
        f"  Expected: {example}.\n"
        f"  Recover:  add the missing key to {path} under '{dotted_key}'."
    )


def load_pools(path: Path = _DATA_POOLS_PATH) -> dict:
    """Load and validate config/data_pools.yml, failing fast on any missing key.

    Args:
        path: Path to the pools YAML file.

    Returns:
        The parsed pools dict.

    Raises:
        FileNotFoundError: `path` does not exist.
        ValueError: a required top-level or nested key is missing.
    """
    if not path.exists():
        raise FileNotFoundError(
            "content pool file not found.\n"
            f"  What:     {path} does not exist.\n"
            f"  Where:    {path}\n"
            "  Expected: a YAML file with the required top-level pool keys "
            "(see generators/content_engine.py _REQUIRED_KEYS).\n"
            f"  Recover:  create {path} (see config/data_pools.yml in the repo for the canonical shape)."
        )

    data = yaml.safe_load(path.read_text())

    for key, subkeys in _REQUIRED_KEYS.items():
        if key not in data:
            raise ValueError(_missing_key_error(path, key, subkeys))
        if subkeys:
            if not isinstance(data[key], dict):
                raise ValueError(_missing_key_error(path, key, subkeys))
            for sub in subkeys:
                if sub not in data[key]:
                    raise ValueError(_missing_key_error(path, f"{key}.{sub}", []))

    return data


def sample(rng: random.Random, pool: list):
    """Seeded single draw from a non-empty pool."""
    if not pool:
        raise ValueError(
            "content_engine.sample: pool is empty; cannot draw.\n"
            "  What:     sample() was called with an empty pool.\n"
            "  Where:    caller of generators.content_engine.sample.\n"
            "  Expected: a non-empty list.\n"
            "  Recover:  widen the source pool in config/data_pools.yml before sampling from it."
        )
    return rng.choice(pool)


class NonRepeatingSampler:
    """Cycles a shuffled copy of `pool`, reshuffling on exhaustion.

    Replaces `pool[i % len(pool)]`: draws are a random permutation of the
    pool each pass (not the same fixed order every cycle), so entity
    selection varies and de-correlates across doc types even when two
    samplers share the same underlying pool.
    """

    def __init__(self, rng: random.Random, pool: list) -> None:
        if not pool:
            raise ValueError(
                "content_engine.NonRepeatingSampler: pool is empty; cannot draw.\n"
                "  What:     NonRepeatingSampler was constructed with an empty pool.\n"
                "  Where:    caller of generators.content_engine.NonRepeatingSampler.\n"
                "  Expected: a non-empty list.\n"
                "  Recover:  widen the source pool in config/data_pools.yml before sampling from it."
            )
        self._rng = rng
        self._pool = list(pool)
        self._order: list = []
        self._i = 0

    def draw(self):
        """Return the next item; reshuffles a fresh permutation on exhaustion."""
        if self._i >= len(self._order):
            self._order = list(self._pool)
            self._rng.shuffle(self._order)
            self._i = 0
        item = self._order[self._i]
        self._i += 1
        return item
