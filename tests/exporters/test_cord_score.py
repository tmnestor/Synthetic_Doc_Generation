"""Tests for score_cord (generators.exporters.cord_score).

Wires the previously-unconsumed ``cord_extension_scoring`` config key into
real behaviour: the headline CORD F1 must stay comparable to public CORD
leaderboards (no ``extension`` slot exists there), while the extension
subtree (supplier/ABN/address/date/payer) is either folded back in, scored
separately, or dropped, per the configured mode.
"""

import copy
from typing import Any

import pytest

from conftest import assert_diagnostic_error
from generators.exporters.cord_score import score_cord

TREE_A: dict[str, Any] = {
    "menu": [{"nm": "Widget", "cnt": "1", "unitprice": "4.73", "price": "4.73"}],
    "total": {"total_price": "4.73"},
    "extension": {"supplier_name": "Ravensdale Health Store", "business_abn": "79104332181"},
}

TREE_B: dict[str, Any] = {
    "menu": [{"nm": "Gadget", "cnt": "1", "unitprice": "8.87", "price": "8.87"}],
    "total": {"total_price": "8.87"},
    "extension": {"supplier_name": "Example Wholesale Co", "business_abn": "00000000000"},
}


def _config(mode: str) -> dict:
    return {"cord_extension_scoring": mode}


def test_in_tree_mode_scores_the_full_tree_and_reports_no_extension_figure() -> None:
    result = score_cord([TREE_A, TREE_B], [TREE_A, TREE_B], _config("in_tree"))
    assert result["headline_f1"] == 1.0
    assert result["extension_f1"] is None
    assert result["mode"] == "in_tree"


def test_in_tree_mode_is_sensitive_to_an_extension_only_corruption() -> None:
    """Unlike the excluded modes, in_tree must still be dragged down by an
    extension-only mutation, proving the mode genuinely changes behaviour
    rather than the extension key being ignored everywhere.
    """
    mutated = copy.deepcopy([TREE_A, TREE_B])
    mutated[0]["extension"]["supplier_name"] = "Totally Wrong Pty Ltd"

    result = score_cord(mutated, [TREE_A, TREE_B], _config("in_tree"))
    assert result["headline_f1"] < 1.0


def test_excluded_unscored_mode_drops_extension_from_headline_and_reports_none() -> None:
    result = score_cord([TREE_A, TREE_B], [TREE_A, TREE_B], _config("excluded_unscored"))
    assert result["headline_f1"] == 1.0
    assert result["extension_f1"] is None
    assert result["mode"] == "excluded_unscored"


def test_excluded_unscored_mode_ignores_an_extension_only_corruption() -> None:
    mutated = copy.deepcopy([TREE_A, TREE_B])
    mutated[0]["extension"]["supplier_name"] = "Totally Wrong Pty Ltd"

    result = score_cord(mutated, [TREE_A, TREE_B], _config("excluded_unscored"))
    assert result["headline_f1"] == 1.0
    assert result["extension_f1"] is None


def test_excluded_scored_separately_mode_reports_both_figures_perfectly() -> None:
    result = score_cord([TREE_A, TREE_B], [TREE_A, TREE_B], _config("excluded_scored_separately"))
    assert result["headline_f1"] == 1.0
    assert result["extension_f1"] == 1.0
    assert result["mode"] == "excluded_scored_separately"


def test_excluded_scored_separately_mode_isolates_an_extension_only_corruption() -> None:
    """The whole point of the exclusion: corrupting ONLY the extension subtree
    must leave headline_f1 untouched while extension_f1 drops.
    """
    mutated = copy.deepcopy([TREE_A, TREE_B])
    mutated[0]["extension"]["supplier_name"] = "Totally Wrong Pty Ltd"
    mutated[1]["extension"]["business_abn"] = "99999999999"

    result = score_cord(mutated, [TREE_A, TREE_B], _config("excluded_scored_separately"))

    assert result["headline_f1"] == 1.0, "Extension corruption leaked into the headline score."
    assert result["extension_f1"] < 1.0, "Extension corruption was not detected at all."


def test_excluded_scored_separately_mode_still_catches_a_non_extension_corruption() -> None:
    """The inverse check: corrupting a non-extension field (total_price) must
    still drag the headline score down — exclusion only removes `extension`,
    not sensitivity in general.
    """
    mutated = copy.deepcopy([TREE_A, TREE_B])
    mutated[0]["total"]["total_price"] = "999999.99"

    result = score_cord(mutated, [TREE_A, TREE_B], _config("excluded_scored_separately"))

    assert result["headline_f1"] < 1.0
    assert result["extension_f1"] == 1.0, "Non-extension corruption leaked into the extension score."


def test_inputs_are_never_mutated() -> None:
    pristine_a = copy.deepcopy(TREE_A)
    pristine_b = copy.deepcopy(TREE_B)

    score_cord([TREE_A, TREE_B], [TREE_A, TREE_B], _config("excluded_scored_separately"))

    assert TREE_A == pristine_a, "score_cord mutated a pred/gold input in place."
    assert TREE_B == pristine_b, "score_cord mutated a pred/gold input in place."


def test_unknown_mode_raises_a_diagnostic_error() -> None:
    with pytest.raises(ValueError) as exc:
        score_cord([TREE_A], [TREE_A], _config("hyphenated"))
    assert_diagnostic_error(exc.value)
    assert "hyphenated" in str(exc.value)
    assert "in_tree" in str(exc.value)
    assert "excluded_scored_separately" in str(exc.value)
    assert "excluded_unscored" in str(exc.value)
