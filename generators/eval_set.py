"""Self-contained evaluation-set export, owned entirely by this repo.

`export_eval_set` produces two sibling directories under one output root::

    <out>/synthetic_<YYYYMMDD>/     <out>/degraded_<YYYYMMDD>/
      CASE001_bank_statement.png      CASE001_bank_statement.png
      CASE001_invoice.png             CASE001_invoice.png
      ...  165 images                 ...  165 images
      ground_truth.csv                ground_truth.csv     <- byte-identical copy
      ground_truth.jsonl              ground_truth.jsonl   <- byte-identical copy

Three properties are load-bearing, and each is a deliberate decision rather
than an accident of implementation:

* **Filenames are identical across both directories.** A degraded image
  carries the same ground truth as its clean counterpart, so one ground
  truth scores both and a clean-vs-degraded comparison isolates image
  quality as the only variable.
* **Filenames are generic** -- ``CASE001_bank_statement.png``, never
  ``CASE001_cba_standard.png``. The layout variant must not leak, or a model
  could infer the template before reading a pixel. The suffix is the
  canonical document-type key from ``config/extraction_schema.yml``, so the
  schema is the single source of that name.
* **Each directory is self-contained**, carrying its own copy of both
  ground-truth files, so a model run points at one path and finds
  everything. The degraded copies are produced with ``shutil.copy2`` from
  the files written into the clean directory, which is what makes them
  byte-identical rather than merely equivalent.

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

import yaml

from generators.common import FitError, degrade_image
from generators.exporters.eval_projection import ExtractionSchema, load_extraction_schema
from generators.loader import load_ground_truth, load_layout_registry
from generators.overflow_check import build_overflow_error

NOT_FOUND = "NOT_FOUND"

_ROOT_KEY = "eval_set"

# Required sub-keys of eval_set, mapped to the expected shape used in diagnostics.
_REQUIRED_KEYS: dict[str, str] = {
    "document_types": "a non-empty list of keys from the top-level document_types block",
    "clean_dir_prefix": "the clean output directory's name before the date stamp, e.g. 'synthetic'",
    "degraded_dir_prefix": "the degraded output directory's name before the date stamp, e.g. 'degraded'",
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

    return cfg


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
    return projected


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
) -> list[dict]:
    """Render every document once, saving a clean and a degraded copy of each.

    Both copies are written under the same generic ``{case}_{doc_type}.png``
    name, in their respective directories, from a single render -- which is
    what makes the two filename sets identical by construction rather than by
    a later reconciliation step.

    Args:
        config_path: Path to generation_config.yml, for the degradation params.
        eval_cfg: The validated `eval_set` block.
        schema: The loaded extraction schema.
        clean_dir: Directory to save clean images into.
        degraded_dir: Directory to save degraded images into.
        renderers: Document type -> renderer callable.

    Returns:
        `{"filename": str, "fields": dict}` records sorted by filename.

    Raises:
        ValueError: any missing renderer, layout, seed, document type, or
            duplicate output filename.
    """
    data = yaml.safe_load(config_path.read_text())
    degradation_params = data.get("degradation")
    if not isinstance(degradation_params, dict) or not degradation_params:
        raise _err(
            "the top-level 'degradation' block is missing or empty, so the degraded "
            "half of the evaluation set cannot be produced.",
            path=config_path,
            key_path="degradation",
            expected="a mapping of parameter name to [min, max], e.g. "
            "'degradation:\\n  blur_radius: [0.3, 0.8]'.",
            recover="restore the 'degradation:' block",
        )

    documents: list[dict] = []
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
            projected = project_fields(str(case_id), fields, str(doc_type), schema, gt_path)
            filename = f"{case_id}_{schema.resolve_doc_type(str(doc_type))}.png"

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

            img.save(clean_dir / filename)
            degrade_image(img, seed=seed, params=degradation_params).save(degraded_dir / filename)

            documents.append({"filename": filename, "fields": projected})

    documents.sort(key=lambda doc: doc["filename"])
    return documents


def export_eval_set(
    config_path: Path,
    out_dir: Path,
    *,
    force: bool = False,
    renderers: dict | None = None,
    today: date | None = None,
) -> dict:
    """Export a clean and a degraded evaluation set as sibling directories.

    Args:
        config_path: Path to generation_config.yml.
        out_dir: Parent directory the two dated directories are created under.
        force: Replace either target directory if it exists and is non-empty.
        renderers: Document type -> renderer callable; defaults to the
            pipeline's registry. Injectable so tests can render a subset.
        today: Date to stamp the directory names with; defaults to today.

    Returns:
        Summary dict with `images`, `clean_dir`, `degraded_dir`, `csv` and
        `jsonl` -- the latter two naming the copies in the clean directory,
        which the degraded directory's are byte-identical copies of.

    Raises:
        ValueError: any configuration, directory, layout or projection failure.
        FileNotFoundError: the generation config or a ground-truth file is missing.
    """
    eval_cfg = load_eval_set_config(config_path)
    schema = load_extraction_schema()

    if renderers is None:
        from generators.pipeline import _RENDERERS

        renderers = _RENDERERS

    stamp = (today or date.today()).strftime(_DATE_FORMAT)
    clean_dir = out_dir / f"{eval_cfg['clean_dir_prefix']}_{stamp}"
    degraded_dir = out_dir / f"{eval_cfg['degraded_dir_prefix']}_{stamp}"

    # Both directories are cleared before anything is rendered, so a refusal
    # never leaves half an export behind.
    _prepare_dir(clean_dir, force=force)
    _prepare_dir(degraded_dir, force=force)

    documents = _render_documents(config_path, eval_cfg, schema, clean_dir, degraded_dir, renderers)

    jsonl_path = write_jsonl(documents, clean_dir / eval_cfg["jsonl_name"])
    csv_path = csv_from_jsonl(jsonl_path, clean_dir / eval_cfg["csv_name"])

    # Copied, not re-derived: a copy is byte-identical by construction, whereas
    # two independent writes could drift without anything noticing.
    for source in (jsonl_path, csv_path):
        shutil.copy2(source, degraded_dir / source.name)

    return {
        "images": len(documents),
        "clean_dir": str(clean_dir),
        "degraded_dir": str(degraded_dir),
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
    }
