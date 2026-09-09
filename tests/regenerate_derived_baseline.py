"""Regenerate `tests/fixtures/derived_baseline.json` (local-only; `tests/` is
gitignored).

This is Task 1 of Stage 4 of the layout-DSL narrowing plan
(docs/layout_dsl_stage4_plan.md): before deleting the credit-card and four
trust document types, pin what `python -m generators.pipeline derive`
currently produces for the three *surviving* types — bank statements,
receipts, invoices — so the schema trim in a later task (dropping columns
from config/field_definitions.yml) can be checked against something more
precise than "the pixel snapshots still pass". A column silently dropped
from `all_columns` that a surviving type still relies on would change that
type's CSV header or JSONL key set without ever touching a rendered pixel.

`generators/derive_outputs.py` writes six artefacts from ground truth YAML:
`ground_truth.csv`, `ground_truth.jsonl`, `cord.jsonl`, `docile.jsonl`,
`native.jsonl`, `doc_refs.jsonl` (a seventh file, `geometry.jsonl`, is
written by `generate`, not `derive` — it is read here only as `derive_docile`'s
input, exactly as `pipeline.py`'s `derive` command does).

Three of the six already contain nothing but surviving-type rows by
construction — `cord.jsonl` (RECEIPT/INVOICE only), `docile.jsonl` (INVOICE
only) — those are baselined as a single whole-file subset. The other three
interleave surviving and doomed rows in one file and must be split before
hashing:

- `ground_truth.csv` / `ground_truth.jsonl`: split by the `DOCUMENT_TYPE`
  field into BANK_STATEMENT / RECEIPT / INVOICE (surviving) vs CC_STATEMENT
  and the four trust types (doomed, excluded).
- `native.jsonl`: split the same way — only BANK_STATEMENT survives; CC and
  the four trust types are excluded.
- `doc_refs.jsonl`: split by `link_type` — `receipt_to_bank` survives (this
  is the linking machinery Stage 4 explicitly retains); `trust_distribution_quad`
  is entirely doomed and excluded.

(This baseline predates Stage 4 Task 3's deletion of credit-card statements
and stays worded in terms of the original five doomed types — the surviving
BANK_STATEMENT / RECEIPT / INVOICE split below is unaffected either way.)

For each surviving subset this records the column header (CSV) or the
sorted key set (JSONL — records don't share a fixed column list, since only
fields actually present on an entry are emitted), the row count, and a
sha256 of the filtered rows (sorted by a stable identifying key, then
JSON-canonicalised) — a per-subset hash rather than one whole-file hash, so
a later failure names which artefact *and which surviving type* changed
instead of just "derived output changed".

Usage — dry run (default, writes nothing):

    conda run -n synthetic python tests/regenerate_derived_baseline.py

Usage — actually write the fixture:

    conda run -n synthetic python tests/regenerate_derived_baseline.py --confirm

`--confirm` is required and defaults to False, matching
`regenerate_doc_pixel_snapshot.py`'s convention: re-blessing a baseline is a
deliberate act, never a side effect of looking at what would change. Before
writing anything the script always computes and prints a delta against
whatever is currently on disk, on the same code path for both the dry run
and the `--confirm` run, so what `--confirm` is about to bless is exactly
what the preceding dry run showed.
"""

import csv
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).parent.parent))

from generators.derive_outputs import (  # noqa: E402
    derive_cord,
    derive_csv,
    derive_docile,
    derive_jsonl,
    derive_links,
    derive_native,
)
from generators.exporters.config import load_export_config  # noqa: E402
from generators.loader import load_generation_config  # noqa: E402

_REPO_ROOT = Path(__file__).parent.parent
_GENERATION_CONFIG_PATH = _REPO_ROOT / "config" / "generation_config.yml"
_EXPORT_CONFIG_PATH = _REPO_ROOT / "config" / "export_config.yml"
_FIELD_DEFS_PATH = _REPO_ROOT / "config" / "field_definitions.yml"
_GEOMETRY_PATH = _REPO_ROOT / "derived" / "geometry.jsonl"

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_BASELINE_PATH = _FIXTURES_DIR / "derived_baseline.json"

