# ruff: noqa: B008 - typer.Option in defaults is the standard Typer pattern
"""Generate the trust classification ground-truth YAML from ground truth.

Derives a flat ``{image_filename: DOCUMENT_TYPE}`` mapping that the
``stages.evaluate_trust`` step in LMM_POC consumes to score document-type
classification accuracy (``pipeline.trust.classification_ground_truth`` in
LMM_POC ``run_config.yml``).

The image filename is reconstructed with the SAME rule the renderer uses
(``generators/pipeline.py``): ``f"{case_id}_{layout}.png"``. This is why the
file must be generated rather than hand-maintained — when distribution
statements were spread across six layouts, the old ``*_distribution_statement_standard.png``
keys went stale and no longer matched the rendered images
(e.g. ``CASE223_dist_letter_formal.png``).

Document type is determined by the source ground-truth file; the four canonical
types match LMM_POC ``stages/trust_classify.py``'s ``_TYPE_TO_COLUMN``.

Usage:
    python scripts/generate_trust_classification_gt.py
    python scripts/generate_trust_classification_gt.py --output /path/to/trust_classification_gt.yml
"""

import logging
from pathlib import Path

import typer
import yaml

logger = logging.getLogger(__name__)
app = typer.Typer()

_REPO = Path(__file__).parent.parent

# Source ground-truth file (stem) -> canonical document type.
# Types MUST match LMM_POC stages/trust_classify.py:_TYPE_TO_COLUMN.
_SOURCE_TYPE_MAP: dict[str, str] = {
    "trust_returns": "TRUST_RETURN",
    "distribution_statements": "DISTRIBUTION_STMT",
    "trust_income_schedules": "INCOME_SCHEDULE",
    "beneficiary_itrs": "BENEFICIARY_ITR",
}


def _load_entries(path: Path) -> dict[str, dict]:
    """Load a ground-truth YAML mapping CASE### -> entry.

    Args:
        path: Path to a ground_truth/*.yml file.

    Returns:
        Mapping of case_id -> entry dict.

    Raises:
        typer.Exit: with a diagnostic message if the file is missing or malformed.
    """
    if not path.is_file():
        logger.error(
            "Ground-truth source file not found: %s\n"
            "  Expected one YAML per document type in: %s\n"
            "  Required stems: %s\n"
            "  Recover: re-seed with `python scripts/seed_trust_distributions.py`, "
            "or pass the correct directory via `--ground-truth-dir`.",
            path,
            path.parent,
            ", ".join(sorted(_SOURCE_TYPE_MAP)),
        )
        raise typer.Exit(1) from None

    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not data:
        logger.error(
            "Ground-truth file is empty or not a CASE###-keyed mapping: %s\n"
            "  Expected top-level keys like:\n"
            "    CASE201:\n      layout: <layout_id>\n      fields: {...}\n"
            "  Recover: re-seed with `python scripts/seed_trust_distributions.py`.",
            path,
        )
        raise typer.Exit(1) from None
    return data


def build_classification_gt(ground_truth_dir: Path) -> dict[str, str]:
    """Build the ``{image_filename: DOCUMENT_TYPE}`` classification ground truth.

    Reads the four trust ground-truth YAMLs and reconstructs each rendered
    image filename as ``f"{case_id}_{layout}.png"``.

    Args:
        ground_truth_dir: Directory holding the four ground_truth/*.yml files.

    Returns:
        Mapping of image filename -> canonical document type, sorted by filename.

    Raises:
        typer.Exit: with a diagnostic message on a missing file, a missing
            ``layout`` field, or a duplicate filename.
    """
    gt: dict[str, str] = {}
    for stem, doc_type in _SOURCE_TYPE_MAP.items():
        path = ground_truth_dir / f"{stem}.yml"
        for case_id, entry in _load_entries(path).items():
            layout = entry.get("layout")
            if not layout:
                logger.error(
                    "Entry %s in %s has no `layout` field.\n"
                    "  Every entry must name the layout it renders with, e.g.:\n"
                    "    %s:\n      layout: trust_return_standard\n"
                    "  Recover: re-seed with `python scripts/seed_trust_distributions.py`.",
                    case_id,
                    path,
                    case_id,
                )
                raise typer.Exit(1) from None

            filename = f"{case_id}_{layout}.png"
            if filename in gt:
                logger.error(
                    "Duplicate image filename derived: %s\n"
                    "  Two ground-truth entries map to the same rendered file "
                    "(case_id + layout collision).\n"
                    "  Where: %s and an earlier source file.\n"
                    "  Recover: ensure each (case_id, layout) pair is unique across "
                    "the four ground_truth/*.yml files.",
                    filename,
                    path,
                )
                raise typer.Exit(1) from None
            gt[filename] = doc_type

    return dict(sorted(gt.items()))


@app.command()
def generate(
    ground_truth_dir: Path = typer.Option(
        _REPO / "ground_truth",
        "--ground-truth-dir",
        help="Directory containing the four trust ground_truth/*.yml files.",
    ),
    output: Path = typer.Option(
        _REPO / "derived" / "trust_classification_gt.yml",
        "--output",
        "-o",
        help="Output path for the classification ground-truth YAML.",
    ),
) -> None:
    """Generate trust_classification_gt.yml from ground truth."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    gt = build_classification_gt(ground_truth_dir)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(gt, sort_keys=True, default_flow_style=False))

    by_type: dict[str, int] = {}
    for doc_type in gt.values():
        by_type[doc_type] = by_type.get(doc_type, 0) + 1
    logger.info("Wrote %d entries to %s", len(gt), output)
    for doc_type in sorted(by_type):
        logger.info("  %-18s %d", doc_type, by_type[doc_type])


if __name__ == "__main__":
    app()
