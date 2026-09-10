"""Self-contained evaluation-set export, owned entirely by this repo.

`export_eval_set` produces two sibling directories under one output root::

    <out>/synthetic_<YYYYMMDD>/     <out>/degraded_<YYYYMMDD>/
      CASE001_invoice.png             CASE001_invoice_moderate.png
      CASE001_receipt.png             CASE001_invoice_heavy.png
                                      CASE001_receipt_moderate.png
                                      CASE001_receipt_heavy.png
      ...  110 images, 2 types        ...  220 images, 2 types x 2 tiers
      ground_truth.csv                ground_truth.csv     <- describes THESE rows
      ground_truth.jsonl              ground_truth.jsonl   <- describes THESE rows
      quality_ground_truth.jsonl      quality_ground_truth.jsonl

The two halves are NOT mirrors of each other, and the asymmetry is the whole
design. Four properties are load-bearing:

* **The degraded half holds one image per type per severity tier.** Which types
  are degraded is declared in ``eval_set.degrade_types:``; the tiers under
  ``document_degradation:`` in ``config/generation_config.yml`` fix how many
  variants each gets. So the degraded half is 110 documents at 2 severities,
  not 220 distinct documents.
* **A degraded filename carries its tier**: ``CASE001_receipt.png`` becomes
  ``CASE001_receipt_moderate.png``, taking the suffix from the tier's own
  ``suffix:`` key. Anything pairing the two halves must therefore join on the
  filename with that suffix removed, NOT on the filename itself.
* **Both halves carry a quality ground truth** alongside the extraction one.
  ``quality_ground_truth.jsonl`` records, per image, which defects it actually
  carries and the values drawn to produce them -- the labels the quality screen
  is scored against. The clean half's rows are all-false by construction, and
  are what measures the screen's false-positive rate.
* **Filenames are generic** -- ``CASE001_bank_statement.png``, never
  ``CASE001_cba_standard.png``. The layout variant must not leak, or a model
  could infer the template before reading a pixel. The type portion is the
  canonical document-type key from ``config/extraction_schema.yml``, so the
  schema is the single source of that name. Case ids stay unsuffixed so
  ``transaction_links.yml`` keeps resolving.
* **Each directory is self-contained**, carrying the ground truth for the
  images IT holds, so a model run points at one path and finds everything.
  The degraded ground truth is written rather than copied: each variant row
  repeats its source receipt's field values verbatim and differs only in
  ``image_file``, so a copy of the clean file would name images this
  directory does not contain. The two ground truths are consequently NOT
  byte-identical, and the degraded one carries only the receipt columns.

The schema projection this export needs -- which fields a document type is
scored on, in what order, and which are monetary or boolean -- comes from
`generators.exporters.eval_projection`, reading
``config/extraction_schema.yml``. Nothing here shells out to, or imports
from, another repository.

Record order is the CSV's column order: records are emitted sorted by
filename, so the first record is a bank statement and its five fields lead
the header, exactly as the pinned format requires. Nothing is sorted or
set-ified anywhere order is observable.
"""

import csv
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from generators.common import FitError
from generators.degradation import compose_clean, degrade_document, load_tiers, tier_seed
from generators.degradation.augment import apply_augraphy
from generators.degradation.camera import apply_photometrics, warp_to_photo
from generators.degradation.collage import ARRANGEMENTS, compose_collage, compose_folded
from generators.degradation.labels import defects_for, load_defect_labels
from generators.exporters.eval_projection import ExtractionSchema, load_extraction_schema
from generators.loader import load_ground_truth, load_layout_registry
from generators.overflow_check import build_overflow_error

NOT_FOUND = "NOT_FOUND"

# What a clean image records for jpeg_quality: no compression applied. Mirrors
# generators.degradation._NO_JPEG, which is private to that module.
_CLEAN_JPEG = 100

_ROOT_KEY = "eval_set"

# Which document types get degraded is declared in the YAML
# (`eval_set.degrade_types:`), not here. It was a constant (`_DEGRADED_TYPE =
# "receipt"`) until the quality screen needed invoices degraded too, at which
# point a Python constant meant the config could not answer "what gets
# degraded?" on its own.

# Required sub-keys of eval_set, mapped to the expected shape used in diagnostics.
_REQUIRED_KEYS: dict[str, str] = {
    "document_types": "a non-empty list of keys from the top-level document_types block",
    "degrade_types": "a non-empty list, a subset of document_types, naming the types to degrade",
    "clean_dir_prefix": "the clean output directory's name before the date stamp, e.g. 'synthetic'",
    "degraded_dir_prefix": "the degraded output directory's name before the date stamp, e.g. 'degraded'",
    "quality_dir_prefix": "the combined output directory's name before the date stamp, e.g. 'quality'",
    "csv_name": "the CSV filename to write into both directories, e.g. 'ground_truth.csv'",
    "jsonl_name": "the JSONL filename to write into both directories, e.g. 'ground_truth.jsonl'",
}

# Date stamp appended to both directory names. Not configurable: the format is
# part of the pinned export contract, not an operator choice.
_DATE_FORMAT = "%Y%m%d"

# Generator field name -> canonical extraction-schema field name (only where they
# differ). The generation contract (config/field_definitions.yml) and the
# extraction contract (config/extraction_schema.yml) name the same bank-statement
# column differently; this bridges them. Mirrors ``_FIELD_ALIASES`` in
# scripts/generate_extraction_gt.py.
FIELD_ALIASES: dict[str, str] = {
    "TRANSACTION_DESCRIPTIONS": "LINE_ITEM_DESCRIPTIONS",  # bank statements
}


def _err(what: str, *, path: Path, key_path: str, expected: str, recover: str) -> ValueError:
    """Build a four-element fail-fast diagnostic (what / where / expected / recover)."""
    return ValueError(
        f"{what}\n"
        f"  What:     {what}\n"
        f"  Where:    {path} -> '{key_path}'.\n"
        f"  Expected: {expected}\n"
        f"  Recover:  {recover} in {path}."
    )


