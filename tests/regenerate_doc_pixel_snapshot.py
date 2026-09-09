"""Regenerate the receipt/invoice legacy pixel-snapshot fixtures consumed by
`tests/test_receipt_pixel_snapshot.py` and `tests/test_invoice_pixel_snapshot.py`
(local-only; `tests/` is gitignored).

This is Task 0 of the receipt/invoice layout-DSL migration: the Phase A
parity baseline, captured from the legacy renderers
(`generators/receipt.py`'s `render_receipt`, `generators/invoice.py`'s
`render_invoice`) while they still exist. Later tasks in the plan delete
those legacy renderers; after that there is no oracle left to diff a new
declarative-DSL render against. So this baseline is captured now, before a
single body is migrated, exactly for the same reason
`tests/regenerate_bank_pixel_snapshot.py`'s docstring records for banks.

Writes two fixtures, both under `tests/fixtures/`:

- `receipt_legacy_snapshot.json` — one entry per `ground_truth/receipts.yml`
  case, keyed `"{case_id}_{layout_id}"`, recording `{"hash", "size", "boxes"}`
  from a legacy `render_receipt` call.
- `invoice_legacy_snapshot.json` — the same, from `render_invoice` against
  `ground_truth/invoices.yml`.

`hash` is a sha256 of the rendered page's RGB bytes, `size` is `[width,
height]` (recorded explicitly, not just folded into the hash, because
receipts are variable-height — the renderer crops to content — so a height
regression should be caught as an explicit size mismatch rather than showing
up only as an opaque hash difference), and `boxes` is the full per-field
geometry dict populated by `geometry_out`.

Usage — dry run (default, writes nothing):

    conda run -n synthetic python tests/regenerate_doc_pixel_snapshot.py

Usage — actually write the fixtures:

    conda run -n synthetic python tests/regenerate_doc_pixel_snapshot.py --confirm

`--confirm` is required and defaults to False so that re-blessing the
snapshot is a deliberate act, not a side effect of running the script to see
what it would do. There is no other way to write these files.

Before writing anything, the script always computes a delta against whatever
is currently on disk for each fixture — which case ids would change — and
prints it. The delta computation and its printing are on ONE code path
shared by the dry run and the `--confirm` run (see `main`), so the two can
never show different things: whatever `--confirm` is about to bless is
exactly what the preceding dry run would have shown.
"""

import hashlib
import json
import sys
from pathlib import Path

import typer
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from generators.invoice import render_invoice  # noqa: E402
from generators.loader import load_ground_truth, load_layout_registry  # noqa: E402
from generators.receipt import render_receipt  # noqa: E402

_RECEIPT_LAYOUT_PATH = Path("config/layouts/receipts.yml")
_RECEIPT_GT_PATH = Path("ground_truth/receipts.yml")
_INVOICE_LAYOUT_PATH = Path("config/layouts/invoices.yml")
_INVOICE_GT_PATH = Path("ground_truth/invoices.yml")

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_RECEIPT_SNAPSHOT_PATH = _FIXTURES_DIR / "receipt_legacy_snapshot.json"
_INVOICE_SNAPSHOT_PATH = _FIXTURES_DIR / "invoice_legacy_snapshot.json"


def _entries(path: Path) -> list[dict]:
    """Return ground-truth entries for one document type, sorted by case_id.

    `load_ground_truth` returns a dict keyed by case_id whose entry dicts do
    not themselves carry the case_id (it's only the mapping key). The legacy
    renderers read `entry.get("case_id", ...)` for POS-detail derivation
    (receipts) and geometry logging, so it must be injected onto each entry
    here — mirroring `regenerate_bank_pixel_snapshot.py`'s `_entries`.

    Args:
        path: Path to a ground-truth YAML file, e.g. `ground_truth/receipts.yml`.

    Returns:
        Entry dicts sorted by case_id, each with a 'case_id' key added.
    """
    gt = load_ground_truth(path)
    out = []
    for case_id, entry in sorted(gt.items()):
        entry = dict(entry)
        entry["case_id"] = str(case_id)
        out.append(entry)
    return out


