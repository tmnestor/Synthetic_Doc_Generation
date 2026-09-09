"""Phase A parity gate. Renders every receipt entry and asserts the page hash
and every recorded box match the baseline captured from the legacy renderer.

This does not retire with the legacy path the way the bank equivalence harness
did. After Task 14 it becomes the permanent regression guard for receipts, and
it is re-blessed only when Phase B intentionally changes the rendering.

To re-bless after an *intended* rendering change:

    conda run -n synthetic python tests/regenerate_doc_pixel_snapshot.py --confirm

There is no other way to update this fixture — `--confirm` is required and
defaults to False, so a bare run only prints a dry-run summary.
"""

import json

import pytest

from generators.loader import load_layout_registry
from generators.receipt import render_receipt

from regenerate_doc_pixel_snapshot import (
    _RECEIPT_GT_PATH,
    _RECEIPT_LAYOUT_PATH,
    _RECEIPT_SNAPSHOT_PATH,
    _digest,
    _entries,
)

BASELINE = json.loads(_RECEIPT_SNAPSHOT_PATH.read_text())
LAYOUTS = load_layout_registry(_RECEIPT_LAYOUT_PATH)
ENTRIES = _entries(_RECEIPT_GT_PATH)


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: f"{e['case_id']}_{e['layout']}")
def test_receipt_render_matches_baseline(entry):
    key = f"{entry['case_id']}_{entry['layout']}"
    geometry: dict = {}
    image = render_receipt(entry, LAYOUTS[entry["layout"]], geometry_out=geometry)
    expected = BASELINE[key]

    assert [image.width, image.height] == expected["size"]
    assert _digest(image) == expected["hash"]
    assert geometry["boxes"] == expected["boxes"]