# The three document types Stage 4 keeps. Every subset recorded in the
# baseline is scoped to these — the five doomed types (cc_statement plus the
# four trust types) are deliberately excluded because they legitimately
# disappear in later tasks.
SURVIVING_DOCUMENT_TYPES: tuple[str, ...] = ("BANK_STATEMENT", "RECEIPT", "INVOICE")


def _gt_files() -> list[Path]:
    """Return the ground-truth YAML paths in the same order `pipeline.py`'s
    `derive` command builds them, resolved against the repo root so this
    script works regardless of the caller's cwd.
    """
    cfg = load_generation_config(_GENERATION_CONFIG_PATH)
    files = []
    for doc_cfg in cfg.get("document_types", {}).values():
        gt_path = _REPO_ROOT / doc_cfg["ground_truth"]
        if gt_path.exists():
            files.append(gt_path)
    return files


def _hash_rows(rows: list[dict], sort_key: str) -> str:
    """sha256 of a list of dict rows, order-stabilised by `sort_key`.

    Args:
        rows: Filtered rows belonging to one surviving subset.
        sort_key: The dict key to sort rows by before hashing (e.g.
            'image_file' or 'case_id') — rows are sorted rather than hashed
            in on-disk order so an incidental reordering of ground-truth
            entries doesn't register as a content change.

    Returns:
        Hex sha256 digest of the canonical JSON encoding.
    """
    ordered = sorted(rows, key=lambda r: r[sort_key])
    blob = json.dumps(ordered, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _jsonl_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line]


def _subset_by_document_type(rows: list[dict], sort_key: str) -> dict[str, dict]:
    """Split rows on DOCUMENT_TYPE and summarise each surviving subset.

    Args:
        rows: All rows from one artefact (CSV or JSONL), any document type.
        sort_key: Row key to sort by before hashing (see `_hash_rows`).

    Returns:
        Mapping of surviving DOCUMENT_TYPE -> {'keys', 'row_count', 'hash'}.
    """
    by_type: dict[str, dict] = {}
    for doc_type in SURVIVING_DOCUMENT_TYPES:
        subset = [r for r in rows if r.get("DOCUMENT_TYPE") == doc_type]
        keys = sorted(subset[0].keys()) if subset else []
        by_type[doc_type] = {
            "keys": keys,
            "row_count": len(subset),
            "hash": _hash_rows(subset, sort_key),
        }
    return by_type


def build_summary() -> dict:
    """Run every `derive_*` function into a scratch directory and summarise
    the surviving-type subset of each artefact.

    Returns:
        The full baseline dict, keyed by artefact filename.
    """
    gt_files = _gt_files()
    export_cfg = load_export_config(_EXPORT_CONFIG_PATH)
    cfg = load_generation_config(_GENERATION_CONFIG_PATH)
    gt_dir = _REPO_ROOT / cfg["ground_truth_dir"]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        csv_path = derive_csv(gt_files, _FIELD_DEFS_PATH, tmp_dir / "ground_truth.csv")
        jsonl_path = derive_jsonl(gt_files, tmp_dir / "ground_truth.jsonl")
        cord_path = derive_cord(gt_files, export_cfg, tmp_dir / "cord.jsonl")
        docile_path = derive_docile(gt_files, _GEOMETRY_PATH, export_cfg, tmp_dir / "docile.jsonl")
        native_path = derive_native(gt_files, tmp_dir / "native.jsonl")
        links_path = derive_links(
            gt_dir / "transaction_links.yml",
            export_cfg,
            tmp_dir / "doc_refs.jsonl",
        )

        csv_rows = _csv_rows(csv_path)
        summary: dict = {
            "ground_truth.csv": {
                "header": list(csv_rows[0].keys()) if csv_rows else [],
                "by_type": _subset_by_document_type(csv_rows, "image_file"),
            },
            "ground_truth.jsonl": {
                "by_type": _subset_by_document_type(_jsonl_rows(jsonl_path), "case_id"),
            },
            "native.jsonl": {
                # Of the six NATIVE_DOCUMENT_TYPES only BANK_STATEMENT
                # survives Stage 4 — the other five (cc + four trust) are
                # excluded here by SURVIVING_DOCUMENT_TYPES not naming them.
                "by_type": _subset_by_document_type(_jsonl_rows(native_path), "case_id"),
            },
            "doc_refs.jsonl": {
                "by_link_type": _subset_doc_refs(_jsonl_rows(links_path)),
            },
        }

        # cord.jsonl and docile.jsonl are already scoped to surviving types
        # by derive_cord/derive_docile's own CORD_DOCUMENT_TYPES /
        # DOCILE_DOCUMENT_TYPES filters (RECEIPT+INVOICE, INVOICE
        # respectively) — no doomed row can appear in either, so each is
        # baselined as one whole-file subset rather than split further.
        cord_rows = _jsonl_rows(cord_path)
        summary["cord.jsonl"] = {
            "keys": sorted(cord_rows[0].keys()) if cord_rows else [],
            "row_count": len(cord_rows),
            "hash": _hash_rows(cord_rows, "case_id"),
        }
        docile_rows = _jsonl_rows(docile_path)
        summary["docile.jsonl"] = {
            "keys": sorted(docile_rows[0].keys()) if docile_rows else [],
            "row_count": len(docile_rows),
            "hash": _hash_rows(docile_rows, "case_id"),
        }

    return summary


