"""Flat evaluation-set export for the LMM_POC extraction pipeline.

Renders one clean image per document for the configured document types into a
single directory, writes the raw ``synthetic.yml`` describing them (duplicate
``CASE###`` keys, one block per document), then hands the directory to
LMM_POC's ``relabel_evaluation_set.py``. That script owns schema projection —
nothing here duplicates it — and renames each image to ``{case}_{suffix}.png``,
emitting the projected ``synthetic.yml``, ``ground_truth.jsonl`` and
``relabel_mapping.csv``. The final ``ground_truth.csv`` is a transposition of
that JSONL, so CSV, JSONL and YAML always carry identical fields.
"""

import csv
import json
import shutil
import subprocess
from pathlib import Path

import yaml

from generators.common import FitError
from generators.loader import load_ground_truth, load_layout_registry
from generators.overflow_check import build_overflow_error

NOT_FOUND = "NOT_FOUND"

_ROOT_KEY = "eval_set"

# Required sub-keys of eval_set, mapped to the expected shape used in diagnostics.
_REQUIRED_KEYS: dict[str, str] = {
    "document_types": "a non-empty list of keys from the top-level document_types block",
    "relabel_script": "an absolute path to LMM_POC's scripts/relabel_evaluation_set.py",
    "relabel_repo_root": "an absolute path to the LMM_POC repo root (its import root)",
    "csv_name": "the CSV filename to write, e.g. 'ground_truth.csv'",
}

# Generator metadata that must not reach the exported set: the relabel script
# reads `layout` and `fields` only, and drops everything else on projection.
_GENERATOR_ONLY_KEYS = ("degradation_seed",)


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


def write_raw_synthetic_yaml(blocks: list[tuple[str, dict]], out_path: Path) -> Path:
    """Write blocks as YAML, preserving duplicate top-level case keys.

    A Python dict cannot hold three blocks under one ``CASE###`` key, so each
    block is dumped on its own and the text concatenated. This is the shape
    LMM_POC's ``load_blocks()`` parses with ``yaml.compose``.

    Args:
        blocks: (case_id, block) pairs; block carries `layout` and `fields`.
        out_path: Where to write synthetic.yml.

    Returns:
        The written path.
    """
    chunks: list[str] = []
    for case_id, block in blocks:
        payload = {k: v for k, v in block.items() if k not in _GENERATOR_ONLY_KEYS}
        body = yaml.safe_dump({case_id: payload}, sort_keys=False, allow_unicode=True)
        chunks.append(body)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(chunks))
    return out_path


def csv_from_jsonl(jsonl_path: Path, csv_path: Path) -> Path:
    """Transpose the projected JSONL ground truth into a CSV.

    Columns are the union of every record's keys, in first-seen order, with the
    JSONL's `filename` renamed to `image_file` to match this repo's convention.
    A field absent from a record is filled with NOT_FOUND, never left blank.

    Args:
        jsonl_path: The relabel script's ground_truth.jsonl.
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
    config_path: Path, eval_cfg: dict, out_dir: Path, renderers: dict
) -> list[tuple[str, dict]]:
    """Render one clean image per document into `out_dir`, flat.

    Returns:
        (case_id, block) pairs in document-type order, for synthetic.yml.
    """
    data = yaml.safe_load(config_path.read_text())
    blocks: list[tuple[str, dict]] = []

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

        gt_data = load_ground_truth(Path(doc_cfg["ground_truth"]))
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
            entry["case_id"] = str(case_id)
            try:
                img = renderer(entry, layout)
            except FitError as exc:
                raise build_overflow_error(
                    [f"{case_id} / {layout_ref}: {str(exc).splitlines()[0]}"]
                ) from None
            img.save(out_dir / f"{case_id}_{layout_ref}.png")
            blocks.append((str(case_id), entry))

    return blocks


def _run_relabel(eval_cfg: dict, out_dir: Path, config_path: Path) -> None:
    """Run LMM_POC's relabel script over `out_dir`, surfacing its output."""
    script = Path(eval_cfg["relabel_script"])
    repo_root = Path(eval_cfg["relabel_repo_root"])

    for label, path in (("relabel_script", script), ("relabel_repo_root", repo_root)):
        if not path.exists():
            raise _err(
                f"{label} path {path} does not exist.",
                path=config_path,
                key_path=f"{_ROOT_KEY}.{label}",
                expected="an existing path to LMM_POC's relabel script and repo root.",
                recover=f"correct '{label}' under {_ROOT_KEY}",
            )

    result = subprocess.run(  # noqa: S603
        ["python", str(script), "--apply", "--dir", str(out_dir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise _err(
            f"relabel script exited {result.returncode}.",
            path=script,
            key_path=f"{_ROOT_KEY}.relabel_script",
            expected="a clean --apply run over the exported directory. Its output was:\n"
            f"{result.stdout.strip()}\n{result.stderr.strip()}",
            recover="fix the reported problem and re-run the export",
        )


def export_eval_set(
    config_path: Path,
    out_dir: Path,
    *,
    relabel: bool = True,
    force: bool = False,
    renderers: dict | None = None,
) -> dict:
    """Export a flat evaluation set, optionally relabelled and projected.

    Args:
        config_path: Path to generation_config.yml.
        out_dir: Directory to write the set into.
        relabel: Run LMM_POC's relabel script and write the CSV afterwards.
            With False, the raw set (images + synthetic.yml) is written and
            nothing is projected — no JSONL and no CSV.
        force: Replace `out_dir` if it exists and is non-empty.
        renderers: Document type -> renderer callable; defaults to the
            pipeline's registry. Injectable so tests can render a subset.

    Returns:
        Summary dict with `images`, `out_dir`, `relabelled`, and — when
        relabelled — `csv`.

    Raises:
        ValueError: any configuration, directory, or relabel failure.
    """
    eval_cfg = load_eval_set_config(config_path)

    if renderers is None:
        from generators.pipeline import _RENDERERS

        renderers = _RENDERERS

    if relabel:
        # Validate the external dependency before rendering 165 images.
        _run_relabel_preflight(eval_cfg, config_path)

    _prepare_dir(out_dir, force=force)
    blocks = _render_documents(config_path, eval_cfg, out_dir, renderers)
    write_raw_synthetic_yaml(blocks, out_dir / "synthetic.yml")

    summary = {"images": len(blocks), "out_dir": str(out_dir), "relabelled": relabel}
    if not relabel:
        return summary

    _run_relabel(eval_cfg, out_dir, config_path)
    csv_path = csv_from_jsonl(out_dir / "ground_truth.jsonl", out_dir / eval_cfg["csv_name"])
    summary["csv"] = str(csv_path)
    return summary


def _run_relabel_preflight(eval_cfg: dict, config_path: Path) -> None:
    """Fail fast on a missing relabel script or repo root before any rendering."""
    for label in ("relabel_script", "relabel_repo_root"):
        path = Path(eval_cfg[label])
        if not path.exists():
            raise _err(
                f"{label} path {path} does not exist.",
                path=config_path,
                key_path=f"{_ROOT_KEY}.{label}",
                expected="an existing path to LMM_POC's relabel script and repo root.",
                recover=f"correct '{label}' under {_ROOT_KEY}",
            )
