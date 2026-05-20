"""Ground truth seed generator for synthetic Australian business documents.

Generates 55 YAML entries per document type (bank statements, receipts, invoices,
CC statements) using deterministic seed=42, writing to ground_truth/*.yml.
"""

import random

# Ensure we can import from project root
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from generators.common import generate_abn  # noqa: E402

_SEED = 42
_COUNT = 55
_GT_DIR = Path(__file__).parent.parent / "ground_truth"

# ── layout IDs per document type ────────────────────────────────────────────
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

# ── data pools ───────────────────────────────────────────────────────────────
_RETAILERS = [
    ("Bunnings Warehouse", "123 Main St, Alexandria NSW 2015", "hardware"),
    ("Woolworths", "100 George St, Sydney NSW 2000", "grocery"),
    ("Coles", "800 Toorak Rd, Hawthorn East VIC 3123", "grocery"),
    ("Officeworks", "245 Bourke St, Melbourne VIC 3000", "office"),
    ("JB Hi-Fi", "2 Parliament Sq, Melbourne VIC 3002", "electronics"),
    ("Harvey Norman", "A1 Richmond Rd, Homebush West NSW 2140", "electronics"),
    ("Kmart Australia", "690 Springvale Rd, Mulgrave VIC 3170", "retail"),
    ("Big W", "1 Woolworths Way, Bella Vista NSW 2153", "retail"),
    ("Chemist Warehouse", "250 Bourke St, Melbourne VIC 3000", "pharmacy"),
    ("Dan Murphy's", "47-61 Egan St, Richmond VIC 3121", "liquor"),
    ("BP Australia", "717 Bourke St, Docklands VIC 3008", "fuel"),
    ("Shell Australia", "8 Redfern Rd, Hawthorn East VIC 3123", "fuel"),
    ("Ampol Limited", "29-33 Bourke Rd, Alexandria NSW 2015", "fuel"),
    ("7-Eleven Australia", "357 Ferntree Gully Rd, Mount Waverley VIC 3149", "fuel"),
    ("Myer", "295 Lonsdale St, Melbourne VIC 3000", "retail"),
    ("David Jones", "310 Bourke St, Melbourne VIC 3000", "retail"),
    ("Target Australia", "12-14 Polo Ave, Mona Vale NSW 2103", "retail"),
    ("Spotlight", "91 Dunning Ave, Rosebery NSW 2018", "retail"),
    ("Supercheap Auto", "751-753 Springvale Rd, Mulgrave VIC 3170", "automotive"),
    ("Repco", "53-57 Lonsdale St, Melbourne VIC 3000", "automotive"),
]

_PROFESSIONAL_SERVICES = [
    ("Smith & Associates Accounting", "Level 12, 100 Collins St, Melbourne VIC 3000", "accounting"),
    ("Johnson Legal", "Suite 5, 200 George St, Sydney NSW 2000", "legal"),
    ("Brisbane IT Solutions", "42 Creek St, Brisbane QLD 4000", "it_services"),
    ("Adelaide Business Consulting", "Level 3, 77 King William St, Adelaide SA 5000", "consulting"),
    ("Perth Marketing Group", "Level 8, 140 St Georges Tce, Perth WA 6000", "marketing"),
]

_ACCOUNT_HOLDERS = [
    "Sarah Johnson",
    "Michael Chen",
    "Emma Williams",
    "David Nguyen",
    "Jessica Brown",
    "James Wilson",
    "Olivia Taylor",
    "Daniel Lee",
    "Sophie Martin",
    "Ryan Thompson",
    "Hannah White",
    "Thomas Anderson",
    "Mia Robinson",
    "William Harris",
    "Charlotte Clark",
]

_LOCATIONS = [
    ("Alexandria", "2015", "NSW"),
    ("Hawthorn East", "3123", "VIC"),
    ("Fortitude Valley", "4006", "QLD"),
    ("Norwood", "5067", "SA"),
    ("Subiaco", "6008", "WA"),
    ("Hobart", "7000", "TAS"),
    ("Parramatta", "2150", "NSW"),
    ("South Yarra", "3141", "VIC"),
    ("Toowoomba", "4350", "QLD"),
    ("Glenelg", "5045", "SA"),
]

