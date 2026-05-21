# Synthetic Business Document Generator

YAML-driven pipeline for generating synthetic Australian business documents with pixel-perfect ground truth. Produces 440 benchmark images (220 clean + 220 degraded) across 4 document types with transaction linking ground truth.

---

## Quick Start

```bash
# Validate ground truth against schema and layout registries
python -m generators.pipeline validate

# Generate all 440 images (220 clean + 220 degraded)
python -m generators.pipeline generate

# Generate only one document type
python -m generators.pipeline generate --type receipts

# Generate clean images only (skip degradation)
python -m generators.pipeline generate --clean-only

# Regenerate derived CSV/JSONL from YAML ground truth
python -m generators.pipeline derive
```

### Dependencies

```
Pillow    # Image rendering
numpy     # Noise generation for degradation
PyYAML    # YAML parsing
typer     # CLI framework
rich      # Coloured console output
```

---

## What It Produces

| Output | Count | Description |
|--------|-------|-------------|
| Clean PNGs | 220 | Pixel-perfect rendered documents (55 per type) |
| Degraded PNGs | 220 | Simulated phone photos with noise, blur, rotation, JPEG artifacts |
| Ground truth YAML | 4 files | Field-level truth for all 220 documents |
| Transaction links YAML | 1 file | 110 receipt/invoice-to-bank-statement links at 3 difficulty levels |
| Derived CSV | 1 file | Flat CSV with all 23 columns (NOT_FOUND for inapplicable fields) |
| Derived JSONL | 1 file | One JSON object per document with all field values |

## Document Types

| Type | Layouts | Fields | Example Layouts |
|------|---------|--------|-----------------|
| Bank Statement | 12 | 9 | CBA classic/modern/minimal, Westpac, NAB, ANZ |
| Receipt | 6 | 12 | Thermal 80mm/57mm, retail tax, fuel, professional, hospitality |
| Invoice | 4 | 14 | Standard, GST-inclusive, high-value, mixed |
| CC Statement | 8 | 11 | 2 per bank (CBA, Westpac, NAB, ANZ) |

---

## Pipeline CLI

```
python -m generators.pipeline <command> [OPTIONS]
```

| Command | Description |
|---------|-------------|
| `validate` | Validate ground truth YAML against schema + layout registries |
| `generate` | Render document images from ground truth + layouts |
| `derive` | Regenerate CSV/JSONL from ground truth YAML |

| Flag | Default | Applies To | Description |
|------|---------|------------|-------------|
| `--config` | `config/generation_config.yml` | all | Path to generation config |
| `--type` | all types | generate | Generate only this document type |
| `--clean-only` | `false` | generate | Skip degraded variants |

---

## Architecture

```mermaid
graph TD
    GT["ground_truth/*.yml<br/>Field values (220 entries)"]
    LR["config/layouts/*.yml<br/>Visual rendering specs (30 layouts)"]
    GC["config/generation_config.yml<br/>Pipeline configuration"]
    FD["config/field_definitions.yml<br/>23-column schema"]

    GT --> V["validate<br/>Schema + layout checks"]
    LR --> V
    FD --> V

    GT --> G["generate<br/>Render PIL images"]
    LR --> G
    GC --> G

    G --> CLEAN["output/clean/<br/>220 PNGs"]
    G --> DEG["output/degraded/<br/>220 PNGs"]

    GT --> D["derive<br/>YAML → CSV/JSONL"]
    FD --> D
    D --> CSV["derived/ground_truth.csv"]
    D --> JSONL["derived/ground_truth.jsonl"]
```

---

## Ground Truth YAML Format

YAML is the single source of truth. Each entry specifies a layout reference, degradation seed, and field values:

```yaml
CASE001:
  layout: receipt_thermal_80mm
  degradation_seed: 1001
  fields:
    DOCUMENT_TYPE: RECEIPT
    SUPPLIER_NAME: Bunnings Warehouse
    BUSINESS_ABN: '53 004 085 616'
    BUSINESS_ADDRESS: '123 Main St, Alexandria NSW 2015'
    INVOICE_DATE: '15/03/2024'
    IS_GST_INCLUDED: 'true'
    GST_AMOUNT: '6.12'
    TOTAL_AMOUNT: '67.32'
    LINE_ITEM_DESCRIPTIONS: Drill Bit|Glue|Glasses
    LINE_ITEM_QUANTITIES: '1|2|1'
    LINE_ITEM_PRICES: '12.50|8.95|15.42'
    LINE_ITEM_TOTAL_PRICES: '12.50|17.90|15.42'
```

