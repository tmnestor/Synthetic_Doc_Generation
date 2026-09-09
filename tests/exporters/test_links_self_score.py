"""The doc_refs export, scored against its own ground truth, must be perfect.

``linking.link_validator.validate_links`` already computes precision/recall/F1
overall and per difficulty (spec section 8.6, the ``LinkScore``/``DifficultyScore``
dataclasses) -- this file proves the Task 8 doc_refs export round-trips through
that *existing* validator rather than standing up a second scorer.

Step 1 of this task's brief was to inspect the real interface rather than trust
a guessed one. The actual signature (confirmed via
``inspect.signature(link_validator.validate_links)``) is::

    validate_links(ground_truth: dict, predictions: dict[str, dict]) -> LinkScore

which differs from the brief's guessed shape (a flat list of prediction dicts)
in two ways:

- ``ground_truth`` is keyed by receipt filename (``source_doc`` in doc_refs
  terms); each value is a *list* of link records (only index ``[0]`` is read
  by the validator), each with ``bank_statement``, ``bank_amount`` and
  ``match_difficulty`` keys.
- ``predictions`` is keyed the same way, but each value is a single dict
  ``{"bank_statement": ..., "bank_amount": ...}`` -- no list wrapper.

``_ground_truth_and_predictions`` below reshapes the exported doc_refs
records (which carry ``target_doc``, ``match_keys.amount`` and
``difficulty``) into that exact shape.

A self-score alone (``score(x, x) == 1.0``) is near-tautological: it proves
the scorer ingests our shape but not that it can catch a wrong mapping. Every
perfect-score assertion below is therefore paired with a mutation test that
proves the corresponding gate can actually fail.
"""

import copy
import json
import math
from pathlib import Path

from linking.link_validator import validate_links

REPO = Path(__file__).resolve().parents[2]


def _exported_transaction_links() -> list[dict]:
    """Load the receipt_to_bank records from the real derived export."""
    lines = (REPO / "derived" / "doc_refs.jsonl").read_text().strip().split("\n")
    records = [json.loads(line) for line in lines]
    return [r for r in records if r["link_type"] == "receipt_to_bank"]


def _ground_truth_and_predictions(records: list[dict]) -> tuple[dict, dict[str, dict]]:
    """Reshape doc_refs records into validate_links's actual (gt, predictions) shape.

    Args:
        records: receipt_to_bank doc_refs records, each with ``source_doc``,
            ``target_doc``, ``match_keys`` (containing ``amount``) and
            ``difficulty``.

    Returns:
        A ``(ground_truth, predictions)`` pair shaped exactly as
        ``validate_links`` expects.
    """
    ground_truth = {
        r["source_doc"]: [
            {
                "bank_statement": r["target_doc"],
                "bank_amount": r["match_keys"]["amount"],
                "match_difficulty": r["difficulty"],
            }
        ]
        for r in records
    }
    predictions = {
        r["source_doc"]: {
            "bank_statement": r["target_doc"],
            "bank_amount": r["match_keys"]["amount"],
        }
        for r in records
    }
    return ground_truth, predictions


def test_every_difficulty_band_is_populated() -> None:
    """A band with no links would self-score perfectly while testing nothing."""
    exported = _exported_transaction_links()
    counts = {d: sum(1 for r in exported if r["difficulty"] == d) for d in ("easy", "medium", "hard")}
    assert counts == {"easy": 52, "medium": 36, "hard": 22}, counts
    assert all(count > 0 for count in counts.values()), counts


def test_transaction_links_self_score_is_perfect() -> None:
    """Feeding the export back to itself as predictions must score a perfect 1.0
    overall and in every per-difficulty band.
    """
    exported = _exported_transaction_links()
    assert len(exported) == 110, f"Expected 110 links, found {len(exported)}"

    ground_truth, predictions = _ground_truth_and_predictions(exported)
    score = validate_links(ground_truth, predictions)

    assert score.true_positives == 110
    assert score.false_positives == 0
    assert score.false_negatives == 0
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.f1 == 1.0

    assert set(score.by_difficulty) == {"easy", "medium", "hard"}
    for difficulty, expected_count in (("easy", 52), ("medium", 36), ("hard", 22)):
        band = score.by_difficulty[difficulty]
        assert band.true_positives == expected_count
        assert band.false_positives == 0
        assert band.false_negatives == 0
        assert band.precision == 1.0
        assert band.recall == 1.0
        assert band.f1 == 1.0


