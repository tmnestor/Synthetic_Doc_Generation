"""The degraded eval set is receipts only, one image per tier, with ground
truth duplicated per variant."""

import csv
import json
from pathlib import Path

import pytest

from generators.eval_set import export_eval_set

CONFIG = Path("config/generation_config.yml")


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("evalset")
    summary = export_eval_set(CONFIG, out, force=True)
    return summary, Path(summary["clean_dir"]), Path(summary["degraded_dir"])


def test_clean_dir_still_holds_every_type(exported):
    _, clean_dir, _ = exported
    names = [p.name for p in clean_dir.glob("*.png")]
    assert len(names) == 165
    assert sum("bank_statement" in n for n in names) == 55
    assert sum("invoice" in n for n in names) == 55
    assert sum("receipt" in n for n in names) == 55


def test_degraded_dir_holds_only_receipt_variants(exported):
    _, _, degraded_dir = exported
    names = [p.name for p in degraded_dir.glob("*.png")]
    assert len(names) == 165, "55 receipts x 3 tiers"
    assert all("receipt" in n for n in names)
    assert not any("bank_statement" in n or "invoice" in n for n in names)


def test_every_receipt_has_one_image_per_tier(exported):
    _, _, degraded_dir = exported
    names = {p.name for p in degraded_dir.glob("*.png")}
    for case in (1, 27, 55):
        for suffix in ("v1", "v2", "v3"):
            assert f"CASE{case:03d}_receipt_{suffix}.png" in names


def test_degraded_ground_truth_has_one_row_per_variant(exported):
    _, _, degraded_dir = exported
    rows = list(csv.DictReader((degraded_dir / "ground_truth.csv").open()))
    assert len(rows) == 165
    images = {p.name for p in degraded_dir.glob("*.png")}
    assert {r["image_file"] for r in rows} == images


def test_variants_of_a_case_share_identical_field_values(exported):
    """The value-F1 contract: distortion never changes the answer."""
    _, _, degraded_dir = exported
    rows = {r["image_file"]: r for r in csv.DictReader((degraded_dir / "ground_truth.csv").open())}
    for case in (1, 27, 55):
        variants = [rows[f"CASE{case:03d}_receipt_v{i}.png"] for i in (1, 2, 3)]
        for other in variants[1:]:
            for column, value in variants[0].items():
                if column == "image_file":
                    continue
                assert other[column] == value, f"CASE{case:03d} {column} differs across tiers"


def test_degraded_jsonl_matches_the_csv(exported):
    """The JSONL keys the image as `filename`; only the CSV renames it to
    `image_file` (see csv_from_jsonl)."""
    _, _, degraded_dir = exported
    lines = (degraded_dir / "ground_truth.jsonl").read_text().splitlines()
    assert len(lines) == 165
    assert {json.loads(line)["filename"] for line in lines} == {
        p.name for p in degraded_dir.glob("*.png")
    }


def test_variant_values_match_the_clean_receipt_row(exported):
    """A variant must carry its *source receipt's* answers, not merely be
    self-consistent across tiers.

    Compared over the degraded CSV's own columns, not the clean one's: the
    clean file spans all three document types, so its header carries bank- and
    invoice-only fields that a receipt-only file has no reason to include.
    """
    _, clean_dir, degraded_dir = exported
    clean = {r["image_file"]: r for r in csv.DictReader((clean_dir / "ground_truth.csv").open())}
    degraded = {r["image_file"]: r for r in csv.DictReader((degraded_dir / "ground_truth.csv").open())}
    for case in (1, 27, 55):
        source = clean[f"CASE{case:03d}_receipt.png"]
        variant = degraded[f"CASE{case:03d}_receipt_v2.png"]
        for column, value in variant.items():
            if column == "image_file":
                continue
            assert value == source[column], f"CASE{case:03d} {column} drifted from the clean row"


def test_degraded_header_is_receipt_shaped(exported):
    """A receipt-only file should not carry columns that would be NOT_FOUND in
    every row."""
    _, _, degraded_dir = exported
    header = next(iter(csv.DictReader((degraded_dir / "ground_truth.csv").open())))
    assert "STATEMENT_DATE_RANGE" not in header, "bank-only column in a receipt-only file"
    assert "TRANSACTION_DATES" not in header


def test_case_ids_still_resolve_for_linking(exported):
    """Case ids are unsuffixed, so transaction_links.yml keeps resolving."""
    _, _, degraded_dir = exported
    rows = list(csv.DictReader((degraded_dir / "ground_truth.csv").open()))
    for row in rows:
        assert row["image_file"].split("_")[0].startswith("CASE")


def test_summary_reports_both_counts(exported):
    summary, _, _ = exported
    assert summary["images"] == 165
    assert summary["degraded_images"] == 165