def _subset_doc_refs(rows: list[dict]) -> dict[str, dict]:
    """Split doc_refs rows on `link_type` and summarise the surviving side.

    Only 'receipt_to_bank' survives Stage 4 — 'trust_distribution_quad' is
    the trust-distribution linking machinery, entirely doomed, and excluded.

    Args:
        rows: All rows from doc_refs.jsonl, both link types.

    Returns:
        Mapping with a single surviving key, 'receipt_to_bank'.
    """
    subset = [r for r in rows if r.get("link_type") == "receipt_to_bank"]
    return {
        "receipt_to_bank": {
            "keys": sorted(subset[0].keys()) if subset else [],
            "row_count": len(subset),
            "hash": _hash_rows(subset, "source_doc"),
        }
    }


def compute_delta(new_summary: dict, existing_path: Path) -> tuple[bool, list[str]]:
    """Compare a freshly built summary against what's currently on disk.

    Returns:
        (has_baseline, changed_paths). has_baseline is False only when
        `existing_path` doesn't exist yet (first-ever capture). changed_paths
        is a list of dotted artefact/subset paths whose recorded summary
        would change; empty means nothing would change.
    """
    if not existing_path.exists():
        return False, []

    old = json.loads(existing_path.read_text())
    changed = []
    for artefact in sorted(new_summary):
        if new_summary[artefact] != old.get(artefact):
            changed.append(artefact)
    return True, changed


def main(
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Actually write the fixture file. Without this flag, only a dry-run summary is printed.",
    ),
) -> None:
    """Regenerate `tests/fixtures/derived_baseline.json`.

    Always computes and prints the delta against what's currently on disk
    BEFORE checking `confirm`, on the same code path the dry run uses, so a
    bare dry run can never look clean while `--confirm` silently blesses a
    regression.
    """
    summary = build_summary()
    has_baseline, changed = compute_delta(summary, _BASELINE_PATH)

    if not has_baseline:
        print(f"No existing baseline at {_BASELINE_PATH} — this run would capture the INITIAL baseline.")
    elif not changed:
        print(f"No changes detected across {len(summary)} artefact(s).")
    else:
        print(f"{len(changed)} of {len(summary)} artefact(s) WOULD CHANGE:")
        for artefact in changed:
            print(f"  - {artefact}")

    if not confirm:
        print("\nDry run: nothing written. Pass --confirm to write the fixture.")
        return

    _FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    _BASELINE_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"\nWrote {_BASELINE_PATH}.")


if __name__ == "__main__":
    typer.run(main)
