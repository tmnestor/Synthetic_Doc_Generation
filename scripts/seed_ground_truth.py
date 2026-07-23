"""Ground truth seed generator for synthetic Australian business documents.

Generates 55 YAML entries per document type (bank statements, receipts, invoices,
CC statements) using deterministic seed=42, writing to ground_truth/*.yml.

Each case's shared entities (account holder, home location) are generated once
via content_engine and projected across that case's bank/cc/invoice entries, so
widened content never desyncs a PAYER_NAME across a case's linked documents.
"""

import random

# Ensure we can import from project root
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import typer
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from generators.content_engine import (  # noqa: E402
    ContentEngine,
    NonRepeatingSampler,
    build_engine,
    sample,
)
from generators.loader import load_layout_registry  # noqa: E402
from generators.overflow_check import check_overflow  # noqa: E402
from generators.schema import validate_entry  # noqa: E402

_SEED = 42
_COUNT = 55
_GT_DIR = Path(__file__).parent.parent / "ground_truth"

# ── layout IDs per document type (structural, not content — unchanged) ─────
_BANK_LAYOUTS = [
    "cba_standard",
    "cba_date_grouped",
    "westpac_standard",
    "westpac_premium",
    "nab_classic",
    "nab_dense",
    "anz_standard",
    "anz_modern",
]

_RECEIPT_LAYOUTS = [
    "receipt_thermal_80mm",
    "receipt_thermal_57mm",
    "receipt_retail_tax",
    "receipt_fuel",
    "receipt_professional",
    "receipt_hospitality",
]

_INVOICE_LAYOUTS = [
    "tax_invoice_standard",
    "tax_invoice_gst_inclusive",
    "tax_invoice_high_value",
    "tax_invoice_mixed",
]

_CC_LAYOUTS = [
    "cba_cc_standard",
    "cba_cc_rewards",
    "westpac_cc_standard",
    "westpac_cc_altitude",
    "nab_cc_standard",
    "nab_cc_low_rate",
    "anz_cc_standard",
    "anz_cc_platinum",
]


def _fmt_date(day: int, month: int, year: int) -> str:
    """Format date as DD/MM/YYYY."""
    return f"{day:02d}/{month:02d}/{year}"


def _rand_date(rng: random.Random, year_start: int = 2023, year_end: int = 2024) -> tuple[int, int, int]:
    """Generate a random date tuple (day, month, year)."""
    year = rng.randint(year_start, year_end)
    month = rng.randint(1, 12)
    max_day = 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31
    day = rng.randint(1, max_day)
    return day, month, year


def _rand_amount(rng: random.Random, lo: float, hi: float) -> Decimal:
    """Generate a random Decimal amount in [lo, hi] rounded to 2dp."""
    raw = rng.uniform(lo, hi)
    return Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt_decimal(d: Decimal) -> str:
    """Format Decimal as plain string with 2dp (no $ sign)."""
    return f"{d:.2f}"


def _generate_case_entities(engine: ContentEngine, rng: random.Random, count: int) -> list[dict]:
    """Generate each case's shared entities once, projected across bank/cc/invoice.

    Receipts have no payer/holder field, so they draw their own supplier
    independently and do not consume this bundle.
    """
    return [{"holder": engine.person(rng), "location": engine.location(rng)} for _ in range(count)]


def _draw_bank_description(
    engine: ContentEngine, rng: random.Random, *, suburb: str, holder_first: str
) -> str:
    """Fill a seeded bank_descriptions grammar template with a fictional merchant.

    The merchant portion is upper-cased to match real AU bank-statement
    styling and to keep `_extract_suburb()` in scripts/seed_transaction_links.py
    (which distinguishes an ALL-CAPS merchant token from a Title-Case suburb)
    parsing EFTPOS descriptions correctly.
    """
    templates = engine.pools["bank_descriptions"]
    template_key = sample(rng, list(templates.keys()))
    template = templates[template_key]
    all_categories = engine.pools["receipt_categories"] + engine.pools["service_categories"]
    category = sample(rng, all_categories)
    merchant = engine.fictional_business_name(rng, category)[:12].upper()
    return template.format(
        merchant=merchant,
        location=suburb,
        last4=f"{rng.randint(1000, 9999)}",
        biller=merchant,
        crn=rng.randint(100000000, 999999999),
        ref=f"REF{rng.randint(10000, 99999)}",
        mhf=rng.randint(1000, 9999),
        name=holder_first,
    )


