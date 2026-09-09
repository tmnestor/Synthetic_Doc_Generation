"""Every CORD-exported document must score 1.0 against itself — and the gate
that says so must be able to fail.

Uses the vendored, apted-backed evaluator at generators/exporters/cord_eval.py
(cal_acc/cal_f1) rather than the unavailable ``donut.util.JSONParseEvaluator``
— see generators/exporters/cord_eval.py's module docstring for provenance.

The self-score below (``test_whole_corpus_self_scores_perfectly``) proves the
evaluator ACCEPTS our schema: it normalises, flattens and tree-edits our trees
without choking. It cannot, however, prove the evaluator would NOTICE a wrong
field mapping — scoring any non-degenerate corpus against itself is
mathematically guaranteed to return 1.0. A gate that cannot fail manufactures
false confidence.

The mutation tests that follow supply the missing half: they take the real
derived corpus, perturb copies of it, and assert the score genuinely degrades
— for a single wrong value, for a dropped menu row, for a dropped top-level
key, monotonically with the amount of wrongness, and (most importantly) for a
unitprice/price field swap, the exact class of mapping bug the self-score is
blind to.

Every mutation operates on a ``copy.deepcopy`` of the pristine trees. If a
mutation leaked into the baseline, these tests would compare wrong against
wrong and pass spuriously, so ``test_mutation_helpers_never_touch_the_pristine_corpus``
asserts the isolation directly.
"""

import copy
import json
from pathlib import Path

from generators.exporters.config import load_export_config
from generators.exporters.cord_eval import cal_acc, cal_f1
from generators.exporters.cord_score import score_cord

REPO = Path(__file__).resolve().parents[1]
CORD_PATH = REPO / "derived" / "cord.jsonl"
EXPORT_CONFIG_PATH = REPO / "config" / "export_config.yml"

EXPECTED_RECEIPT_COUNT = 55
EXPECTED_INVOICE_COUNT = 55
EXPECTED_TOTAL_COUNT = EXPECTED_RECEIPT_COUNT + EXPECTED_INVOICE_COUNT

MUTATED_TOTAL_PRICE = "999999.99"
MONOTONICITY_SMALL_N = 1
MONOTONICITY_LARGE_N = 10


def _load_records() -> list[dict]:
    text = CORD_PATH.read_text().strip()
    assert text, (
        f"{CORD_PATH} is empty — run 'conda run -n synthetic python -m "
        f"generators.pipeline derive' before running this test."
    )
    return [json.loads(line) for line in text.split("\n")]


def _load_trees() -> list[dict]:
    """Return the pristine gt_parse tree of every derived CORD record.

    Returns:
        One gt_parse dict per document, in corpus order.
    """
    return [record["gt_parse"] for record in _load_records()]


def test_corpus_is_populated_and_non_trivial() -> None:
    """Guard for the self-score test below: a perfect score over an empty or
    trivial corpus (zero records, or records with no menu/total/sub_total)
    would be meaningless. This must pass before the self-score assertion is
    trusted.
    """
    records = _load_records()

    assert len(records) == EXPECTED_TOTAL_COUNT, (
        f"Expected exactly {EXPECTED_TOTAL_COUNT} CORD records "
        f"({EXPECTED_RECEIPT_COUNT} receipts + {EXPECTED_INVOICE_COUNT} invoices), "
        f"got {len(records)}."
    )

    # Structural: every record has the three top-level keys derive_cord promises.
    for record in records:
        assert set(record.keys()) == {"case_id", "image_file", "gt_parse"}

    # Non-trivial: every tree carries at least one of the three scored subtrees,
    # and at least one field within it — not just an empty dict.
    trivial = [
        r["case_id"]
        for r in records
        if not any(key in r["gt_parse"] for key in ("menu", "sub_total", "total"))
    ]
    assert not trivial, f"Documents with a completely empty gt_parse tree: {trivial[:10]}"

    non_empty_leaf_counts = [len(_leaf_values(r["gt_parse"])) for r in records]
    assert all(count > 0 for count in non_empty_leaf_counts)
    assert sum(non_empty_leaf_counts) > EXPECTED_TOTAL_COUNT, (
        "Corpus trees carry suspiciously few total leaf values for "
        f"{EXPECTED_TOTAL_COUNT} documents — expected several fields per document."
    )


