"""Bank statement fit-safety: the old silent character-truncation of transaction
descriptions is replaced by lossless wrap. Budgets present, nothing clips, and
docs whose descriptions already fit stay byte-identical."""

import hashlib
import json
from pathlib import Path

from generators.bank_statement import _parse_transactions, render_bank_statement
from generators.common import fit_text, load_font
from generators.layout_budgets import field_budget
from generators.loader import load_ground_truth, load_layout_registry

_LP = "config/layouts/bank_statements.yml"


def _layouts() -> dict:
    return load_layout_registry(Path(_LP))


def _entries() -> dict:
    return load_ground_truth(Path("ground_truth/bank_statements.yml"))


def _baseline() -> dict:
    return json.loads(Path("tests/fixtures/bank_baseline_hashes.json").read_text())


def _body_size(layout: dict) -> int:
    return layout["font_sizes"]["body"]


def _family(layout: dict) -> str:
    """The face this layout renders in — read from the layout, never hardcoded.

    Bank layouts no longer share one face (CBA/NAB are carlito, Westpac/ANZ are
    liberation_sans), so a hardcoded family here would measure a different face
    than the renderer draws and quietly invalidate the fit assertions.
    """
    return str(layout["defaults"]["family"])


def _measure(text: str, size: int, family: str) -> int:
    bbox = load_font(size, family=family).getbbox(text)
    return int(bbox[2] - bbox[0])


def test_every_bank_layout_has_transaction_desc_budget_that_wraps():
    layouts = _layouts()
    for lid, layout in layouts.items():
        b = field_budget(layout, lid, "TRANSACTION_DESC", layout_path=_LP)
        assert b["fit"] == "wrap", f"{lid} TRANSACTION_DESC must wrap, got {b['fit']}"


def test_no_bank_description_overflows_after_fitting():
    layouts = _layouts()
    for entry in _entries().values():
        layout = layouts[entry["layout"]]
        size = _body_size(layout)
        b = field_budget(layout, entry["layout"], "TRANSACTION_DESC", layout_path=_LP)
        for txn in _parse_transactions(entry["fields"]):
            if not txn["description"]:
                continue
            fit_text(
                txn["description"], width=b["width"], fit=b["fit"], min_font=b["min_font"],
                max_lines=b["max_lines"], nominal_size=size, family=_family(layout),
            )  # must not raise — no silent truncation, and it fits losslessly


def test_unchanged_bank_docs_byte_identical():
    # Baselines regenerated from the Phase 1B reseeded corpus. The renderers are
    # unchanged (content-only reseed), so every current entry must byte-match its
    # recaptured hash — a renderer-regression guard for the new corpus. (The Phase 0
    # "truncation fix fired" proof was a one-time historical check against pre-fix
    # renders and cannot be reproduced after a content reseed.)
    layouts = _layouts()
    baseline = _baseline()
    for case_id, entry in _entries().items():
        entry["case_id"] = str(case_id)
        layout = layouts[entry["layout"]]
        digest = hashlib.sha256(render_bank_statement(entry, layout).tobytes()).hexdigest()
        key = f"{case_id}_{entry['layout']}"
        assert digest == baseline[key], f"{key} should be byte-identical but changed"
