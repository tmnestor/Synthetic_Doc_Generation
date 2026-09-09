"""The degraded eval set holds the declared types at each declared tier, with
extraction ground truth duplicated per variant and a quality ground truth
describing each image's condition.

Every expectation here is read from config/generation_config.yml rather than
written as a literal. These tests are the executable spec of the degradation
design, and that design is a configuration: when it said "receipts only, three
tiers" the literals agreed with it, and when it changed to "whatever
degrade_types says, two tiers" fifteen tests failed for asserting a decision
rather than a behaviour. Deriving means retuning the ladder in YAML does not
require editing this file -- and that a type or tier silently vanishing from
the config still fails, because the counts stop matching the images.
"""

import csv
import json
from pathlib import Path

import pytest
import yaml

from generators.eval_set import export_eval_set

CONFIG = Path("config/generation_config.yml")


def _singular(config_key: str) -> str:
    """Bridge the config's plural type keys to the singular name in filenames.

    generation_config.yml keys document types in the plural (``receipts:``);
    exported filenames carry the singular canonical name from
    config/extraction_schema.yml (``CASE001_receipt.png``). Every test that
    uses this also asserts the derived name actually appears, so a divergence
    fails loudly instead of quietly matching nothing.
    """
    return config_key.removesuffix("s")


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(CONFIG.read_text())


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("evalset")
    summary = export_eval_set(CONFIG, out, force=True)
    return summary, Path(summary["clean_dir"]), Path(summary["degraded_dir"])


@pytest.fixture(scope="module")
def combined(exported):
    """The single-directory half, for consumers that take one path."""
    summary, _, _ = exported
    return Path(summary["quality_dir"])


@pytest.fixture(scope="module")
def shape(cfg, exported):
    """The corpus dimensions the config implies, plus the case count observed."""
    _, clean_dir, _ = exported
    doc_types = [_singular(t) for t in cfg["eval_set"]["document_types"]]
    degrade_types = [_singular(t) for t in cfg["eval_set"]["degrade_types"]]
    # Tiers are declared per document type, but the loader guarantees every
    # type declares the same rungs, so any type's suffixes describe them all.
    tiers_by_type = cfg["document_degradation"]["tiers"]
    suffixes = [t["suffix"] for t in next(iter(tiers_by_type.values()))]
    cases = sorted({p.name.split("_")[0] for p in clean_dir.glob("*.png")})
    return {
        "doc_types": doc_types,
        "degrade_types": degrade_types,
        "suffixes": suffixes,
        "cases": cases,
    }


def _type_of(name: str, suffixes: list[str]) -> str:
    """Extract the document type from an exported filename."""
    stem = Path(name).stem.split("_", 1)[1]
    for suffix in suffixes:
        stem = stem.removesuffix(f"_{suffix}")
    return stem


def test_clean_dir_holds_every_declared_type_once_per_case(exported, shape):
    _, clean_dir, _ = exported
    names = [p.name for p in clean_dir.glob("*.png")]
    assert len(names) == len(shape["cases"]) * len(shape["doc_types"])
    for doc_type in shape["doc_types"]:
        got = sum(1 for n in names if _type_of(n, shape["suffixes"]) == doc_type)
        assert got == len(shape["cases"]), f"expected one {doc_type} per case, got {got}"


def test_degraded_dir_holds_exactly_the_types_declared_for_degradation(exported, shape):
    """Which types get degraded is a config decision, so read it from config.

    Replaces a test that asserted "receipts only" -- true when written, and a
    statement about intent rather than about the exporter.
    """
    _, _, degraded_dir = exported
    types = {_type_of(p.name, shape["suffixes"]) for p in degraded_dir.glob("*.png")}
    assert types == set(shape["degrade_types"])


def test_types_not_declared_for_degradation_have_no_variants(exported, shape):
    """A clean-only type must appear in the clean half and nowhere else."""
    _, _, degraded_dir = exported
    clean_only = set(shape["doc_types"]) - set(shape["degrade_types"])
    degraded_types = {_type_of(p.name, shape["suffixes"]) for p in degraded_dir.glob("*.png")}
    assert clean_only.isdisjoint(degraded_types)


