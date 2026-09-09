"""Eval-set export: config validation, projection, CSV/JSONL shape.

The full export is exercised once, in a module-scoped fixture, because
rendering the whole corpus twice (clean + degraded) is the expensive part;
every property of the products is then asserted against that one export.

Counts are derived from config/generation_config.yml and from the export
itself, never written as literals. The corpus size is an operator decision --
it has already gone from 165 images across three types to 110 across two --
and a test that hardcodes it fails for expressing a preference rather than a
contract.
"""

import csv as csv_module
import json
from datetime import date
from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error
from test_eval_format import assert_eval_export_matches_baseline

from generators.bank_statement import render_bank_statement
from generators.eval_set import (
    csv_from_jsonl,
    export_eval_set,
    format_value,
    load_eval_set_config,
    project_fields,
    write_jsonl,
)
from generators.exporters.eval_projection import load_extraction_schema

_CONFIG = Path("config/generation_config.yml")

_REQUIRED = [
    "document_types",
    "clean_dir_prefix",
    "degraded_dir_prefix",
    "csv_name",
    "jsonl_name",
]


def _config_without(tmp_path: Path, key: str | None) -> Path:
    """Copy generation_config.yml with one eval_set key (or the block) removed."""
    data = yaml.safe_load(_CONFIG.read_text())
    if key is None:
        del data["eval_set"]
    else:
        del data["eval_set"][key]
    out = tmp_path / "generation_config.yml"
    out.write_text(yaml.safe_dump(data))
    return out


# --------------------------------------------------------------------------
# Config validation
# --------------------------------------------------------------------------


def test_loads_real_config():
    """Assert the config is coherent, not that it names particular types.

    Which types the corpus carries is an operator decision that has already
    changed once; pinning the list here made this test fail for expressing a
    preference rather than a contract. What must hold is that every declared
    type is renderable and every degraded type is one the export actually
    produces.
    """
    cfg = load_eval_set_config(_CONFIG)
    for key in _REQUIRED:
        assert key in cfg

    declared = yaml.safe_load(_CONFIG.read_text())["document_types"]
    assert cfg["document_types"], "the corpus must contain at least one document type"
    assert set(cfg["document_types"]) <= set(declared), (
        "eval_set.document_types names a type with no top-level document_types entry"
    )
    assert set(cfg["degrade_types"]) <= set(cfg["document_types"]), (
        "eval_set.degrade_types must be a subset of document_types -- a type cannot be "
        "degraded without also being exported"
    )


def test_relabel_keys_are_gone_from_the_config():
    """The export owns its projection; no path into another repo may survive."""
    text = _CONFIG.read_text()
    assert "relabel_script" not in text
    assert "relabel_repo_root" not in text
    assert "LMM_POC" not in text


@pytest.mark.parametrize("key", _REQUIRED)
def test_missing_key_is_four_element_diagnostic(tmp_path, key):
    path = _config_without(tmp_path, key)
    with pytest.raises(ValueError) as exc_info:
        load_eval_set_config(path)
    assert key in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_missing_eval_set_block_is_diagnostic(tmp_path):
    path = _config_without(tmp_path, None)
    with pytest.raises(ValueError) as exc_info:
        load_eval_set_config(path)
    assert_diagnostic_error(exc_info.value)


def test_unknown_document_type_is_diagnostic(tmp_path):
    data = yaml.safe_load(_CONFIG.read_text())
    data["eval_set"]["document_types"] = ["bank_statements", "unicorns"]
    path = tmp_path / "generation_config.yml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError) as exc_info:
        load_eval_set_config(path)
    assert "unicorns" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


# The `degradation:` block this once guarded no longer exists — degradation is
# tiered now, declared under `document_degradation:`, and which types it applies
# to is declared separately under `eval_set.degrade_types:`. Its fail-fast
# coverage lives in tests/degradation/test_tiers.py, and the defect-label rules
# that read a tier's output are covered in tests/test_labels.py.


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------


def test_format_value_applies_monetary_boolean_and_pipe_conventions():
    schema = load_extraction_schema()
    assert format_value("TOTAL_AMOUNT", "137.73", schema) == "$137.73"
    assert format_value("TOTAL_AMOUNT", "$137.73", schema) == "$137.73"
    assert format_value("TOTAL_AMOUNT", "NOT_FOUND", schema) == "NOT_FOUND"
    assert format_value("IS_GST_INCLUDED", "True", schema) == "true"
    assert format_value("LINE_ITEM_DESCRIPTIONS", "Fuel|Coffee", schema) == "Fuel | Coffee"
    # A multi-value monetary field takes the $ per item, not once for the whole.
    assert format_value("LINE_ITEM_PRICES", "1.00|2.00", schema) == "$1.00 | $2.00"
    assert format_value("SUPPLIER_NAME", "", schema) == "NOT_FOUND"