def _generate_bank_entries(
    engine: ContentEngine, rng: random.Random, case_entities: list[dict], count: int
) -> dict:
    """Generate bank statement ground truth entries (25-40 txns each)."""
    entries: dict = {}
    layout_draw = NonRepeatingSampler(rng, _BANK_LAYOUTS)
    bank_draw = NonRepeatingSampler(rng, engine.pools["banks"])

    for i in range(count):
        case_id = f"CASE{i + 1:03d}"
        layout = layout_draw.draw()

        bank = bank_draw.draw()
        holder = case_entities[i]["holder"]
        suburb = case_entities[i]["location"]["suburb"]

        _d, m, y = _rand_date(rng)
        period_start = _fmt_date(1, m, y)
        max_day = 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31
        period_end = _fmt_date(max_day, m, y)
        statement_range = f"{period_start} - {period_end}"

        n_txns = rng.randint(25, 40)
        txn_days = sorted(rng.randint(1, max_day) for _ in range(n_txns))

        txn_dates, txn_descs, txn_debits, txn_credits = [], [], [], []
        closing_balance = _rand_amount(rng, 500, 15000)

        for txn_day in txn_days:
            txn_dates.append(_fmt_date(txn_day, m, y))
            is_debit = rng.random() < 0.80
            desc = _draw_bank_description(engine, rng, suburb=suburb, holder_first=holder["first_name"])
            txn_descs.append(desc)
            if is_debit:
                amt = _rand_amount(rng, 10, 600)
                txn_debits.append(_fmt_decimal(amt))
                txn_credits.append("NOT_FOUND")
            else:
                amt = _rand_amount(rng, 100, 5000)
                txn_debits.append("NOT_FOUND")
                txn_credits.append(_fmt_decimal(amt))

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "BANK_STATEMENT",
                "SUPPLIER_NAME": bank["name"],
                "STATEMENT_DATE_RANGE": statement_range,
                "TRANSACTION_DATES": "|".join(txn_dates),
                "TRANSACTION_DESCRIPTIONS": "|".join(txn_descs),
                "TRANSACTION_AMOUNTS_PAID": "|".join(txn_debits),
                "TRANSACTION_AMOUNTS_RECEIVED": "|".join(txn_credits),
                "ACCOUNT_BALANCE": _fmt_decimal(closing_balance),
                "PAYER_NAME": holder["full_name"],
            },
        }

    return entries


def _generate_receipt_entries(
    engine: ContentEngine, rng: random.Random, case_entities: list[dict], count: int
) -> dict:
    """Generate receipt ground truth entries with GST-inclusive pricing."""
    entries: dict = {}
    layout_draw = NonRepeatingSampler(rng, _RECEIPT_LAYOUTS)
    item_pool = engine.pools["product_catalog"]

    for i in range(count):
        case_id = f"CASE{i + 1:03d}"
        layout = layout_draw.draw()

        category = sample(rng, engine.pools["receipt_categories"])
        retailer = engine.fictional_business(rng, category)

        d, m, y = _rand_date(rng)
        invoice_date = _fmt_date(d, m, y)

        n_items = rng.randint(1, 6)
        items = rng.sample(item_pool, min(n_items, len(item_pool)))

        item_descs, item_qtys, item_prices, item_totals = [], [], [], []
        gst_inclusive_total = Decimal("0")

        for item in items:
            qty = rng.randint(1, 3)
            unit_price = _rand_amount(rng, item["price_low"], item["price_high"])
            line_total = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            item_descs.append(item["description"])
            item_qtys.append(str(qty))
            item_prices.append(_fmt_decimal(unit_price))
            item_totals.append(_fmt_decimal(line_total))
            gst_inclusive_total += line_total

        gst_amount = (gst_inclusive_total / Decimal("11")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "RECEIPT",
                "SUPPLIER_NAME": retailer["name"],
                "BUSINESS_ABN": retailer["abn"],
                "BUSINESS_ADDRESS": retailer["address"],
                "INVOICE_DATE": invoice_date,
                "IS_GST_INCLUDED": "true",
                "GST_AMOUNT": _fmt_decimal(gst_amount),
                "TOTAL_AMOUNT": _fmt_decimal(gst_inclusive_total),
                "LINE_ITEM_DESCRIPTIONS": "|".join(item_descs),
                "LINE_ITEM_QUANTITIES": "|".join(item_qtys),
                "LINE_ITEM_PRICES": "|".join(item_prices),
                "LINE_ITEM_TOTAL_PRICES": "|".join(item_totals),
            },
        }

    return entries


