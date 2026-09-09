"""The DocILE export, scored against itself via the published evaluate_dataset,
must be perfect -- and the gate must be able to fail.

Step 1 (this task's brief) was to inspect the real interfaces rather than trust
guessed ones. Reading Dataset.__init__, Document.__init__ and DataPaths (all in
docile.dataset) showed that Dataset is not an in-memory container: it expects
an on-disk directory following DocILE's own layout --
``{root}/annotations/{docid}.json`` and ``{root}/ocr/{docid}.json`` -- loaded
lazily through ``CachedObject.content`` (reads from disk if the path exists).
``Dataset(split_name, root, docids=[...])`` accepts an explicit docid list, so
no index file is required.

``Field.from_dict``'s expected keys -- {bbox, page, score, text, fieldtype,
line_item_id, use_only_for_ap} -- are exactly the keys ``to_docile`` already
emits (confirmed by reading ``Field.from_dict``'s source), so the *same*
record dicts serve as both the on-disk gold annotation
(field_extractions / line_item_extractions) and the in-memory ``Field``
predictions. Self-score is therefore a genuine round trip through the
library's own matching code, not a hand-rolled stub of it.

The published matching metric (``docile.evaluation.pcc.pccs_iou``) computes
IoU over OCR-derived Pseudo-Character-Centers (PCCs), not raw bbox overlap --
confirmed by reading ``get_document_pccs`` / ``pccs_iou`` / ``_calculate_pccs``
directly. This project's ground truth carries no independent OCR word stream,
so each document's ``ocr/{docid}.json`` here is built from the *same*
field text+bbox pairs already in the export: one "OCR word" per field, with
its ``snapped_geometry`` pre-supplied so no PDF rendering is required
(``DocumentOCR._get_bbox_from_ocr_word`` uses the cached snapped geometry
directly when present). ``_calculate_pccs`` then distributes one
pseudo-character-center per character across each field's own bbox width --
so for identical gold/prediction boxes, the covered-PCC sets are identical
and the resulting IoU is a genuinely computed 1.0, not the library's
degenerate empty-PCC-set fallback (confirmed present in ``pccs_iou``'s
source, but deliberately not relied on here since it would make the gate
untestable: with zero PCCs of any kind, *any* two intersecting boxes score
IoU 1 regardless of true overlap).

A self-score alone (predictions == gold) is near-tautological: it proves the
adapter's shape round-trips through the library, not that the library can
detect a wrong prediction. Every perfect-score assertion below is therefore
paired with a mutation test that perturbs one field's bbox to a location with
no covered PCCs, proving the corresponding gate can actually fail.
"""

import copy
import dataclasses
import json
from pathlib import Path

from docile.dataset import BBox, CachingConfig, Dataset, Field
from docile.dataset import KILE_FIELDTYPES as CONFIRMED_KILE_FIELDTYPES
from docile.dataset import LIR_FIELDTYPES as CONFIRMED_LIR_FIELDTYPES
from docile.evaluation.evaluate import evaluate_dataset

REPO = Path(__file__).resolve().parents[2]

# A tiny bbox in a page corner. Every real field bbox in this corpus sits well
# inside the printed page body, so this corner carries no OCR-derived PCCs --
# moving a prediction's bbox here makes it fail to match its (unmoved) gold
# annotation, which is exactly what the mutation tests need.
_ESCAPE_BBOX = BBox(0.0, 0.0, 0.005, 0.005)


def _records() -> list[dict]:
    path = REPO / "derived" / "docile.jsonl"
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line]


def _ocr_json_for(entries: list[dict]) -> dict:
    """Build DocILE's on-disk OCR schema from this document's own field text+bbox pairs.

    Each field's text becomes a single "OCR word" positioned exactly at its own
    gold bbox, with ``snapped_geometry`` pre-supplied so ``DocumentOCR`` never
    needs to render the (nonexistent) PDF to perform real text-snapping.
    """
    page_to_words: dict[int, list[dict]] = {}
    for entry in entries:
        left, top, right, bottom = entry["bbox"]
        geometry = [[left, top], [right, bottom]]
        page_to_words.setdefault(entry["page"], []).append(
            {"value": entry["text"], "geometry": geometry, "snapped_geometry": geometry}
        )
    max_page = max(page_to_words) if page_to_words else 0
    pages = []
    for page in range(max_page + 1):
        words = page_to_words.get(page, [])
        blocks = [{"lines": [{"words": words}]}] if words else []
        pages.append({"blocks": blocks})
    return {"pages": pages}


