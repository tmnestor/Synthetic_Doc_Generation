"""Tests for the rewired scripts/seed_ground_truth.py (local-only; tests/ is gitignored)."""

import importlib
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
seed_ground_truth = importlib.import_module("seed_ground_truth")


def test_generate_case_entities_produces_one_bundle_per_case():
    engine = seed_ground_truth.build_engine()
    rng = random.Random(1)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 5)
    assert len(entities) == 5
    assert all("holder" in e and "location" in e for e in entities)
    assert all(e["holder"]["full_name"] for e in entities)


def test_bank_and_invoice_share_holder_for_the_same_case():
    """PAYER_NAME must be identical across bank/invoice for a case (cross-case parity)."""
    engine = seed_ground_truth.build_engine()
    rng = random.Random(seed_ground_truth._SEED)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 3)
    bank = seed_ground_truth._generate_bank_entries(engine, rng, entities, 3)
    invoices = seed_ground_truth._generate_invoice_entries(engine, rng, entities, 3)
    for case_id in ("CASE001", "CASE002", "CASE003"):
        bank_payer = bank[case_id]["fields"]["PAYER_NAME"]
        invoice_payer = invoices[case_id]["fields"]["PAYER_NAME"]
        assert bank_payer == invoice_payer == entities[int(case_id[-3:]) - 1]["holder"]["full_name"]


def test_receipt_supplier_never_matches_a_real_retailer():
    engine = seed_ground_truth.build_engine()
    rng = random.Random(seed_ground_truth._SEED)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 55)
    receipts = seed_ground_truth._generate_receipt_entries(engine, rng, entities, 55)
    real_names = {r["name"] for r in engine.pools["retailers"]}
    assert len(receipts) == 55
    for entry in receipts.values():
        assert entry["fields"]["SUPPLIER_NAME"] not in real_names


def test_invoice_provider_never_matches_a_real_service_and_has_payer_address():
    engine = seed_ground_truth.build_engine()
    rng = random.Random(seed_ground_truth._SEED)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 55)
    invoices = seed_ground_truth._generate_invoice_entries(engine, rng, entities, 55)
    real_names = {p["name"] for p in engine.pools["professional_services"]}
    assert len(invoices) == 55
    for entry in invoices.values():
        fields = entry["fields"]
        assert fields["SUPPLIER_NAME"] not in real_names
        assert fields["PAYER_NAME"]
        assert "," in fields["PAYER_ADDRESS"]


def test_seeded_bank_supplier_matches_its_layout():
    """Root cause: the bank must be derived from the layout, not drawn independently,
    so SUPPLIER_NAME is always the canonical bank name implied by the layout prefix."""
    engine = seed_ground_truth.build_engine()
    rng = random.Random(seed_ground_truth._SEED)
    entities = seed_ground_truth._generate_case_entities(engine, rng, 55)
    bank = seed_ground_truth._generate_bank_entries(engine, rng, entities, 55)
    names = {b["code"]: b["name"] for b in engine.pools["banks"]}
    for entry in bank.values():
        code = entry["layout"].split("_")[0]
        assert entry["fields"]["SUPPLIER_NAME"] == names[code]


def test_dry_run_validates_without_writing_ground_truth(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_ground_truth, "_GT_DIR", tmp_path)
    seed_ground_truth.main(dry_run=True)
    assert not any(tmp_path.iterdir())