def test_project_fields_uses_schema_order_and_fills_gaps():
    schema = load_extraction_schema()
    projected = project_fields(
        "CASE001",
        {"DOCUMENT_TYPE": "BANK_STATEMENT", "TRANSACTION_DESCRIPTIONS": "EFTPOS|ATM"},
        "BANK_STATEMENT",
        schema,
        Path("ground_truth/bank_statements.yml"),
    )
    assert list(projected) == schema.get_extraction_fields("bank_statement")
    # The generation-contract name is bridged to the extraction-contract name.
    assert projected["LINE_ITEM_DESCRIPTIONS"] == "EFTPOS | ATM"
    # A schema field the generator never emitted is filled, never absent.
    assert projected["STATEMENT_DATE_RANGE"] == "NOT_FOUND"


def test_project_fields_unknown_document_type_is_diagnostic():
    schema = load_extraction_schema()
    with pytest.raises(ValueError) as exc_info:
        project_fields(
            "CASE001",
            {"DOCUMENT_TYPE": "CREDIT_CARD_STATEMENT"},
            "CREDIT_CARD_STATEMENT",
            schema,
            Path("ground_truth/bank_statements.yml"),
        )
    assert "CASE001" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_csv_from_jsonl_matches_records(tmp_path):
    jsonl = tmp_path / "ground_truth.jsonl"
    records = [
        {"filename": "CASE001_bank_statement.png", "DOCUMENT_TYPE": "BANK_STATEMENT", "A": "1"},
        {"filename": "CASE001_receipt.png", "DOCUMENT_TYPE": "RECEIPT", "B": "2"},
    ]
    jsonl.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    csv_path = csv_from_jsonl(jsonl, tmp_path / "ground_truth.csv")
    lines = csv_path.read_text().splitlines()
    assert lines[0].split(",") == ["image_file", "DOCUMENT_TYPE", "A", "B"]
    assert len(lines) == 3
    assert lines[1].startswith("CASE001_bank_statement.png,")
    # A field absent from a record is filled, never left blank.
    assert "NOT_FOUND" in lines[2]


def test_write_jsonl_preserves_field_order(tmp_path):
    documents = [{"filename": "CASE001_receipt.png", "fields": {"B": "2", "A": "1"}}]
    path = write_jsonl(documents, tmp_path / "ground_truth.jsonl")
    record = json.loads(path.read_text().strip())
    assert list(record) == ["filename", "B", "A"]


# --------------------------------------------------------------------------
# The full export
# --------------------------------------------------------------------------


def _rungs(cfg: dict) -> list[dict]:
    """The severity rungs, read from any one document type's ladder.

    Tiers are declared per document type and the loader guarantees every type
    declares the same rungs, so one type's list describes them all. Counting
    `tiers` directly would count TYPES, not rungs -- which happens to give the
    same number today (2 types, 2 rungs) and would therefore pass while
    measuring the wrong thing.
    """
    return next(iter(cfg["document_degradation"]["tiers"].values()))


@pytest.fixture(scope="module")
def expected_counts() -> dict:
    """Corpus dimensions implied by the config, so no count is a literal."""
    cfg = yaml.safe_load(_CONFIG.read_text())
    types = len(cfg["eval_set"]["document_types"])
    degraded_types = len(cfg["eval_set"]["degrade_types"])
    tiers = len(_rungs(cfg))
    return {"types": types, "degraded_types": degraded_types, "tiers": tiers}


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> dict:
    """Run the real export once and share it across the module."""
    out = tmp_path_factory.mktemp("eval_export")
    summary = export_eval_set(_CONFIG, out, today=date(2026, 1, 2))
    return {
        "out": out,
        "summary": summary,
        "clean": Path(summary["clean_dir"]),
        "degraded": Path(summary["degraded_dir"]),
        "cases": len({p.name.split("_")[0] for p in Path(summary["clean_dir"]).glob("*.png")}),
    }


def test_export_creates_dated_sibling_directories(exported, expected_counts):
    """One directory per declared prefix, all sharing the same date stamp.

    Was `..._two_dated_sibling_directories`, pinning the count at two. A third
    was added -- the combined half, for consumers that take a single input
    directory -- so the assertion now derives the expected names from the
    configured prefixes rather than listing them.
    """
    out = exported["out"]
    cfg = yaml.safe_load(_CONFIG.read_text())["eval_set"]
    expected = sorted(
        f"{cfg[key]}_20260102"
        for key in ("clean_dir_prefix", "degraded_dir_prefix", "quality_dir_prefix")
    )

    assert exported["clean"] == out / f"{cfg['clean_dir_prefix']}_20260102"
    assert exported["degraded"] == out / f"{cfg['degraded_dir_prefix']}_20260102"
    assert sorted(p.name for p in out.iterdir()) == expected
    assert exported["summary"]["images"] == exported["cases"] * expected_counts["types"]


def test_the_three_directories_share_one_date_stamp(exported):
    """A mismatched stamp would let a run score new images against an older
    answer key and report plausible numbers."""
    out = exported["out"]
    stamps = {p.name.rsplit("_", 1)[1] for p in out.iterdir()}
    assert len(stamps) == 1, f"directories disagree on the date stamp: {sorted(stamps)}"


