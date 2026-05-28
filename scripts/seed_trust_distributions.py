"""Ground truth seed generator for trust distribution document quads.

Generates 50 document quads (200 entries across 4 YAML files):
- 35 compliant cases: all 5 linking fields reconcile perfectly
- 15 non-compliant cases: deliberate amount discrepancies injected

Non-compliance types:
  - Under-reported income (~5 cases): ITR reports 60-90% of actual share
  - Over-claimed franking (~4 cases): ITR claims 110-150% of actual franking
  - Missing CGT (~3 cases): Trust Income Schedule reports $0 CGT despite non-zero
  - Trust Return mismatch (~3 cases): Trust Return share differs by 5-20%

Usage:
    python scripts/seed_trust_distributions.py
"""

import random
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from generators.common import generate_abn, generate_tfn  # noqa: E402

_SEED = 42
_TOTAL_CASES = 50
_COMPLIANT_CASES = 35
_NON_COMPLIANT_CASES = 15
_GT_DIR = Path(__file__).parent.parent / "ground_truth"

# Case ID offset to avoid collision with existing CASE001-CASE055
_CASE_ID_START = 201

# ── Layout IDs ──────────────────────────────────────────────────────────────

_TRUST_RETURN_LAYOUTS = ["trust_return_standard"]
_DISTRIBUTION_STATEMENT_LAYOUTS = ["distribution_statement_standard"]
_TRUST_INCOME_SCHEDULE_LAYOUTS = ["trust_income_schedule_standard"]
_BENEFICIARY_ITR_LAYOUTS = ["beneficiary_itr_standard"]

# ── Data pools ──────────────────────────────────────────────────────────────

_TRUST_NAMES = [
    "Smith Family Trust",
    "Johnson Discretionary Trust",
    "Williams Family Trust",
    "Chen Investment Trust",
    "Brown Family Trust",
    "Taylor Discretionary Trust",
    "Anderson Family Trust",
    "Wilson Investment Trust",
    "Martin Family Trust",
    "Thompson Discretionary Trust",
    "Robinson Family Trust",
    "Harris Investment Trust",
    "Clark Family Trust",
    "Lee Discretionary Trust",
    "White Family Trust",
    "Nguyen Investment Trust",
    "Mitchell Family Trust",
    "Campbell Discretionary Trust",
    "Stewart Family Trust",
    "Cooper Investment Trust",
    "Murray Family Trust",
    "Kelly Discretionary Trust",
    "Parker Family Trust",
    "Hughes Investment Trust",
    "Morgan Family Trust",
]

_TRUSTEE_NAMES = [
    "Smith Holdings Pty Ltd",
    "Johnson Corp Pty Ltd",
    "Williams Investments Pty Ltd",
    "Chen Capital Pty Ltd",
    "Brown Group Pty Ltd",
    "Taylor Enterprises Pty Ltd",
    "Anderson Holdings Pty Ltd",
    "Wilson Capital Pty Ltd",
    "Martin Group Pty Ltd",
    "Thompson Holdings Pty Ltd",
    "Robinson Investments Pty Ltd",
    "Harris Capital Pty Ltd",
    "Clark Group Pty Ltd",
    "Lee Enterprises Pty Ltd",
    "White Holdings Pty Ltd",
    "Nguyen Capital Pty Ltd",
    "Mitchell Group Pty Ltd",
    "Campbell Holdings Pty Ltd",
    "Stewart Investments Pty Ltd",
    "Cooper Capital Pty Ltd",
    "Murray Group Pty Ltd",
    "Kelly Enterprises Pty Ltd",
    "Parker Holdings Pty Ltd",
    "Hughes Capital Pty Ltd",
    "Morgan Group Pty Ltd",
]

_BENEFICIARY_FIRST_NAMES = [
    "Sarah",
    "Michael",
    "Emma",
    "David",
    "Jessica",
    "James",
    "Olivia",
    "Daniel",
    "Sophie",
    "Ryan",
    "Hannah",
    "Thomas",
    "Mia",
    "William",
    "Charlotte",
    "Alexander",
    "Grace",
    "Benjamin",
    "Chloe",
    "Ethan",
    "Isabella",
    "Noah",
    "Amelia",
    "Liam",
    "Emily",
]

