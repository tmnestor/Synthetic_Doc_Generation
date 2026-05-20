"""Generate transaction linking ground truth from existing ground truth entries.

Reads receipts.yml, invoices.yml, and bank_statements.yml, then creates
matching pairs in transaction_links.yml. Assigns difficulty levels based
on date proximity and description similarity.

Usage:
    python scripts/seed_transaction_links.py
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import yaml


def _load_gt(name: str) -> dict:
    path = Path(f"ground_truth/{name}.yml")
    return yaml.safe_load(path.read_text())


def _parse_date(date_str: str) -> datetime | None:
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y")
    except (ValueError, AttributeError):
        return None


def main() -> None:
    rng = random.Random(42)
    receipts = _load_gt("receipts")
    invoices = _load_gt("invoices")
    bank_stmts = _load_gt("bank_statements")

    links: dict = {}
    link_idx = 0

    # For each receipt/invoice, find or create a matching bank transaction
    sources = [
        *[(cid, entry, "RECEIPT") for cid, entry in receipts.items()],
        *[(cid, entry, "INVOICE") for cid, entry in invoices.items()],
    ]

    bank_list = list(bank_stmts.items())

    for src_id, src_entry, src_type in sources:
        src_fields = src_entry["fields"]
        src_total = src_fields.get("TOTAL_AMOUNT", "")
        src_date_str = src_fields.get("INVOICE_DATE", "")
        src_date = _parse_date(src_date_str)

        if not src_total or not src_date:
            continue

        # Assign to a random bank statement
        bank_id, bank_entry = rng.choice(bank_list)
        bank_fields = bank_entry["fields"]

        # Find matching amount in bank transactions
        bank_amounts = bank_fields.get("TRANSACTION_AMOUNTS_PAID", "").split("|")
        bank_dates = bank_fields.get("TRANSACTION_DATES", "").split("|")

        # Try to find exact amount match
        matched_idx = None
        for idx, amt in enumerate(bank_amounts):
            if amt.strip() == src_total:
                matched_idx = idx
                break

        # If no match, inject the amount into a random position
        if matched_idx is None:
            matched_idx = rng.randint(0, len(bank_amounts) - 1)
            bank_amounts[matched_idx] = src_total
            bank_fields["TRANSACTION_AMOUNTS_PAID"] = "|".join(bank_amounts)

            # Also set the date
            if matched_idx < len(bank_dates):
                # Determine difficulty
                difficulty = rng.choice(["easy", "easy", "medium", "medium", "hard"])
                if difficulty == "easy":
                    bank_dates[matched_idx] = src_date_str
                elif difficulty == "medium":
                    offset = rng.randint(1, 3)
                    new_date = src_date + timedelta(days=offset)
                    bank_dates[matched_idx] = new_date.strftime("%d/%m/%Y")
                else:
                    offset = rng.randint(3, 7)
                    new_date = src_date + timedelta(days=offset)
                    bank_dates[matched_idx] = new_date.strftime("%d/%m/%Y")
            else:
                difficulty = "easy"

            bank_fields["TRANSACTION_DATES"] = "|".join(bank_dates)
        else:
            # Determine difficulty from date match
            if matched_idx < len(bank_dates):
                bank_date = _parse_date(bank_dates[matched_idx])
                if bank_date and src_date:
                    delta = abs((bank_date - src_date).days)
                    if delta == 0:
                        difficulty = "easy"
                    elif delta <= 3:
                        difficulty = "medium"
                    else:
                        difficulty = "hard"
                else:
                    difficulty = "easy"
            else:
                difficulty = "easy"

        link_idx += 1
        link_key = f"LINK{link_idx:03d}"
        links[link_key] = {
            "source_type": src_type,
            "source_id": src_id,
            "target_type": "BANK_STATEMENT",
            "target_id": bank_id,
            "target_transaction_index": matched_idx,
            "match_fields": {
                "date": src_date_str,
                "amount": src_total,
            },
            "match_difficulty": difficulty,
        }

    # Write updated bank statements (with injected amounts)
    Path("ground_truth/bank_statements.yml").write_text(
        yaml.dump(dict(bank_stmts), default_flow_style=False, sort_keys=False)
    )

    # Write links
    Path("ground_truth/transaction_links.yml").write_text(
        yaml.dump(links, default_flow_style=False, sort_keys=False)
    )

    # Stats
    difficulties: dict[str, int] = {}
    for link in links.values():
        d = link["match_difficulty"]
        difficulties[d] = difficulties.get(d, 0) + 1
    print(f"Generated {len(links)} transaction links: {difficulties}")


if __name__ == "__main__":
    main()