_BANKS = [
    ("Commonwealth Bank", "CBA", "06"),
    ("Westpac", "WBC", "03"),
    ("National Australia Bank", "NAB", "08"),
    ("ANZ", "ANZ", "01"),
]

_BANK_DESCS = [
    "EFTPOS COLES {suburb} AUS",
    "VISA DEBIT PURCHASE {merchant} {suburb} AU",
    "BPAY ORIGIN ENERGY CRN {crn}",
    "DD AGL {ref} MHF 1234",
    "EFTPOS WOOLWORTHS {suburb} AUS",
    "EFTPOS BUNNINGS W/HOUSE {suburb} AUS",
    "EFTPOS OFFICEWORKS {suburb} AUS",
    "VISA DEBIT PURCHASE SHELL {suburb} AU",
    "EFTPOS JB HI-FI {suburb} AUS",
    "BPAY TELSTRA CRN {crn}",
    "DD INSURANCE {ref}",
    "VISA DEBIT PURCHASE CHEMIST WHSE {suburb} AU",
    "EFTPOS KMART {suburb} AUS",
    "EFTPOS TARGET {suburb} AUS",
    "EFTPOS DAN MURPHYS {suburb} AUS",
    "EFTPOS BP {suburb} AUS",
    "EFTPOS AMPOL {suburb} AUS",
    "Salary ATO PAYROLL {ref}",
    "Transfer To {name} NetBank",
    "ATM WITHDRAWAL {suburb}",
]

_INVOICE_SERVICES = [
    ("Professional consultation services", "hrs", 150, 350),
    ("Legal document preparation", "hrs", 200, 500),
    ("Software development services", "hrs", 120, 280),
    ("Business strategy consulting", "hrs", 250, 600),
    ("Marketing campaign management", "hrs", 100, 200),
    ("Accounting and bookkeeping", "hrs", 80, 180),
    ("IT support and maintenance", "hrs", 90, 220),
    ("Financial planning services", "hrs", 180, 400),
    ("Tax return preparation", "ea", 350, 800),
    ("Audit services", "hrs", 220, 450),
    ("Trademark registration", "ea", 500, 1200),
    ("Website design and development", "ea", 800, 3000),
    ("Annual report preparation", "ea", 600, 1500),
    ("Corporate training workshop", "day", 1200, 3500),
    ("Risk assessment review", "ea", 900, 2500),
]

_RECEIPT_ITEMS = [
    ("Milk 2L", "ea", 2.50, 5.50),
    ("Bread White 700g", "ea", 3.00, 5.00),
    ("Chicken Breast 500g", "ea", 7.00, 14.00),
    ("Pasta 500g", "ea", 1.50, 4.00),
    ("Tomato Sauce 500ml", "ea", 2.50, 5.50),
    ("Chips BBQ 175g", "ea", 3.00, 6.00),
    ("Toilet Paper 12pk", "ea", 8.00, 16.00),
    ("Dishwashing Liquid", "ea", 3.50, 7.00),
    ("Laundry Powder 2kg", "ea", 12.00, 22.00),
    ("Shampoo 400ml", "ea", 5.00, 12.00),
    ("Batteries AA 8pk", "ea", 8.00, 18.00),
    ("HDMI Cable 2m", "ea", 12.00, 35.00),
    ("USB Hub 4-port", "ea", 15.00, 45.00),
    ("Phone Case", "ea", 10.00, 40.00),
    ("Printer Paper A4 500pk", "ea", 8.00, 18.00),
    ("Pens Ballpoint 10pk", "ea", 4.00, 10.00),
    ("Paint Brush Set", "ea", 12.00, 35.00),
    ("Drill Bit Set", "ea", 25.00, 80.00),
    ("Garden Hose 20m", "ea", 35.00, 120.00),
    ("Potting Mix 25L", "ea", 8.00, 20.00),
    ("Motor Oil 5L", "ea", 28.00, 60.00),
    ("Car Air Freshener", "ea", 5.00, 15.00),
    ("Wine Red 750ml", "ea", 12.00, 35.00),
    ("Beer Case 24", "ea", 45.00, 75.00),
    ("Sparkling Water 12pk", "ea", 8.00, 16.00),
]