def load_eval_set_config(config_path: Path) -> dict:
    """Load and validate the `eval_set` block of the generation config.

    Args:
        config_path: Path to generation_config.yml.

    Returns:
        The validated `eval_set` mapping, with `document_types` checked against
        the top-level `document_types` block.

    Raises:
        FileNotFoundError: `config_path` does not exist.
        ValueError: the block, a required key, or a document type is invalid.
    """
    if not config_path.exists():
        raise FileNotFoundError(
            "generation config not found.\n"
            f"  What:     {config_path} does not exist.\n"
            f"  Where:    {config_path}\n"
            f"  Expected: a YAML file with a top-level '{_ROOT_KEY}' mapping.\n"
            f"  Recover:  pass --config with the path to generation_config.yml."
        )

    data = yaml.safe_load(config_path.read_text())
    cfg = data.get(_ROOT_KEY) if isinstance(data, dict) else None
    if not isinstance(cfg, dict):
        raise _err(
            f"'{_ROOT_KEY}' block is missing or not a mapping in {config_path}.",
            path=config_path,
            key_path=_ROOT_KEY,
            expected="a mapping with keys " + ", ".join(_REQUIRED_KEYS) + ".",
            recover=f"add an '{_ROOT_KEY}:' block",
        )

    for key, expected in _REQUIRED_KEYS.items():
        if key not in cfg or not cfg[key]:
            raise _err(
                f"'{_ROOT_KEY}.{key}' is missing or empty.",
                path=config_path,
                key_path=f"{_ROOT_KEY}.{key}",
                expected=expected + ".",
                recover=f"set '{key}' under {_ROOT_KEY}",
            )

    known = data.get("document_types", {})
    for dtype in cfg["document_types"]:
        if dtype not in known:
            raise _err(
                f"eval_set document type '{dtype}' is not a configured document type.",
                path=config_path,
                key_path=f"{_ROOT_KEY}.document_types",
                expected=f"keys of the top-level document_types block: {sorted(known)}.",
                recover=f"remove '{dtype}' or add it to document_types",
            )

    _validate_collage(cfg, config_path)
    return cfg


_COLLAGE_KEYS = {
    "enabled": "true or false",
    "count": "how many multi-receipt plates to render, e.g. 90",
    "documents_per_image": "a [min, max] pair, e.g. [2, 5]",
    "arrangements": f"a list drawn from {list(ARRANGEMENTS)}",
    "overlap_fraction": "a [min, max] pair between 0.0 and 1.0, e.g. [0.0, 0.55]",
    "per_document_rotation_deg": "a [min, max] pair, e.g. [-18, 18]",
    "seed": "a fixed integer, so the plates regenerate identically, e.g. 20260910",
    "hard_negatives": "a mapping declaring at least folded_long_receipt",
}


def _validate_collage(cfg: dict, config_path: Path) -> None:
    """Validate `eval_set.collage`.

    Every key is required even when `enabled: false`, so that turning collages
    back on is a one-word change rather than an archaeology exercise, and so
    the YAML answers "what would this generate?" without being run.

    Args:
        cfg: The `eval_set` mapping.
        config_path: For diagnostics.

    Raises:
        ValueError: The block is missing, or a key is absent or unusable.
    """
    collage = cfg.get("collage")
    if not isinstance(collage, dict):
        raise _err(
            f"'{_ROOT_KEY}.collage' is missing or not a mapping.",
            path=config_path,
            key_path=f"{_ROOT_KEY}.collage",
            expected="a mapping with keys " + ", ".join(_COLLAGE_KEYS) + ".",
            recover=f"add a 'collage:' block under {_ROOT_KEY}, with 'enabled: false' to generate none",
        )

    for key, expected in _COLLAGE_KEYS.items():
        if key not in collage:
            raise _err(
                f"'{_ROOT_KEY}.collage.{key}' is missing.",
                path=config_path,
                key_path=f"{_ROOT_KEY}.collage.{key}",
                expected=expected + ".",
                recover=f"set '{key}' under {_ROOT_KEY}.collage",
            )

    unknown = sorted(set(collage["arrangements"]) - set(ARRANGEMENTS))
    if unknown:
        raise _err(
            f"'{_ROOT_KEY}.collage.arrangements' names layouts that do not exist: {unknown}.",
            path=config_path,
            key_path=f"{_ROOT_KEY}.collage.arrangements",
            expected=f"a list drawn from {list(ARRANGEMENTS)}.",
            recover="correct the names, or add the arrangement to generators/degradation/collage.py",
        )

    low, high = collage["documents_per_image"]
    if low < 2:
        raise _err(
            f"'{_ROOT_KEY}.collage.documents_per_image' starts at {low}, so some plates "
            f"would hold a single receipt and be labelled MULTIPLE.",
            path=config_path,
            key_path=f"{_ROOT_KEY}.collage.documents_per_image",
            expected="a minimum of 2 or more, e.g. [2, 5].",
            recover="raise the minimum to 2",
        )
    if high < low:
        raise _err(
            f"'{_ROOT_KEY}.collage.documents_per_image' is [{low}, {high}], which is empty.",
            path=config_path,
            key_path=f"{_ROOT_KEY}.collage.documents_per_image",
            expected="a [min, max] pair with max >= min, e.g. [2, 5].",
            recover="swap the bounds",
        )

    # How much one receipt may cover another. Capped because a taxpayer
    # photographing receipts is SUBSTANTIATING an expense: they lay them out so
    # the business name, date and total show. Past roughly a fifth, the receipt
    # underneath loses its total, and the corpus starts teaching from images no
    # taxpayer would submit.
    #
    # Checked here rather than left to judgement because the failure is
    # invisible downstream: an obscured plate still labels correctly as
    # MULTIPLE, still crosses the severity ladder, and still scores. Only
    # looking at it shows the total is gone.
    _OVERLAP_CEILING = 0.25
    if max(collage["overlap_fraction"]) > _OVERLAP_CEILING:
        raise _err(
            f"'{_ROOT_KEY}.collage.overlap_fraction' allows up to "
            f"{max(collage['overlap_fraction'])}, which buries the totals of the receipts "
            f"underneath.",
            path=config_path,
            key_path=f"{_ROOT_KEY}.collage.overlap_fraction",
            expected=f"a maximum of {_OVERLAP_CEILING} or less, e.g. [0.0, 0.18]. A taxpayer "
            f"photographing receipts lays them out so the amounts can be read.",
            recover="lower the upper bound",
        )

    if "folded_long_receipt" not in collage["hard_negatives"]:
        raise _err(
            f"'{_ROOT_KEY}.collage.hard_negatives' declares no folded_long_receipt.",
            path=config_path,
            key_path=f"{_ROOT_KEY}.collage.hard_negatives.folded_long_receipt",
            expected="a mapping with count, fold_position and fold_angle_deg.",
            recover="add folded_long_receipt -- without it every collage is an obvious "
            "MULTIPLE, the screen scores near 1.0 and the measurement means nothing",
        )