def _build_dataset(records: list[dict], root: Path) -> Dataset:
    """Materialise the on-disk DocILE dataset backing ``records``' gold annotations."""
    (root / "annotations").mkdir(parents=True, exist_ok=True)
    (root / "ocr").mkdir(parents=True, exist_ok=True)
    docids = []
    for record in records:
        docid = record["case_id"]
        docids.append(docid)
        annotation = {
            "metadata": {"page_count": 1, "page_sizes_at_200dpi": [[1000, 1400]]},
            "field_extractions": record["kile"],
            "line_item_extractions": record["lir"],
        }
        (root / "annotations" / f"{docid}.json").write_text(json.dumps(annotation))
        ocr = _ocr_json_for(record["kile"] + record["lir"])
        (root / "ocr" / f"{docid}.json").write_text(json.dumps(ocr))
    return Dataset("test", root, docids=docids, cache_images=CachingConfig.OFF)


def _predictions_from_records(
    records: list[dict],
) -> tuple[dict[str, list[Field]], dict[str, list[Field]]]:
    """Build docid-keyed KILE/LIR prediction Field lists straight from the export.

    Every key in a ``to_docile`` entry dict is a key ``Field.from_dict`` expects,
    so the export's own dicts convert directly -- no reshaping needed.
    """
    kile_predictions = {r["case_id"]: [Field.from_dict(e) for e in r["kile"]] for r in records}
    lir_predictions = {r["case_id"]: [Field.from_dict(e) for e in r["lir"]] for r in records}
    return kile_predictions, lir_predictions


def _build_docile_inputs(
    records: list[dict], dataset_root: Path
) -> tuple[Dataset, dict[str, list[Field]], dict[str, list[Field]]]:
    dataset = _build_dataset(records, dataset_root)
    kile_predictions, lir_predictions = _predictions_from_records(records)
    return dataset, kile_predictions, lir_predictions


def test_export_is_populated() -> None:
    """Structural guard: exactly 55 invoices (spec section 8.3, invoice-only scope
    supersedes any receipt+invoice count named elsewhere), every one carrying
    non-empty kile and lir, before the self-score test spends any time on them.
    """
    records = _records()
    assert len(records) == 55, f"Expected 55 invoices, got {len(records)}"
    assert all(r["kile"] for r in records)
    assert all(r["lir"] for r in records)

    for record in records:
        assert set(record.keys()) == {"case_id", "image_file", "kile", "lir"}
        for entry in record["kile"]:
            assert entry["page"] == 0
            assert len(entry["bbox"]) == 4
            assert all(isinstance(c, float) for c in entry["bbox"])
            assert all(0.0 <= c <= 1.0 for c in entry["bbox"])
            assert entry["fieldtype"] in CONFIRMED_KILE_FIELDTYPES
            assert isinstance(entry["text"], str) and entry["text"]
        for entry in record["lir"]:
            assert entry["page"] == 0
            assert len(entry["bbox"]) == 4
            assert all(0.0 <= c <= 1.0 for c in entry["bbox"])
            assert entry["fieldtype"] in CONFIRMED_LIR_FIELDTYPES
            assert isinstance(entry["text"], str) and entry["text"]
            assert isinstance(entry["line_item_id"], int)