def _digest(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def build_snapshot(entries: list[dict], layouts: dict, render_fn) -> dict[str, dict]:
    """Render every entry through the legacy renderer and record its baseline.

    Args:
        entries: Entry dicts as returned by `_entries`.
        layouts: Layout registry, as returned by `load_layout_registry`.
        render_fn: `render_receipt` or `render_invoice`.

    Returns:
        Dict keyed `"{case_id}_{layout_id}"` to `{"hash", "size", "boxes"}`.
    """
    snapshot: dict[str, dict] = {}
    for entry in entries:
        layout_id = entry["layout"]
        key = f"{entry['case_id']}_{layout_id}"
        layout = layouts[layout_id]

        # geometry_out={} (a real dict, not omitted) so this captures the
        # same recorder-present path generators/pipeline.py always uses in
        # production, not a recorder-absent shortcut. See
        # test_bank_pixel_snapshot.py's docstring for why that distinction
        # is load-bearing for legacy renderers of this shape.
        geometry: dict = {}
        image = render_fn(entry, layout, geometry_out=geometry)

        snapshot[key] = {
            "hash": _digest(image),
            "size": [image.width, image.height],
            "boxes": geometry["boxes"],
        }
    return snapshot


def compute_delta(new_snapshot: dict[str, dict], existing_path: Path) -> tuple[bool, list[str]]:
    """Compare a freshly rendered snapshot against what's currently on disk.

    Returns:
        (has_baseline, changed_keys). has_baseline is False only when
        `existing_path` doesn't exist yet (first-ever capture, nothing to
        diff against). changed_keys lists case/layout keys whose hash, size,
        or boxes would change; empty means nothing would change.
    """
    if not existing_path.exists():
        return False, []

    old_snapshot = json.loads(existing_path.read_text())
    changed = [key for key in sorted(new_snapshot) if new_snapshot[key] != old_snapshot.get(key)]
    return True, changed


def _report(label: str, snapshot: dict[str, dict], path: Path) -> None:
    has_baseline, changed = compute_delta(snapshot, path)
    print(f"{label}: {len(snapshot)} entries -> {path}")
    if not has_baseline:
        print(
            f"  No existing snapshot at {path} — this run would capture the "
            f"INITIAL baseline of {len(snapshot)} entries (nothing to diff against)."
        )
    elif not changed:
        print(f"  No changes detected — {len(snapshot)}/{len(snapshot)} entries match the current snapshot.")
    else:
        print(f"  {len(changed)} of {len(snapshot)} CASE(S) WOULD CHANGE:")
        for key in changed:
            print(f"    - {key}")


def main(
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Actually write the fixture files. Without this flag, only a dry-run summary is printed.",
    ),
) -> None:
    """Regenerate the receipt and invoice legacy pixel-snapshot fixtures.

    Always computes and prints the delta against what's currently on disk
    BEFORE checking `confirm` — the dry run and the `--confirm` run share
    this one code path, so a bare dry run can never look clean while
    `--confirm` would silently bless a regression: whatever the dry run
    shows is exactly what gets written.
    """
    receipt_layouts = load_layout_registry(_RECEIPT_LAYOUT_PATH)
    receipt_entries = _entries(_RECEIPT_GT_PATH)
    receipt_snapshot = build_snapshot(receipt_entries, receipt_layouts, render_receipt)

    invoice_layouts = load_layout_registry(_INVOICE_LAYOUT_PATH)
    invoice_entries = _entries(_INVOICE_GT_PATH)
    invoice_snapshot = build_snapshot(invoice_entries, invoice_layouts, render_invoice)

    _report("Receipts", receipt_snapshot, _RECEIPT_SNAPSHOT_PATH)
    print()
    _report("Invoices", invoice_snapshot, _INVOICE_SNAPSHOT_PATH)

    if not confirm:
        print("\nDry run: nothing written. Pass --confirm to write these fixtures.")
        return

    _FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    _RECEIPT_SNAPSHOT_PATH.write_text(json.dumps(receipt_snapshot, indent=2, sort_keys=True) + "\n")
    _INVOICE_SNAPSHOT_PATH.write_text(json.dumps(invoice_snapshot, indent=2, sort_keys=True) + "\n")
    print("\nWrote both fixtures.")


if __name__ == "__main__":
    typer.run(main)
