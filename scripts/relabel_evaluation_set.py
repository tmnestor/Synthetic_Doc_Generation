"""Turn a raw synthetic evaluation set into pipeline-ready ground truth.

The generator emits ``synthetic.yml`` with one ``CASE0NN`` key per *case*, repeated
once per document type, carrying generator metadata and a superset of fields. YAML
allows duplicate keys, so a plain ``yaml.safe_load`` silently keeps only the last
block and drops two thirds of the ground truth.

This script rewrites the set into the shape the information-extraction pipeline
actually consumes. One ``--apply`` pass does three things:

1. **Relabel** — every document gets a unique key that matches its image stem::

       CASE001 (layout: cba_standard)   -> CASE001_bank_statement
       CASE001 (layout: tax_invoice_..) -> CASE001_invoice
       CASE001 (layout: receipt_fuel)   -> CASE001_receipt

   Images are renamed to match, so ``safe_load`` is safe and key == image stem.

2. **Project onto the schema** — each block is cut down to exactly the fields
   ``config/field_definitions.yaml`` defines for its document type, read through
   ``common.field_schema`` (the single source of truth). Generator metadata
   (``layout``, ``degradation_seed``) is dropped, non-schema fields are dropped,
   ``TRANSACTION_DESCRIPTIONS`` is renamed to its schema name, schema fields the
   generator did not emit become ``NOT_FOUND``, and values are formatted to the
   model-output convention (`` | `` separators, ``$`` on monetary, lowercase
   booleans).

   This matters: ``ExtractionEvaluator`` in JSONL mode scores *every* key in a
   ground-truth record, so a stray key is not inert — it is scored as a miss.

3. **Emit both artefacts** — ``synthetic.yml`` (readable) and
   ``ground_truth.jsonl`` (what ``pipeline.information_extraction.input.ground_truth``
   points at). Both carry identical field sets and identical values.

Nothing is lost: the original YAML is preserved as ``synthetic.yml.bak`` and every
rename is recorded in ``relabel_mapping.csv``, so the whole pass is reversible.

Defaults to a dry run. Nothing is touched without ``--apply``.

Usage:
    python scripts/relabel_evaluation_set.py                    # preview
    python scripts/relabel_evaluation_set.py --apply            # relabel + emit
    python scripts/relabel_evaluation_set.py --rebuild          # re-emit from .bak
    python scripts/relabel_evaluation_set.py --apply --dir /some/other/set
"""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.field_schema import FieldSchema, get_field_schema  # noqa: E402

DEFAULT_DIR = Path("/Users/tod/Desktop/evaluation_data/synthetic_20260728")
YAML_NAME = "synthetic.yml"
BACKUP_NAME = "synthetic.yml.bak"
JSONL_NAME = "ground_truth.jsonl"
MAPPING_NAME = "relabel_mapping.csv"

NOT_FOUND = "NOT_FOUND"

DOC_TYPE_SUFFIX = {
    "BANK_STATEMENT": "bank_statement",
    "INVOICE": "invoice",
    "RECEIPT": "receipt",
}

# Generator field name -> canonical schema field name (only where they differ).
# Mirrors ``_FIELD_ALIASES`` in scripts/generate_extraction_gt.py.
FIELD_ALIASES = {
    "TRANSACTION_DESCRIPTIONS": "LINE_ITEM_DESCRIPTIONS",  # bank statements
}


def diagnostic(what: str, where: str, expected: str, how_to_fix: str) -> str:
    """Assemble the four-element diagnostic every fail-fast error must carry."""
    return (
        f"❌ FATAL\n"
        f"   What: {what}\n"
        f"   Where: {where}\n"
        f"   Expected: {expected}\n"
        f"   How to fix: {how_to_fix}"
    )


