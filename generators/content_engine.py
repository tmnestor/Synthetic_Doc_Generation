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
from faker import Faker

from generators.common import generate_abn

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


class ContentEngine:
    """Seeded generator for fictional AU business/trust/person/address content."""

    def __init__(self, pools: dict) -> None:
        self.pools = pools
        self._faker = Faker(pools["faker_config"]["locale"])
        # Defined baseline state before any per-call reseed in _seed_faker();
        # keeps a freshly-constructed engine deterministic even if a caller
        # (e.g. a future primitive) drew from self._faker before seeding rng.
        self._faker.seed_instance(pools["faker_config"]["seed_base"])
        self._blocklist = {
            name.lower()
            for name in (
                [r["name"] for r in pools["retailers"]]
                + [p["name"] for p in pools["professional_services"]]
                + pools["real_name_blocklist_extra"]
            )
        }

    def _seed_faker(self, rng: random.Random) -> None:
        """Reseed the engine's Faker instance from the injected rng stream."""
        self._faker.seed_instance(rng.randint(0, 2**32 - 1))

    def person(self, rng: random.Random) -> dict:
        """Return a seeded en_AU person: {first_name, last_name, full_name}."""
        self._seed_faker(rng)
        first = self._faker.first_name()
        last = self._faker.last_name()
        return {"first_name": first, "last_name": last, "full_name": f"{first} {last}"}

    def location(self, rng: random.Random) -> dict:
        """Return a seeded {suburb, postcode, state} dict from the locations pool."""
        return sample(rng, self.pools["locations"])

    def address(self, rng: random.Random) -> str:
        """Return a seeded AU-style address: "N Street St, Suburb ST PPPP"."""
        self._seed_faker(rng)
        street_num = self._faker.random_int(min=1, max=400)
        street_name = self._faker.last_name()
        street_type = sample(rng, self.pools["street_types"])
        loc = self.location(rng)
        return f"{street_num} {street_name} {street_type}, {loc['suburb']} {loc['state']} {loc['postcode']}"

    def fictional_business(self, rng: random.Random, category: str) -> dict:
        """Invented AU business (blocklist-screened) + generate_abn() + address.

        Returns:
            {name, address, abn, category}.

        Raises:
            ValueError: `category` has no entry in business_name_parts.category_nouns.
            RuntimeError: the retry budget was exhausted without a clean name.
        """
        parts = self.pools["business_name_parts"]
        nouns = parts["category_nouns"].get(category)
        if not nouns:
            raise ValueError(
                "content_engine.fictional_business: unknown category.\n"
                f"  What:     category {category!r} has no entry under "
                "'business_name_parts.category_nouns'.\n"
                f"  Where:    {_DATA_POOLS_PATH} -> "
                f"'business_name_parts.category_nouns.{category}'.\n"
                "  Expected: a list of nouns, e.g. "
                '\'hardware: ["Hardware", "Trade Supplies"]\'.\n'
                f"  Recover:  add a '{category}:' entry under "
                f"'business_name_parts.category_nouns' in {_DATA_POOLS_PATH}."
            )
        max_attempts = 20
        for _ in range(max_attempts):
            noun = sample(rng, nouns)
            if rng.random() < 0.5:
                name = f"{sample(rng, parts['surnames'])} {noun}"
            else:
                name = f"{sample(rng, parts['suburb_prefixes'])} {noun}"
            if name.lower() not in self._blocklist:
                return {
                    "name": name,
                    "address": self.address(rng),
                    "abn": generate_abn(),
                    "category": category,
                }
        raise RuntimeError(
            "content_engine.fictional_business: exhausted retry budget without a clean name.\n"
            f"  What:     {max_attempts} draws for category {category!r} all collided with "
            "the real-name blocklist.\n"
            f"  Where:    {_DATA_POOLS_PATH} -> 'business_name_parts' (category {category!r}) "
            "and 'real_name_blocklist_extra'.\n"
            "  Expected: enough surname/noun combinations for the category to clear the "
            f"blocklist within {max_attempts} attempts.\n"
            "  Recover:  widen 'business_name_parts.surnames', 'suburb_prefixes', or "
            f"'category_nouns.{category}' in {_DATA_POOLS_PATH}."
        )


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


def build_engine(path: Path = _DATA_POOLS_PATH) -> "ContentEngine":
    """Load pools from `path` and construct a ContentEngine."""
    return ContentEngine(load_pools(path))