def format_value(field_name: str, raw: Any, schema: ExtractionSchema) -> str:
    """Format one generator value to the model-output convention.

    Multi-value fields are re-joined with `` | ``, monetary fields get a ``$``
    per item (``NOT_FOUND`` items untouched), booleans are lowercased.

    Args:
        field_name: The extraction-schema field name being formatted.
        raw: The ground-truth value, of whatever type the YAML produced.
        schema: The loaded extraction schema, for the monetary/boolean sets.

    Returns:
        The formatted value, or NOT_FOUND when `raw` is blank.
    """
    text = str(raw).strip()
    if not text:
        return NOT_FOUND

    items = [item.strip() for item in text.split("|")]

    if field_name in schema.monetary_fields:
        items = [it if it.upper() == NOT_FOUND or it.startswith("$") else f"${it}" for it in items]
    elif field_name in schema.boolean_fields:
        items = [it.lower() for it in items]

    return " | ".join(items)


def project_fields(
    case_id: str,
    raw_fields: dict,
    doc_type: str,
    schema: ExtractionSchema,
    source_path: Path,
) -> dict[str, str]:
    """Cut one entry's fields down to its document type's extraction fields.

    Applies :data:`FIELD_ALIASES`, emits the schema's field order, fills absent
    schema fields with NOT_FOUND, and formats every value.

    The document type is checked for membership here rather than relying on
    `get_extraction_fields`'s own raise, because this is the only place that
    knows the offending case id and the ground-truth file it came from --
    which is where an operator would actually fix it.

    Args:
        case_id: The ground-truth case id, named in the diagnostic.
        raw_fields: The entry's `fields` mapping, in generation-contract names.
        doc_type: The entry's DOCUMENT_TYPE value.
        schema: The loaded extraction schema.
        source_path: The ground-truth YAML the entry came from.

    Returns:
        Field name -> formatted value, in extraction-schema declaration order.

    Raises:
        ValueError: `doc_type` is not a document type the schema declares.
    """
    canonical = schema.resolve_doc_type(doc_type)
    known_types = schema.get_all_doc_type_fields()
    if canonical not in known_types:
        raise _err(
            f"{case_id} has DOCUMENT_TYPE '{doc_type}', which is not an extraction document type.",
            path=source_path,
            key_path=f"{case_id}.fields.DOCUMENT_TYPE",
            expected=f"one of: {sorted(known_types)} (or a name resolving to one).",
            recover=(
                f"correct DOCUMENT_TYPE for {case_id}, or add '{canonical}:' under "
                f"'document_fields:' in config/extraction_schema.yml"
            ),
        )

    aliased = {FIELD_ALIASES.get(name, name): value for name, value in raw_fields.items()}

    projected: dict[str, str] = {}
    for name in schema.get_extraction_fields(canonical):
        value = aliased.get(name)
        projected[name] = (
            format_value(name, value, schema) if value is not None and str(value).strip() else NOT_FOUND
        )
    # The extraction answer key is debit-only: the 5-field bank contract has no
    # TRANSACTION_AMOUNTS_RECEIVED, so credit rows have no home in it.
    #
    # It is also print-only: a value the document does not show cannot be an
    # extraction answer, which on receipts means the per-unit price.
    return _blank_unprinted_unit_prices(_drop_credit_rows(projected))


_PAID_COLUMN = "TRANSACTION_AMOUNTS_PAID"
_STATEMENT_TYPE = "BANK_STATEMENT"


def _drop_credit_rows(projected: dict[str, str]) -> dict[str, str]:
    """Drop credit rows from a projected bank statement's register columns.

    The canonical register in `ground_truth/bank_statements.yml` is the FULL
    table: index-aligned TRANSACTION_* columns where a credit row carries
    NOT_FOUND in the paid column. That stays untouched -- it is correct for the
    register, for `derive_native`, and for transaction linking.

    The extraction contract is narrower. `config/extraction_schema.yml` gives
    bank_statement five fields and no TRANSACTION_AMOUNTS_RECEIVED, so a credit
    amount has nowhere to go. Projecting the full register into that answer key
    leaves placeholder rows no model is asked to produce; a consumer scoring
    position-by-position then finds the two lists offset by the credit count and
    marks a correct extraction wrong.

    Rows are identified by NOT_FOUND in the paid column, and every register
    column of matching length is filtered with the same indices so the columns
    stay aligned. Detection is by shape rather than by field name because the
    projection renames TRANSACTION_DESCRIPTIONS to LINE_ITEM_DESCRIPTIONS; a
    bank record's only multi-member fields are the register columns.

    Returns a new dict in the original key order (the JSONL key order is the
    contract), or the input unchanged when filtering does not apply or would
    not be safe.
    """
    if projected.get("DOCUMENT_TYPE") != _STATEMENT_TYPE:
        return projected

    paid_raw = str(projected.get(_PAID_COLUMN, NOT_FOUND))
    if "|" not in paid_raw:
        return projected

    paid_items = [item.strip() for item in paid_raw.split("|")]
    keep = [i for i, value in enumerate(paid_items) if value.upper() != NOT_FOUND]

    # Nothing to drop, or every row is a credit. Emitting an empty register
    # would be a silently wrong answer key, so leave the record alone.
    if len(keep) == len(paid_items) or not keep:
        return projected

    result = dict(projected)
    for name, value in projected.items():
        text = str(value)
        if "|" not in text:
            continue
        items = [item.strip() for item in text.split("|")]
        if len(items) != len(paid_items):
            # Not an aligned register column -- filtering it by these indices
            # would drop the wrong entries. Leave it whole.
            continue
        separator = " | " if " | " in text else "|"
        result[name] = separator.join(items[i] for i in keep)
    return result


