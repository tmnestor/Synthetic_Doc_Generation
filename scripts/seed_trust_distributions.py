"""Ground truth seed generator for trust distribution document quads.

Generates 50 document quads (200 entries across 4 YAML files):
- 35 compliant cases: all 5 linking fields reconcile perfectly
- 15 non-compliant cases: deliberate amount discrepancies injected

Non-compliance types:
  - Under-reported income (~5 cases): ITR reports 60-90% of actual share
  - Over-claimed franking (~4 cases): ITR claims 110-150% of actual franking
  - Missing CGT (~3 cases): Trust Income Schedule reports $0 CGT despite non-zero
  - Trust Return mismatch (~3 cases): Trust Return share differs by 5-20%

Each case's shared entities (trust, trustee, beneficiary) are generated once
via content_engine and projected across that case's 4 trust documents, so
widened content never desyncs a trust_distribution_links.yml quad.

Usage:
    python scripts/seed_trust_distributions.py [--dry-run]
"""

import random
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import typer
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from generators.common import generate_tfn  # noqa: E402
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
_TOTAL_CASES = 50
_COMPLIANT_CASES = 35
_NON_COMPLIANT_CASES = 15
_GT_DIR = Path(__file__).parent.parent / "ground_truth"

# Case ID offset to avoid collision with existing CASE001-CASE055
_CASE_ID_START = 201

# ── Layout IDs (structural, not content — unchanged) ────────────────────────
_TRUST_RETURN_LAYOUTS = ["trust_return_standard"]
_DISTRIBUTION_STATEMENT_LAYOUTS = [
    "dist_software_navy",
    "dist_software_teal",
    "dist_table_plain",
    "dist_table_ruled",
    "dist_letter_formal",
    "dist_letter_compact",
]
_TRUST_INCOME_SCHEDULE_LAYOUTS = ["trust_income_schedule_standard"]
_BENEFICIARY_ITR_LAYOUTS = ["beneficiary_itr_standard"]

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


