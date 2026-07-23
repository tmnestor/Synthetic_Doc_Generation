"""Pipeline CLI — generate, derive, validate synthetic documents.

Usage:
    python -m generators.pipeline generate --config config/generation_config.yml
    python -m generators.pipeline derive --config config/generation_config.yml
    python -m generators.pipeline validate --config config/generation_config.yml
"""

from pathlib import Path

import typer
from rich import print as rprint

from generators.bank_statement import render_bank_statement
from generators.beneficiary_itr import render_beneficiary_itr
from generators.cc_statement import render_cc_statement
from generators.common import FitError, degrade_image
from generators.derive_outputs import derive_cord, derive_csv, derive_jsonl
from generators.distribution_statement import render_distribution_statement
from generators.exporters.config import load_export_config
from generators.invoice import render_invoice
from generators.loader import (
    load_generation_config,
    load_ground_truth,
    load_layout_registry,
)
from generators.overflow_check import build_overflow_error, check_overflow
from generators.receipt import render_receipt
from generators.schema import validate_entry
from generators.trust_income_schedule import render_trust_income_schedule
from generators.trust_return import render_trust_return

app = typer.Typer(help="Synthetic Australian business document generator.")

_RENDERERS = {
    "bank_statements": render_bank_statement,
    "receipts": render_receipt,
    "invoices": render_invoice,
    "cc_statements": render_cc_statement,
    "trust_returns": render_trust_return,
    "distribution_statements": render_distribution_statement,
    "trust_income_schedules": render_trust_income_schedule,
    "beneficiary_itrs": render_beneficiary_itr,
}

_DEFAULT_CONFIG = Path("config/generation_config.yml")


@app.command()
def validate(
    config: Path = typer.Option(_DEFAULT_CONFIG, help="Path to generation_config.yml"),
) -> None:
    """Validate all ground truth YAML files against schema and layout registries."""
    cfg = load_generation_config(config)
    all_errors: list[str] = []

    for doc_type, doc_cfg in cfg.get("document_types", {}).items():
        gt_path = Path(doc_cfg["ground_truth"])
        if not gt_path.exists():
            all_errors.append(f"{doc_type}: ground truth not found at {gt_path}")
            continue

        gt_data = load_ground_truth(gt_path)

        layouts: dict = {}
        if "layouts" in doc_cfg:
            layout_path = Path(doc_cfg["layouts"])
            if layout_path.exists():
                layouts = load_layout_registry(layout_path)

        for case_id, entry in gt_data.items():
            errors = validate_entry(str(case_id), entry)
            all_errors.extend(errors)

            layout_ref = entry.get("layout", "")
            if layouts and layout_ref not in layouts:
                all_errors.append(
                    f"{case_id}: layout '{layout_ref}' not found in "
                    f"{doc_cfg.get('layouts')}. "
                    f"Available layouts: {sorted(layouts.keys())}"
                )

        # Overflow backstop: render each entry and surface any content that
        # cannot fit its box even after lossless wrap/shrink (a real design error).
        renderer = _RENDERERS.get(doc_type)
        if renderer and layouts:
            all_errors.extend(check_overflow(gt_data, layouts, renderer))

    if all_errors:
        rprint(f"[red]Validation failed with {len(all_errors)} error(s):[/red]")
        for err in all_errors:
            rprint(f"  [red]- {err}[/red]")
        raise typer.Exit(1) from None

    rprint("[green]Validation passed.[/green]")


@app.command()
def derive(
    config: Path = typer.Option(_DEFAULT_CONFIG, help="Path to generation_config.yml"),
) -> None:
    """Regenerate CSV/JSONL from ground truth YAML."""
    cfg = load_generation_config(config)
    derived_dir = Path(cfg["derived_dir"])
    derived_dir.mkdir(parents=True, exist_ok=True)

    gt_files: list[Path] = []
    for doc_cfg in cfg.get("document_types", {}).values():
        gt_path = Path(doc_cfg["ground_truth"])
        if gt_path.exists():
            gt_files.append(gt_path)

    formats = cfg.get("derived_formats", {})
    field_defs_path = Path("config/field_definitions.yml")

    if formats.get("csv"):
        csv_path = derive_csv(gt_files, field_defs_path, derived_dir / "ground_truth.csv")
        rprint(f"[green]CSV written: {csv_path}[/green]")

    if formats.get("jsonl"):
        jsonl_path = derive_jsonl(gt_files, derived_dir / "ground_truth.jsonl")
        rprint(f"[green]JSONL written: {jsonl_path}[/green]")

    export_cfg = load_export_config(Path("config/export_config.yml"))
    if "cord" in export_cfg["export_targets"]:
        cord_path = derive_cord(gt_files, export_cfg, derived_dir / "cord.jsonl")
        rprint(f"[green]CORD JSONL written: {cord_path}[/green]")


@app.command()
def generate(
    config: Path = typer.Option(_DEFAULT_CONFIG, help="Path to generation_config.yml"),
    doc_type: str | None = typer.Option(None, "--type", help="Generate only this document type"),
    clean_only: bool = typer.Option(False, "--clean-only", help="Skip degraded variants"),
) -> None:
    """Generate synthetic document images from ground truth YAML."""
    cfg = load_generation_config(config)

    output_dir = Path(cfg["output_dir"])
    degradation_params = cfg.get("degradation", None)

    doc_types = cfg.get("document_types", {})
    if doc_type:
        if doc_type not in doc_types:
            rprint(f"[red]Unknown document type '{doc_type}'. Available: {sorted(doc_types.keys())}[/red]")
            raise typer.Exit(1) from None
        doc_types = {doc_type: doc_types[doc_type]}

    for dtype, doc_cfg in doc_types.items():
        renderer = _RENDERERS.get(dtype)
        if not renderer:
            rprint(f"[yellow]No renderer for '{dtype}', skipping.[/yellow]")
            continue

        gt_data = load_ground_truth(Path(doc_cfg["ground_truth"]))
        layouts = load_layout_registry(Path(doc_cfg["layouts"]))
        subdir = doc_cfg.get("output_subdir", dtype)

        clean_dir = output_dir / "clean" / subdir
        degraded_dir = output_dir / "degraded" / subdir
        clean_dir.mkdir(parents=True, exist_ok=True)
        if not clean_only:
            degraded_dir.mkdir(parents=True, exist_ok=True)

        generate_clean = doc_cfg.get("generate_clean", True)
        generate_degraded = doc_cfg.get("generate_degraded", True) and not clean_only

        count = 0
        for case_id, entry in gt_data.items():
            layout_ref = entry.get("layout", "")
            layout = layouts.get(layout_ref, {})
            if not layout:
                rprint(f"[yellow]Skipping {case_id}: layout '{layout_ref}' not found.[/yellow]")
                continue

            entry["case_id"] = str(case_id)
            try:
                img = renderer(entry, layout)
            except FitError as exc:
                raise build_overflow_error(
                    [f"{case_id} / {layout_ref}: {str(exc).splitlines()[0]}"]
                ) from None
            filename = f"{case_id}_{layout_ref}.png"

            if generate_clean:
                img.save(clean_dir / filename)

            if generate_degraded:
                seed = entry.get("degradation_seed", hash(case_id) % 10000)
                degraded = degrade_image(img, seed=seed, params=degradation_params)
                degraded_filename = f"{case_id}_{layout_ref}_degraded.png"
                degraded.save(degraded_dir / degraded_filename)

            count += 1

        rprint(f"[green]{dtype}: generated {count} documents.[/green]")


if __name__ == "__main__":
    app()