def test_docile_self_score_is_perfect(tmp_path: Path) -> None:
    """Feed the gold annotations back as predictions; AP and f1 must be 1.0.

    What this proves: the export round-trips through the published library --
    bboxes validate as in-range, fieldtypes are accepted KILE/LIR enum members,
    and the Dataset/Field/evaluate_dataset gauntlet accepts our structure. This
    is exactly the conformance spec section 8.3 asks for.

    What this does NOT prove, and must not be trusted to catch: that our bboxes
    land on the real text pixels, or that the source-column -> fieldtype mapping
    is semantically correct. Both the gold annotations and the predictions here
    derive from the same to_docile output, and the synthesized OCR is built from
    those same bboxes, so a *systematic* export bug -- a transposed axis, a
    shifted origin, a swapped fieldtype mapping -- moves gold, OCR, and
    prediction in lockstep and still scores 1.0. Verified by simulation in the
    Task 12 review. Pixel-correctness of a bbox is guaranteed upstream instead,
    by construction in generators/common.py's capture (the recorder stores the
    exact draw coordinates), not by this gate.

    The mutation tests below perturb only the prediction side, proving the
    library discriminates a wrong prediction from a right one -- not that this
    self-score would catch a wrong exporter.
    """
    records = _records()
    dataset, kile_predictions, lir_predictions = _build_docile_inputs(
        records, tmp_path / "docile_dataset"
    )

    result = evaluate_dataset(dataset, kile_predictions, lir_predictions, iou_threshold=1.0)

    assert result.get_primary_metric("kile") == 1.0
    assert result.get_primary_metric("lir") == 1.0


def test_corrupting_one_kile_bbox_degrades_only_the_kile_score(tmp_path: Path) -> None:
    """Moving one KILE prediction's bbox to an empty page corner must turn that
    field into a false negative (its own gold annotation goes unmatched),
    strictly lowering KILE's AP while leaving LIR's f1 untouched at 1.0 --
    proving the KILE gate can actually fail, not just tautologically pass.
    """
    records = _records()
    dataset, kile_predictions, lir_predictions = _build_docile_inputs(
        records, tmp_path / "docile_dataset"
    )

    docid = records[0]["case_id"]
    original = kile_predictions[docid][0]
    kile_predictions[docid] = copy.copy(kile_predictions[docid])
    kile_predictions[docid][0] = dataclasses.replace(original, bbox=_ESCAPE_BBOX)

    result = evaluate_dataset(dataset, kile_predictions, lir_predictions, iou_threshold=1.0)

    assert result.get_primary_metric("kile") < 1.0
    assert result.get_primary_metric("lir") == 1.0


def test_corrupting_one_lir_bbox_degrades_only_the_lir_score(tmp_path: Path) -> None:
    """The same proof for LIR: moving one LIR prediction's bbox away from its
    gold annotation strictly lowers LIR's f1 while KILE's AP stays at 1.0.
    """
    records = _records()
    dataset, kile_predictions, lir_predictions = _build_docile_inputs(
        records, tmp_path / "docile_dataset"
    )

    docid = records[0]["case_id"]
    original = lir_predictions[docid][0]
    lir_predictions[docid] = copy.copy(lir_predictions[docid])
    lir_predictions[docid][0] = dataclasses.replace(original, bbox=_ESCAPE_BBOX)

    result = evaluate_dataset(dataset, kile_predictions, lir_predictions, iou_threshold=1.0)

    assert result.get_primary_metric("kile") == 1.0
    assert result.get_primary_metric("lir") < 1.0


def test_corrupting_one_kile_fieldtype_also_degrades_the_score(tmp_path: Path) -> None:
    """A wrong fieldtype string (rather than a wrong bbox) must also break the
    match: the corrupted prediction is compared against a different gold
    field's candidates and its original gold field goes unmatched, degrading
    precision/recall even though every bbox is untouched.
    """
    records = _records()
    dataset, kile_predictions, lir_predictions = _build_docile_inputs(
        records, tmp_path / "docile_dataset"
    )

    docid = records[0]["case_id"]
    fieldtypes_present = {f.fieldtype for f in kile_predictions[docid]}
    original = kile_predictions[docid][0]
    other_fieldtype = next(ft for ft in fieldtypes_present if ft != original.fieldtype)
    kile_predictions[docid] = copy.copy(kile_predictions[docid])
    kile_predictions[docid][0] = dataclasses.replace(original, fieldtype=other_fieldtype)

    result = evaluate_dataset(dataset, kile_predictions, lir_predictions, iou_threshold=1.0)

    assert result.get_primary_metric("kile") < 1.0
    assert result.get_primary_metric("lir") == 1.0