_RECEIPT_TYPE = "RECEIPT"
_UNIT_PRICE_COLUMN = "LINE_ITEM_PRICES"
_QUANTITY_COLUMN = "LINE_ITEM_QUANTITIES"


def _blank_unprinted_unit_prices(projected: dict[str, str]) -> dict[str, str]:
    """Blank a receipt's unit prices where the receipt does not print them.

    A receipt line carries ONE amount, and that amount is the line total::

        3x <item name>                          9.72

    The unit price (3.24) appears nowhere on the page -- the generator knows it
    because it composed the line, but no reader can extract it. Carrying the
    derived value in the answer key makes the field unscoreable in the honest
    sense: a model that reports exactly what is printed is marked wrong, and the
    only way to score well is to divide, which is arithmetic rather than
    extraction. Measured on a 55-receipt corpus, both models under test read the
    printed amount correctly and scored 0.20-0.46 on this field for it.

    Where the quantity is 1 the two coincide, so the printed amount IS the unit
    price and is kept. Everywhere else the position becomes NOT_FOUND.

    INVOICES ARE DELIBERATELY EXCLUDED. Their layout has an explicit ``Unit
    Price`` column, so the value is on the page and the answer key is correct as
    generated. This filter is keyed on DOCUMENT_TYPE for exactly that reason --
    it is a fact about the receipt template, not about the field name.

    Returns a new dict in the original key order, or the input unchanged when
    the rule does not apply.
    """
    if projected.get("DOCUMENT_TYPE") != _RECEIPT_TYPE:
        return projected

    prices_raw = str(projected.get(_UNIT_PRICE_COLUMN, NOT_FOUND))
    quantities_raw = str(projected.get(_QUANTITY_COLUMN, NOT_FOUND))
    if prices_raw.upper() == NOT_FOUND or quantities_raw.upper() == NOT_FOUND:
        return projected

    prices = [item.strip() for item in prices_raw.split("|")]
    quantities = [item.strip() for item in quantities_raw.split("|")]
    if len(prices) != len(quantities):
        # Not an aligned pair -- deciding per position would be guesswork, and
        # guessing in an answer key is worse than leaving it as generated.
        return projected

    kept = []
    for price, quantity in zip(prices, quantities):
        try:
            shown = float(quantity) == 1.0
        except ValueError:
            # A quantity that is not a number: cannot establish that the unit
            # price is unprinted, so leave the value alone.
            shown = True
        kept.append(price if shown else NOT_FOUND)

    if all(value == NOT_FOUND for value in kept):
        result = dict(projected)
        result[_UNIT_PRICE_COLUMN] = NOT_FOUND
        return result

    separator = " | " if " | " in prices_raw else "|"
    result = dict(projected)
    result[_UNIT_PRICE_COLUMN] = separator.join(kept)
    return result


def write_jsonl(documents: list[dict], jsonl_path: Path) -> Path:
    """Write the projected ground truth as one JSON object per line.

    Each record is `filename` followed by the document type's extraction
    fields in schema order -- the key order is the contract, so the fields
    dict is spread as built and never re-sorted.

    Args:
        documents: `{"filename": str, "fields": dict}` records, in output order.
        jsonl_path: Where to write the JSONL.

    Returns:
        The written path.
    """
    lines = [
        json.dumps({"filename": doc["filename"], **doc["fields"]}, ensure_ascii=False) for doc in documents
    ]
    jsonl_path.write_text("\n".join(lines) + "\n")
    return jsonl_path


def csv_from_jsonl(jsonl_path: Path, csv_path: Path) -> Path:
    """Transpose the projected JSONL ground truth into a CSV.

    Columns are the union of every record's keys, in first-seen order, with the
    JSONL's `filename` renamed to `image_file` to match this repo's convention.
    A field absent from a record is filled with NOT_FOUND, never left blank.

    Args:
        jsonl_path: The projected ground_truth.jsonl.
        csv_path: Where to write the CSV.

    Returns:
        The written path.
    """
    records = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]

    columns: list[str] = []
    for record in records:
        for key in record:
            if key != "filename" and key not in columns:
                columns.append(key)

    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["image_file", *columns])
        writer.writeheader()
        for record in records:
            row = {"image_file": record["filename"]}
            for col in columns:
                row[col] = record.get(col, NOT_FOUND)
            writer.writerow(row)
    return csv_path


