"""Baseline gate for the surviving corpus's derived outputs (Stage 4 Task 1
of the layout-DSL narrowing plan, docs/layout_dsl_stage4_plan.md).

`tests/test_bank_pixel_snapshot.py`, `test_receipt_pixel_snapshot.py` and
`test_invoice_pixel_snapshot.py` pin what the three surviving document types
(bank statements, receipts, invoices) render as pixels. Nothing pins what
`python -m generators.pipeline derive` produces from the same ground truth —
`ground_truth.csv`, `ground_truth.jsonl`, `cord.jsonl`, `docile.jsonl`,
`native.jsonl`, `doc_refs.jsonl`. The schema trim due later in Stage 4
(`config/field_definitions.yml` losing columns only the doomed types used)
is exactly the kind of change that could silently alter a surviving type's
CSV header or JSONL key set without changing a single pixel — this test
closes that gap.

`tests/regenerate_derived_baseline.py` captures the fixture this compares
against (`tests/fixtures/derived_baseline.json`) by calling the same
`derive_*` functions this test calls, filtering every artefact down to
BANK_STATEMENT / RECEIPT / INVOICE rows (and, for doc_refs.jsonl, the
'receipt_to_bank' link type) and hashing each subset. The doomed types
(cc_statement and the four trust types) are excluded on both sides by
construction, so this test stays green across their deletion in Tasks 2-3 —
it only ever asserts about the three survivors.

Task 4 (the schema trim) then hit the one artefact whose shape is a function
of `all_columns` rather than of each entry's own fields: `ground_truth.csv`,
whose header is `["image_file", *all_columns]` and whose every row carries a
NOT_FOUND cell for each column the entry doesn't use. Trimming 26 doomed
columns necessarily changes that header and those rows for all three
survivors, so "unchanged" was never satisfiable there. The fixture was NOT
re-captured; instead the two CSV assertions became *delta* assertions against
the still-47-column fixture (see DOOMED_COLUMNS below), and a fourth test
pins the CSV's surviving values against `ground_truth.jsonl`, which the trim
left byte-identical and which is still hash-compared to the fixture. The
other five artefacts are untouched by the trim and still assert equality.

To re-bless after an *intended* change to a surviving type's derived output:

    conda run -n synthetic python tests/regenerate_derived_baseline.py --confirm

There is no other way to update this fixture — `--confirm` is required and
defaults to False, so a bare run only prints a dry-run summary.
"""

import json
import tempfile
from pathlib import Path

from regenerate_derived_baseline import (
    _BASELINE_PATH,
    _FIELD_DEFS_PATH,
    _csv_rows,
    _gt_files,
    _jsonl_rows,
    build_summary,
)

from generators.derive_outputs import derive_csv, derive_jsonl

BASELINE = json.loads(_BASELINE_PATH.read_text())
CURRENT = build_summary()

# The 26 columns Stage 4 Task 4 removed from field_definitions.yml's
# `all_columns`, in the order the pre-trim CSV header carried them: three the
# credit-card statement owned, then the 23 the four trust types owned. The
# fixture is deliberately NOT re-captured for the trim — it still records the
# 47-column header — so these tests assert the *delta* against it rather than
# equality. That keeps the gate's protective power: a surviving column dropped
# by mistake would not appear in this list and the projection below would
# catch it.
DOOMED_COLUMNS: tuple[str, ...] = (
    # cc_statement
    "CREDIT_LIMIT",
    "MINIMUM_PAYMENT",
    "PAYMENT_DUE_DATE",
    # trust_return / distribution_statement / trust_income_schedule
    "TRUST_NAME",
    "TRUST_TFN",
    "TRUST_ABN",
    "TRUSTEE_NAME",
    "TRUST_ADDRESS",
    "INCOME_YEAR",
    "TOTAL_NET_INCOME",
    "BENEFICIARY_NAME",
    "BENEFICIARY_TFN",
    "BENEFICIARY_ADDRESS",
    "SHARE_OF_NET_INCOME",
    "FRANKING_CREDIT",
    "CAPITAL_GAIN_COMPONENT",
    "FOREIGN_INCOME",
    "TAX_FREE_AMOUNT",
    "TAX_DEFERRED_AMOUNT",
    "DATE_OF_DISTRIBUTION",
    # beneficiary_itr
    "INDIVIDUAL_NAME",
    "INDIVIDUAL_TFN",
    "DATE_OF_BIRTH",
    "INDIVIDUAL_ADDRESS",
    "TOTAL_TRUST_INCOME",
    "TRUST_FRANKING_CREDIT",
)


def _without_doomed(columns):
    """Project a pre-trim column list onto the columns that should survive."""
    return [c for c in columns if c not in DOOMED_COLUMNS]


def test_baseline_fixture_covers_the_expected_artefacts():
    """Guards against an artefact silently going uncovered — the fixture
    must name exactly the six files `pipeline.py derive` writes.
    """
    assert set(BASELINE.keys()) == {
        "ground_truth.csv",
        "ground_truth.jsonl",
        "cord.jsonl",
        "docile.jsonl",
        "native.jsonl",
        "doc_refs.jsonl",
    }