def load_blocks(yaml_path: Path) -> list[tuple[str, dict]]:
    """Parse the YAML preserving duplicate top-level keys."""
    text = yaml_path.read_text()
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if root is None:
        raise SystemExit(
            diagnostic(
                what=f"{yaml_path.name} is empty or not a YAML mapping.",
                where=str(yaml_path),
                expected=(
                    "a mapping of CASE ids to document blocks, e.g.\n"
                    "       CASE001:\n"
                    "         layout: cba_standard\n"
                    "         fields:\n"
                    "           DOCUMENT_TYPE: BANK_STATEMENT"
                ),
                how_to_fix=f"point --dir at an evaluation set containing a valid {YAML_NAME}.",
            )
        )

    loader = yaml.SafeLoader(text)
    return [(key.value, loader.construct_document(value)) for key, value in root.value]


def format_value(field_name: str, raw: Any, schema: FieldSchema) -> str:
    """Format one generator value to the model-output convention.

    Multi-value fields are re-joined with `` | ``, monetary fields get a ``$``
    per item (``NOT_FOUND`` items untouched), booleans are lowercased.
    """
    text = str(raw).strip()
    if not text:
        return NOT_FOUND

    items = [item.strip() for item in text.split("|")]

    if field_name in schema.monetary_fields:
        items = [it if it.upper() == NOT_FOUND or it.startswith("$") else f"${it}" for it in items]
    elif field_name in schema.boolean_fields:
        items = [it.lower() for it in items]

    return " | ".join(items)


def project_fields(
    case_id: str, raw_fields: dict, doc_type: str, schema: FieldSchema, yaml_path: Path
) -> dict[str, str]:
    """Cut one block's fields down to its document type's schema fields.

    Applies :data:`FIELD_ALIASES`, emits the schema's field order, fills absent
    schema fields with ``NOT_FOUND``, and formats every value.
    """
    canonical = schema.resolve_doc_type(doc_type)
    known_types = schema.get_all_doc_type_fields()
    if canonical not in known_types:
        raise SystemExit(
            diagnostic(
                what=(
                    f"block '{case_id}' has DOCUMENT_TYPE={doc_type!r}, which is not a "
                    f"document type defined in the field schema."
                ),
                where=f"{yaml_path}, at '{case_id}.fields.DOCUMENT_TYPE'",
                expected=f"one of: {sorted(known_types)} (or a documented alias of one).",
                how_to_fix=(
                    "correct DOCUMENT_TYPE in the source YAML, or add the type to "
                    "config/field_definitions.yaml under 'document_fields:'."
                ),
            )
        )

    aliased = {FIELD_ALIASES.get(name, name): value for name, value in raw_fields.items()}

    projected: dict[str, str] = {}
    for name in schema.get_extraction_fields(canonical):
        value = aliased.get(name)
        projected[name] = (
            format_value(name, value, schema) if value is not None and str(value).strip() else NOT_FOUND
        )
    return projected