def _leaf_values(node: object) -> list[object]:
    """Recursively collect every leaf (non-container) value in a gt_parse tree."""
    if isinstance(node, dict):
        values: list[object] = []
        for value in node.values():
            values.extend(_leaf_values(value))
        return values
    if isinstance(node, list):
        values = []
        for item in node:
            values.extend(_leaf_values(item))
        return values
    return [node]


def test_whole_corpus_self_scores_perfectly() -> None:
    records = _load_records()
    trees = [r["gt_parse"] for r in records]

    f1 = cal_f1(trees, trees)
    assert f1 == 1.0, f"Corpus CORD self-score (F1) was {f1}, expected 1.0"

    # cal_acc's per-document nTED accuracy: every document scored against
    # itself must also be a perfect 1.0 (content assertion, individually,
    # not just in the micro-averaged F1 aggregate above).
    accuracies = [cal_acc(tree, tree) for tree in trees]
    assert all(acc == 1.0 for acc in accuracies), (
        f"Not every document self-scored 1.0 on cal_acc: "
        f"{[(r['case_id'], acc) for r, acc in zip(records, accuracies) if acc != 1.0][:10]}"
    )


def test_whole_corpus_self_scores_perfectly_via_score_cord() -> None:
    """The production path: score through score_cord with the REAL export
    config, not cal_f1 called directly. config/export_config.yml's
    cord_extension_scoring is 'excluded_scored_separately', so this must
    report a perfect headline_f1 (extension excluded) AND a perfect
    extension_f1 (scored separately) — proving cord_extension_scoring is
    actually consumed by production code, not merely validated.
    """
    export_config = load_export_config(EXPORT_CONFIG_PATH)
    assert export_config["cord_extension_scoring"] == "excluded_scored_separately"

    trees = _load_trees()
    result = score_cord(trees, trees, export_config)

    assert result["mode"] == "excluded_scored_separately"
    assert result["headline_f1"] == 1.0, f"Headline self-score was {result['headline_f1']}, expected 1.0"
    assert result["extension_f1"] == 1.0, f"Extension self-score was {result['extension_f1']}, expected 1.0"


def test_every_record_has_a_populated_tree() -> None:
    records = _load_records()
    empty = [r["case_id"] for r in records if not r["gt_parse"].get("menu")]
    assert not empty, f"Documents exported with no menu: {empty[:10]}"


# ---------------------------------------------------------------------------
# Mutation tests: prove the gate above can actually fail.
# ---------------------------------------------------------------------------


def _indices_with_total(trees: list[dict]) -> list[int]:
    """Return the indices of documents carrying a total.total_price leaf.

    Args:
        trees: The pristine corpus trees.

    Returns:
        Corpus indices whose tree has a non-empty ``total.total_price``.
    """
    return [i for i, tree in enumerate(trees) if tree.get("total", {}).get("total_price")]


def _indices_with_multiple_menu_items(trees: list[dict]) -> list[int]:
    """Return the indices of documents with at least two menu rows.

    Dropping a row from a single-row menu would delete the whole ``menu``
    subtree, which is a different (coarser) mutation than the one under test.

    Args:
        trees: The pristine corpus trees.

    Returns:
        Corpus indices whose ``menu`` list holds two or more items.
    """
    return [i for i, tree in enumerate(trees) if len(tree.get("menu", [])) >= 2]


def _swappable_rows(trees: list[dict]) -> dict[int, list[int]]:
    """Map each document index to the menu rows where unitprice != price.

    Most rows have quantity 1, so the unit price equals the line total and
    swapping the two fields is invisible to any value-based metric. Only rows
    where the two values genuinely differ (quantity > 1) can demonstrate that
    the evaluator would catch a unitprice/price mapping bug.

    Args:
        trees: The pristine corpus trees.

    Returns:
        ``{document_index: [row_index, ...]}`` for every document with at
        least one such row. Documents with none are omitted entirely.
    """
    swappable: dict[int, list[int]] = {}
    for i, tree in enumerate(trees):
        rows = [
            j
            for j, item in enumerate(tree.get("menu", []))
            if item.get("unitprice") and item.get("price") and item["unitprice"] != item["price"]
        ]
        if rows:
            swappable[i] = rows
    return swappable