_BENEFICIARY_LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Chen",
    "Brown",
    "Taylor",
    "Anderson",
    "Wilson",
    "Martin",
    "Thompson",
    "Robinson",
    "Harris",
    "Clark",
    "Lee",
    "White",
    "Nguyen",
    "Mitchell",
    "Campbell",
    "Stewart",
    "Cooper",
    "Murray",
    "Kelly",
    "Parker",
    "Hughes",
    "Morgan",
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

# Non-compliance type assignments (must sum to _NON_COMPLIANT_CASES = 15)
_DISCREPANCY_TYPES = (
    ["under_reported_income"] * 5
    + ["over_claimed_franking"] * 4
    + ["missing_cgt"] * 3
    + ["trust_return_mismatch"] * 3
)


def _fmt_decimal(d: Decimal) -> str:
    """Format Decimal as plain string with 2dp (no $ sign)."""
    return f"{d:.2f}"


def _rand_amount(rng: random.Random, lo: float, hi: float) -> Decimal:
    """Generate a random Decimal amount in [lo, hi] rounded to 2dp."""
    raw = rng.uniform(lo, hi)
    return Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _rand_date(rng: random.Random, year_start: int = 2023, year_end: int = 2024) -> str:
    """Generate a random date as DD/MM/YYYY."""
    year = rng.randint(year_start, year_end)
    month = rng.randint(1, 12)
    max_day = 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31
    day = rng.randint(1, max_day)
    return f"{day:02d}/{month:02d}/{year}"


def _rand_dob(rng: random.Random) -> str:
    """Generate a random date of birth for an adult (25-70 years old)."""
    year = rng.randint(1954, 1999)
    month = rng.randint(1, 12)
    max_day = 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31
    day = rng.randint(1, max_day)
    return f"{day:02d}/{month:02d}/{year}"


def _generate_address(rng: random.Random) -> str:
    """Generate a random Australian address."""
    loc = rng.choice(_LOCATIONS)
    street_num = rng.randint(1, 200)
    street_names = [
        "Main St",
        "George St",
        "Collins St",
        "King William St",
        "Bourke St",
        "Pitt St",
        "Queen St",
        "Flinders St",
        "Elizabeth St",
        "Murray St",
        "Adelaide St",
        "Victoria Ave",
    ]
    street = rng.choice(street_names)
    return f"{street_num} {street}, {loc[0]} {loc[2]} {loc[1]}"


