"""No real business name may be reachable by the fictional-name grammar.

`fictional_business_name` composes `{surname | suburb_prefix} {category_noun}` and
rejects blocklisted candidates at runtime. That guard is the last line of defence;
`reachable_blocked_names` is the first, and `pipeline validate` calls it so a pool
edit that makes a real company emittable fails when the pool is edited rather than
when a corpus is seeded.

Today nothing on the blocklist is reachable — the nouns are trade phrases and real
brands are not shaped like that — so these tests pin a property that currently holds
with room to spare, and would break loudly the moment it stopped.
"""

import pytest

from generators.content_engine import load_pools, reachable_blocked_names


@pytest.fixture
def pools() -> dict:
    return load_pools()


def test_no_blocklisted_name_is_reachable_from_the_real_pools(pools):
    reachable = reachable_blocked_names(pools)
    assert reachable == [], (
        f"the business-name grammar can emit {len(reachable)} real business name(s): "
        f"{reachable}. A prefix in business_name_parts combined with a category noun "
        f"produces them exactly — rename or remove the offending part."
    )


def test_a_colliding_pool_edit_is_detected(pools):
    """Adding 'Origin' + 'Energy' must surface Origin Energy as reachable."""
    parts = pools["business_name_parts"]
    parts["suburb_prefixes"] = [*parts["suburb_prefixes"], "Origin"]
    first_category = next(iter(parts["category_nouns"]))
    parts["category_nouns"][first_category] = [
        *parts["category_nouns"][first_category],
        "Energy",
    ]

    assert reachable_blocked_names(pools) == ["Origin Energy"]


def test_matching_is_case_insensitive(pools):
    """A lowercase pool entry must still be caught — the runtime guard lowercases too."""
    parts = pools["business_name_parts"]
    parts["suburb_prefixes"] = [*parts["suburb_prefixes"], "oRiGiN"]
    first_category = next(iter(parts["category_nouns"]))
    parts["category_nouns"][first_category] = [
        *parts["category_nouns"][first_category],
        "eNeRgY",
    ]

    assert reachable_blocked_names(pools) == ["Origin Energy"]


def test_a_near_miss_is_not_flagged(pools):
    """Only exact `{prefix} {noun}` matches count; resemblance is not reachability."""
    parts = pools["business_name_parts"]
    parts["suburb_prefixes"] = [*parts["suburb_prefixes"], "Origin"]
    # 'Energy' is never added, so "Origin Energy" cannot be composed.
    assert reachable_blocked_names(pools) == []