def test_export_matches_pinned_format(exported):
    """The pinned format describes the *clean* export: every document type
    once, under `CASE###_<type>.png`.

    The degraded export deliberately no longer has that shape -- it is receipts
    only, one image per severity tier, under `CASE###_receipt_v#.png`. Its
    shape is pinned separately in tests/test_eval_set_variants.py.
    """
    assert_eval_export_matches_baseline(exported["clean"])


def test_the_two_directories_no_longer_mirror_each_other(exported, expected_counts):
    """Different counts and different contents.

    The two halves used to happen to share a count; they no longer do, and
    asserting equality was pinning a coincidence. What is load-bearing is that
    every degraded name carries a tier suffix declared in the config, so the
    two halves can be joined by stripping it.
    """
    cfg = yaml.safe_load(_CONFIG.read_text())
    suffixes = tuple(f"_{t['suffix']}.png" for t in _rungs(cfg))
    clean = sorted(p.name for p in exported["clean"].glob("*.png"))
    degraded = sorted(p.name for p in exported["degraded"].glob("*.png"))

    assert len(clean) == exported["cases"] * expected_counts["types"]
    assert len(degraded) == (
        exported["cases"] * expected_counts["degraded_types"] * expected_counts["tiers"]
    )
    assert clean != degraded
    assert all(name.endswith(suffixes) for name in degraded)


def test_export_filenames_carry_no_layout_variant(exported):
    """A leaked layout name would let a model infer the template for free."""
    layouts = yaml.safe_load(Path("config/layouts/bank_statements.yml").read_text())
    names = " ".join(p.name for p in exported["clean"].glob("*.png"))
    for layout_id in layouts:
        assert layout_id not in names


@pytest.mark.parametrize("name", ["ground_truth.csv", "ground_truth.jsonl"])
def test_each_directory_carries_its_own_ground_truth(exported, name):
    """The degraded ground truth is written, not copied.

    It describes different rows entirely -- receipt variants rather than one
    document per type -- so a copy of the clean file would name images that do
    not exist in that directory.
    """
    clean = (exported["clean"] / name).read_bytes()
    degraded = (exported["degraded"] / name).read_bytes()
    assert clean != degraded
    assert degraded, f"{name} is empty in the degraded directory"


@pytest.mark.parametrize("half", ["clean", "degraded"])
def test_every_csv_image_file_exists_in_its_own_directory(exported, half):
    directory = exported[half]
    rows = (directory / "ground_truth.csv").read_text().splitlines()[1:]
    names = [row.split(",")[0] for row in rows]
    assert len(names) == len(list(directory.glob("*.png")))
    missing = [name for name in names if not (directory / name).exists()]
    assert not missing, f"CSV names {len(missing)} images absent from {directory}: {missing[:5]}"


# The clean and degraded sets no longer share a filename set, so a
# name-for-name pixel comparison no longer expresses anything. The stronger
# contract that replaced it — the degraded set is receipt variants only, one
# per tier, each carrying its source receipt's field values — is asserted in
# tests/test_eval_set_variants.py.


def test_jsonl_and_csv_agree_row_for_row(exported):
    """CSV is a transposition of the JSONL: same order, same values."""
    directory = exported["clean"]
    records = [
        json.loads(line)
        for line in (directory / "ground_truth.jsonl").read_text().splitlines()
        if line.strip()
    ]
    with (directory / "ground_truth.csv").open(newline="") as handle:
        rows = list(csv_module.DictReader(handle))
    assert len(records) == len(rows) == len(list(directory.glob("*.png")))
    for record, row in zip(records, rows, strict=True):
        assert row["image_file"] == record["filename"]
        for key, value in record.items():
            if key != "filename":
                assert row[key] == value


@pytest.mark.parametrize("half", ["synthetic", "degraded"])
def test_export_refuses_non_empty_dir_without_force(tmp_path, half):
    """Either target directory being occupied stops the export, not just the first."""
    stale = tmp_path / f"{half}_20260102"
    stale.mkdir()
    (stale / "stray.png").write_bytes(b"")
    with pytest.raises(ValueError) as exc_info:
        export_eval_set(_CONFIG, tmp_path, today=date(2026, 1, 2))
    assert str(stale) in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def _bank_only_config(tmp_path: Path) -> Path:
    """generation_config.yml narrowed to bank statements, for a cheap export."""
    data = yaml.safe_load(_CONFIG.read_text())
    data["eval_set"]["document_types"] = ["bank_statements"]
    path = tmp_path / "generation_config.yml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_export_force_overwrites_non_empty_dir(tmp_path):
    stale = tmp_path / "synthetic_20260102"
    stale.mkdir()
    (stale / "stray.png").write_bytes(b"")
    summary = export_eval_set(
        _bank_only_config(tmp_path),
        tmp_path,
        force=True,
        today=date(2026, 1, 2),
        renderers={"bank_statements": render_bank_statement},
    )
    assert summary["images"] == 55
    assert not (stale / "stray.png").exists(), "force must clear the previous set"
