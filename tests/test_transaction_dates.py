"""Bank-statement transaction dates must be realistic and internally consistent.

Target state (all four user directives):
1. A linked receipt/invoice and its bank transaction share the SAME date
   (the common real-world case: a purchase appears on the statement on its date).
2. Every transaction date falls within the statement's ~1-month period
   (all dates share one calendar month + year).
3. Each statement's transactions are in chronological (ascending) order.
4. STATEMENT_DATE_RANGE == earliest - latest of the date column.

Difficulty is now defined by description quality (date is always an exact match):
easy = full merchant name in the bank description, medium = an abbreviation,
hard = no merchant reference at all.
"""

from datetime import datetime
from pathlib import Path

import yaml

_BANK = "ground_truth/bank_statements.yml"
_RECEIPTS = "ground_truth/receipts.yml"
_INVOICES = "ground_truth/invoices.yml"
_LINKS = "ground_truth/transaction_links.yml"


def _load(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _parse(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%d/%m/%Y")


def _dates(entry: dict) -> list[datetime]:
    return [_parse(x) for x in entry["fields"]["TRANSACTION_DATES"].split("|")]


def test_bank_transaction_dates_are_chronological():
    for cid, entry in _load(_BANK).items():
        ds = _dates(entry)
        assert ds == sorted(ds), f"{cid}: transaction dates are not in chronological order"


def test_statement_date_range_equals_earliest_to_latest():
    for cid, entry in _load(_BANK).items():
        ds = _dates(entry)
        want = f"{min(ds).strftime('%d/%m/%Y')} - {max(ds).strftime('%d/%m/%Y')}"
        got = entry["fields"]["STATEMENT_DATE_RANGE"]
        assert got == want, f"{cid}: STATEMENT_DATE_RANGE {got!r} != earliest-latest {want!r}"


def test_all_transaction_dates_fall_within_one_month():
    for cid, entry in _load(_BANK).items():
        months = {(d.year, d.month) for d in _dates(entry)}
        assert len(months) == 1, (
            f"{cid}: transactions span multiple months {sorted(months)} — not a realistic statement period"
        )


def test_linked_receipt_and_bank_dates_are_identical():
    links = _load(_LINKS)
    for src_file, records in links.items():
        for rec in records:
            assert rec["receipt_date"] == rec["bank_date"], (
                f"{src_file}: receipt_date {rec['receipt_date']!r} != bank_date {rec['bank_date']!r}"
            )


def test_link_dates_match_the_underlying_ground_truth():
    """The link's date must actually be the receipt/invoice date AND appear on the
    named bank statement against the linked amount — otherwise the link is unscoreable."""
    links = _load(_LINKS)
    receipts, invoices, banks = _load(_RECEIPTS), _load(_INVOICES), _load(_BANK)
    for src_file, records in links.items():
        case_id = src_file.split("_")[0]
        src = invoices[case_id] if "invoice" in src_file else receipts[case_id]
        for rec in records:
            assert src["fields"]["INVOICE_DATE"] == rec["receipt_date"], (
                f"{src_file}: ground-truth INVOICE_DATE != link receipt_date"
            )
            bank = banks[case_id]["fields"]
            dates = bank["TRANSACTION_DATES"].split("|")
            amounts = bank["TRANSACTION_AMOUNTS_PAID"].split("|")
            hit = any(
                d.strip() == rec["bank_date"] and a.strip() == rec["bank_amount"]
                for d, a in zip(dates, amounts)
            )
            assert hit, (
                f"{src_file}: no bank transaction with date {rec['bank_date']} and amount {rec['bank_amount']}"
            )


def test_difficulty_distribution_is_preserved():
    links = _load(_LINKS)
    from collections import Counter

    counts = Counter(rec["match_difficulty"] for recs in links.values() for rec in recs)
    assert set(counts) == {"easy", "medium", "hard"}, f"unexpected difficulty labels: {set(counts)}"
    assert sum(counts.values()) == 110


def test_description_quality_matches_difficulty():
    """easy => full merchant name present; hard => no merchant reference."""
    links = _load(_LINKS)
    for src_file, records in links.items():
        for rec in records:
            merchant = rec["supplier"].upper()
            desc = rec["bank_description"].upper()
            if rec["match_difficulty"] == "easy":
                assert merchant in desc, (
                    f"{src_file}: easy link but merchant {merchant!r} absent from {desc!r}"
                )
            elif rec["match_difficulty"] == "hard":
                assert merchant not in desc, (
                    f"{src_file}: hard link but full merchant {merchant!r} present in {desc!r}"
                )
