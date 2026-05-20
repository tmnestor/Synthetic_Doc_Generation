# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YAML-driven pipeline for generating synthetic Australian business documents with pixel-perfect ground truth. Produces 440 benchmark images (220 clean + 220 degraded) across 4 document types (bank statements, receipts, invoices, credit card statements) with transaction linking ground truth for LLM evaluation.

## Commands

```bash
# Validate ground truth YAML against schema and layout registries
python -m generators.pipeline validate

# Generate all document images (clean + degraded)
python -m generators.pipeline generate

# Generate a single document type
python -m generators.pipeline generate --type receipts

# Generate clean-only (skip degradation)
python -m generators.pipeline generate --clean-only

# Derive CSV/JSONL from ground truth YAML
python -m generators.pipeline derive

# Seed ground truth entries (destructive — overwrites ground_truth/*.yml)
python scripts/seed_ground_truth.py

# Seed transaction links
python scripts/seed_transaction_links.py
```

### Testing & Linting

```bash
conda run -n du pytest tests/
conda run -n du pytest tests/test_schema.py::test_specific  # single test
conda run -n du ruff check --fix --ignore ARG001,ARG002,F841 *.py
conda run -n du ruff format .
conda run -n du mypy . --ignore-missing-imports
```

Note: `tests/` is gitignored — tests are local-only. Ruff also ignores B008 (function call in default argument) per pyproject.toml.

## Architecture

### Data Flow

```
ground_truth/*.yml  →  generators/schema.py (validate)
                    →  generators/*.py renderers (generate)  →  output/{clean,degraded}/
                    →  generators/derive_outputs.py (derive)  →  derived/{csv,jsonl}
```

### YAML is the Single Source of Truth

- `ground_truth/*.yml` — 220 document entries (55 per type), never auto-generated after seeding
- `ground_truth/transaction_links.yml` — 110 links at 3 difficulty levels (easy/medium/hard)
- `config/generation_config.yml` — master pipeline config (output dirs, degradation params)
- `config/field_definitions.yml` — 23-column unified schema with type-specific field subsets
- `config/layouts/*.yml` — visual rendering specs (30 layouts: 12 bank, 8 cc, 6 receipt, 4 invoice)
- `config/data_pools.yml` — Australian business data (retailers, banks, ABNs)

Python reads YAML — it does not shadow or merge with hardcoded defaults. Missing keys must fail fast.

### Renderers

One PIL renderer per document type in `generators/`, each with signature `render_*(entry, layout) → PIL.Image`:
- `bank_statement.py` — 12 layouts (CBA, Westpac, NAB, ANZ variants)
- `receipt.py` — 6 layouts (thermal 80mm/57mm, retail, fuel, professional, hospitality)
- `invoice.py` — 4 ATO-compliant layouts (standard, GST-inclusive, high-value, mixed)
- `cc_statement.py` — 8 layouts (2 per Big 4 bank)

Shared rendering utilities live in `generators/common.py` (fonts, text drawing, ABN validation, amount formatting, degradation pipeline).

### Degradation Pipeline

7-stage deterministic pipeline in `common.py:degrade_image()` seeded per document via `degradation_seed`: paper tint → contrast → brightness → blur → rotation → noise → JPEG compression. All parameter ranges configured in `generation_config.yml`.

### Linking Module

`linking/` validates transaction matching (receipt/invoice → bank statement):
- `transaction_matcher.py` — amount parsing, date normalization, fuzzy description matching
- `link_validator.py` — precision/recall/F1 overall and per-difficulty via `LinkScore` dataclass

### CLI Entry Point

`generators/pipeline.py` uses Typer with three subcommands: `validate`, `generate`, `derive`. Config path defaults to `config/generation_config.yml`.

## Key Data Conventions

- **Case IDs**: `CASEB###` (bank), `CASER###` (receipt), `CASEI###` (invoice), `CASEC###` (cc)
- **Dates**: DD/MM/YYYY in ground truth (e.g., `20/09/2024`)
- **Amounts**: Decimal string without `$` sign (e.g., `137.73`)
- **ABNs**: `XX XXX XXX XXX` format, must pass ATO checksum (weights `[10,1,3,5,7,9,11,13,15,17,19]`)
- **Pipe-delimited lists**: LINE_ITEM_DESCRIPTIONS/QUANTITIES/PRICES/TOTAL_PRICES — all must have matching counts
- **GST**: If `IS_GST_INCLUDED=true`, GST = total / 11
- **Missing fields**: Filled with `NOT_FOUND` in derived outputs
- **Layout references**: Each ground truth entry's `layout` field must exist in the corresponding `config/layouts/*.yml`

## Dependencies

Pillow, numpy, PyYAML, typer, rich. Managed via conda environment `du`.