def _quality_record(filename: str, doc_type: str, provenance: dict, rules: dict) -> dict:
    """Build one image's quality-screen ground-truth record.

    Args:
        filename: The image's name within its directory.
        doc_type: The resolved extraction document type, e.g. "receipt".
        provenance: What the generator drew for this image.
        rules: Validated defect rules from `load_defect_labels`.

    Returns:
        A record carrying the condition, the per-defect booleans the screen is
        scored against, and the raw drawn values behind them. The raw values are
        kept so a disputed label can be checked, and so a threshold can be moved
        and the labels recomputed without re-rendering 330 images.
    """
    return {
        "filename": filename,
        "document_type": doc_type,
        "condition": provenance["tier"],
        # How many documents are in the picture, on its own axis.
        #
        # SEPARATE from `defects` and from `condition`, because it answers a
        # different question with a different remedy: a photograph of four
        # receipts is often sharp, evenly lit and undamaged -- nothing is wrong
        # with the picture -- and the fix is to split it, not to re-take it.
        # Folding it into the defect rules would be the same conflation the
        # screen's prompt already refuses.
        #
        # Written on EVERY record, including single-document ones, and never by
        # omission. An absent key means "this corpus predates the label", which
        # is what makes the screen's scorer report NOT SCORED instead of a
        # number; a corpus that has been labelled must say SINGLE out loud.
        "composition": "MULTIPLE" if provenance.get("document_count", 1) > 1 else "SINGLE",
        "defects": defects_for(provenance, rules),
        "params": {key: value for key, value in provenance.items() if key not in ("tier", "augmentations")},
        "augmentations": provenance["augmentations"],
    }


def write_quality_jsonl(records: list[dict], path: Path) -> Path:
    """Write the quality-screen ground truth for one directory.

    Args:
        records: Records from `_quality_record`, already sorted by filename.
        path: Where to write the JSONL.

    Returns:
        The path written.
    """
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n")
    return path


def _flat_receipt_pages(config_path: Path, renderers: dict) -> list:
    """Render the receipts a collage draws from, flat and undamaged.

    FLAT is the requirement, and the reason this exists rather than reusing the
    images `_render_documents` has already written. Those have been through
    `compose_clean`, which composites each page onto a desk background -- build
    a plate from them and every receipt arrives carrying its own coloured
    rectangle, desk upon desk. It is glaring in a render and invisible in the
    provenance, which is exactly the kind of mistake this corpus cannot afford.

    Re-rendering costs a few seconds against a build measured in minutes, and
    buys a function that cannot be handed the wrong images.

    Args:
        config_path: Path to generation_config.yml.
        renderers: Document type -> renderer callable.

    Returns:
        Flat receipt renders, in ground-truth order.

    Raises:
        ValueError: The receipts type declares no renderer.
    """
    data = yaml.safe_load(config_path.read_text())
    doc_cfg = data["document_types"]["receipts"]
    renderer = renderers.get("receipts")
    if renderer is None:
        raise _err(
            "no renderer is registered for 'receipts', which collages are built from.",
            path=config_path,
            key_path="document_types.receipts",
            expected=f"a type with a renderer: {sorted(renderers)}.",
            recover="register a receipts renderer, or set eval_set.collage.enabled: false",
        )

    gt_data = load_ground_truth(Path(doc_cfg["ground_truth"]))
    layouts = load_layout_registry(Path(doc_cfg["layouts"]))

    pages = []
    for case_id, entry in gt_data.items():
        layout = layouts.get(entry.get("layout", ""), {})
        if not layout:
            continue
        entry["case_id"] = str(case_id)
        pages.append(renderer(entry, layout))
    return pages


