"""Tests for the doc_refs link mapper (spec Mapping C)."""

import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from conftest import assert_diagnostic_error
from generators.derive_outputs import derive_links
from generators.exporters.links import transaction_links_to_doc_refs

TRANSACTION_FIXTURE = {
    "CASE001_receipt_fuel.png": [
        {
            "bank_statement": "CASE001_cba_standard.png",
            "supplier": "Ravensdale Health Store",
            "receipt_date": "02/03/2023",
            "receipt_total": "13.60",
            "bank_date": "02/03/2023",
            "bank_description": "VISA DEBIT PURCHASE RAVENSDALE HEALTH STORE Alexandria AU",
            "bank_amount": "13.60",
            "match_status": "FOUND",
            "match_difficulty": "easy",
            "notes": "Early row on cba standard",
        }
    ]
}


def test_transaction_link_maps_to_doc_refs() -> None:
    records = transaction_links_to_doc_refs(TRANSACTION_FIXTURE, "spaced")
    assert records == [
        {
            "link_type": "receipt_to_bank",
            "source_doc": "CASE001_receipt_fuel.png",
            "target_doc": "CASE001_cba_standard.png",
            "match_keys": {
                "supplier": "Ravensdale Health Store",
                "date": "02/03/2023",
                "amount": "13.60",
            },
            "target_evidence": {
                "date": "02/03/2023",
                "description": ("VISA DEBIT PURCHASE RAVENSDALE HEALTH STORE Alexandria AU"),
                "amount": "13.60",
            },
            "label": "FOUND",
            "difficulty": "easy",
            "notes": "Early row on cba standard",
        }
    ]
    # Structural: exact top-level key set, in case the equality check above is
    # ever loosened to a subset comparison during a future refactor.
    assert set(records[0].keys()) == {
        "link_type",
        "source_doc",
        "target_doc",
        "match_keys",
        "target_evidence",
        "label",
        "difficulty",
        "notes",
    }
    assert set(records[0]["match_keys"].keys()) == {"supplier", "date", "amount"}
    assert set(records[0]["target_evidence"].keys()) == {"date", "description", "amount"}


def test_one_source_with_several_targets_yields_several_records() -> None:
    """The YAML value is a list — one receipt may match several bank rows."""
    fixture = {
        "CASE001_receipt_fuel.png": [
            TRANSACTION_FIXTURE["CASE001_receipt_fuel.png"][0],
            {
                **TRANSACTION_FIXTURE["CASE001_receipt_fuel.png"][0],
                "bank_statement": "CASE001_westpac_standard.png",
                "match_difficulty": "hard",
            },
        ]
    }
    records = transaction_links_to_doc_refs(fixture, "spaced")
    assert len(records) == 2
    assert {r["difficulty"] for r in records} == {"easy", "hard"}
    # Structural: both records trace back to the one source, each record
    # names a distinct target, and neither record is a duplicate of the other.
    assert all(r["source_doc"] == "CASE001_receipt_fuel.png" for r in records)
    assert all(r["link_type"] == "receipt_to_bank" for r in records)
    assert {r["target_doc"] for r in records} == {
        "CASE001_cba_standard.png",
        "CASE001_westpac_standard.png",
    }
    assert records[0]["target_doc"] == "CASE001_cba_standard.png"
    assert records[1]["target_doc"] == "CASE001_westpac_standard.png"


def test_transaction_links_rejects_unknown_identifier_form_diagnostic() -> None:
    """Transaction links carry no ABN or TFN, so identifier_form is otherwise
    unused on this path — but an invalid value (e.g. a typo'd
    abn_tfn_canonical_form in config/export_config.yml) must still fail fast
    here, rather than being silently accepted because this path never
    happens to call canonical_identifier itself.
    """
    with pytest.raises(ValueError) as exc:
        transaction_links_to_doc_refs(TRANSACTION_FIXTURE, "hyphenated")
    assert_diagnostic_error(exc.value)
    assert "hyphenated" in str(exc.value)
    assert "spaced" in str(exc.value)


def test_derive_links_writes_transaction_jsonl(tmp_path: Path) -> None:
    transactions_path = tmp_path / "transaction_links.yml"
    transactions_path.write_text(yaml.safe_dump(TRANSACTION_FIXTURE))
    out = tmp_path / "doc_refs.jsonl"

    result = derive_links(
        transactions_path,
        {"abn_tfn_canonical_form": "spaced", "abn_tfn_equality_form": "digits_only"},
        out,
    )

    assert result == out
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["link_type"] == "receipt_to_bank"
    assert record["source_doc"] == "CASE001_receipt_fuel.png"


def test_derive_links_creates_parent_directories(tmp_path: Path) -> None:
    """Mirrors derive_csv/derive_jsonl/derive_cord's mkdir(parents=True) behaviour."""
    transactions_path = tmp_path / "transaction_links.yml"
    transactions_path.write_text(yaml.safe_dump(TRANSACTION_FIXTURE))
    out = tmp_path / "nested" / "deeper" / "doc_refs.jsonl"

    derive_links(
        transactions_path,
        {"abn_tfn_canonical_form": "spaced", "abn_tfn_equality_form": "digits_only"},
        out,
    )

    assert out.exists()


def test_real_derived_output_has_expected_counts(tmp_path: Path) -> None:
    """A silent record drop is the main failure mode of this task: run the
    real derivation over the actual repo ground truth and pin exact counts
    per difficulty band, per the Task 1 Step 1 figures.
    """
    gt_dir = Path(__file__).parent.parent.parent / "ground_truth"
    out = tmp_path / "doc_refs.jsonl"

    derive_links(
        gt_dir / "transaction_links.yml",
        {"abn_tfn_canonical_form": "spaced", "abn_tfn_equality_form": "digits_only"},
        out,
    )

    records = [json.loads(line) for line in out.read_text().strip().split("\n")]
    assert len(records) == 110

    by_type = Counter(r["link_type"] for r in records)
    assert by_type == Counter({"receipt_to_bank": 110})

    by_difficulty = Counter(r["difficulty"] for r in records)
    assert by_difficulty == Counter({"easy": 52, "medium": 36, "hard": 22})

    # All 110 transaction links are match_status FOUND in the live data.
    labels = Counter(r["label"] for r in records)
    assert labels == Counter({"FOUND": 110})

    # Sanity-check the first record names a real receipt image, without pinning
    # which layout CASE001 happens to draw — that moves with every reseed, and
    # a literal here fails for a reason unrelated to link derivation.
    import yaml

    receipts = yaml.safe_load((gt_dir / "receipts.yml").read_text())
    expected = f"CASE001_{receipts['CASE001']['layout']}.png"
    assert records[0]["source_doc"] == expected