---

## Transaction Links

`ground_truth/transaction_links.yml` maps receipts and invoices to bank statement debit transactions at three difficulty levels:

| Difficulty | Criteria | Count |
|------------|----------|-------|
| Easy | Exact date and amount match | ~50 |
| Medium | Amount match, date offset 1-3 days | ~30 |
| Hard | Amount match, date offset 3-7 days | ~28 |

```yaml
# Keys are image filenames; source and target share the same CASE### prefix
CASE001_receipt_thermal_80mm.png:
- bank_statement: CASE001_cba_standard.png
  supplier: Bunnings Warehouse
  receipt_date: '15/03/2024'
  receipt_total: '67.32'
  bank_date: '15/03/2024'
  bank_description: EFTPOS BUNNINGS W/HOUSE Alexandria AUS
  bank_amount: '67.32'
  match_status: FOUND
  match_difficulty: easy
```

---

## Linking Validation API

```python
from linking.transaction_matcher import parse_amount, normalize_date, description_score
from linking.link_validator import validate_links, LinkScore

# Parse amounts: handles "$1,234.56", negatives, NOT_FOUND
amount = parse_amount("$1,234.56")  # 1234.56

# Normalize dates: DD/MM/YYYY, DD/MM/YY, DD Mon YYYY, YYYY-MM-DD
d = normalize_date("15/03/2024")  # date(2024, 3, 15)

# Fuzzy description matching (SequenceMatcher)
score = description_score("BUNNINGS WAREHOUSE", "Bunnings Whse")  # ~0.6

# Score predictions against ground truth
result: LinkScore = validate_links(ground_truth_dict, predictions_dict)
print(f"F1: {result.f1:.2f}, by difficulty: {result.by_difficulty}")
```

---

## Degradation Pipeline

Simulates phone photos of printed documents with a deterministic 7-stage pipeline:

1. **Paper tint** — off-white/yellowed overlay
2. **Contrast reduction**
3. **Brightness variation**
4. **Gaussian blur**
5. **Rotation** (slight skew)
6. **Salt-and-pepper noise**
7. **JPEG compression artifacts**

All parameters are configurable in `generation_config.yml` under `degradation:`. Each entry's `degradation_seed` ensures reproducible results.

---

## Regenerating the Dataset

```bash
# Re-seed ground truth (220 entries, deterministic with seed=42)
python scripts/seed_ground_truth.py

# Re-seed transaction links (110 links across 3 difficulty levels)
python scripts/seed_transaction_links.py

# Validate, generate images, derive CSV/JSONL
python -m generators.pipeline validate
python -m generators.pipeline generate
python -m generators.pipeline derive
```

---

## File Structure

```
generators/
├── __init__.py
├── common.py              # Fonts, text helpers, ABN validation, GST, degradation
├── schema.py              # Ground truth schema validation
├── loader.py              # YAML loaders with fail-fast diagnostics
├── derive_outputs.py      # YAML → CSV/JSONL derivation
├── pipeline.py            # Typer CLI (validate, generate, derive)
├── bank_statement.py      # Bank statement renderer
├── receipt.py             # Receipt renderer (thermal/letterhead)
├── invoice.py             # Tax-compliant invoice renderer
└── cc_statement.py        # Credit card statement renderer

linking/
├── __init__.py
├── transaction_matcher.py # parse_amount, normalize_date, description_score
└── link_validator.py      # validate_links with per-difficulty scoring

scripts/
├── seed_ground_truth.py       # Generate 220 ground truth entries (seed=42)
└── seed_transaction_links.py  # Generate 110 transaction links

ground_truth/
├── bank_statements.yml    # 55 entries
├── receipts.yml           # 55 entries
├── invoices.yml           # 55 entries
├── cc_statements.yml      # 55 entries
└── transaction_links.yml  # 110 links

config/
├── generation_config.yml  # Pipeline configuration
├── field_definitions.yml  # 23-column schema for 4 document types
├── data_pools.yml         # Australian business data (retailers, services, banks)
└── layouts/
    ├── bank_statements.yml  # 12 layouts
    ├── receipts.yml         # 6 layouts
    ├── invoices.yml         # 4 layouts
    └── cc_statements.yml    # 8 layouts
```
