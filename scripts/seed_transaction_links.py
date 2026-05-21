"""Generate transaction linking ground truth from existing ground truth entries.

Reads receipts.yml, invoices.yml, and bank_statements.yml, then creates
matching pairs in transaction_links.yml. Produces a denormalized format keyed
by image filenames for direct consumption by the LMM evaluation pipeline.

Usage:
    python scripts/seed_transaction_links.py
"""

import random
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# Bank description shorthands matching real Australian bank statement conventions.
# Derived from existing TRANSACTION_DESCRIPTIONS in bank_statements.yml and
# the transaction_patterns section of config/data_pools.yml.
_RECEIPT_SHORTHANDS: dict[str, str] = {
    "Bunnings Warehouse": "BUNNINGS W/HOUSE",
    "Woolworths": "WOOLWORTHS",
    "Coles": "COLES",
    "Officeworks": "OFFICEWORKS",
    "JB Hi-Fi": "JB HI-FI",
    "Harvey Norman": "HARVEY NORMAN",
    "Kmart Australia": "KMART",
    "Big W": "Big W",
    "Chemist Warehouse": "CHEMIST WHSE",
    "Dan Murphy's": "DAN MURPHYS",
    "BP Australia": "BP",
    "Shell Australia": "SHELL",
    "Ampol Limited": "AMPOL",
    "7-Eleven Australia": "7-Eleven Aus",
    "Myer": "Myer",
    "David Jones": "David Jones",
    "Target Australia": "TARGET",
    "Spotlight": "SPOTLIGHT",
    "Supercheap Auto": "SUPERCHEAP AUTO",
    "Repco": "REPCO",
}

_INVOICE_SHORTHANDS: dict[str, str] = {
    "Smith & Associates Accounting": "SMITH ASSOCIATES",
    "Johnson Legal": "JOHNSON LEGAL",
    "Brisbane IT Solutions": "BRISBANE IT SOLUTIONS",
    "Adelaide Business Consulting": "ADELAIDE BUS CONSULTING",
    "Perth Marketing Group": "PERTH MARKETING GROUP",
}

# EFTPOS vs VISA DEBIT prefixes for retail transactions.
_RETAIL_PREFIXES = [
    ("EFTPOS", "AUS"),
    ("VISA DEBIT PURCHASE", "AU"),
]

# Payment prefixes for professional service invoices.
_INVOICE_PREFIXES = ["BPAY", "DIRECT DEBIT", "EFT PAYMENT"]


def _load_gt(name: str) -> dict:
    path = Path(f"ground_truth/{name}.yml")
    return yaml.safe_load(path.read_text())


def _parse_date(date_str: str) -> datetime | None:
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y")
    except (ValueError, AttributeError):
        return None


def _extract_suburb(bank_entry: dict) -> str:
    """Extract the suburb used in a bank statement's transaction descriptions.

    All transactions for a given bank statement use the same suburb (the
    account holder's local area). We find it by looking at EFTPOS descriptions
    and extracting the title-case words between the uppercase retailer name
    and the trailing "AUS" suffix.
    """
    descriptions = bank_entry["fields"].get("TRANSACTION_DESCRIPTIONS", "").split("|")
    for desc in descriptions:
        desc = desc.strip()
        if not (desc.startswith("EFTPOS ") and desc.endswith(" AUS")):
            continue
        # Strip "EFTPOS " prefix and " AUS" suffix
        middle = desc[7:-4]
        words = middle.split()
        # Walk backwards: title-case words are the suburb, uppercase words
        # are the retailer name.
        suburb_words: list[str] = []
        for word in reversed(words):
            if word[0].isupper() and not word.isupper():
                suburb_words.insert(0, word)
            else:
                break
        if suburb_words:
            return " ".join(suburb_words)
    return "Sydney"


def _generate_receipt_description(
    supplier: str,
    suburb: str,
    rng: random.Random,
) -> str:
    """Generate a bank description for a retail receipt transaction."""
    shorthand = _RECEIPT_SHORTHANDS.get(supplier, supplier.upper())
    prefix, suffix = rng.choice(_RETAIL_PREFIXES)
    return f"{prefix} {shorthand} {suburb} {suffix}"


def _generate_invoice_description(
    supplier: str,
    rng: random.Random,
) -> str:
    """Generate a bank description for an invoice / professional service."""
    shorthand = _INVOICE_SHORTHANDS.get(supplier, supplier.upper())
    prefix = rng.choice(_INVOICE_PREFIXES)
    if prefix == "BPAY":
        crn = rng.randint(100_000_000, 999_999_999)
        return f"BPAY {shorthand} CRN {crn}"
    return f"{prefix} {shorthand}"


def _position_label(matched_idx: int, total_txns: int) -> str:
    if matched_idx < total_txns / 3:
        return "Early row"
    if matched_idx < 2 * total_txns / 3:
        return "Mid row"
    return "Late row"