def _generate_invoice_entries(
    engine: ContentEngine, rng: random.Random, case_entities: list[dict], count: int
) -> dict:
    """Generate invoice ground truth entries with GST-exclusive pricing."""
    entries: dict = {}
    layout_draw = NonRepeatingSampler(rng, _INVOICE_LAYOUTS)
    svc_pool = engine.pools["service_catalog"]

    for i in range(count):
        case_id = f"CASE{i + 1:03d}"
        layout = layout_draw.draw()

        category = sample(rng, engine.pools["service_categories"])
        provider = engine.fictional_business(rng, category)

        d, m, y = _rand_date(rng)
        invoice_date = _fmt_date(d, m, y)
        due_day = min(d + 30, 28)
        due_m = m + 1 if due_day < d else m
        due_y = y + 1 if due_m > 12 else y
        due_m = due_m % 12 if due_m > 12 else due_m
        if due_m == 0:
            due_m = 12
        payment_due_date = _fmt_date(due_day, due_m, due_y)

        holder = case_entities[i]["holder"]
        payer_address = engine.address(rng)

        n_items = rng.randint(1, 4)
        services = rng.sample(svc_pool, min(n_items, len(svc_pool)))

        item_descs, item_qtys, item_prices, item_totals = [], [], [], []
        subtotal_ex_gst = Decimal("0")

        for svc in services:
            qty = rng.randint(1, 8)
            unit_price = _rand_amount(rng, svc["price_low"], svc["price_high"])
            line_total = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            item_descs.append(svc["description"])
            item_qtys.append(str(qty))
            item_prices.append(_fmt_decimal(unit_price))
            item_totals.append(_fmt_decimal(line_total))
            subtotal_ex_gst += line_total

        gst_amount = (subtotal_ex_gst * Decimal("0.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_incl_gst = subtotal_ex_gst + gst_amount

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "INVOICE",
                "SUPPLIER_NAME": provider["name"],
                "BUSINESS_ABN": provider["abn"],
                "BUSINESS_ADDRESS": provider["address"],
                "INVOICE_DATE": invoice_date,
                "IS_GST_INCLUDED": "false",
                "GST_AMOUNT": _fmt_decimal(gst_amount),
                "TOTAL_AMOUNT": _fmt_decimal(total_incl_gst),
                "LINE_ITEM_DESCRIPTIONS": "|".join(item_descs),
                "LINE_ITEM_QUANTITIES": "|".join(item_qtys),
                "LINE_ITEM_PRICES": "|".join(item_prices),
                "LINE_ITEM_TOTAL_PRICES": "|".join(item_totals),
                "PAYER_NAME": holder["full_name"],
                "PAYER_ADDRESS": payer_address,
            },
        }

    return entries


def _generate_cc_entries(
    engine: ContentEngine, rng: random.Random, case_entities: list[dict], count: int
) -> dict:
    """Generate credit card statement ground truth entries."""
    entries: dict = {}
    layout_draw = NonRepeatingSampler(rng, _CC_LAYOUTS)
    bank_draw = NonRepeatingSampler(rng, engine.pools["banks"])

    for i in range(count):
        case_id = f"CASE{i + 1:03d}"
        layout = layout_draw.draw()

        bank = bank_draw.draw()
        holder = case_entities[i]["holder"]
        suburb = case_entities[i]["location"]["suburb"]

        d, m, y = _rand_date(rng)
        period_start = _fmt_date(1, m, y)
        max_day = 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31
        period_end = _fmt_date(max_day, m, y)
        statement_range = f"{period_start} - {period_end}"

        due_d = min(max_day + 21, 28)
        due_m = m + 1 if due_d <= max_day else m
        if due_m > 12:
            due_m = 1
            due_y = y + 1
        else:
            due_y = y
        payment_due_date = _fmt_date(due_d, due_m, due_y)

        credit_limit = _rand_amount(rng, 2000, 20000)
        credit_limit = Decimal(str(round(float(credit_limit) / 500) * 500))

        n_txns = rng.randint(5, 12)
        txn_dates, txn_descs, txn_amounts = [], [], []
        total_charges = Decimal("0")

        for _j in range(n_txns):
            txn_day = rng.randint(1, max_day)
            txn_dates.append(_fmt_date(txn_day, m, y))
            desc = _draw_bank_description(engine, rng, suburb=suburb, holder_first=holder["first_name"])
            txn_descs.append(desc)
            amt = _rand_amount(rng, 10, 800)
            txn_amounts.append(_fmt_decimal(amt))
            total_charges += amt

        closing_balance = total_charges
        min_payment_pct = (closing_balance * Decimal("0.02")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        minimum_payment = max(Decimal("25.00"), min_payment_pct)

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "CC_STATEMENT",
                "SUPPLIER_NAME": bank["name"],
                "STATEMENT_DATE_RANGE": statement_range,
                "TRANSACTION_DATES": "|".join(txn_dates),
                "TRANSACTION_DESCRIPTIONS": "|".join(txn_descs),
                "TRANSACTION_AMOUNTS_PAID": "|".join(txn_amounts),
                "ACCOUNT_BALANCE": _fmt_decimal(closing_balance),
                "CREDIT_LIMIT": _fmt_decimal(credit_limit),
                "MINIMUM_PAYMENT": _fmt_decimal(minimum_payment),
                "PAYMENT_DUE_DATE": payment_due_date,
                "PAYER_NAME": holder["full_name"],
            },
        }

    return entries


