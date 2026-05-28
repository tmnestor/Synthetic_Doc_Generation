"""Generate trust distribution linking ground truth from document quad entries.

Reads trust_returns.yml, distribution_statements.yml, trust_income_schedules.yml,
and beneficiary_itrs.yml, then creates trust_distribution_links.yml with
4-document quad linking records and compliance metadata.

Usage:
    python scripts/seed_trust_distribution_links.py
"""

import sys
from decimal import Decimal
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

_GT_DIR = Path(__file__).parent.parent / "ground_truth"

# Non-compliance assignments — must match seed_trust_distributions.py
# Cases 201-235 are compliant, 236-250 are non-compliant
_COMPLIANT_CASES = 35
_CASE_ID_START = 201
_TOTAL_CASES = 50

# Discrepancy type assignments — same shuffle order as seed script (seed=42)

_DISCREPANCY_TYPES_ORDERED = (
    ["under_reported_income"] * 5
    + ["over_claimed_franking"] * 4
    + ["missing_cgt"] * 3
    + ["trust_return_mismatch"] * 3
)


def _load_gt(name: str) -> dict:
    path = _GT_DIR / f"{name}.yml"
    return yaml.safe_load(path.read_text())


def _detect_discrepancy(
    tr_fields: dict,
    ds_fields: dict,
    tis_fields: dict,
    itr_fields: dict,
) -> tuple[str, str | None, str | None]:
    """Detect discrepancy type by comparing field values across documents.

    Returns:
        (compliance_status, discrepancy_type, discrepancy_details)
    """
    ds_share = Decimal(ds_fields["SHARE_OF_NET_INCOME"])
    tr_share = Decimal(tr_fields["SHARE_OF_NET_INCOME"])
    tis_share = Decimal(tis_fields["SHARE_OF_NET_INCOME"])
    itr_income = Decimal(itr_fields["TOTAL_TRUST_INCOME"])

    ds_franking = Decimal(ds_fields["FRANKING_CREDIT"])
    itr_franking = Decimal(itr_fields["TRUST_FRANKING_CREDIT"])

    ds_cgt = Decimal(ds_fields["CAPITAL_GAIN_COMPONENT"])
    tis_cgt = Decimal(tis_fields["CAPITAL_GAIN_COMPONENT"])

    # Check Trust Return vs Distribution Statement share mismatch
    if tr_share != ds_share:
        return (
            "non_compliant",
            "trust_return_mismatch",
            f"Trust Return Item 57 shows ${tr_share:.2f} but Distribution Statement shows ${ds_share:.2f}",
        )

    # Check under-reported income (ITR vs Distribution Statement)
    if itr_income != ds_share:
        return (
            "non_compliant",
            "under_reported_income",
            f"ITR reports ${itr_income:.2f} trust income but Distribution Statement shows ${ds_share:.2f}",
        )

    # Check over-claimed franking (ITR vs Distribution Statement)
    if itr_franking != ds_franking:
        return (
            "non_compliant",
            "over_claimed_franking",
            f"ITR claims ${itr_franking:.2f} franking credit "
            f"but Distribution Statement shows ${ds_franking:.2f}",
        )

    # Check missing CGT (Trust Income Schedule vs Distribution Statement)
    if ds_cgt != Decimal("0.00") and tis_cgt == Decimal("0.00"):
        return (
            "non_compliant",
            "missing_cgt",
            f"Distribution Statement shows ${ds_cgt:.2f} CGT but Trust Income Schedule reports $0.00",
        )

    return ("compliant", None, None)


def main() -> None:
    trust_returns = _load_gt("trust_returns")
    distribution_statements = _load_gt("distribution_statements")
    trust_income_schedules = _load_gt("trust_income_schedules")
    beneficiary_itrs = _load_gt("beneficiary_itrs")

    links: dict = {}

    compliant_count = 0
    non_compliant_count = 0

    for case_num in range(_CASE_ID_START, _CASE_ID_START + _TOTAL_CASES):
        case_id = f"CASE{case_num:03d}"

        tr_entry = trust_returns[case_id]
        ds_entry = distribution_statements[case_id]
        tis_entry = trust_income_schedules[case_id]
        itr_entry = beneficiary_itrs[case_id]

        tr_fields = tr_entry["fields"]
        ds_fields = ds_entry["fields"]
        tis_fields = tis_entry["fields"]
        itr_fields = itr_entry["fields"]

        # Build image filenames
        tr_filename = f"{case_id}_{tr_entry['layout']}.png"
        ds_filename = f"{case_id}_{ds_entry['layout']}.png"
        tis_filename = f"{case_id}_{tis_entry['layout']}.png"
        itr_filename = f"{case_id}_{itr_entry['layout']}.png"

        # Detect compliance status by comparing actual field values
        compliance_status, discrepancy_type, discrepancy_details = _detect_discrepancy(
            tr_fields,
            ds_fields,
            tis_fields,
            itr_fields,
        )

        if compliance_status == "compliant":
            compliant_count += 1
        else:
            non_compliant_count += 1

        # Linking fields from the Distribution Statement (source of truth)
        links[ds_filename] = {
            "trust_return": tr_filename,
            "trust_income_schedule": tis_filename,
            "beneficiary_itr": itr_filename,
            "linking_fields": {
                "trust_abn": ds_fields["TRUST_ABN"],
                "beneficiary_tfn": ds_fields["BENEFICIARY_TFN"],
                "share_of_net_income": ds_fields["SHARE_OF_NET_INCOME"],
                "franking_credit": ds_fields["FRANKING_CREDIT"],
                "capital_gain_component": ds_fields["CAPITAL_GAIN_COMPONENT"],
            },
            "compliance_status": compliance_status,
            "discrepancy_type": discrepancy_type,
            "discrepancy_details": discrepancy_details,
            "match_status": "FOUND",
        }

    # Write links
    out_path = _GT_DIR / "trust_distribution_links.yml"
    with out_path.open("w", encoding="utf-8") as fh:
        yaml.dump(links, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(
        f"Generated {len(links)} trust distribution links: "
        f"{compliant_count} compliant, {non_compliant_count} non-compliant"
    )


if __name__ == "__main__":
    main()