def plan_documents(
    blocks: list[tuple[str, dict]], eval_dir: Path, schema: FieldSchema, yaml_path: Path
) -> list[dict]:
    """Work out the unique key, image rename and projected fields for every block."""
    plan: list[dict] = []
    seen_keys: dict[str, str] = {}

    for case_id, block in blocks:
        missing = [k for k in ("layout", "fields") if k not in block]
        if missing:
            raise SystemExit(
                diagnostic(
                    what=f"block '{case_id}' is missing required key(s): {missing}.",
                    where=f"{yaml_path}, under '{case_id}:'",
                    expected=(
                        "every block needs 'layout' and 'fields', e.g.\n"
                        f"       {case_id}:\n"
                        "         layout: cba_standard\n"
                        "         fields:\n"
                        "           DOCUMENT_TYPE: BANK_STATEMENT"
                    ),
                    how_to_fix="add the missing key(s), or regenerate the evaluation set.",
                )
            )

        doc_type = block["fields"].get("DOCUMENT_TYPE")
        if doc_type not in DOC_TYPE_SUFFIX:
            raise SystemExit(
                diagnostic(
                    what=(
                        f"block '{case_id}' has DOCUMENT_TYPE={doc_type!r}, which has no "
                        f"filename suffix mapping."
                    ),
                    where=f"{yaml_path}, at '{case_id}.fields.DOCUMENT_TYPE'",
                    expected=f"one of: {sorted(DOC_TYPE_SUFFIX)}",
                    how_to_fix=(
                        f"correct DOCUMENT_TYPE, or add a mapping for it to DOC_TYPE_SUFFIX "
                        f"in {Path(__file__).name}."
                    ),
                )
            )

        new_key = f"{case_id}_{DOC_TYPE_SUFFIX[doc_type]}"
        old_stem = f"{case_id}_{block['layout']}"

        if new_key in seen_keys:
            raise SystemExit(
                diagnostic(
                    what=(
                        f"key collision - '{new_key}' would be produced twice (from "
                        f"'{seen_keys[new_key]}' and from '{old_stem}')."
                    ),
                    where=str(yaml_path),
                    expected="exactly one bank_statement, one invoice and one receipt per case.",
                    how_to_fix="remove or re-type the duplicate block before relabelling.",
                )
            )
        seen_keys[new_key] = old_stem

        plan.append(
            {
                "old_key": case_id,
                "new_key": new_key,
                "layout": block["layout"],
                "document_type": doc_type,
                "old_image": eval_dir / f"{old_stem}.png",
                "new_image": eval_dir / f"{new_key}.png",
                "fields": project_fields(case_id, block["fields"], doc_type, schema, yaml_path),
            }
        )

    plan.sort(key=lambda item: item["new_key"])
    return plan


def require_images(plan: list[dict], key: str, yaml_path: Path) -> None:
    """Fail fast unless every planned document has its image on disk."""
    missing = [item for item in plan if not item[key].exists()]
    if missing:
        first = missing[0]
        raise SystemExit(
            diagnostic(
                what=(
                    f"{len(missing)} of {len(plan)} documents have no image on disk "
                    f"(first: block '{first['old_key']}', layout '{first['layout']}')."
                ),
                where=f"expected file: {first[key]}",
                expected=(
                    "one PNG per block, named "
                    + ("{CASE}_{layout}.png" if key == "old_image" else "{CASE}_{doc_type}.png")
                ),
                how_to_fix=(
                    f"restore the missing image(s), or remove the orphaned block from {yaml_path.name}."
                ),
            )
        )


def unclaimed_images(plan: list[dict], eval_dir: Path, key: str) -> list[Path]:
    """PNGs in the directory that no block accounts for."""
    claimed = {item[key] for item in plan}
    return sorted(p for p in eval_dir.glob("*.png") if p not in claimed)


def write_yaml(plan: list[dict], yaml_path: Path) -> None:
    """Write the relabelled, schema-projected YAML."""
    document = {item["new_key"]: {"fields": item["fields"]} for item in plan}
    yaml_path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=10**6))


def write_jsonl(plan: list[dict], jsonl_path: Path) -> None:
    """Write the ground-truth JSONL the evaluate stage reads."""
    lines = [
        json.dumps({"filename": item["new_image"].name, **item["fields"]}, ensure_ascii=False)
        for item in plan
    ]
    jsonl_path.write_text("\n".join(lines) + "\n")


def write_mapping(plan: list[dict], mapping_path: Path) -> None:
    """Record every rename so the pass stays reversible."""
    with mapping_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["old_key", "new_key", "old_image", "new_image", "layout", "document_type"])
        for item in plan:
            writer.writerow(
                [
                    item["old_key"],
                    item["new_key"],
                    item["old_image"].name,
                    item["new_image"].name,
                    item["layout"],
                    item["document_type"],
                ]
            )