def _validate_dry_run(all_entries: dict[str, dict]) -> None:
    """Validate generated entries in-memory (schema + overflow) without writing YAML."""
    from generators.bank_statement import render_bank_statement
    from generators.cc_statement import render_cc_statement
    from generators.invoice import render_invoice
    from generators.receipt import render_receipt

    renderer_map = {
        "bank_statements.yml": (render_bank_statement, "config/layouts/bank_statements.yml"),
        "receipts.yml": (render_receipt, "config/layouts/receipts.yml"),
        "invoices.yml": (render_invoice, "config/layouts/invoices.yml"),
        "cc_statements.yml": (render_cc_statement, "config/layouts/cc_statements.yml"),
    }

    errors: list[str] = []
    for filename, entries in all_entries.items():
        renderer, layout_path = renderer_map[filename]
        layouts = load_layout_registry(Path(layout_path))
        for case_id, entry in entries.items():
            errors.extend(validate_entry(str(case_id), entry))
        errors.extend(check_overflow(entries, layouts, renderer))

    if errors:
        listing = "\n    ".join(errors)
        raise RuntimeError(
            "Dry run failed: generated content did not validate.\n"
            f"  What:     {len(errors)} error(s) across generated entries:\n"
            f"    {listing}\n"
            "  Where:    scripts/seed_ground_truth.py generator functions and the "
            "config/data_pools.yml content they draw from.\n"
            "  Expected: every generated entry passes schema validation and renders "
            "within its layout's field_budgets (no FitError).\n"
            "  Recover:  fix the failing generator logic or widen the offending pool/budget, "
            "then rerun `python scripts/seed_ground_truth.py --dry-run`."
        )


def build_all_entries() -> dict[str, dict]:
    """Generate all document-type entries in-memory, keyed by doc type (no I/O).

    Both `main()` (which appends `.yml` for the write/dry-run paths) and tests
    that need the generated entries without touching the filesystem call this.
    """
    rng = random.Random(_SEED)
    # generate_abn()/generate_tfn() draw from the module-global RNG; seed it too
    # so ABN/TFN digit fields are reproducible run-to-run, not just content selection.
    random.seed(_SEED)
    engine = build_engine()
    case_entities = _generate_case_entities(engine, rng, _COUNT)

    generators = [
        ("bank_statements", _generate_bank_entries),
        ("receipts", _generate_receipt_entries),
        ("invoices", _generate_invoice_entries),
        ("cc_statements", _generate_cc_entries),
    ]

    all_entries: dict[str, dict] = {}
    for doc_type, gen_fn in generators:
        all_entries[doc_type] = gen_fn(engine, rng, case_entities, _COUNT)
    return all_entries


def main(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate in-memory; do not write ground_truth/*.yml"
    ),
) -> None:
    """Generate all ground truth YAML files with deterministic seed=42."""
    all_entries = build_all_entries()

    if dry_run:
        _validate_dry_run({f"{doc_type}.yml": entries for doc_type, entries in all_entries.items()})
        print("Dry run: all entries validated in-memory; ground_truth/*.yml NOT written.")
        return

    _GT_DIR.mkdir(parents=True, exist_ok=True)
    for doc_type, entries in all_entries.items():
        out_path = _GT_DIR / f"{doc_type}.yml"
        with out_path.open("w", encoding="utf-8") as fh:
            yaml.dump(entries, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"Wrote {len(entries)} entries to {out_path}")


if __name__ == "__main__":
    typer.run(main)