def _build_notes(
    matched_idx: int,
    total_txns: int,
    bank_layout: str,
    difficulty: str,
    offset: int,
) -> str:
    position = _position_label(matched_idx, total_txns)
    layout_label = bank_layout.replace("_", " ")

    if difficulty == "easy":
        characteristic = "exact date and amount match"
    elif difficulty == "medium":
        characteristic = f"{offset}-day settlement delay"
    else:
        characteristic = f"{offset}-day settlement delay, description mismatch"

    return f"{position} on {layout_label} \u2014 {characteristic}"


def main() -> None:
    rng = random.Random(42)
    receipts = _load_gt("receipts")
    invoices = _load_gt("invoices")
    bank_stmts = _load_gt("bank_statements")

    links: dict[str, list[dict]] = {}

    # For each receipt/invoice, find or create a matching bank transaction
    sources = [
        *[(cid, entry) for cid, entry in receipts.items()],
        *[(cid, entry) for cid, entry in invoices.items()],
    ]

    bank_list = list(bank_stmts.items())

    for src_id, src_entry in sources:
        src_fields = src_entry["fields"]
        src_total = src_fields.get("TOTAL_AMOUNT", "")
        src_date_str = src_fields.get("INVOICE_DATE", "")
        src_date = _parse_date(src_date_str)
        supplier = src_fields.get("SUPPLIER_NAME", "")

        if not src_total or not src_date:
            continue

        # Assign to a random bank statement
        bank_id, bank_entry = rng.choice(bank_list)
        bank_fields = bank_entry["fields"]

        # Split pipe-delimited transaction fields
        bank_amounts = bank_fields.get("TRANSACTION_AMOUNTS_PAID", "").split("|")
        bank_dates = bank_fields.get("TRANSACTION_DATES", "").split("|")
        bank_descriptions = bank_fields.get("TRANSACTION_DESCRIPTIONS", "").split("|")

        # Try to find exact amount match
        matched_idx = None
        for idx, amt in enumerate(bank_amounts):
            if amt.strip() == src_total:
                matched_idx = idx
                break

        offset = 0

        # If no match, inject the amount into a random position
        if matched_idx is None:
            matched_idx = rng.randint(0, len(bank_amounts) - 1)
            bank_amounts[matched_idx] = src_total
            bank_fields["TRANSACTION_AMOUNTS_PAID"] = "|".join(bank_amounts)

            # Also set the date
            if matched_idx < len(bank_dates):
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
                        offset = delta
                    else:
                        difficulty = "hard"
                        offset = delta
                else:
                    difficulty = "easy"
            else:
                difficulty = "easy"

        # For easy/medium: inject a supplier-matching description into the
        # bank statement so the description realistically references the
        # merchant.  For hard: leave the existing unrelated description —
        # this makes matching genuinely harder (no description confirmation).
        is_invoice = src_id.startswith("CASEI")
        if difficulty in ("easy", "medium") and matched_idx < len(bank_descriptions):
            if is_invoice:
                new_desc = _generate_invoice_description(supplier, rng)
            else:
                suburb = _extract_suburb(bank_entry)
                new_desc = _generate_receipt_description(supplier, suburb, rng)
            bank_descriptions[matched_idx] = new_desc
            bank_fields["TRANSACTION_DESCRIPTIONS"] = "|".join(bank_descriptions)

        # Build image filenames
        receipt_filename = f"{src_id}_{src_entry['layout']}.png"
        bank_filename = f"{bank_id}_{bank_entry['layout']}.png"

        # Extract bank transaction fields at matched index
        bank_date_val = bank_dates[matched_idx].strip() if matched_idx < len(bank_dates) else ""
        bank_desc_val = (
            bank_descriptions[matched_idx].strip() if matched_idx < len(bank_descriptions) else ""
        )
        bank_amt_val = bank_amounts[matched_idx].strip()

        total_txns = len(bank_amounts)
        notes = _build_notes(matched_idx, total_txns, bank_entry["layout"], difficulty, offset)

        links[receipt_filename] = [
            {
                "bank_statement": bank_filename,
                "supplier": supplier,
                "receipt_date": src_date_str,
                "receipt_total": src_total,
                "bank_date": bank_date_val,
                "bank_description": bank_desc_val,
                "bank_amount": bank_amt_val,
                "match_status": "FOUND",
                "match_difficulty": difficulty,
                "notes": notes,
            }
        ]

    # Write updated bank statements (with injected amounts and descriptions)
    Path("ground_truth/bank_statements.yml").write_text(
        yaml.dump(dict(bank_stmts), default_flow_style=False, sort_keys=False)
    )

    # Write links
    Path("ground_truth/transaction_links.yml").write_text(
        yaml.dump(links, default_flow_style=False, sort_keys=False)
    )

    # Stats
    difficulties: dict[str, int] = {}
    for entry_list in links.values():
        for entry in entry_list:
            d = entry["match_difficulty"]
            difficulties[d] = difficulties.get(d, 0) + 1
    print(f"Generated {len(links)} transaction links: {difficulties}")


if __name__ == "__main__":
    main()