def _mutate_total_price(trees: list[dict], indices: list[int]) -> list[dict]:
    """Return a deep copy of `trees` with total.total_price corrupted at `indices`.

    Args:
        trees: The pristine corpus trees (never modified).
        indices: Corpus indices whose total price should be replaced with a
            value that appears nowhere in the pristine corpus.

    Returns:
        The mutated copy.
    """
    mutated = copy.deepcopy(trees)
    for index in indices:
        mutated[index]["total"]["total_price"] = MUTATED_TOTAL_PRICE
    return mutated


def _swap_unitprice_and_price(trees: list[dict], selection: dict[int, list[int]]) -> list[dict]:
    """Return a deep copy of `trees` with unitprice and price swapped per `selection`.

    Args:
        trees: The pristine corpus trees (never modified).
        selection: ``{document_index: [row_index, ...]}`` naming the menu rows
            to swap — as produced by :func:`_swappable_rows`.

    Returns:
        The mutated copy.
    """
    mutated = copy.deepcopy(trees)
    for doc_index, row_indices in selection.items():
        for row_index in row_indices:
            item = mutated[doc_index]["menu"][row_index]
            item["unitprice"], item["price"] = item["price"], item["unitprice"]
    return mutated


def test_mutation_helpers_never_touch_the_pristine_corpus() -> None:
    """Every mutation below must operate on a deepcopy.

    If a mutation leaked into the baseline list, the mutated corpus would be
    compared against an equally-mutated reference and every assertion below
    would pass for the wrong reason. This asserts the isolation explicitly
    rather than trusting it.
    """
    trees = _load_trees()
    snapshot = copy.deepcopy(trees)

    with_total = _indices_with_total(trees)
    swappable = _swappable_rows(trees)
    _mutate_total_price(trees, with_total[:MONOTONICITY_LARGE_N])
    _swap_unitprice_and_price(trees, swappable)

    assert trees == snapshot, "A mutation helper modified the pristine corpus in place."
    assert cal_f1(trees, snapshot) == 1.0


def test_single_value_mutation_degrades_the_score() -> None:
    """Mutation 1: corrupting ONE leaf value in ONE document must score
    strictly below a perfect 1.0, and — because 109 of 110 documents and all
    but one field of the 110th are still correct — well above 0.
    """
    trees = _load_trees()
    with_total = _indices_with_total(trees)
    assert with_total, "No document carries total.total_price; cannot mutate a leaf value."

    target = with_total[0]
    mutated = _mutate_total_price(trees, [target])
    assert mutated[target] != trees[target], "The mutation was a no-op."

    f1 = cal_f1(mutated, trees)
    assert 0.0 < f1 < 1.0, f"Single-value mutation scored {f1}; expected strictly inside (0, 1)."
    # A single wrong field out of thousands must still leave the corpus mostly
    # right — a collapse towards 0 would mean the metric is not field-level.
    assert f1 > 0.9, f"Single-value mutation collapsed the corpus F1 to {f1}; expected > 0.9."

    # The affected document's own nTED accuracy must also drop below 1.0,
    # while every other document is untouched.
    assert cal_acc(mutated[target], trees[target]) < 1.0
    assert all(cal_acc(mutated[i], trees[i]) == 1.0 for i in range(len(trees)) if i != target), (
        "A single-document mutation perturbed some other document's score."
    )


def test_dropping_one_menu_item_degrades_the_score() -> None:
    """Mutation 2: deleting one menu row from one document (structural, not
    just a wrong value) must score strictly below 1.0.
    """
    trees = _load_trees()
    multi = _indices_with_multiple_menu_items(trees)
    assert multi, "No document has two or more menu rows; cannot drop one row."

    target = multi[0]
    mutated = copy.deepcopy(trees)
    dropped = mutated[target]["menu"].pop(0)

    assert len(mutated[target]["menu"]) == len(trees[target]["menu"]) - 1
    assert len(trees[target]["menu"]) > len(mutated[target]["menu"]), "Pristine corpus was mutated."

    f1 = cal_f1(mutated, trees)
    assert 0.0 < f1 < 1.0, (
        f"Dropping menu row {dropped!r} from document {target} scored {f1}; "
        f"expected strictly inside (0, 1)."
    )
    assert cal_acc(mutated[target], trees[target]) < 1.0