def verify(plan: list[dict], yaml_path: Path, jsonl_path: Path, schema: FieldSchema) -> None:
    """Prove the rewrite is complete and consistent across both artefacts."""
    reloaded = yaml.safe_load(yaml_path.read_text())
    if len(reloaded) != len(plan):
        raise SystemExit(
            diagnostic(
                what=(
                    f"verification failed - safe_load returned {len(reloaded)} entries but "
                    f"{len(plan)} were written."
                ),
                where=str(yaml_path),
                expected=f"{len(plan)} unique top-level keys.",
                how_to_fix=f"restore {BACKUP_NAME} over {yaml_path.name} and re-run.",
            )
        )

    records = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    if len(records) != len(plan):
        raise SystemExit(
            diagnostic(
                what=f"verification failed - {jsonl_path.name} has {len(records)} records, expected {len(plan)}.",
                where=str(jsonl_path),
                expected=f"{len(plan)} JSON objects, one per line.",
                how_to_fix=f"restore {BACKUP_NAME} over {yaml_path.name} and re-run.",
            )
        )

    for item, record in zip(plan, records, strict=True):
        key = item["new_key"]
        expected_fields = schema.get_extraction_fields(schema.resolve_doc_type(item["document_type"]))

        if reloaded[key]["fields"] != item["fields"]:
            raise SystemExit(
                diagnostic(
                    what=f"verification failed - fields changed for '{key}' after the YAML round trip.",
                    where=str(yaml_path),
                    expected="the projected fields, byte for byte.",
                    how_to_fix=f"restore {BACKUP_NAME} over {yaml_path.name} and re-run.",
                )
            )

        if record != {"filename": item["new_image"].name, **item["fields"]}:
            raise SystemExit(
                diagnostic(
                    what=f"verification failed - the JSONL record for '{key}' does not match the YAML block.",
                    where=str(jsonl_path),
                    expected="filename plus exactly the fields written to the YAML.",
                    how_to_fix=f"restore {BACKUP_NAME} over {yaml_path.name} and re-run.",
                )
            )

        if sorted(record) != sorted(["filename", *expected_fields]):
            raise SystemExit(
                diagnostic(
                    what=(
                        f"verification failed - record '{key}' does not carry exactly the schema "
                        f"fields for {item['document_type']}."
                    ),
                    where=str(jsonl_path),
                    expected=f"keys: {sorted(['filename', *expected_fields])}",
                    how_to_fix="re-run; if it persists, check config/field_definitions.yaml.",
                )
            )

        if not item["new_image"].exists():
            raise SystemExit(
                diagnostic(
                    what=f"verification failed - expected image {item['new_image'].name} is missing.",
                    where=str(item["new_image"]),
                    expected="one renamed PNG per document.",
                    how_to_fix=f"consult {MAPPING_NAME} in the evaluation set to undo the rename.",
                )
            )

    print(
        f"✅ verified: {len(reloaded)} documents in {yaml_path.name} and {jsonl_path.name}, "
        f"identical fields, schema-exact keys, every image present"
    )