def _generate_cases(engine: ContentEngine, rng: random.Random) -> tuple[dict, dict, dict, dict]:
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

    discrepancy_list = list(_DISCREPANCY_TYPES)
    rng.shuffle(discrepancy_list)
    discrepancy_idx = 0

    tr_layout_draw = NonRepeatingSampler(rng, _TRUST_RETURN_LAYOUTS)
    ds_layout_draw = NonRepeatingSampler(rng, _DISTRIBUTION_STATEMENT_LAYOUTS)
    tis_layout_draw = NonRepeatingSampler(rng, _TRUST_INCOME_SCHEDULE_LAYOUTS)
    itr_layout_draw = NonRepeatingSampler(rng, _BENEFICIARY_ITR_LAYOUTS)

    for i in range(_TOTAL_CASES):
        case_num = _CASE_ID_START + i
        case_id = f"CASE{case_num:03d}"
        is_compliant = i < _COMPLIANT_CASES

        # --- Identity generation ---
        trust = engine.fictional_trust(rng)
        trust_name = trust["trust_name"]
        trustee_name = trust["trustee_name"]
        trust_abn = trust["abn"]
        trust_tfn = trust["tfn"]
        trust_address = engine.address(rng)

        beneficiary = engine.person(rng)
        beneficiary_name = beneficiary["full_name"]
        beneficiary_tfn = generate_tfn()
        beneficiary_address = engine.address(rng)
        beneficiary_dob = _rand_dob(rng)

        income_year = sample(rng, engine.pools["income_years"])
        distribution_date = _rand_date(rng, 2024, 2024)

        # --- Source of truth amounts (unchanged financial logic) ---
        total_net_income = _rand_amount(rng, 10000, 500000)
        num_beneficiaries = rng.randint(1, 4)
        share_of_net_income = (total_net_income / Decimal(str(num_beneficiaries))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        franking_pct = Decimal(str(rng.uniform(0, 0.30)))
        franking_credit = (share_of_net_income * franking_pct).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        if rng.random() < 0.25:
            capital_gain = Decimal("0.00")
        else:
            cgt_pct = Decimal(str(rng.uniform(0.05, 0.40)))
            capital_gain = (share_of_net_income * cgt_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if rng.random() < 0.80:
            foreign_income = Decimal("0.00")
        else:
            foreign_income = _rand_amount(rng, 100, 5000)

        tax_free = Decimal("0.00")
        tax_deferred = Decimal("0.00")
        if rng.random() < 0.10:
            tax_free = _rand_amount(rng, 100, 2000)
        if rng.random() < 0.08:
            tax_deferred = _rand_amount(rng, 100, 1500)

        # --- Values that go into each document ---
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

        # --- Inject discrepancies for non-compliant cases ---
        if not is_compliant:
            discrepancy_type = discrepancy_list[discrepancy_idx]
            discrepancy_idx += 1

            if discrepancy_type == "under_reported_income":
                reduction = Decimal(str(rng.uniform(0.60, 0.90)))
                itr_total_trust_income = (share_of_net_income * reduction).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            elif discrepancy_type == "over_claimed_franking":
                inflation = Decimal(str(rng.uniform(1.10, 1.50)))
                itr_franking = (franking_credit * inflation).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            elif discrepancy_type == "missing_cgt":
                if capital_gain == Decimal("0.00"):
                    capital_gain = _rand_amount(rng, 2000, 20000)
                    ds_cgt = capital_gain
                    tr_cgt = capital_gain
                tis_cgt = Decimal("0.00")

            elif discrepancy_type == "trust_return_mismatch":
                variance = Decimal(str(rng.uniform(0.05, 0.20)))
                direction = rng.choice([1, -1])
                tr_share = (share_of_net_income * (Decimal("1") + direction * variance)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

        # --- Layout and seed assignment ---
        tr_layout = tr_layout_draw.draw()
        ds_layout = ds_layout_draw.draw()
        tis_layout = tis_layout_draw.draw()
        itr_layout = itr_layout_draw.draw()

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


def _validate_dry_run(all_entries: dict[str, dict]) -> None:
    """Validate generated entries in-memory (schema + overflow) without writing YAML."""
    from generators.beneficiary_itr import render_beneficiary_itr
    from generators.distribution_statement import render_distribution_statement
    from generators.trust_income_schedule import render_trust_income_schedule
    from generators.trust_return import render_trust_return

    renderer_map = {
        "trust_returns.yml": (render_trust_return, "config/layouts/trust_returns.yml"),
        "distribution_statements.yml": (
            render_distribution_statement,
            "config/layouts/distribution_statements.yml",
        ),
        "trust_income_schedules.yml": (
            render_trust_income_schedule,
            "config/layouts/trust_income_schedules.yml",
        ),
        "beneficiary_itrs.yml": (render_beneficiary_itr, "config/layouts/beneficiary_itrs.yml"),
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
            "  Where:    scripts/seed_trust_distributions.py._generate_cases and the "
            "config/data_pools.yml content it draws from.\n"
            "  Expected: every generated entry passes schema validation and renders "
            "within its layout's field_budgets (no FitError).\n"
            "  Recover:  fix the failing generator logic or widen the offending pool/budget, "
            "then rerun `python scripts/seed_trust_distributions.py --dry-run`."
        )


def main(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate in-memory; do not write ground_truth/*.yml"
    ),
) -> None:
    """Generate all trust distribution ground truth YAML files with deterministic seed=42."""
    rng = random.Random(_SEED)
    engine = build_engine()
    tr, ds, tis, itr = _generate_cases(engine, rng)

    outputs = [
        ("trust_returns.yml", tr),
        ("distribution_statements.yml", ds),
        ("trust_income_schedules.yml", tis),
        ("beneficiary_itrs.yml", itr),
    ]

    if dry_run:
        _validate_dry_run(dict(outputs))
        print("Dry run: all entries validated in-memory; ground_truth/*.yml NOT written.")
        return

    _GT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, entries in outputs:
        out_path = _GT_DIR / filename
        with out_path.open("w", encoding="utf-8") as fh:
            yaml.dump(entries, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"Wrote {len(entries)} entries to {out_path}")


if __name__ == "__main__":
    typer.run(main)