def test_dropping_a_top_level_key_degrades_the_score() -> None:
    """Mutation 3: deleting an entire top-level subtree ("total") from one
    document must score strictly below 1.0.
    """
    trees = _load_trees()
    with_total = _indices_with_total(trees)
    assert with_total, "No document carries a 'total' subtree; cannot drop it."

    target = with_total[0]
    mutated = copy.deepcopy(trees)
    del mutated[target]["total"]

    assert "total" not in mutated[target]
    assert "total" in trees[target], "Pristine corpus was mutated."

    f1 = cal_f1(mutated, trees)
    assert 0.0 < f1 < 1.0, f"Dropping the 'total' subtree scored {f1}; expected strictly inside (0, 1)."
    assert cal_acc(mutated[target], trees[target]) < 1.0


def test_score_degrades_monotonically_with_the_number_of_wrong_documents() -> None:
    """Mutation 4: the gate must be sensitive to HOW MUCH is wrong, not merely
    that something is.

    Corrupting the same field in ten documents must score strictly lower than
    corrupting it in one. A metric that merely flagged "some mismatch" would
    return the same number for both.
    """
    trees = _load_trees()
    with_total = _indices_with_total(trees)
    assert len(with_total) >= MONOTONICITY_LARGE_N, (
        f"Need at least {MONOTONICITY_LARGE_N} documents with a total price to test "
        f"monotonicity; found {len(with_total)}."
    )

    one_wrong = cal_f1(_mutate_total_price(trees, with_total[:MONOTONICITY_SMALL_N]), trees)
    ten_wrong = cal_f1(_mutate_total_price(trees, with_total[:MONOTONICITY_LARGE_N]), trees)

    assert ten_wrong < one_wrong < 1.0, (
        f"Expected 10 wrong documents ({ten_wrong}) to score strictly below "
        f"1 wrong document ({one_wrong}), which must itself be below 1.0."
    )
    assert ten_wrong > 0.0


def test_swapping_unitprice_and_price_degrades_the_score() -> None:
    """Mutation 5: a unitprice/price field swap — the exact mapping bug the
    self-score cannot catch — must score strictly below 1.0.

    Only rows where the two values genuinely differ (quantity > 1) are
    swapped: with quantity 1 the unit price equals the line total, so the swap
    is a no-op that no value-based metric could see. This test asserts such
    rows exist in the corpus AND that swapping them is detected.

    NOTE ON WHAT THIS DOES AND DOES NOT PROVE. This proves the METRIC is
    sensitive to a unitprice/price swap. It does not, and cannot, detect a
    real swap inside generators/exporters/cord.py, because both sides of a
    self-score come from that same code path — a swapped to_cord would emit a
    consistently swapped corpus that still self-scores 1.0, and this test
    would still pass. Catching a real swap needs an INDEPENDENT oracle that
    pins the emitted menu row against the source LINE_ITEM_PRICES /
    LINE_ITEM_TOTAL_PRICES columns using values that actually differ; that
    oracle is test_derive_cord_maps_unit_price_and_total_price_distinctly in
    tests/test_derive_cord.py. The two tests are complements, not substitutes.
    """
    trees = _load_trees()
    swappable = _swappable_rows(trees)
    assert swappable, (
        "No menu row in the corpus has unitprice != price, so a unitprice/price "
        "swap would be undetectable by construction. Regenerate the corpus with "
        "at least one line item of quantity > 1."
    )

    # 5a: swap within a single document.
    single_doc = min(swappable)
    single = _swap_unitprice_and_price(trees, {single_doc: swappable[single_doc]})
    single_f1 = cal_f1(single, trees)
    assert 0.0 < single_f1 < 1.0, (
        f"Swapping unitprice/price in document {single_doc} scored {single_f1}; "
        f"expected strictly inside (0, 1)."
    )
    assert cal_acc(single[single_doc], trees[single_doc]) < 1.0

    # 5b: swap across the whole corpus — strictly worse again (monotonicity of
    # the same mutation class), and far enough below 1.0 to be unmissable.
    corpus_wide = _swap_unitprice_and_price(trees, swappable)
    corpus_f1 = cal_f1(corpus_wide, trees)
    assert 0.0 < corpus_f1 < single_f1, (
        f"Corpus-wide unitprice/price swap scored {corpus_f1}, not strictly below the "
        f"single-document swap ({single_f1})."
    )
    assert corpus_f1 < 0.95, (
        f"A corpus-wide unitprice/price swap only moved F1 to {corpus_f1}; a mapping "
        f"bug of that scale must be conspicuous, not marginal."
    )

    # And the pristine corpus is still pristine.
    assert cal_f1(trees, _load_trees()) == 1.0