def summarise(plan: list[dict], blocks: list[tuple[str, dict]], eval_dir: Path, key: str) -> None:
    """Print what the pass will do (or did)."""
    unclaimed = unclaimed_images(plan, eval_dir, key)
    duplicate_keys = len(blocks) - len({case_id for case_id, _ in blocks})

    print(f"evaluation set : {eval_dir}")
    print(f"documents      : {len(plan)}")
    print(f"unique keys    : before {len({k for k, _ in blocks})}, after {len(plan)}")
    print(f"duplicate keys : {duplicate_keys} (these are what safe_load was dropping)")
    if unclaimed:
        print(f"⚠️  images not referenced by the YAML ({len(unclaimed)}): {[p.name for p in unclaimed[:5]]}")

    by_type: dict[str, list[dict]] = {}
    for item in plan:
        by_type.setdefault(item["document_type"], []).append(item)
    print("\nschema projection:")
    for doc_type, items in sorted(by_type.items()):
        fields = items[0]["fields"]
        filled = sum(1 for value in fields.values() if value != NOT_FOUND)
        print(
            f"  {doc_type:<15} {len(items):>3} docs, {len(fields)} fields ({filled} populated in the first)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dir", type=Path, default=DEFAULT_DIR, help=f"evaluation set directory (default: {DEFAULT_DIR})"
    )
    parser.add_argument(
        "--apply", action="store_true", help="actually relabel and emit; without this it is a dry run"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            f"re-emit {YAML_NAME} + {JSONL_NAME} from {BACKUP_NAME} without renaming images "
            f"(use after a schema change)"
        ),
    )
    args = parser.parse_args()

    eval_dir: Path = args.dir
    yaml_path = eval_dir / YAML_NAME
    backup_path = eval_dir / BACKUP_NAME
    jsonl_path = eval_dir / JSONL_NAME
    schema = get_field_schema()

    if args.rebuild:
        if not backup_path.exists():
            raise SystemExit(
                diagnostic(
                    what=f"--rebuild needs the original YAML, but {BACKUP_NAME} does not exist.",
                    where=str(backup_path),
                    expected=f"{BACKUP_NAME}, written by a previous --apply run.",
                    how_to_fix="run without --rebuild to relabel the set from scratch.",
                )
            )
        source_path, image_key = backup_path, "new_image"
    else:
        if not yaml_path.exists():
            raise SystemExit(
                diagnostic(
                    what=f"{YAML_NAME} not found.",
                    where=str(eval_dir),
                    expected=f"{YAML_NAME} in the evaluation set directory.",
                    how_to_fix="pass --dir pointing at the evaluation set directory.",
                )
            )
        if backup_path.exists():
            raise SystemExit(
                diagnostic(
                    what=(
                        f"{BACKUP_NAME} already exists, so this set has already been relabelled. "
                        f"Relabelling again would overwrite the only pristine copy."
                    ),
                    where=str(backup_path),
                    expected="an evaluation set that has not been relabelled yet.",
                    how_to_fix=(
                        f"use --rebuild to re-emit {YAML_NAME} + {JSONL_NAME} from {BACKUP_NAME}, or "
                        f"restore {BACKUP_NAME} over {YAML_NAME} and undo the renames via {MAPPING_NAME} "
                        f"before re-running."
                    ),
                )
            )
        source_path, image_key = yaml_path, "old_image"

    blocks = load_blocks(source_path)
    plan = plan_documents(blocks, eval_dir, schema, source_path)
    require_images(plan, image_key, source_path)

    summarise(plan, blocks, eval_dir, image_key)

    if not args.rebuild:
        print("\nsample renames:")
        for item in plan[:6]:
            print(f"  {item['old_image'].name:<42} -> {item['new_image'].name}")
        if len(plan) > 6:
            print(f"  ... {len(plan) - 6} more")

    if not args.apply and not args.rebuild:
        print(f"\nDRY RUN - nothing changed. Re-run with --apply to relabel and write {JSONL_NAME}.")
        return

    if not args.rebuild:
        # Preserve the pristine YAML before touching anything.
        shutil.copy2(yaml_path, backup_path)
        print(f"\nbacked up {yaml_path.name} -> {backup_path.name}")

        # Record the mapping first so the rename is always reversible.
        write_mapping(plan, eval_dir / MAPPING_NAME)
        print(f"wrote {MAPPING_NAME}")

        # Two-phase rename so a new name can never clobber a not-yet-renamed file.
        for index, item in enumerate(plan):
            item["old_image"].rename(eval_dir / f".relabel_tmp_{index}.png")
        for index, item in enumerate(plan):
            (eval_dir / f".relabel_tmp_{index}.png").rename(item["new_image"])
        print(f"renamed {len(plan)} images")

    write_yaml(plan, yaml_path)
    print(f"wrote {yaml_path.name} ({len(plan)} unique keys, schema fields only)")

    write_jsonl(plan, jsonl_path)
    print(f"wrote {jsonl_path.name}")

    verify(plan, yaml_path, jsonl_path, schema)


if __name__ == "__main__":
    main()