def test_dropping_one_link_degrades_recall_only() -> None:
    """Removing one prediction must strictly lower recall (a real link is no
    longer predicted) while leaving precision at 1.0 (no spurious link was
    added) -- proving the perfect-score gate can actually fail on a missing
    link, not just pass on a tautological self-comparison.
    """
    exported = _exported_transaction_links()
    ground_truth, predictions = _ground_truth_and_predictions(exported)
    predictions = copy.deepcopy(predictions)  # never mutate the pristine baseline

    dropped_receipt = exported[0]["source_doc"]
    del predictions[dropped_receipt]

    score = validate_links(ground_truth, predictions)

    assert score.true_positives == 109
    assert score.false_negatives == 1
    assert score.false_positives == 0
    assert score.precision == 1.0
    assert score.recall == 109 / 110
    assert score.recall < 1.0
    # f1 is computed by LinkScore as 2*p*r/(p+r), a chained float computation
    # that differs from the direct fraction literal at the last ULP -- use
    # math.isclose for the value, plus an exact strict-inequality bound.
    assert math.isclose(score.f1, 218 / 219, rel_tol=1e-12)
    assert score.f1 < 1.0


def test_adding_a_spurious_link_degrades_precision_only() -> None:
    """Adding one prediction absent from ground truth must strictly lower
    precision while recall (every real link is still predicted) stays 1.0.
    """
    exported = _exported_transaction_links()
    ground_truth, predictions = _ground_truth_and_predictions(exported)
    predictions = copy.deepcopy(predictions)  # never mutate the pristine baseline

    predictions["ZZZ_not_a_real_receipt.png"] = {
        "bank_statement": "ZZZ_not_a_real_bank_statement.png",
        "bank_amount": "999.99",
    }

    score = validate_links(ground_truth, predictions)

    assert score.true_positives == 110
    assert score.false_positives == 1
    assert score.false_negatives == 0
    assert score.recall == 1.0
    assert score.precision == 110 / 111
    assert score.precision < 1.0
    assert math.isclose(score.f1, 220 / 221, rel_tol=1e-12)
    assert score.f1 < 1.0


def test_corrupting_a_target_doc_degrades_the_score() -> None:
    """Changing one prediction's bank_statement to a wrong value (rather than
    deleting the prediction outright) must turn that true positive into a
    false negative, proving the equality check on bank_statement is actually
    exercised rather than the validator merely checking key presence.
    """
    exported = _exported_transaction_links()
    ground_truth, predictions = _ground_truth_and_predictions(exported)
    predictions = copy.deepcopy(predictions)  # never mutate the pristine baseline

    corrupted_receipt = exported[0]["source_doc"]
    real_target = predictions[corrupted_receipt]["bank_statement"]
    wrong_target = "WRONG_bank_statement_not_in_corpus.png"
    assert wrong_target != real_target
    predictions[corrupted_receipt]["bank_statement"] = wrong_target

    score = validate_links(ground_truth, predictions)

    assert score.true_positives == 109
    assert score.false_negatives == 1
    assert score.false_positives == 0
    assert score.precision == 1.0
    assert score.recall == 109 / 110
    assert score.recall < 1.0
    assert math.isclose(score.f1, 218 / 219, rel_tol=1e-12)
    assert score.f1 < 1.0


def test_removing_only_hard_links_degrades_the_hard_band_alone() -> None:
    """Dropping a single hard-difficulty prediction must degrade only the
    hard per-difficulty band -- proving by_difficulty is wired through to
    real per-link difficulty data rather than merely reported alongside the
    overall score.
    """
    exported = _exported_transaction_links()
    ground_truth, predictions = _ground_truth_and_predictions(exported)
    predictions = copy.deepcopy(predictions)  # never mutate the pristine baseline

    hard_receipt = next(r["source_doc"] for r in exported if r["difficulty"] == "hard")
    del predictions[hard_receipt]

    score = validate_links(ground_truth, predictions)

    hard = score.by_difficulty["hard"]
    easy = score.by_difficulty["easy"]
    medium = score.by_difficulty["medium"]

    assert hard.true_positives == 21
    assert hard.false_negatives == 1
    assert hard.false_positives == 0
    assert hard.precision == 1.0
    assert hard.recall == 21 / 22
    assert hard.recall < 1.0
    assert math.isclose(hard.f1, 42 / 43, rel_tol=1e-12)
    assert hard.f1 < 1.0

    assert easy.true_positives == 52
    assert easy.false_negatives == 0
    assert easy.precision == 1.0
    assert easy.recall == 1.0
    assert easy.f1 == 1.0

    assert medium.true_positives == 36
    assert medium.false_negatives == 0
    assert medium.precision == 1.0
    assert medium.recall == 1.0
    assert medium.f1 == 1.0

    # Overall score also degrades by exactly the one dropped hard link.
    assert score.true_positives == 109
    assert score.false_negatives == 1
    assert score.recall == 109 / 110
    assert score.recall < 1.0