# ---------------------------------------------------------------------------
# Mutation tests for score_cord / cord_extension_scoring: prove the config
# key genuinely changes behaviour, not just that score_cord round-trips.
# ---------------------------------------------------------------------------


def _indices_with_extension(trees: list[dict]) -> list[int]:
    """Return the indices of documents carrying a non-empty extension subtree.

    Args:
        trees: The pristine corpus trees.

    Returns:
        Corpus indices whose tree has a non-empty 'extension' dict.
    """
    return [i for i, tree in enumerate(trees) if tree.get("extension")]


def _mutate_extension_only(trees: list[dict], indices: list[int]) -> list[dict]:
    """Return a deep copy of `trees` with ONLY the extension subtree corrupted.

    Every non-extension key (menu, sub_total, total) is left byte-identical,
    so any headline-score movement can only be attributed to the extension
    change.

    Args:
        trees: The pristine corpus trees (never modified).
        indices: Corpus indices whose extension subtree should be corrupted.

    Returns:
        The mutated copy.
    """
    mutated = copy.deepcopy(trees)
    for index in indices:
        for key, value in mutated[index]["extension"].items():
            mutated[index]["extension"][key] = f"WRONG_{value}"
    return mutated


def test_extension_only_corruption_leaves_headline_perfect_but_drops_extension_score() -> None:
    """This is the whole point of cord_extension_scoring=excluded_scored_separately:
    corrupting ONLY the extension subtree (supplier/ABN/address/date/payer)
    across the whole corpus must leave headline_f1 at a perfect 1.0 — because
    the headline is computed over the tree with 'extension' removed — while
    extension_f1 drops strictly below 1.0, proving the corruption was not
    simply invisible to the evaluator.

    Without this test, cord_extension_scoring could be silently ignored (the
    whole tree scored every time) and every other test in this file would
    still pass.
    """
    export_config = load_export_config(EXPORT_CONFIG_PATH)
    trees = _load_trees()
    with_extension = _indices_with_extension(trees)
    assert with_extension, "No document carries an extension subtree; cannot corrupt it."

    mutated = _mutate_extension_only(trees, with_extension)
    assert mutated != trees, "The extension-only mutation was a no-op."
    # Confirm the mutation truly touched nothing outside 'extension'.
    for index in with_extension:
        pristine_no_ext = {k: v for k, v in trees[index].items() if k != "extension"}
        mutated_no_ext = {k: v for k, v in mutated[index].items() if k != "extension"}
        assert pristine_no_ext == mutated_no_ext, (
            f"Document {index}: the 'extension-only' mutation touched a non-extension key."
        )

    result = score_cord(mutated, trees, export_config)

    assert result["headline_f1"] == 1.0, (
        f"Extension-only corruption leaked into headline_f1 ({result['headline_f1']}); "
        f"cord_extension_scoring is not actually excluding 'extension' from the headline."
    )
    assert result["extension_f1"] < 1.0, (
        "Extension-only corruption was not detected at all — extension_f1 stayed 1.0."
    )


def test_non_extension_corruption_still_drops_the_headline_score() -> None:
    """The inverse of the test above: corrupting a NON-extension value (a
    total_price) must still drag headline_f1 down. Exclusion applies only to
    'extension', not to sensitivity in general.
    """
    export_config = load_export_config(EXPORT_CONFIG_PATH)
    trees = _load_trees()
    with_total = _indices_with_total(trees)
    assert with_total, "No document carries total.total_price; cannot mutate a leaf value."

    mutated = _mutate_total_price(trees, with_total)
    result = score_cord(mutated, trees, export_config)

    assert result["headline_f1"] < 1.0, (
        "Corrupting total_price (a non-extension field) did not move headline_f1 at all."
    )
    assert result["extension_f1"] == 1.0, (
        "Corrupting total_price leaked into extension_f1, which should be untouched."
    )