_PAYMENT_METHODS = ["EFTPOS", "Visa", "Mastercard", "Cash", "AMEX", "PayPal"]


def _fmt_date(day: int, month: int, year: int) -> str:
    """Format date as DD/MM/YYYY."""
    return f"{day:02d}/{month:02d}/{year}"


def _rand_date(rng: random.Random, year_start: int = 2023, year_end: int = 2024) -> tuple[int, int, int]:
    """Generate a random date tuple (day, month, year)."""
    year = rng.randint(year_start, year_end)
    month = rng.randint(1, 12)
    # Simple day range avoiding overflow
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


def _rand_bsb(rng: random.Random, prefix: str) -> str:
    """Generate a BSB like prefix-XXX."""
    suffix = rng.randint(0, 999)
    return f"{prefix}{suffix:01d}-{rng.randint(0, 999):03d}"


def _rand_account(rng: random.Random) -> str:
    """Generate a random account number."""
    return str(rng.randint(10000000, 99999999))


def _rand_card_last4(rng: random.Random) -> str:
    return f"{rng.randint(1000, 9999)}"


# ── Bank statement generator ─────────────────────────────────────────────────


def _generate_bank_entries(rng: random.Random, count: int) -> dict:
    """Generate bank statement ground truth entries.

    Each entry has 25-40 transactions, chronologically sorted within the
    statement period month.
    """
    entries: dict = {}
    layouts = _BANK_LAYOUTS

    for i in range(count):
        case_id = f"CASEB{i + 1:03d}"
        layout = layouts[i % len(layouts)]

        bank_name, bank_code, bsb_prefix = _BANKS[i % len(_BANKS)]
        holder = _ACCOUNT_HOLDERS[i % len(_ACCOUNT_HOLDERS)]
        loc = _LOCATIONS[i % len(_LOCATIONS)]
        suburb, postcode, state = loc

        # Statement period: 1-month window
        _d, m, y = _rand_date(rng)
        period_start = _fmt_date(1, m, y)
        max_day = 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31
        period_end = _fmt_date(max_day, m, y)
        statement_range = f"{period_start} - {period_end}"

        # 25-40 transactions, sorted by day within the month
        n_txns = rng.randint(25, 40)
        txn_days = sorted(rng.randint(1, max_day) for _ in range(n_txns))

        txn_dates = []
        txn_descs = []
        txn_debits = []
        txn_credits = []

        closing_balance = _rand_amount(rng, 500, 15000)

        for txn_day in txn_days:
            txn_dates.append(_fmt_date(txn_day, m, y))

            is_debit = rng.random() < 0.80  # 80% debits
            template = rng.choice(_BANK_DESCS)
            desc = template.format(
                suburb=suburb,
                merchant=rng.choice(_RETAILERS)[0][:12],
                crn=rng.randint(100000000, 999999999),
                ref=f"REF{rng.randint(10000, 99999)}",
                name=rng.choice(_ACCOUNT_HOLDERS).split()[0],
            )
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
                "SUPPLIER_NAME": bank_name,
                "STATEMENT_DATE_RANGE": statement_range,
                "TRANSACTION_DATES": "|".join(txn_dates),
                "TRANSACTION_DESCRIPTIONS": "|".join(txn_descs),
                "TRANSACTION_AMOUNTS_PAID": "|".join(txn_debits),
                "TRANSACTION_AMOUNTS_RECEIVED": "|".join(txn_credits),
                "ACCOUNT_BALANCE": _fmt_decimal(closing_balance),
                "PAYER_NAME": holder,
            },
        }

    return entries


# ── Receipt generator ─────────────────────────────────────────────────────────


