"""Structural contract for evaluation-set export directories.

Pins the *shape* of an exported evaluation-set directory -- filename
pattern and count, `ground_truth.csv` header and column order, and
`ground_truth.jsonl` key set and key order per document type -- against
`tests/fixtures/eval_format_baseline.json`. That fixture was captured from
the existing hand-verified dataset at
`/Users/tod/Desktop/evaluation_data/synthetic_20260731`.

Field *values* are deliberately never inspected: the corpus is reseeded
independently of this format, so a value-based comparison would fail for
the wrong reason forever. Shape is the only part of the dataset that is a
contract with external consumers (competing vision-language models scored
against it), and shape is what stays meaningful as a regression signal.

`assert_eval_export_matches_baseline` takes a directory path rather than
being hard-coded to the legacy dataset, because later tasks in the eval-set
export refactor point it at freshly produced export directories to confirm
the in-house replacement reproduces the same contract.
"""

import csv
import json
import re
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_BASELINE_PATH = _FIXTURES_DIR / "eval_format_baseline.json"

# The dataset this fixture was captured from. Used only by the test in this
# file that confirms the fixture describes reality; other callers of
# assert_eval_export_matches_baseline supply their own directory.
#
# It lives outside the repository and `docs/eval_export_plan.md` records it as
# disposable, so it is frequently absent -- on any machine but the one it was
# captured on, always. The test below therefore skips rather than fails when it
# is gone, which is a statement about this one dataset's availability and not a
# relaxation of the format contract: every other caller pins a freshly exported
# directory against the same baseline on every run.
_LEGACY_DATASET = Path("/Users/tod/Desktop/evaluation_data/synthetic_20260731")


def load_baseline() -> dict:
    """Load the pinned eval-export format fixture."""
    return json.loads(_BASELINE_PATH.read_text())


def assert_eval_export_matches_baseline(directory: Path, baseline: dict | None = None) -> None:
    """Assert that `directory` has the pinned evaluation-set export shape.

    Checks, against `baseline` (defaults to the fixture on disk):
      - every `*.png` filename matches the pinned pattern, with no leakage
        of layout-variant names (e.g. `CASE001_cba_standard.png`)
      - the total image count and the per-document-type-suffix image count
      - `ground_truth.csv` exists with the pinned header, in the pinned
        column order, and the pinned row count
      - `ground_truth.jsonl` exists with the pinned record count, and each
        record's key set and key order match the pinned order for its
        `DOCUMENT_TYPE`

    Never compares field values -- only the structural shape above. Files
    beside the images that are not in `baseline["required_files"]` are
    permitted but not required, since some of them (e.g. `synthetic.yml`,
    `relabel_mapping.csv` in the legacy dataset) are incidental to how a
    particular export happened to be produced rather than part of the
    format itself.

    Args:
        directory: Path to an evaluation-set export directory to check.
        baseline: Pinned format description; loaded from the fixture file
            on disk if not given.

    Raises:
        AssertionError: If `directory` does not match the pinned shape.
    """
    if baseline is None:
        baseline = load_baseline()
    directory = Path(directory)
    assert directory.is_dir(), f"not a directory: {directory}"

    _assert_images_match(directory, baseline)
    _assert_required_files_present(directory, baseline)
    _assert_csv_matches(directory, baseline["csv"])
    _assert_jsonl_matches(directory, baseline["jsonl"])


def _assert_images_match(directory: Path, baseline: dict) -> None:
    images = sorted(p.name for p in directory.glob("*.png"))
    pattern = re.compile(baseline["filename_pattern"])

    non_matching = [name for name in images if not pattern.fullmatch(name)]
    assert not non_matching, (
        f"filenames not matching pattern {baseline['filename_pattern']!r} "
        f"(possible layout-variant leakage): {non_matching}"
    )

    assert len(images) == baseline["image_count"], (
        f"expected {baseline['image_count']} images in {directory}, found {len(images)}"
    )

    counts_by_suffix: dict[str, int] = {}
    for name in images:
        suffix = name.split("_", 1)[1].removesuffix(".png")
        counts_by_suffix[suffix] = counts_by_suffix.get(suffix, 0) + 1
    assert counts_by_suffix == baseline["images_per_suffix"], (
        f"image count per document-type suffix mismatch: "
        f"expected {baseline['images_per_suffix']}, found {counts_by_suffix}"
    )


def _assert_required_files_present(directory: Path, baseline: dict) -> None:
    missing = [name for name in baseline["required_files"] if not (directory / name).exists()]
    assert not missing, f"missing required files in {directory}: {missing}"


def _assert_csv_matches(directory: Path, csv_baseline: dict) -> None:
    csv_path = directory / "ground_truth.csv"
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    assert header == csv_baseline["columns"], (
        f"ground_truth.csv header mismatch.\nexpected: {csv_baseline['columns']}\nfound:    {header}"
    )
    assert len(rows) == csv_baseline["row_count"], (
        f"ground_truth.csv row count mismatch: expected {csv_baseline['row_count']}, found {len(rows)}"
    )


def _assert_jsonl_matches(directory: Path, jsonl_baseline: dict) -> None:
    jsonl_path = directory / "ground_truth.jsonl"
    records = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]

    assert len(records) == jsonl_baseline["record_count"], (
        f"ground_truth.jsonl record count mismatch: "
        f"expected {jsonl_baseline['record_count']}, found {len(records)}"
    )

    expected_by_type = jsonl_baseline["keys_by_document_type"]
    found_orderings: dict[str, set[tuple[str, ...]]] = {}
    for record in records:
        doc_type = record.get("DOCUMENT_TYPE")
        assert doc_type in expected_by_type, (
            f"unexpected DOCUMENT_TYPE {doc_type!r} in ground_truth.jsonl record; "
            f"expected one of {sorted(expected_by_type)}"
        )
        found_orderings.setdefault(doc_type, set()).add(tuple(record.keys()))

    assert set(found_orderings) == set(expected_by_type), (
        f"ground_truth.jsonl document types mismatch: "
        f"expected {sorted(expected_by_type)}, found {sorted(found_orderings)}"
    )
    for doc_type, orderings in found_orderings.items():
        assert orderings == {tuple(expected_by_type[doc_type])}, (
            f"ground_truth.jsonl key order mismatch for {doc_type}:\n"
            f"expected: {expected_by_type[doc_type]}\nfound:    {sorted(orderings)}"
        )


@pytest.mark.skipif(
    not _LEGACY_DATASET.is_dir(),
    reason=(
        f"the legacy evaluation dataset is not present at {_LEGACY_DATASET}. It lives "
        "outside the repository and is recorded as disposable, so its absence is an "
        "expected local condition rather than a defect. The format contract is still "
        "enforced -- every other caller of assert_eval_export_matches_baseline pins a "
        "freshly exported directory against the same baseline."
    ),
)
def test_legacy_dataset_matches_baseline() -> None:
    """The fixture must describe the dataset it was captured from.

    Skipped where that dataset no longer exists. The check is worth keeping for
    the machine that still has it, because it is the only one that verifies the
    baseline was captured from something real rather than written by hand.
    """
    assert_eval_export_matches_baseline(_LEGACY_DATASET)
