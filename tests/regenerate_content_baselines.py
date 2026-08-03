"""Re-capture the content-pinned render baselines after a reseed.

`scripts/seed_ground_truth.py` regenerates every document type from one shared
RNG, so any change to one type's seeding shifts the content of all of them. The
`*_fit.py` byte-identity tests pin renders of that content, and after a reseed
they fail with no documented way to fix them — which invites hand-editing a
fixture or deleting the test.

Bank statements are deliberately absent: their baseline is written by
`regenerate_bank_pixel_snapshot.py`, alongside the pixel snapshot that hashes the
same render. Running both after a reseed re-captures everything.

Dry run by default; pass --confirm to write.

    conda run -n synthetic python tests/regenerate_content_baselines.py --confirm
"""

import hashlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from generators.cc_statement import render_cc_statement  # noqa: E402
from generators.invoice import render_invoice  # noqa: E402
from generators.loader import load_ground_truth, load_layout_registry  # noqa: E402
from generators.receipt import render_receipt  # noqa: E402

_FIXTURES = Path(__file__).parent / "fixtures"

# doc type -> (renderer, fixture filename)
_TARGETS = {
    "receipts": (render_receipt, "receipt_baseline_hashes.json"),
    "invoices": (render_invoice, "invoice_baseline_hashes.json"),
    "cc_statements": (render_cc_statement, "cc_baseline_hashes.json"),
}


def _hashes(doc_type: str, renderer) -> dict[str, str]:
    """Hash every entry's render for one document type.

    Args:
        doc_type: Ground-truth stem, e.g. "receipts".
        renderer: The `render_*(entry, layout)` callable for that type.

    Returns:
        Mapping of "<case_id>_<layout>" to the render's sha256.
    """
    entries = load_ground_truth(_REPO_ROOT / "ground_truth" / f"{doc_type}.yml")
    layouts = load_layout_registry(_REPO_ROOT / "config" / "layouts" / f"{doc_type}.yml")
    out: dict[str, str] = {}
    for case_id, entry in entries.items():
        entry["case_id"] = str(case_id)
        layout = layouts[entry["layout"]]
        digest = hashlib.sha256(renderer(entry, layout).tobytes()).hexdigest()
        out[f"{case_id}_{entry['layout']}"] = digest
    return out


def main() -> None:
    """Report what would change, and write the fixtures when --confirm is given."""
    confirm = "--confirm" in sys.argv
    for doc_type, (renderer, filename) in _TARGETS.items():
        path = _FIXTURES / filename
        fresh = _hashes(doc_type, renderer)
        old = json.loads(path.read_text()) if path.exists() else {}
        changed = sorted(k for k in fresh if old.get(k) != fresh[k])
        gone = sorted(k for k in old if k not in fresh)
        print(f"  {doc_type}: {len(fresh)} entries, {len(changed)} changed, {len(gone)} no longer present")
        for key in changed[:3]:
            print(f"      {key}")
        if len(changed) > 3:
            print(f"      ... and {len(changed) - 3} more")
        if confirm:
            path.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n")

    print("\nWrote all baselines." if confirm else "\nDry run: pass --confirm to write.")


if __name__ == "__main__":
    main()