def _generate_receipt_entries(rng: random.Random, count: int) -> dict:
    """Generate receipt ground truth entries with GST-inclusive pricing."""
    entries: dict = {}
    layouts = _RECEIPT_LAYOUTS

    for i in range(count):
        case_id = f"CASER{i + 1:03d}"
        layout = layouts[i % len(layouts)]

        retailer, address, _category = _RETAILERS[i % len(_RETAILERS)]
        # CRITICAL: Always use generate_abn() — do NOT use real-world ABNs from data_pools
        abn = generate_abn()

        d, m, y = _rand_date(rng)
        invoice_date = _fmt_date(d, m, y)

        # 1-6 line items
        n_items = rng.randint(1, 6)
        items = rng.sample(_RECEIPT_ITEMS, min(n_items, len(_RECEIPT_ITEMS)))

        item_descs = []
        item_qtys = []
        item_prices = []  # unit prices (GST-inclusive)
        item_totals = []  # line total (GST-inclusive)

        gst_inclusive_total = Decimal("0")

        for item_name, _unit, lo, hi in items:
            qty = rng.randint(1, 3)
            unit_price = _rand_amount(rng, lo, hi)
            line_total = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            item_descs.append(item_name)
            item_qtys.append(str(qty))
            item_prices.append(_fmt_decimal(unit_price))
            item_totals.append(_fmt_decimal(line_total))
            gst_inclusive_total += line_total

        # GST inclusive: GST = total / 11
        gst_amount = (gst_inclusive_total / Decimal("11")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "RECEIPT",
                "SUPPLIER_NAME": retailer,
                "BUSINESS_ABN": abn,
                "BUSINESS_ADDRESS": address,
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


# ── Invoice generator ─────────────────────────────────────────────────────────


def _generate_invoice_entries(rng: random.Random, count: int) -> dict:
    """Generate invoice ground truth entries with GST-exclusive pricing."""
    entries: dict = {}
    layouts = _INVOICE_LAYOUTS

    for i in range(count):
        case_id = f"CASEI{i + 1:03d}"
        layout = layouts[i % len(layouts)]

        svc_name, svc_address, _category = _PROFESSIONAL_SERVICES[i % len(_PROFESSIONAL_SERVICES)]
        # CRITICAL: Always use generate_abn() — do NOT use real-world ABNs from data_pools
        abn = generate_abn()

        d, m, y = _rand_date(rng)
        invoice_date = _fmt_date(d, m, y)
        # Due date: 30 days later (simple addition)
        due_day = min(d + 30, 28)
        due_m = m + 1 if due_day < d else m
        due_y = y + 1 if due_m > 12 else y
        due_m = due_m % 12 if due_m > 12 else due_m
        if due_m == 0:
            due_m = 12
        payment_due_date = _fmt_date(due_day, due_m, due_y)

        payer = _ACCOUNT_HOLDERS[i % len(_ACCOUNT_HOLDERS)]
        loc = _LOCATIONS[i % len(_LOCATIONS)]
        payer_address = f"{rng.randint(1, 99)} {loc[0]} St, {loc[0]} {loc[2]} {loc[1]}"

        # 1-4 service line items
        n_items = rng.randint(1, 4)
        services = rng.sample(_INVOICE_SERVICES, min(n_items, len(_INVOICE_SERVICES)))

        item_descs = []
        item_qtys = []
        item_prices = []  # unit prices ex-GST
        item_totals = []  # line totals ex-GST

        subtotal_ex_gst = Decimal("0")

        for svc_desc, _unit, lo, hi in services:
            qty = rng.randint(1, 8)
            unit_price = _rand_amount(rng, lo, hi)
            line_total = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            item_descs.append(svc_desc)
            item_qtys.append(str(qty))
            item_prices.append(_fmt_decimal(unit_price))
            item_totals.append(_fmt_decimal(line_total))
            subtotal_ex_gst += line_total

        # GST exclusive: GST = subtotal * 10%
        gst_amount = (subtotal_ex_gst * Decimal("0.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_incl_gst = subtotal_ex_gst + gst_amount

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "INVOICE",
                "SUPPLIER_NAME": svc_name,
                "BUSINESS_ABN": abn,
                "BUSINESS_ADDRESS": svc_address,
                "INVOICE_DATE": invoice_date,
                "IS_GST_INCLUDED": "false",
                "GST_AMOUNT": _fmt_decimal(gst_amount),
                "TOTAL_AMOUNT": _fmt_decimal(total_incl_gst),
                "LINE_ITEM_DESCRIPTIONS": "|".join(item_descs),
                "LINE_ITEM_QUANTITIES": "|".join(item_qtys),
                "LINE_ITEM_PRICES": "|".join(item_prices),
                "LINE_ITEM_TOTAL_PRICES": "|".join(item_totals),
                "PAYER_NAME": payer,
                "PAYER_ADDRESS": payer_address,
            },
        }

    return entries


# ── CC statement generator ────────────────────────────────────────────────────


def _generate_cc_entries(rng: random.Random, count: int) -> dict:
    """Generate credit card statement ground truth entries."""
    entries: dict = {}
    layouts = _CC_LAYOUTS

    for i in range(count):
        case_id = f"CASECC{i + 1:03d}"
        layout = layouts[i % len(layouts)]

        bank_name, bank_code, bsb_prefix = _BANKS[i % len(_BANKS)]
        holder = _ACCOUNT_HOLDERS[i % len(_ACCOUNT_HOLDERS)]
        loc = _LOCATIONS[i % len(_LOCATIONS)]
        suburb = loc[0]

        # Statement period
        d, m, y = _rand_date(rng)
        period_start = _fmt_date(1, m, y)
        max_day = 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31
        period_end = _fmt_date(max_day, m, y)
        statement_range = f"{period_start} - {period_end}"

        # Payment due date: 21 days after period end
        due_d = min(max_day + 21, 28)
        due_m = m + 1 if due_d <= max_day else m
        if due_m > 12:
            due_m = 1
            due_y = y + 1
        else:
            due_y = y
        payment_due_date = _fmt_date(due_d, due_m, due_y)

        # Credit limit
        credit_limit = _rand_amount(rng, 2000, 20000)
        # Round to nearest 500
        credit_limit = Decimal(str(round(float(credit_limit) / 500) * 500))

        # 5-12 transactions
        n_txns = rng.randint(5, 12)
        txn_dates = []
        txn_descs = []
        txn_amounts = []  # positive = charge, negative = payment/credit

        total_charges = Decimal("0")

        for _j in range(n_txns):
            txn_day = rng.randint(1, max_day)
            txn_dates.append(_fmt_date(txn_day, m, y))

            template = rng.choice(_BANK_DESCS)
            desc = template.format(
                suburb=suburb,
                merchant=rng.choice(_RETAILERS)[0][:12],
                crn=rng.randint(100000000, 999999999),
                ref=f"REF{rng.randint(10000, 99999)}",
                name=rng.choice(_ACCOUNT_HOLDERS).split()[0],
            )
            txn_descs.append(desc)

            amt = _rand_amount(rng, 10, 800)
            txn_amounts.append(_fmt_decimal(amt))
            total_charges += amt

        # Closing balance = total of charges
        closing_balance = total_charges

        # Minimum payment: max(25, 2% of balance) rounded to 2dp
        min_payment_pct = (closing_balance * Decimal("0.02")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        minimum_payment = max(Decimal("25.00"), min_payment_pct)

        entries[case_id] = {
            "layout": layout,
            "degradation_seed": rng.randint(1000, 9999),
            "fields": {
                "DOCUMENT_TYPE": "CC_STATEMENT",
                "SUPPLIER_NAME": bank_name,
                "STATEMENT_DATE_RANGE": statement_range,
                "TRANSACTION_DATES": "|".join(txn_dates),
                "TRANSACTION_DESCRIPTIONS": "|".join(txn_descs),
                "TRANSACTION_AMOUNTS_PAID": "|".join(txn_amounts),
                "ACCOUNT_BALANCE": _fmt_decimal(closing_balance),
                "CREDIT_LIMIT": _fmt_decimal(credit_limit),
                "MINIMUM_PAYMENT": _fmt_decimal(minimum_payment),
                "PAYMENT_DUE_DATE": payment_due_date,
                "PAYER_NAME": holder,
            },
        }

    return entries


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Generate all ground truth YAML files with deterministic seed=42."""
    _GT_DIR.mkdir(parents=True, exist_ok=True)

    rng = random.Random(_SEED)

    generators = [
        ("bank_statements.yml", _generate_bank_entries),
        ("receipts.yml", _generate_receipt_entries),
        ("invoices.yml", _generate_invoice_entries),
        ("cc_statements.yml", _generate_cc_entries),
    ]

    for filename, gen_fn in generators:
        entries = gen_fn(rng, _COUNT)
        out_path = _GT_DIR / filename
        with out_path.open("w", encoding="utf-8") as fh:
            yaml.dump(entries, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"Wrote {len(entries)} entries to {out_path}")


if __name__ == "__main__":
    main()