def test_no_doomed_column_survives_in_the_header():
    """None of the columns the schema trim removed may reappear.

    The fixture is now captured post-trim, so the delta projection these tests
    used during the trim itself has retired — comparing a post-trim baseline
    against a post-trim export is plain equality, done by the tests below. What
    is still worth asserting is the one-way property: a deleted document type's
    column must never come back, which would mean a column describing a
    document this corpus no longer contains.
    """
    header = set(CURRENT["ground_truth.csv"]["header"])
    resurrected = sorted(set(DOOMED_COLUMNS) & header)
    assert not resurrected, f"columns removed by the schema trim reappeared: {resurrected}"


def test_ground_truth_csv_header_unchanged():
    """The CSV header — names and order — matches the baseline exactly."""
    assert CURRENT["ground_truth.csv"]["header"] == BASELINE["ground_truth.csv"]["header"]


def test_ground_truth_csv_surviving_types_unchanged():
    """Per-type column set, in order, plus row count."""
    for doc_type in ("BANK_STATEMENT", "RECEIPT", "INVOICE"):
        current = CURRENT["ground_truth.csv"]["by_type"][doc_type]
        baseline = BASELINE["ground_truth.csv"]["by_type"][doc_type]
        assert current["keys"] == baseline["keys"], f"ground_truth.csv/{doc_type} column set drifted"
        assert current["row_count"] == baseline["row_count"]


def test_ground_truth_csv_cells_agree_with_the_hash_pinned_jsonl():
    """Pins the CSV's *values*, which the trim's changed row hash can no
    longer do on its own.

    `ground_truth.jsonl` emits only the fields an entry actually carries, so
    the trim left it byte-identical — `test_ground_truth_jsonl_surviving_types_unchanged`
    still compares its hash against the un-recaptured fixture. Every surviving
    CSV cell is the same `str(value)` off the same ground-truth entry, so
    checking the CSV against the JSONL transitively pins the CSV to the
    baseline without re-blessing anything.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        gt_files = _gt_files()
        csv_rows = _csv_rows(derive_csv(gt_files, _FIELD_DEFS_PATH, tmp_dir / "gt.csv"))
        jsonl_by_image = {
            r["image_file"]: r for r in _jsonl_rows(derive_jsonl(gt_files, tmp_dir / "gt.jsonl"))
        }

    assert csv_rows, "derive_csv produced no rows"
    for row in csv_rows:
        record = jsonl_by_image[row["image_file"]]
        for column, cell in row.items():
            if column == "image_file":
                continue
            assert cell == record.get(column, "NOT_FOUND"), (
                f"{row['image_file']}: CSV column {column} disagrees with ground_truth.jsonl"
            )


def test_ground_truth_jsonl_surviving_types_unchanged():
    for doc_type in ("BANK_STATEMENT", "RECEIPT", "INVOICE"):
        assert (
            CURRENT["ground_truth.jsonl"]["by_type"][doc_type]
            == (BASELINE["ground_truth.jsonl"]["by_type"][doc_type])
        ), f"ground_truth.jsonl/{doc_type} drifted from baseline"


def test_native_jsonl_bank_statement_unchanged():
    """Only BANK_STATEMENT is a native document among the three survivors —
    receipts and invoices route through CORD instead (see
    generators/derive_outputs.py's NATIVE_DOCUMENT_TYPES / CORD_DOCUMENT_TYPES
    partition), so their native.jsonl row_count is 0 by design, not a gap.
    """
    assert (
        CURRENT["native.jsonl"]["by_type"]["BANK_STATEMENT"]
        == (BASELINE["native.jsonl"]["by_type"]["BANK_STATEMENT"])
    )


def test_cord_jsonl_unchanged():
    assert CURRENT["cord.jsonl"] == BASELINE["cord.jsonl"]


def test_docile_jsonl_unchanged():
    assert CURRENT["docile.jsonl"] == BASELINE["docile.jsonl"]


def test_doc_refs_receipt_to_bank_unchanged():
    """Only the receipt<->bank half of doc_refs.jsonl survives Stage 4 — the
    'trust_distribution_quad' half is entirely doomed and excluded from both
    sides of this comparison (see module docstring).
    """
    assert (
        CURRENT["doc_refs.jsonl"]["by_link_type"]["receipt_to_bank"]
        == (BASELINE["doc_refs.jsonl"]["by_link_type"]["receipt_to_bank"])
    )


def test_row_counts_match_the_known_corpus_size():
    """Sanity-anchors the baseline itself against the documented corpus shape
    (CLAUDE.md: 55 cases per business type) so a baseline captured against a
    corrupted tree can't silently pass everything else in this file.
    """
    assert BASELINE["ground_truth.csv"]["by_type"]["BANK_STATEMENT"]["row_count"] == 55
    assert BASELINE["ground_truth.csv"]["by_type"]["RECEIPT"]["row_count"] == 55
    assert BASELINE["ground_truth.csv"]["by_type"]["INVOICE"]["row_count"] == 55
    assert BASELINE["cord.jsonl"]["row_count"] == 110  # 55 receipts + 55 invoices
    assert BASELINE["docile.jsonl"]["row_count"] == 55  # invoices only
    assert BASELINE["doc_refs.jsonl"]["by_link_type"]["receipt_to_bank"]["row_count"] == 110
