"""Derive flat CSV and JSONL from ground truth YAML files.

YAML is the single source of truth. This module regenerates derived
formats (CSV, JSONL) from YAML on every invocation.
"""

import csv
import json
from pathlib import Path

import yaml

from generators.exporters.cord import to_cord
from generators.exporters.links import transaction_links_to_doc_refs, trust_quads_to_doc_refs


def derive_csv(
    gt_files: list[Path],
    field_defs_path: Path,
    output_path: Path,
) -> Path:
    """Derive a flat CSV from one or more ground truth YAML files.

    Omitted fields are filled with 'NOT_FOUND'. An 'image_file' column
    is prepended using the filename convention: {CASEID}_{layout}.png.

    Args:
        gt_files: Paths to ground truth YAML files.
        field_defs_path: Path to field_definitions.yml.
        output_path: Where to write the CSV.

    Returns:
        Path to the written CSV file.
    """
    field_defs = yaml.safe_load(field_defs_path.read_text())
    all_columns = field_defs["all_columns"]

    rows: list[dict[str, str]] = []
    for gt_path in gt_files:
        data = yaml.safe_load(gt_path.read_text())
        if not isinstance(data, dict):
            continue
        for case_id, entry in data.items():
            fields = entry.get("fields", {})
            layout = entry.get("layout", "unknown")
            image_file = f"{case_id}_{layout}.png"
            row: dict[str, str] = {"image_file": image_file}
            for col in all_columns:
                row[col] = str(fields.get(col, "NOT_FOUND"))
            rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["image_file", *all_columns]
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)

    return output_path


def derive_jsonl(
    gt_files: list[Path],
    output_path: Path,
) -> Path:
    """Derive JSONL from one or more ground truth YAML files.

    Each line is a JSON object with case_id, layout, degradation_seed,
    image_file, and all field values.

    Args:
        gt_files: Paths to ground truth YAML files.
        output_path: Where to write the JSONL.

    Returns:
        Path to the written JSONL file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for gt_path in gt_files:
            data = yaml.safe_load(gt_path.read_text())
            if not isinstance(data, dict):
                continue
            for case_id, entry in data.items():
                fields = entry.get("fields", {})
                layout = entry.get("layout", "unknown")
                record = {
                    "case_id": str(case_id),
                    "layout": layout,
                    "degradation_seed": entry.get("degradation_seed"),
                    "image_file": f"{case_id}_{layout}.png",
                    **{k: str(v) for k, v in fields.items()},
                }
                f.write(json.dumps(record) + "\n")

    return output_path


CORD_DOCUMENT_TYPES: frozenset[str] = frozenset({"RECEIPT", "INVOICE"})


def derive_cord(
    gt_files: list[Path],
    export_config: dict,
    output_path: Path,
) -> Path:
    """Derive CORD gt_parse JSONL from ground truth YAML files.

    Only receipts and invoices are emitted; other document types have no CORD
    equivalent (spec section 7).

    Args:
        gt_files: Paths to ground truth YAML files.
        export_config: The validated export config mapping.
        output_path: Where to write the JSONL.

    Returns:
        Path to the written JSONL file.
    """
    identifier_form = export_config["abn_tfn_canonical_form"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for gt_path in gt_files:
            data = yaml.safe_load(gt_path.read_text())
            if not isinstance(data, dict):
                continue
            for case_id, entry in data.items():
                fields = entry.get("fields", {})
                if fields.get("DOCUMENT_TYPE") not in CORD_DOCUMENT_TYPES:
                    continue
                layout = entry.get("layout", "unknown")
                record = {
                    "case_id": str(case_id),
                    "image_file": f"{case_id}_{layout}.png",
                    "gt_parse": to_cord(fields, identifier_form),
                }
                f.write(json.dumps(record) + "\n")

    return output_path


def derive_links(
    link_files: dict[str, Path],
    export_config: dict,
    output_path: Path,
) -> Path:
    """Derive doc_refs JSONL from the two link ground truth files.

    Args:
        link_files: Mapping with keys 'transactions' and 'trust_quads' to
            their YAML paths.
        export_config: The validated export config mapping.
        output_path: Where to write the JSONL.

    Returns:
        Path to the written JSONL file.
    """
    identifier_form = export_config["abn_tfn_canonical_form"]
    records: list[dict] = []

    transactions = yaml.safe_load(link_files["transactions"].read_text())
    records.extend(transaction_links_to_doc_refs(transactions, identifier_form))

    quads = yaml.safe_load(link_files["trust_quads"].read_text())
    records.extend(trust_quads_to_doc_refs(quads, identifier_form))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    return output_path
