"""Persisted pixel-snapshot regression test — prerequisite for Task 14.

`tests/test_bank_dsl_equivalence.py` only compares recorded field geometry.
It cannot see colour, font weight, rules, fills, or anything drawn in a
region that carries no ground-truth field — and four consecutive banks
shipped exactly that kind of defect (Westpac grey-vs-black text, NAB/ANZ
bold-weight mismatches, a stray #CCCCCC row rule CBA shipped for four tasks:
53,217 spurious pixels against legacy's 386). Every one was caught by ad-hoc
pixel inspection, never by an assertion, and none of that evidence persisted.

Task 14 deletes `generators/bank_statement.py`. After that there is no
oracle left to diff against, so this snapshot is captured now, while legacy
still exists, and split into two halves with different lifetimes:

- `test_dsl_pixel_snapshot_unchanged` is the permanent regression guard. It
  hashes the full page of every DSL-rendered bank ground-truth entry and
  asserts the hash is unchanged. This is what survives Task 14 and catches
  future regressions in colour, weight, rules and fills anywhere on the
  page — not just at recorded field boxes.
- `test_legacy_dsl_identity_snapshot_is_well_formed` checks the *shape* of
  the historical legacy-vs-DSL identity record captured by
  `regenerate_bank_pixel_snapshot.py`. It deliberately does not assert that
  any entry's legacy/DSL identity status holds — most entries are not
  byte-identical and that is expected (see the snapshot's `_meta` and
  `summary` for the recorded facts: today ANZ is 14/14 identical, 0 diff
  pixels; CBA/Westpac/NAB are not). This half retires with Task 14.

To re-bless after an *intended* rendering change:

    conda run -n synthetic python tests/regenerate_bank_pixel_snapshot.py --confirm

There is no other way to update these fixtures — `--confirm` is required and
defaults to False, so a bare run only prints a dry-run summary.
"""

import json
from pathlib import Path

import pytest

from generators.bank_statement import render_via_dsl
from generators.loader import load_ground_truth

from bank_pixel_diagnostics import explain_hash_mismatch
from regenerate_bank_pixel_snapshot import (
    _BANK_OF_LAYOUT,
    _DSL_HASH_PATH,
    _DSL_REF_DIR,
    _LEGACY_SNAPSHOT_PATH,
    _digest,
    _entries,
)

GT_PATH = Path("ground_truth/bank_statements.yml")


def _dsl_baseline() -> dict[str, str]:
    return json.loads(_DSL_HASH_PATH.read_text())


def _legacy_snapshot() -> dict:
    return json.loads(_LEGACY_SNAPSHOT_PATH.read_text())


def test_dsl_pixel_snapshot_unchanged():
    """The permanent regression guard: every DSL-rendered page hashes to its
    recorded baseline. Checks the full corpus, not a sample, for the same
    reason `test_bank_dsl_equivalence.py` did — it was the long, wrapped-row
    statements least likely to show up in a small sample.

    Renders with `geometry_out={}` (a real dict, not omitted) so this exercises
    the same recorder-present path `generators/pipeline.py` always uses in
    production — not a recorder-absent shortcut. A prior version of this test
    called `render_via_dsl` with no `geometry_out` at all, which certified a
    render path production never takes: `primitives_table.py`'s `last_row_field`
    handling used to draw certain cells a second time only when a recorder was
    present, and PIL alpha-composites each `draw.text` call's antialiased glyph
    mask onto what's already there, so that second draw measurably darkened
    every soft edge — invisible to a recorder-absent snapshot, live on every
    production image. Fixed in `_draw_row` (single draw, field name selected
    up front); this call now guards against that class of gap recurring."""
    baseline = _dsl_baseline()

    failures = []
    for case_id, entry, layout_id, layout in _entries():
        key = f"{case_id}_{layout_id}"
        image = render_via_dsl(entry, layout, layout_id, geometry_out={})
        digest = _digest(image)
        if digest != baseline.get(key):
            failures.append(explain_hash_mismatch(key, layout_id, layout, entry, image, _DSL_REF_DIR))

    assert not failures, (
        f"DSL pixel snapshot changed for {len(failures)}/{len(baseline)} case(s). "
        "If this is an intended rendering change, re-bless with "
        "`conda run -n synthetic python tests/regenerate_bank_pixel_snapshot.py --confirm`.\n\n"
        + "\n".join(failures)
    )


def test_legacy_dsl_identity_snapshot_is_well_formed():
    """Sanity-checks the historical legacy-vs-DSL record's shape and internal
    consistency. Deliberately does NOT assert that any entry's identical/
    diff_pixel_count value holds — that data documents what the migration
    changed (most entries are not byte-identical, by design), not a
    regression contract. It retires with Task 14 alongside the legacy
    renderers it was captured from."""
    snapshot = _legacy_snapshot()
    gt = load_ground_truth(GT_PATH)
    expected_keys = {f"{case_id}_{entry['layout']}" for case_id, entry in gt.items()}

    assert set(snapshot["cases"]) == expected_keys, (
        "legacy identity snapshot is stale relative to ground_truth/bank_statements.yml "
        "(case/layout set changed) — re-run "
        "`conda run -n synthetic python tests/regenerate_bank_pixel_snapshot.py --confirm`."
    )
    assert snapshot["_meta"]["entry_count"] == len(expected_keys)

    recomputed_summary: dict[str, dict[str, int]] = {}
    for key, record in snapshot["cases"].items():
        for field in ("bank", "legacy_hash", "dsl_hash", "identical", "diff_pixel_count"):
            assert field in record, f"{key}: legacy identity record missing '{field}'"
        assert record["bank"] == _BANK_OF_LAYOUT[key.split("_", 1)[1]]
        assert record["identical"] == (record["diff_pixel_count"] == 0), (
            f"{key}: identical/diff_pixel_count disagree"
        )

        bucket = recomputed_summary.setdefault(
            record["bank"], {"entries": 0, "identical": 0, "total_diff_pixels": 0}
        )
        bucket["entries"] += 1
        bucket["identical"] += int(record["identical"])
        bucket["total_diff_pixels"] += record["diff_pixel_count"]

    assert recomputed_summary == snapshot["summary"], (
        "legacy snapshot's per-bank summary doesn't match its cases"
    )


@pytest.mark.parametrize("bank", ["ANZ", "CBA", "Westpac", "NAB"])
def test_legacy_dsl_identity_summary_has_expected_shape(bank: str):
    """Coverage check only: each bank's summary counts entries and stays
    within [0, entries] — not a claim about what the counts should be."""
    summary = _legacy_snapshot()["summary"][bank]
    assert summary["entries"] > 0
    assert 0 <= summary["identical"] <= summary["entries"]
    assert summary["total_diff_pixels"] >= 0