def _render_collages(
    flat_pages: list,
    collage_cfg: dict,
    tiers: list,
    clean_warp: dict,
    rules: dict,
    out_dir: Path,
    seed: int,
) -> list[dict]:
    """Render the multi-receipt plates and the folded hard negatives.

    Quality records only. A collage has no meaningful extraction answer -- three
    receipts carry three sets of fields, and the whole point of the image is
    that extraction cannot process it -- so emitting one would put rows in the
    ground truth that nothing can ever score.

    Args:
        flat_pages: Rendered receipts, BEFORE compose_clean. This matters: the
            clean corpus images already sit on a desk background, and building
            a plate from those gives every receipt its own coloured rectangle,
            desk on desk. It is obvious in a render and invisible in the
            provenance.
        collage_cfg: The validated `eval_set.collage` block.
        tiers: Receipt severity tiers, so composition is crossed with quality
            rather than correlated with it. A corpus where every collage is
            clean lets the screen score well by reading "no defects" as
            "several documents".
        clean_warp: The clean camera settings, for plates drawn at the clean
            rung.
        rules: Validated defect rules, for `_quality_record`.
        out_dir: Where to write the images.
        seed: Base seed. Every plate derives from it, so the set regenerates
            identically and a disputed label can be re-examined.

    Returns:
        Quality records, sorted by filename.
    """
    if not collage_cfg.get("enabled"):
        return []

    rng = np.random.default_rng(seed)
    records: list[dict] = []
    low, high = collage_cfg["documents_per_image"]
    arrangements = list(collage_cfg["arrangements"])
    overlap_lo, overlap_hi = collage_cfg["overlap_fraction"]
    rotation = tuple(collage_cfg["per_document_rotation_deg"])
    # Clean plus every declared tier, cycled, so the three conditions come out
    # even without a second config knob to keep in step with the ladder.
    rungs = [None, *tiers]

    for index in range(int(collage_cfg["count"])):
        count = int(rng.integers(low, high + 1))
        pages = [flat_pages[int(rng.integers(0, len(flat_pages)))] for _ in range(count)]
        arrangement = arrangements[index % len(arrangements)]
        overlap = float(rng.uniform(overlap_lo, overlap_hi))

        rung = rungs[index % len(rungs)]

        def layout(ready, _a=arrangement, _o=overlap):
            return compose_collage(
                ready, arrangement=_a, overlap_fraction=_o, rotation_deg=rotation, rng=rng
            )

        frame, provenance = _photograph_plate(pages, layout, rung, clean_warp, seed + index)
        stem = f"COLLAGE{index + 1:03d}_receipts"
        filename = f"{stem}.png" if rung is None else f"{stem}_{rung.suffix}.png"
        frame.save(out_dir / filename)
        records.append(_quality_record(filename, "receipt", provenance, rules))

    folded_cfg = collage_cfg["hard_negatives"]["folded_long_receipt"]
    # The longest receipts, because a fold only reads as a second document when
    # there is enough paper either side of the crease.
    longest = sorted(flat_pages, key=lambda page: page.height, reverse=True)
    position_lo, position_hi = folded_cfg["fold_position"]
    angle_lo, angle_hi = folded_cfg["fold_angle_deg"]

    for index in range(int(folded_cfg["count"])):
        page = longest[index % max(1, len(longest) // 3)]
        rung = rungs[index % len(rungs)]
        position = float(rng.uniform(position_lo, position_hi))
        angle = float(rng.uniform(angle_lo, angle_hi))

        def layout(ready, _p=position, _a=angle):
            return compose_folded(ready[0], fold_position=_p, fold_angle_deg=_a, rng=rng)

        frame, provenance = _photograph_plate([page], layout, rung, clean_warp, seed + 1000 + index)
        stem = f"FOLDED{index + 1:03d}_receipt"
        filename = f"{stem}.png" if rung is None else f"{stem}_{rung.suffix}.png"
        frame.save(out_dir / filename)
        records.append(_quality_record(filename, "receipt", provenance, rules))

    records.sort(key=lambda record: record["filename"])
    return records


def _photograph_plate(pages: list, layout, tier, clean_warp: dict, seed: int) -> tuple:
    """Damage the paper, lay it out, then photograph it once.

    A collage CANNOT go through `degrade_document`, and the reason is worth
    stating because it is a physical distinction rather than a plumbing one.

    `degrade_document` runs augraphy on a flat page and then photographs it,
    which is right for one document. For a plate it is wrong twice over.
    Augraphy works on opaque RGB, so it would flatten the transparency the
    layout depends on and hand back a collage on a black rectangle. And it
    would apply one ink/paper condition to a canvas holding several separate
    receipts.

    Ink and paper damage -- fading, bleed, low ink -- belongs to EACH RECEIPT.
    Every receipt on a table has its own history. Blur, noise and jpeg
    artefacts belong to the PHOTOGRAPH: one camera, one exposure, one blur
    across everything in frame. So the augmentation runs per page, before the
    layout, and the photometrics run once, after it.

    Args:
        pages: Flat rendered receipts, before any degradation.
        layout: Callable taking the (possibly damaged) pages and returning
            `(plate, provenance)` -- `compose_collage` or `compose_folded`,
            already bound to their arguments.
        tier: Severity tier, or None for the clean rung.
        clean_warp: Clean camera settings, used when *tier* is None.
        seed: Seed for this image.

    Returns:
        `(frame, provenance)`, the provenance carrying the same keys a single
        document's does plus the layout's, so one code path can label both.
    """
    rng = np.random.default_rng(seed)

    if tier is None:
        plate, layout_provenance = layout(pages)
        frame, warp_provenance = warp_to_photo(plate, clean_warp, rng)
        provenance = {
            "tier": "clean",
            "augmentations": [],
            **warp_provenance,
            "blur_sigma": 0.0,
            "noise_sigma": 0.0,
            "jpeg_quality": _CLEAN_JPEG,
            **layout_provenance,
        }
        provenance["rotation_deg"] = _effective_rotation(provenance)
        return frame, provenance

    damaged = [apply_augraphy(page, tier, seed + offset) for offset, page in enumerate(pages)]
    plate, layout_provenance = layout(damaged)
    warped, warp_provenance = warp_to_photo(plate, tier.warp, rng)
    frame, camera_provenance = apply_photometrics(warped, tier.camera, rng)
    provenance = {
        "tier": tier.name,
        "augmentations": [spec["augmentation"] for spec in (*tier.ink, *tier.paper)],
        **warp_provenance,
        **camera_provenance,
        **layout_provenance,
    }
    provenance["rotation_deg"] = _effective_rotation(provenance)
    return frame, provenance


def _effective_rotation(provenance: dict) -> float:
    """The rotation a viewer would actually judge TILT by.

    The tilt label is `rotation_deg_abs at_least 5.0`, taken from the whole
    page's rotation. For a single document that is the whole story. For a plate
    it is not: the layout turns each receipt independently, so a plate sitting
    square with its receipts at 15 degrees records `rotation_deg` near zero and
    is labelled tilt-free, while every receipt in it is visibly crooked.

    A wrong label is wrong whatever it is later used for, so the recorded
    rotation is the largest angle any single receipt ends up at -- plate
    rotation plus its own -- which is what the question "is the paper
    noticeably turned or crooked in the picture?" is actually asking about.

    Args:
        provenance: The merged warp, camera and layout provenance.

    Returns:
        The signed angle of the most-turned receipt, or the plate's own
        rotation when there are no placements to consider.
    """
    plate_rotation = float(provenance.get("rotation_deg", 0.0))
    placements = provenance.get("placements") or []
    if not placements:
        return plate_rotation

    angles = [plate_rotation + float(p.get("rotation_deg", 0.0)) for p in placements]
    return max(angles, key=abs)


def _prepare_dir(out_dir: Path, *, force: bool) -> None:
    """Create `out_dir`, refusing to write into a non-empty one unless forced."""
    if out_dir.exists() and any(out_dir.iterdir()):
        if not force:
            raise _err(
                f"output directory {out_dir} already exists and is not empty.",
                path=out_dir,
                key_path="--out",
                expected="an empty or non-existent directory, so an existing evaluation "
                "set a benchmark run points at is never overwritten.",
                recover="pass --force to replace it, or choose another --out",
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def _render_documents(
    config_path: Path,
    eval_cfg: dict,
    schema: ExtractionSchema,
    clean_dir: Path,
    degraded_dir: Path,
    renderers: dict,
) -> tuple[list[dict], list[dict]]:
    """Render the clean set once, and a tiered degraded set for the chosen types.

    Which types are degraded comes from `eval_set.degrade_types:`; each such
    document is degraded once per declared severity tier. Every variant's
    ground-truth record carries field values identical to its source document,
    differing only in `image_file`, which is the value-F1 contract: distortion
    never changes the answer.

    Clean copies are composited onto the same desk background the degraded ones
    use, undamaged and square-on, so that background cannot by itself separate
    clean from degraded.

    Args:
        config_path: Path to generation_config.yml, for the document-type,
            degradation-tier and defect-label blocks.
        eval_cfg: The validated `eval_set` block.
        schema: The loaded extraction schema.
        clean_dir: Directory to save clean images into.
        degraded_dir: Directory to save degraded variants into.
        renderers: Document type -> renderer callable.

    Returns:
        `(clean_documents, degraded_documents, clean_quality, degraded_quality)`.
        The first two are `{"filename": str, "fields": dict}` extraction records;
        the last two are quality-screen records from `_quality_record`. All four
        are sorted by filename. The clean and degraded lists differ in both
        length and content.

    Raises:
        ValueError: any missing renderer, layout, seed, document type, or
            duplicate output filename.
        TierConfigError: the document_degradation block is missing or malformed.
        DefectLabelError: the defect_labels block is missing or malformed.
    """
    tiers_by_type = load_tiers(config_path)
    rules, _quality_filename = load_defect_labels(config_path)

    # Kept despite the degradation params moving out: the loop below reads
    # `doc_cfg = data["document_types"][dtype]` from this same load.
    data = yaml.safe_load(config_path.read_text())
    clean_warp = data["document_degradation"]["clean_camera"]["warp"]
    degrade_types = eval_cfg["degrade_types"]

    documents: list[dict] = []
    degraded_documents: list[dict] = []
    clean_quality: list[dict] = []
    degraded_quality: list[dict] = []
    seen: dict[str, str] = {}

    for dtype in eval_cfg["document_types"]:
        doc_cfg = data["document_types"][dtype]
        renderer = renderers.get(dtype)
        if renderer is None:
            raise _err(
                f"no renderer is registered for document type '{dtype}'.",
                path=config_path,
                key_path=f"{_ROOT_KEY}.document_types",
                expected=f"a type with a renderer: {sorted(renderers)}.",
                recover=f"remove '{dtype}' from {_ROOT_KEY}.document_types",
            )

        gt_path = Path(doc_cfg["ground_truth"])
        gt_data = load_ground_truth(gt_path)
        layouts = load_layout_registry(Path(doc_cfg["layouts"]))

        for case_id, entry in gt_data.items():
            layout_ref = entry.get("layout", "")
            layout = layouts.get(layout_ref, {})
            if not layout:
                raise _err(
                    f"{case_id} references layout '{layout_ref}', which is not in the registry.",
                    path=Path(doc_cfg["layouts"]),
                    key_path=f"layouts.{layout_ref}",
                    expected="every ground-truth entry's layout to exist in its layout registry.",
                    recover=f"add '{layout_ref}' to the registry or fix {case_id}'s layout",
                )

            fields = entry.get("fields", {}) or {}
            doc_type = fields.get("DOCUMENT_TYPE", "")
            resolved_type = schema.resolve_doc_type(str(doc_type))
            projected = project_fields(str(case_id), fields, str(doc_type), schema, gt_path)
            filename = f"{case_id}_{resolved_type}.png"

            if filename in seen:
                raise _err(
                    f"two documents would both be exported as '{filename}' "
                    f"({seen[filename]} and {case_id} / {layout_ref}).",
                    path=gt_path,
                    key_path=f"{case_id}.fields.DOCUMENT_TYPE",
                    expected="exactly one document per case per extraction document type.",
                    recover=f"remove or re-type the duplicate entry for {case_id}",
                )
            seen[filename] = f"{case_id} / {layout_ref}"

            seed = entry.get("degradation_seed")
            if not isinstance(seed, int):
                raise _err(
                    f"{case_id} has no integer 'degradation_seed', so its degraded image "
                    f"would not be reproducible.",
                    path=gt_path,
                    key_path=f"{case_id}.degradation_seed",
                    expected="an integer, e.g. 'degradation_seed: 9821'.",
                    recover=f"add a 'degradation_seed:' to {case_id}",
                )

            entry["case_id"] = str(case_id)
            try:
                img = renderer(entry, layout)
            except FitError as exc:
                raise build_overflow_error(
                    [f"{case_id} / {layout_ref}: {str(exc).splitlines()[0]}"]
                ) from None

            # The clean copy is composited onto the same desk background the
            # degraded ones use, square-on and undamaged. See `clean_camera:`
            # in the config: a bare white page against page-on-a-desk lets a
            # model split clean from degraded on background alone.
            clean_frame, clean_provenance = compose_clean(img, clean_warp, seed)
            clean_frame.save(clean_dir / filename)
            documents.append({"filename": filename, "fields": projected})
            clean_quality.append(_quality_record(filename, resolved_type, clean_provenance, rules))

            if dtype not in degrade_types:
                continue

            if dtype not in tiers_by_type:
                raise _err(
                    f"'{dtype}' is listed in degrade_types but declares no severity tiers, so "
                    f"it would be exported clean-only while the config says it is degraded.",
                    path=config_path,
                    key_path=f"document_degradation.tiers.{dtype}",
                    expected=f"a tier list for every type in {_ROOT_KEY}.degrade_types. "
                    f"Types with tiers: {sorted(tiers_by_type)}.",
                    recover=f"add a '{dtype}:' tier list under document_degradation.tiers, or "
                    f"remove '{dtype}' from {_ROOT_KEY}.degrade_types",
                )

            for index, tier in enumerate(tiers_by_type[dtype]):
                variant_name = f"{case_id}_{resolved_type}_{tier.suffix}.png"
                frame, provenance = degrade_document(img, tier, tier_seed(seed, index))
                frame.save(degraded_dir / variant_name)
                degraded_documents.append({"filename": variant_name, "fields": projected})
                degraded_quality.append(_quality_record(variant_name, resolved_type, provenance, rules))

    documents.sort(key=lambda doc: doc["filename"])
    degraded_documents.sort(key=lambda doc: doc["filename"])
    clean_quality.sort(key=lambda rec: rec["filename"])
    degraded_quality.sort(key=lambda rec: rec["filename"])
    return documents, degraded_documents, clean_quality, degraded_quality


def export_eval_set(
    config_path: Path,
    out_dir: Path,
    *,
    force: bool = False,
    renderers: dict | None = None,
    today: date | None = None,
) -> dict:
    """Export a clean and a degraded evaluation set as sibling directories.

    The two are no longer parallel. The clean directory holds every document
    type once; the degraded directory holds one image per degraded type per
    declared severity tier, because receipts are the only type users
    photograph. Each therefore carries its own ground truth.

    Args:
        config_path: Path to generation_config.yml.
        out_dir: Parent directory the two dated directories are created under.
        force: Replace either target directory if it exists and is non-empty.
        renderers: Document type -> renderer callable; defaults to the
            pipeline's registry. Injectable so tests can render a subset.
        today: Date to stamp the directory names with; defaults to today.

    Returns:
        Summary dict with `images` (clean), `degraded_images` (receipt
        variants), `clean_dir`, `degraded_dir`, `csv` and `jsonl` -- the latter
        two naming the clean directory's copies.

    Raises:
        ValueError: any configuration, directory, layout or projection failure.
        FileNotFoundError: the generation config or a ground-truth file is missing.
        TierConfigError: the document_degradation block is missing or malformed.
    """
    eval_cfg = load_eval_set_config(config_path)
    schema = load_extraction_schema()

    if renderers is None:
        from generators.pipeline import _RENDERERS

        renderers = _RENDERERS

    stamp = (today or date.today()).strftime(_DATE_FORMAT)
    clean_dir = out_dir / f"{eval_cfg['clean_dir_prefix']}_{stamp}"
    degraded_dir = out_dir / f"{eval_cfg['degraded_dir_prefix']}_{stamp}"
    quality_dir = out_dir / f"{eval_cfg['quality_dir_prefix']}_{stamp}"

    # Every directory is cleared before anything is rendered, so a refusal
    # never leaves half an export behind.
    _prepare_dir(clean_dir, force=force)
    _prepare_dir(degraded_dir, force=force)
    _prepare_dir(quality_dir, force=force)

    documents, degraded_documents, clean_quality, degraded_quality = _render_documents(
        config_path, eval_cfg, schema, clean_dir, degraded_dir, renderers
    )

    jsonl_path = write_jsonl(documents, clean_dir / eval_cfg["jsonl_name"])
    csv_path = csv_from_jsonl(jsonl_path, clean_dir / eval_cfg["csv_name"])

    # Written, not copied: the degraded set holds different rows entirely
    # (one variant per tier), so it needs its own ground truth rather than a
    # copy of the clean one.
    degraded_jsonl = write_jsonl(degraded_documents, degraded_dir / eval_cfg["jsonl_name"])
    csv_from_jsonl(degraded_jsonl, degraded_dir / eval_cfg["csv_name"])

    # The quality-screen ground truth is separate from the extraction ground
    # truth because it answers a different question: extraction GT says what
    # the document reads, this says what condition the image is in. Both
    # directories get one, so each stays self-contained.
    _, quality_filename = load_defect_labels(config_path)
    quality_path = write_quality_jsonl(clean_quality, clean_dir / quality_filename)
    write_quality_jsonl(degraded_quality, degraded_dir / quality_filename)

    # The combined half: every image and one ground truth, for consumers that
    # take a single directory. Real copies rather than links, so the set stays
    # self-contained if either source directory is moved or deleted.
    combined_documents = sorted(documents + degraded_documents, key=lambda d: d["filename"])
    combined_quality = sorted(clean_quality + degraded_quality, key=lambda r: r["filename"])
    for source in (clean_dir, degraded_dir):
        for image in source.glob("*.png"):
            shutil.copy2(image, quality_dir / image.name)

    # Multi-receipt photographs, into the combined directory only.
    #
    # They belong HERE and not in the clean or degraded halves because those
    # two are paired with an extraction ground truth, and a collage has no
    # extraction answer: three receipts carry three sets of fields, and the
    # point of the image is that extraction cannot read it. So the combined
    # directory gains images its extraction CSV does not describe -- deliberate,
    # and the reason the quality ground truth is a separate file rather than a
    # column on the extraction one.
    #
    # Note this changes the combined set's denominator. Figures measured on the
    # 330-image corpus are not comparable to figures measured on this one; the
    # first run against it is a new baseline, not a continuation.
    collage_cfg = eval_cfg["collage"]
    collage_quality: list[dict] = []
    # Receipts must actually be in this export. A narrowed run -- bank
    # statements only, say -- has no receipt renderer, and building plates from
    # a type the export does not include would fail on a document nobody asked
    # for. Skipped rather than raised: not exporting receipts is a legitimate
    # request, and refusing it would make `collage.enabled` a global switch
    # instead of a property of receipt exports.
    if collage_cfg.get("enabled") and "receipts" in eval_cfg["document_types"]:
        rules, _ = load_defect_labels(config_path)
        raw = yaml.safe_load(config_path.read_text())
        collage_quality = _render_collages(
            _flat_receipt_pages(config_path, renderers),
            collage_cfg,
            load_tiers(config_path)["receipts"],
            raw["document_degradation"]["clean_camera"]["warp"],
            rules,
            quality_dir,
            seed=int(collage_cfg["seed"]),
        )
        combined_quality = sorted(combined_quality + collage_quality, key=lambda r: r["filename"])

    combined_jsonl = write_jsonl(combined_documents, quality_dir / eval_cfg["jsonl_name"])
    csv_from_jsonl(combined_jsonl, quality_dir / eval_cfg["csv_name"])
    write_quality_jsonl(combined_quality, quality_dir / quality_filename)

    return {
        "images": len(documents),
        "degraded_images": len(degraded_documents),
        "collage_images": len(collage_quality),
        "combined_images": len(combined_documents) + len(collage_quality),
        "clean_dir": str(clean_dir),
        "degraded_dir": str(degraded_dir),
        "quality_dir": str(quality_dir),
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
        "quality_jsonl": str(quality_path),
    }