def _generate_cases(rng: random.Random) -> tuple[dict, dict, dict, dict]:
    """Generate all 50 document quads.

    Returns:
        Four dicts (trust_returns, distribution_statements,
        trust_income_schedules, beneficiary_itrs), each mapping
        CASE IDs to ground truth entries.
    """
    trust_returns: dict = {}
    distribution_statements: dict = {}
    trust_income_schedules: dict = {}
    beneficiary_itrs: dict = {}

    # Shuffle discrepancy types for non-compliant cases
    discrepancy_list = list(_DISCREPANCY_TYPES)
    rng.shuffle(discrepancy_list)
    discrepancy_idx = 0

    for i in range(_TOTAL_CASES):
        case_num = _CASE_ID_START + i
        case_id = f"CASE{case_num:03d}"
        is_compliant = i < _COMPLIANT_CASES

        # --- Identity generation ---
        trust_idx = i % len(_TRUST_NAMES)
        trust_name = _TRUST_NAMES[trust_idx]
        trustee_name = f"{_TRUSTEE_NAMES[trust_idx]} ATF {trust_name}"
        trust_abn = generate_abn()
        trust_tfn = generate_tfn()
        trust_address = _generate_address(rng)

        beneficiary_first = _BENEFICIARY_FIRST_NAMES[i % len(_BENEFICIARY_FIRST_NAMES)]
        beneficiary_last = _BENEFICIARY_LAST_NAMES[i % len(_BENEFICIARY_LAST_NAMES)]
        beneficiary_name = f"{beneficiary_first} {beneficiary_last}"
        beneficiary_tfn = generate_tfn()
        beneficiary_address = _generate_address(rng)
        beneficiary_dob = _rand_dob(rng)

        income_year = "2023-24"
        distribution_date = _rand_date(rng, 2024, 2024)

        # --- Source of truth amounts ---
        total_net_income = _rand_amount(rng, 10000, 500000)
        num_beneficiaries = rng.randint(1, 4)
        share_of_net_income = (total_net_income / Decimal(str(num_beneficiaries))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Franking credit: 0-30% of share
        franking_pct = Decimal(str(rng.uniform(0, 0.30)))
        franking_credit = (share_of_net_income * franking_pct).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Capital gain component: 0-40% of share (some cases $0)
        if rng.random() < 0.25:
            capital_gain = Decimal("0.00")
        else:
            cgt_pct = Decimal(str(rng.uniform(0.05, 0.40)))
            capital_gain = (share_of_net_income * cgt_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Foreign income: $0 in ~80% of cases
        if rng.random() < 0.80:
            foreign_income = Decimal("0.00")
        else:
            foreign_income = _rand_amount(rng, 100, 5000)

        # Tax-free / tax-deferred: $0 in most cases
        tax_free = Decimal("0.00")
        tax_deferred = Decimal("0.00")
        if rng.random() < 0.10:
            tax_free = _rand_amount(rng, 100, 2000)
        if rng.random() < 0.08:
            tax_deferred = _rand_amount(rng, 100, 1500)

        # --- Values that go into each document ---
        # Start with source of truth for all documents
        tr_share = share_of_net_income
        tr_franking = franking_credit
        tr_cgt = capital_gain

        ds_share = share_of_net_income
        ds_franking = franking_credit
        ds_cgt = capital_gain

        tis_share = share_of_net_income
        tis_franking = franking_credit
        tis_cgt = capital_gain

        itr_total_trust_income = share_of_net_income
        itr_franking = franking_credit

        discrepancy_type = None
        discrepancy_details = None

        # --- Inject discrepancies for non-compliant cases ---
        if not is_compliant:
            discrepancy_type = discrepancy_list[discrepancy_idx]
            discrepancy_idx += 1

            if discrepancy_type == "under_reported_income":
                # ITR reports 60-90% of actual share
                reduction = Decimal(str(rng.uniform(0.60, 0.90)))
                itr_total_trust_income = (share_of_net_income * reduction).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                discrepancy_details = (
                    f"ITR reports ${_fmt_decimal(itr_total_trust_income)} trust income "
                    f"but Distribution Statement shows ${_fmt_decimal(share_of_net_income)}"
                )

            elif discrepancy_type == "over_claimed_franking":
                # ITR claims 110-150% of actual franking credit
                inflation = Decimal(str(rng.uniform(1.10, 1.50)))
                itr_franking = (franking_credit * inflation).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                discrepancy_details = (
                    f"ITR claims ${_fmt_decimal(itr_franking)} franking credit "
                    f"but Distribution Statement shows ${_fmt_decimal(franking_credit)}"
                )

            elif discrepancy_type == "missing_cgt":
                # Ensure source of truth has non-zero CGT
                if capital_gain == Decimal("0.00"):
                    capital_gain = _rand_amount(rng, 2000, 20000)
                    ds_cgt = capital_gain
                    tr_cgt = capital_gain
                # Trust Income Schedule reports $0
                tis_cgt = Decimal("0.00")
                discrepancy_details = (
                    f"Distribution Statement shows ${_fmt_decimal(capital_gain)} CGT "
                    f"but Trust Income Schedule reports $0.00"
                )

            elif discrepancy_type == "trust_return_mismatch":
                # Trust Return share differs by 5-20%
                variance = Decimal(str(rng.uniform(0.05, 0.20)))
                direction = rng.choice([1, -1])
                tr_share = (share_of_net_income * (Decimal("1") + direction * variance)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                discrepancy_details = (
                    f"Trust Return Item 57 shows ${_fmt_decimal(tr_share)} "
                    f"but Distribution Statement shows ${_fmt_decimal(share_of_net_income)}"
                )

        # --- Layout and seed assignment ---
        tr_layout = _TRUST_RETURN_LAYOUTS[i % len(_TRUST_RETURN_LAYOUTS)]
        ds_layout = _DISTRIBUTION_STATEMENT_LAYOUTS[i % len(_DISTRIBUTION_STATEMENT_LAYOUTS)]
        tis_layout = _TRUST_INCOME_SCHEDULE_LAYOUTS[i % len(_TRUST_INCOME_SCHEDULE_LAYOUTS)]
        itr_layout = _BENEFICIARY_ITR_LAYOUTS[i % len(_BENEFICIARY_ITR_LAYOUTS)]

        degradation_seed = rng.randint(1000, 9999)

        # --- Build entries ---
        trust_returns[case_id] = {
            "layout": tr_layout,
            "degradation_seed": degradation_seed,
            "fields": {
                "DOCUMENT_TYPE": "TRUST_RETURN",
                "TRUST_NAME": trust_name,
                "TRUST_TFN": trust_tfn,
                "TRUST_ABN": trust_abn,
                "TRUSTEE_NAME": trustee_name,
                "TRUST_ADDRESS": trust_address,
                "INCOME_YEAR": income_year,
                "TOTAL_NET_INCOME": _fmt_decimal(total_net_income),
                "BENEFICIARY_NAME": beneficiary_name,
                "BENEFICIARY_TFN": beneficiary_tfn,
                "SHARE_OF_NET_INCOME": _fmt_decimal(tr_share),
                "FRANKING_CREDIT": _fmt_decimal(tr_franking),
                "CAPITAL_GAIN_COMPONENT": _fmt_decimal(tr_cgt),
                "FOREIGN_INCOME": _fmt_decimal(foreign_income),
            },
        }

        distribution_statements[case_id] = {
            "layout": ds_layout,
            "degradation_seed": degradation_seed + 1,
            "fields": {
                "DOCUMENT_TYPE": "DISTRIBUTION_STATEMENT",
                "TRUST_NAME": trust_name,
                "TRUST_ABN": trust_abn,
                "TRUST_ADDRESS": trust_address,
                "DATE_OF_DISTRIBUTION": distribution_date,
                "INCOME_YEAR": income_year,
                "BENEFICIARY_NAME": beneficiary_name,
                "BENEFICIARY_TFN": beneficiary_tfn,
                "BENEFICIARY_ADDRESS": beneficiary_address,
                "SHARE_OF_NET_INCOME": _fmt_decimal(ds_share),
                "FRANKING_CREDIT": _fmt_decimal(ds_franking),
                "CAPITAL_GAIN_COMPONENT": _fmt_decimal(ds_cgt),
                "FOREIGN_INCOME": _fmt_decimal(foreign_income),
                "TAX_FREE_AMOUNT": _fmt_decimal(tax_free),
                "TAX_DEFERRED_AMOUNT": _fmt_decimal(tax_deferred),
            },
        }

        trust_income_schedules[case_id] = {
            "layout": tis_layout,
            "degradation_seed": degradation_seed + 2,
            "fields": {
                "DOCUMENT_TYPE": "TRUST_INCOME_SCHEDULE",
                "TRUST_NAME": trust_name,
                "TRUST_ABN": trust_abn,
                "BENEFICIARY_NAME": beneficiary_name,
                "BENEFICIARY_TFN": beneficiary_tfn,
                "SHARE_OF_NET_INCOME": _fmt_decimal(tis_share),
                "FRANKING_CREDIT": _fmt_decimal(tis_franking),
                "CAPITAL_GAIN_COMPONENT": _fmt_decimal(tis_cgt),
                "FOREIGN_INCOME": _fmt_decimal(foreign_income),
            },
        }

        beneficiary_itrs[case_id] = {
            "layout": itr_layout,
            "degradation_seed": degradation_seed + 3,
            "fields": {
                "DOCUMENT_TYPE": "BENEFICIARY_ITR",
                "INDIVIDUAL_NAME": beneficiary_name,
                "INDIVIDUAL_TFN": beneficiary_tfn,
                "DATE_OF_BIRTH": beneficiary_dob,
                "INDIVIDUAL_ADDRESS": beneficiary_address,
                "TOTAL_TRUST_INCOME": _fmt_decimal(itr_total_trust_income),
                "TRUST_FRANKING_CREDIT": _fmt_decimal(itr_franking),
            },
        }

    return trust_returns, distribution_statements, trust_income_schedules, beneficiary_itrs


def main() -> None:
    """Generate all trust distribution ground truth YAML files with deterministic seed=42."""
    _GT_DIR.mkdir(parents=True, exist_ok=True)

    rng = random.Random(_SEED)
    tr, ds, tis, itr = _generate_cases(rng)

    outputs = [
        ("trust_returns.yml", tr),
        ("distribution_statements.yml", ds),
        ("trust_income_schedules.yml", tis),
        ("beneficiary_itrs.yml", itr),
    ]

    for filename, entries in outputs:
        out_path = _GT_DIR / filename
        with out_path.open("w", encoding="utf-8") as fh:
            yaml.dump(entries, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"Wrote {len(entries)} entries to {out_path}")


if __name__ == "__main__":
    main()
