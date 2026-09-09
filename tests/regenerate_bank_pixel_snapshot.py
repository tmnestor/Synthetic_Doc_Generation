"""Regenerate the bank pixel-snapshot fixtures consumed by
`tests/test_bank_pixel_snapshot.py` (local-only; `tests/` is gitignored).

Writes two things, both under `tests/fixtures/`:

1. `bank_dsl_pixel_hashes.json` + `bank_dsl_pixel_reference/*.png` — the
   permanent regression guard. A sha256 of every DSL-rendered page, plus a
   full reference PNG per case used only to produce a diagnostic (differing
   pixel count, bounding box, overlapping field names) when a hash mismatch
   is detected. Re-run this after any *intended* rendering change (colour,
   weight, spacing, a new field) so the snapshot reflects the new reality.

2. `bank_legacy_dsl_identity_snapshot.json` — a one-time-per-run historical
   record of which ground-truth entries are currently byte-identical between
   the legacy per-bank renderers (`generators/bank_statement.py`) and the DSL
   path. This half only makes sense while the legacy renderers exist; Task 14
   deletes them, so this script's legacy half stops working (import error)
   the moment that happens. That is expected — capture it before Task 14.

Usage — dry run (default, writes nothing):

    conda run -n synthetic python tests/regenerate_bank_pixel_snapshot.py

Usage — actually write the fixtures:

    conda run -n synthetic python tests/regenerate_bank_pixel_snapshot.py --confirm

`--confirm` is required and defaults to False so that re-blessing the
snapshot is a deliberate act, not a side effect of running the script to see
what it would do. There is no other way to write these files.

Before writing anything, the script always computes a delta against whatever
is currently on disk — which case ids would change and by how many pixels —
and prints it. The delta computation and its printing are on ONE code path
shared by the dry run and the `--confirm` run (see `main`), so the two can
never show different things: whatever `--confirm` is about to bless is
exactly what the preceding dry run would have shown. That closes the failure
mode where a dry run looks clean (because it only echoed counts, not a diff
against the stored baseline) and `--confirm` then silently blesses a
regression.
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import typer
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from bank_pixel_diagnostics import explain_hash_mismatch  # noqa: E402
from generators.bank_statement import render_bank_statement, render_via_dsl  # noqa: E402
from generators.loader import load_ground_truth, load_layout_registry  # noqa: E402

_LAYOUT_PATH = Path("config/layouts/bank_statements.yml")
_GT_PATH = Path("ground_truth/bank_statements.yml")
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_DSL_HASH_PATH = _FIXTURES_DIR / "bank_dsl_pixel_hashes.json"
_DSL_REF_DIR = _FIXTURES_DIR / "bank_dsl_pixel_reference"
_LEGACY_SNAPSHOT_PATH = _FIXTURES_DIR / "bank_legacy_dsl_identity_snapshot.json"
# test_bank_fit.py's byte-identity guard hashes the same render as the pixel snapshot,
# from its own fixture. Regenerating one without the other leaves that test failing with
# no documented way to fix it, which invites hand-editing a fixture or deleting the test.
# Both are written together for that reason.
_FIT_BASELINE_PATH = _FIXTURES_DIR / "bank_baseline_hashes.json"

_BANK_OF_LAYOUT = {
    "cba_standard": "CBA",
    "cba_date_grouped": "CBA",
    "westpac_standard": "Westpac",
    "westpac_premium": "Westpac",
    "nab_classic": "NAB",
    "nab_dense": "NAB",
    "anz_standard": "ANZ",
    "anz_modern": "ANZ",
}


def _entries() -> list[tuple[str, dict, str, dict]]:
    """Return (case_id, entry, layout_id, layout) tuples, sorted by case_id."""
    layouts = load_layout_registry(_LAYOUT_PATH)
    gt = load_ground_truth(_GT_PATH)
    out = []
    for case_id, entry in sorted(gt.items()):
        entry = dict(entry)
        entry["case_id"] = str(case_id)
        layout_id = entry["layout"]
        out.append((str(case_id), entry, layout_id, layouts[layout_id]))
    return out


def _digest(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def build_snapshots(
    entries: list[tuple[str, dict, str, dict]],
) -> tuple[dict[str, str], dict, dict[str, Image.Image]]:
    """Render every bank ground-truth entry through both paths.

    Args:
        entries: (case_id, entry, layout_id, layout) tuples, as from `_entries()`.

    Returns:
        (dsl_hashes, legacy_snapshot, dsl_images) — dsl_hashes maps
        "{case_id}_{layout_id}" to a sha256 hex digest; legacy_snapshot is the
        full historical-evidence document described in the module docstring;
        dsl_images holds the rendered DSL page per key, for saving as
        reference PNGs.
    """
    dsl_hashes: dict[str, str] = {}
    dsl_images: dict[str, Image.Image] = {}
    cases: dict[str, dict] = {}
    summary: dict[str, dict] = {
        bank: {"entries": 0, "identical": 0, "total_diff_pixels": 0}
        for bank in sorted(set(_BANK_OF_LAYOUT.values()))
    }

    for case_id, entry, layout_id, layout in entries:
        key = f"{case_id}_{layout_id}"
        bank = _BANK_OF_LAYOUT[layout_id]

        # geometry_out={} (a real dict, not omitted) so this captures the same
        # recorder-present path generators/pipeline.py always uses in
        # production. See test_bank_pixel_snapshot.py's
        # test_dsl_pixel_snapshot_unchanged docstring for why that distinction
        # is load-bearing: a recorder-absent render used to differ from a
        # recorder-present one by up to ~1100px on some entries.
        dsl_img = render_via_dsl(entry, layout, layout_id, geometry_out={})
        legacy_img = render_bank_statement(entry, layout, geometry_out={})

        dsl_hash = _digest(dsl_img)
        legacy_hash = _digest(legacy_img)
        dsl_hashes[key] = dsl_hash
        dsl_images[key] = dsl_img

        a = np.array(dsl_img.convert("RGB"))
        b = np.array(legacy_img.convert("RGB"))
        diff_pixel_count = int((a != b).any(axis=-1).sum())
        identical = diff_pixel_count == 0

        cases[key] = {
            "bank": bank,
            "legacy_hash": legacy_hash,
            "dsl_hash": dsl_hash,
            "identical": identical,
            "diff_pixel_count": diff_pixel_count,
        }
        summary[bank]["entries"] += 1
        summary[bank]["identical"] += int(identical)
        summary[bank]["total_diff_pixels"] += diff_pixel_count

    legacy_snapshot = {
        "_meta": {
            "description": (
                "Historical evidence, not an assertion: which bank ground-truth "
                "entries were byte-identical between generators.bank_statement's "
                "legacy per-bank renderers and the layout_dsl path, captured "
                "before Task 14 deletes the legacy renderers. Re-run "
                "tests/regenerate_bank_pixel_snapshot.py --confirm to refresh "
                "while legacy still exists; after Task 14 this file is frozen."
            ),
            "entry_count": len(cases),
        },
        "summary": summary,
        "cases": cases,
    }
    return dsl_hashes, legacy_snapshot, dsl_images


def compute_delta(
    dsl_hashes: dict[str, str],
    dsl_images: dict[str, Image.Image],
    entries: list[tuple[str, dict, str, dict]],
) -> tuple[bool, list[str]]:
    """Compare freshly computed DSL hashes against what's currently on disk.

    Diffs against the CURRENTLY STORED reference PNGs — the ones about to be
    overwritten, not the new ones — so the explanation describes exactly what
    a re-bless would change, before it changes it.

    Returns:
        (has_baseline, changes). has_baseline is False only when
        `bank_dsl_pixel_hashes.json` doesn't exist yet (first-ever capture,
        nothing to diff against). changes is one human-readable line per
        case whose hash would change; empty means nothing would change.
    """
    if not _DSL_HASH_PATH.exists():
        return False, []

    old_hashes = json.loads(_DSL_HASH_PATH.read_text())
    by_key = {
        f"{case_id}_{layout_id}": (layout_id, layout, entry)
        for case_id, entry, layout_id, layout in entries
    }

    changes = []
    for key in sorted(dsl_hashes):
        if dsl_hashes[key] == old_hashes.get(key):
            continue
        layout_id, layout, entry = by_key[key]
        changes.append(explain_hash_mismatch(key, layout_id, layout, entry, dsl_images[key], _DSL_REF_DIR))
    return True, changes


def main(
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Actually write the fixture files. Without this flag, only a dry-run summary is printed.",
    ),
) -> None:
    """Regenerate the bank DSL pixel-snapshot hashes/references and the legacy identity snapshot.

    Always computes and prints the delta against what's currently on disk
    BEFORE checking `confirm` — the dry run and the `--confirm` run share this
    one code path, so a bare dry run can never look clean while `--confirm`
    would silently bless a regression: whatever the dry run shows is exactly
    what gets written.
    """
    entries = _entries()
    dsl_hashes, legacy_snapshot, dsl_images = build_snapshots(entries)
    has_baseline, changes = compute_delta(dsl_hashes, dsl_images, entries)

    print(f"DSL hashes: {len(dsl_hashes)} entries -> {_DSL_HASH_PATH}")
    print(f"DSL reference PNGs: {len(dsl_images)} files -> {_DSL_REF_DIR}/")
    print(f"Legacy identity snapshot -> {_LEGACY_SNAPSHOT_PATH}")
    for bank, s in sorted(legacy_snapshot["summary"].items()):
        print(
            f"  {bank}: {s['identical']}/{s['entries']} identical, {s['total_diff_pixels']} total diff px"
        )

    print()
    if not has_baseline:
        print(
            f"No existing snapshot at {_DSL_HASH_PATH} — this run would capture "
            f"the INITIAL baseline of {len(dsl_hashes)} entries (nothing to diff against)."
        )
    elif not changes:
        print(
            f"No changes detected — {len(dsl_hashes)}/{len(dsl_hashes)} entries match the current snapshot."
        )
    else:
        banner = "=" * 70
        print(banner)
        print(f"{len(changes)} of {len(dsl_hashes)} CASE(S) WOULD CHANGE:")
        print(banner)
        for line in changes:
            print(f"  - {line}")
        print(banner)

    if not confirm:
        print("\nDry run: nothing written. Pass --confirm to write these fixtures.")
        return

    _DSL_REF_DIR.mkdir(parents=True, exist_ok=True)
    for key, image in dsl_images.items():
        image.convert("RGB").save(_DSL_REF_DIR / f"{key}.png")

    _DSL_HASH_PATH.write_text(json.dumps(dsl_hashes, indent=2, sort_keys=True) + "\n")
    _LEGACY_SNAPSHOT_PATH.write_text(json.dumps(legacy_snapshot, indent=2, sort_keys=True) + "\n")
    _FIT_BASELINE_PATH.write_text(json.dumps(dsl_hashes, indent=2, sort_keys=True) + "\n")
    print("\nWrote all fixtures.")


if __name__ == "__main__":
    typer.run(main)
