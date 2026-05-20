"""Derive flat CSV and JSONL from ground truth YAML files.

YAML is the single source of truth. This module regenerates derived
formats (CSV, JSONL) from YAML on every invocation.
"""

import csv
import json
from pathlib import Path

import yaml


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