def test_every_degraded_document_has_one_image_per_tier(exported, shape):
    _, _, degraded_dir = exported
    names = {p.name for p in degraded_dir.glob("*.png")}
    for case in shape["cases"]:
        for doc_type in shape["degrade_types"]:
            for suffix in shape["suffixes"]:
                assert f"{case}_{doc_type}_{suffix}.png" in names


def test_degraded_count_is_cases_times_types_times_tiers(exported, shape):
    _, _, degraded_dir = exported
    expected = len(shape["cases"]) * len(shape["degrade_types"]) * len(shape["suffixes"])
    assert len(list(degraded_dir.glob("*.png"))) == expected


def test_degraded_ground_truth_has_one_row_per_variant(exported):
    _, _, degraded_dir = exported
    rows = list(csv.DictReader((degraded_dir / "ground_truth.csv").open()))
    images = {p.name for p in degraded_dir.glob("*.png")}
    assert len(rows) == len(images)
    assert {r["image_file"] for r in rows} == images


def test_variants_of_a_case_share_identical_field_values(exported, shape):
    """The value-F1 contract: distortion never changes the answer."""
    _, _, degraded_dir = exported
    rows = {r["image_file"]: r for r in csv.DictReader((degraded_dir / "ground_truth.csv").open())}
    for case in shape["cases"][:: max(1, len(shape["cases"]) // 3)]:
        for doc_type in shape["degrade_types"]:
            variants = [rows[f"{case}_{doc_type}_{s}.png"] for s in shape["suffixes"]]
            for other in variants[1:]:
                for column, value in variants[0].items():
                    if column == "image_file":
                        continue
                    assert other[column] == value, f"{case} {column} differs across tiers"


def test_degraded_jsonl_matches_the_csv(exported):
    """The JSONL keys the image as `filename`; only the CSV renames it to
    `image_file` (see csv_from_jsonl)."""
    _, _, degraded_dir = exported
    lines = (degraded_dir / "ground_truth.jsonl").read_text().splitlines()
    images = {p.name for p in degraded_dir.glob("*.png")}
    assert len(lines) == len(images)
    assert {json.loads(line)["filename"] for line in lines} == images


def test_variant_values_match_the_clean_source_row(exported, shape):
    """A variant must carry its *source document's* answers, not merely be
    self-consistent across tiers."""
    _, clean_dir, degraded_dir = exported
    clean = {r["image_file"]: r for r in csv.DictReader((clean_dir / "ground_truth.csv").open())}
    degraded = {r["image_file"]: r for r in csv.DictReader((degraded_dir / "ground_truth.csv").open())}
    suffix = shape["suffixes"][0]
    for case in shape["cases"][:: max(1, len(shape["cases"]) // 3)]:
        for doc_type in shape["degrade_types"]:
            source = clean[f"{case}_{doc_type}.png"]
            variant = degraded[f"{case}_{doc_type}_{suffix}.png"]
            for column, value in variant.items():
                if column == "image_file":
                    continue
                assert value == source[column], f"{case} {column} drifted from the clean row"


def test_degraded_header_carries_no_column_for_an_absent_type(exported, cfg):
    """No column that would be NOT_FOUND in every row.

    Was `test_degraded_header_is_receipt_shaped`, which asserted the degraded
    half held receipts only. That premise is gone -- the half now spans every
    degraded type -- but the guarantee underneath it survives: a type excluded
    from the corpus must not leave its columns behind. Bank statements are the
    excluded type, so their columns are the ones to check for.
    """
    _, _, degraded_dir = exported
    exported_types = set(cfg["eval_set"]["document_types"])
    if "bank_statements" in exported_types:
        pytest.skip("bank statements are in the corpus, so their columns belong")
    header = next(iter(csv.DictReader((degraded_dir / "ground_truth.csv").open())))
    assert "STATEMENT_DATE_RANGE" not in header
    assert "TRANSACTION_DATES" not in header


def test_case_ids_still_resolve_for_linking(exported):
    """Case ids are unsuffixed, so transaction_links.yml keeps resolving."""
    _, _, degraded_dir = exported
    rows = list(csv.DictReader((degraded_dir / "ground_truth.csv").open()))
    for row in rows:
        assert row["image_file"].split("_")[0].startswith("CASE")


def test_summary_reports_both_counts(exported, shape):
    summary, _, _ = exported
    assert summary["images"] == len(shape["cases"]) * len(shape["doc_types"])
    assert summary["degraded_images"] == (
        len(shape["cases"]) * len(shape["degrade_types"]) * len(shape["suffixes"])
    )


# --------------------------------------------------------------------------
# Quality-screen ground truth
# --------------------------------------------------------------------------
# These share the `exported` fixture rather than living in their own file: it
# renders the whole corpus through Augraphy, and a second module-scoped export
# would double an already slow suite for no extra coverage.


@pytest.fixture(scope="module")
def quality(cfg, exported):
    """The quality ground truth from both halves, keyed by filename."""
    _, clean_dir, degraded_dir = exported
    name = cfg["document_degradation"]["defect_labels"]["filename"]

    def _load(directory):
        return {
            json.loads(line)["filename"]: json.loads(line)
            for line in (directory / name).read_text().splitlines()
        }

    return _load(clean_dir), _load(degraded_dir)


def test_quality_ground_truth_covers_every_image(exported, quality):
    _, clean_dir, degraded_dir = exported
    clean_q, degraded_q = quality
    assert set(clean_q) == {p.name for p in clean_dir.glob("*.png")}
    assert set(degraded_q) == {p.name for p in degraded_dir.glob("*.png")}


def test_defect_vocabulary_matches_the_declared_rules(cfg, quality):
    """The prompt's questions are keyed on these names, so a rename that only
    lands on one side must fail here rather than silently score nothing."""
    declared = set(cfg["document_degradation"]["defect_labels"]["rules"])
    for records in quality:
        for record in records.values():
            assert set(record["defects"]) == declared


def test_clean_images_carry_no_defects(quality):
    """The negative class. If a clean image ever labels a defect true, the
    screen's false-positive rate is being measured against a corrupt column."""
    clean_q, _ = quality
    for name, record in clean_q.items():
        assert record["condition"] == "clean"
        assert not any(record["defects"].values()), f"{name} labels a defect on a clean render"


def test_every_degraded_row_names_a_declared_tier(cfg, quality):
    _, degraded_q = quality
    tier_names = {
        t["name"] for tiers in cfg["document_degradation"]["tiers"].values() for t in tiers
    }
    assert {r["condition"] for r in degraded_q.values()} == tier_names


def test_categorical_defects_follow_their_tier_declaration(cfg, quality):
    """A defect decided by "is this augmentation in the tier?" must be true for
    every image of a tier that declares it and false for every image of one
    that does not -- there is no per-image randomness in that decision.

    This is what pins `crease` to the heavy tier: Folding is declared there and
    nowhere else, so a moderate image claiming a crease means the phase lists
    and the labels have drifted apart.
    """
    _, degraded_q = quality
    rules = cfg["document_degradation"]["defect_labels"]["rules"]
    categorical = {d: r["augmentation"] for d, r in rules.items() if "augmentation" in r}
    # Keyed on (document type, tier): the phase lists are declared per type, so
    # a type whose ladder omits an augmentation must not carry its defect.
    declared = {
        (_singular(doc_type), tier["name"]): {
            spec["augmentation"] for spec in (*tier["ink"], *tier["paper"])
        }
        for doc_type, tiers in cfg["document_degradation"]["tiers"].items()
        for tier in tiers
    }
    for name, record in degraded_q.items():
        key = (record["document_type"], record["condition"])
        for defect, augmentation in categorical.items():
            expected = augmentation in declared[key]
            assert record["defects"][defect] is expected, (
                f"{name} ({key}): {defect} is {record['defects'][defect]} "
                f"but {augmentation} is {'' if expected else 'not '}declared for that tier"
            )


# --------------------------------------------------------------------------
# The combined directory
# --------------------------------------------------------------------------
# LMM_POC's classify/extract/clean/evaluate stages all read one image directory
# and score against one ground truth, so the quality screen -- which must see
# clean and degraded images in the same run to have a false-positive rate --
# cannot consume the split halves.


def test_combined_dir_is_exactly_the_union_of_both_halves(exported, combined):
    """No image missing, and none invented."""
    _, clean_dir, degraded_dir = exported
    expected = {p.name for p in clean_dir.glob("*.png")} | {p.name for p in degraded_dir.glob("*.png")}
    assert {p.name for p in combined.glob("*.png")} == expected


def test_combined_images_are_real_copies_not_links(exported, combined):
    """Chosen over links so the set survives either source being moved or
    deleted. A link would pass the union test above while leaving the corpus
    dependent on directories a consumer has no reason to keep."""
    _, clean_dir, _ = exported
    sample = next(iter(clean_dir.glob("*.png")))
    copied = combined / sample.name
    assert not copied.is_symlink()
    assert copied.stat().st_ino != sample.stat().st_ino
    assert copied.read_bytes() == sample.read_bytes()


def test_combined_ground_truths_have_one_row_per_image(cfg, combined):
    images = {p.name for p in combined.glob("*.png")}
    rows = list(csv.DictReader((combined / "ground_truth.csv").open()))
    assert {r["image_file"] for r in rows} == images

    name = cfg["document_degradation"]["defect_labels"]["filename"]
    quality_rows = [json.loads(line) for line in (combined / name).read_text().splitlines()]
    assert {r["filename"] for r in quality_rows} == images


def test_combined_set_holds_every_condition(cfg, combined):
    """The point of the directory: a screen that never sees a clean image has
    no false-positive rate, and one that never sees a heavy image is untested
    at the severity that matters."""
    name = cfg["document_degradation"]["defect_labels"]["filename"]
    rows = [json.loads(line) for line in (combined / name).read_text().splitlines()]
    tier_names = {t["name"] for tiers in cfg["document_degradation"]["tiers"].values() for t in tiers}
    assert {r["condition"] for r in rows} == tier_names | {"clean"}


def test_a_case_carries_identical_extraction_values_across_conditions(exported, combined, shape):
    """Distortion never changes the answer -- now checked across the clean row
    and its variants together, which only the combined set makes possible."""
    rows = {r["image_file"]: r for r in csv.DictReader((combined / "ground_truth.csv").open())}
    for case in shape["cases"][:: max(1, len(shape["cases"]) // 3)]:
        for doc_type in shape["degrade_types"]:
            names = [f"{case}_{doc_type}.png"] + [
                f"{case}_{doc_type}_{s}.png" for s in shape["suffixes"]
            ]
            first = rows[names[0]]
            for other in names[1:]:
                for column, value in first.items():
                    if column == "image_file":
                        continue
                    assert rows[other][column] == value, f"{other} {column} differs from the clean row"


def test_drawn_values_are_recorded_for_every_threshold_rule(cfg, quality):
    """Every value a threshold rule reads must actually be written out, so a
    label can be re-derived without re-rendering."""
    rules = cfg["document_degradation"]["defect_labels"]["rules"]
    wanted = set()
    for rule in rules.values():
        for clause in rule.get("any_of", [rule]):
            if "drawn" in clause:
                wanted.add(clause["drawn"])
    # rotation_deg_abs is derived in labels.py from the recorded rotation_deg.
    wanted = {w.removesuffix("_abs") for w in wanted}
    for records in quality:
        for name, record in records.items():
            missing = wanted - set(record["params"])
            assert not missing, f"{name} does not record {sorted(missing)}"
