"""Tests for the vendored, apted-backed CORD evaluator (generators.exporters.cord_eval).

This is the real deliverable of Task 6: a vendored tree-edit-distance metric that
silently always returned 1.0 would make every later self-scoring gate worthless, so
these tests exist to prove the metric actually discriminates between correct and
incorrect predictions, not just that it round-trips identity.
"""

import copy
from pathlib import Path

import pytest

from generators.exporters.cord import to_cord
from generators.exporters.cord_eval import cal_acc, cal_f1
from generators.loader import load_ground_truth

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def case001_tree() -> dict:
    """The real CASE001 CORD gt_parse tree, built via the actual export pipeline."""
    ground_truth = load_ground_truth(REPO / "ground_truth" / "receipts.yml")
    fields = ground_truth["CASE001"]["fields"]
    return to_cord(fields, "spaced")


# --- IDENTITY -----------------------------------------------------------------


def test_case001_cord_self_score_is_perfect(case001_tree: dict) -> None:
    """A perfect prediction must score exactly 1.0 against itself."""
    accuracy = cal_acc(case001_tree, case001_tree)
    assert accuracy == 1.0, (
        f"CASE001 CORD export scored {accuracy} against itself. "
        f"The exporter and the evaluator disagree about the schema."
    )


# --- NON-EMPTY GUARD ------------------------------------------------------------


def test_case001_tree_is_not_empty(case001_tree: dict) -> None:
    """Guard against a no-op mapper: the CASE001 tree must actually be populated.

    cal_acc(x, x) == 1.0 is trivially true for x == {} too, so the identity test
    above would pass even if to_cord emitted nothing. This checks real content.
    """
    from pathlib import Path

    import yaml

    # Read the expected values from ground truth rather than pinning them here:
    # a corpus reseed legitimately changes every value, and a hardcoded literal
    # turns that into a test failure that says nothing about the mapper.
    gt = yaml.safe_load(Path("ground_truth/receipts.yml").read_text())["CASE001"]["fields"]

    assert case001_tree["menu"]
    assert case001_tree["total"]["total_price"] == gt["TOTAL_AMOUNT"]
    assert case001_tree["extension"]["supplier_name"] == gt["SUPPLIER_NAME"]


def test_cal_acc_on_two_empty_dicts_fails_fast_instead_of_lying() -> None:
    """cal_acc({}, {}) must not silently report a perfect score.

    The upstream Donut evaluator actually raises a bare, undiagnosed
    ZeroDivisionError for this input (confirmed directly against unmodified
    upstream code during this port) rather than returning 1.0. This vendored
    version raises a diagnostic ValueError instead: a degenerate empty-vs-empty
    comparison carries no information and must never be read as "perfect".
    """
    with pytest.raises(ValueError, match="degenerate"):
        cal_acc({}, {})


# --- DISCRIMINATION (essential) --------------------------------------------------


def test_one_field_wrong_scores_strictly_between_zero_and_one(case001_tree: dict) -> None:
    one_wrong = copy.deepcopy(case001_tree)
    one_wrong["total"]["total_price"] = "999.99"

    score = cal_acc(case001_tree, one_wrong)

    assert 0.0 < score < 1.0, f"Expected a discriminating score in (0, 1), got {score}"


def test_everything_different_scores_near_zero(case001_tree: dict) -> None:
    all_wrong = {
        "menu": [{"nm": "zzz", "cnt": "9", "unitprice": "0.00", "price": "0.00"}],
        "sub_total": {"tax_price": "0.00"},
        "total": {"total_price": "0.00"},
        "extension": {"supplier_name": "zzz", "business_abn": "00 000 000 000"},
    }

    score = cal_acc(case001_tree, all_wrong)

    assert score < 0.1, f"Expected a near-zero score for a fully wrong prediction, got {score}"


# --- MONOTONICITY -----------------------------------------------------------------


def test_two_fields_wrong_does_not_score_higher_than_one_field_wrong(case001_tree: dict) -> None:
    one_wrong = copy.deepcopy(case001_tree)
    one_wrong["total"]["total_price"] = "999.99"

    two_wrong = copy.deepcopy(one_wrong)
    two_wrong["extension"]["supplier_name"] = "Completely Different Pty Ltd"

    score_one_wrong = cal_acc(case001_tree, one_wrong)
    score_two_wrong = cal_acc(case001_tree, two_wrong)

    assert score_two_wrong <= score_one_wrong, (
        f"Two wrong fields ({score_two_wrong}) scored higher than one wrong field "
        f"({score_one_wrong}); the metric is not monotonic in error count."
    )
    assert score_two_wrong < score_one_wrong, "Expected a strictly worse score, not a tie."


# --- cal_f1 -------------------------------------------------------------------------


def test_cal_f1_perfect_predictions_score_one(case001_tree: dict) -> None:
    assert cal_f1([case001_tree, case001_tree], [case001_tree, case001_tree]) == 1.0


def test_cal_f1_one_wrong_document_scores_strictly_less_than_one(case001_tree: dict) -> None:
    one_wrong = copy.deepcopy(case001_tree)
    one_wrong["total"]["total_price"] = "999.99"

    score = cal_f1([case001_tree, one_wrong], [case001_tree, case001_tree])

    assert score < 1.0


def test_cal_f1_rejects_mismatched_list_lengths(case001_tree: dict) -> None:
    """Silent zip()-truncation on length mismatch is exactly the kind of silent
    failure this project's fail-fast convention forbids; must raise instead."""
    with pytest.raises(ValueError, match="mismatched lengths"):
        cal_f1([case001_tree, case001_tree], [case001_tree])


# --- Structural differences ------------------------------------------------------


def test_missing_menu_item_reduces_score(case001_tree: dict) -> None:
    missing_item = copy.deepcopy(case001_tree)
    missing_item["menu"].pop()

    score = cal_acc(case001_tree, missing_item)

    assert 0.0 <= score < 1.0


def test_extra_menu_item_reduces_score(case001_tree: dict) -> None:
    extra_item = copy.deepcopy(case001_tree)
    extra_item["menu"].append(
        {"nm": "Extra Thing", "cnt": "1", "unitprice": "5.00", "price": "5.00"}
    )

    score = cal_acc(case001_tree, extra_item)

    assert 0.0 <= score < 1.0
