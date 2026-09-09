from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from generators.common import fmt_amount
from generators.layout_dsl.context import Region
from generators.layout_dsl.defaults import PARAMETER_DEFAULTS
from generators.layout_dsl.engine import render_body
from generators.layout_dsl.field_providers import (
    FieldProviderError,
    apply_field_providers,
    field_provider,
    field_provider_emits,
    field_provider_names,
    field_provider_param_keys,
    get_field_provider,
)
from conftest import assert_diagnostic_error

# Task 0's capture script. `load_ground_truth` returns a flat case_id -> entry
# mapping with no "documents" key; `_entries` is the helper that flattens it to
# the list of entries these tests iterate, each carrying its own `case_id`.
from regenerate_doc_pixel_snapshot import _entries

_RECEIPT_ENTRIES = _entries(Path("ground_truth/receipts.yml"))

# Throwaway probes, registered here rather than in
# generators/layout_dsl/field_providers.py -- the shipped module carries only
# the real providers Tasks 10/11 add. Named distinctly from
# tests/layout_dsl/test_schema.py's "schema_probe" since the registry is a
# single process-wide dict shared by the whole `pytest tests/` run.


@field_provider("probe_pos", params=frozenset(), emits=("POS_STAFF",))
def _probe_pos(entry: dict, params: dict) -> dict:
    return {"POS_STAFF": "Sarah"}


@field_provider("probe_undeclared", params=frozenset(), emits=())
def _probe_undeclared(entry: dict, params: dict) -> dict:
    return {"POS_SURPRISE": "oops"}


@field_provider("probe_payment", params=frozenset(), emits=("PAYMENT_METHOD",))
def _probe_payment(entry: dict, params: dict) -> dict:
    return {"PAYMENT_METHOD": "EFTPOS"}


# Deliberately declares the same emit as probe_pos -- exists only to exercise
# the provider-versus-provider collision check below, never combined with
# anything else.
@field_provider("probe_pos_dup", params=frozenset(), emits=("POS_STAFF",))
def _probe_pos_dup(entry: dict, params: dict) -> dict:
    return {"POS_STAFF": "Someone Else"}


def test_provider_output_is_merged_into_entry_fields():
    layout = {"field_providers": [{"name": "probe_pos", "params": {}}]}
    entry = {"fields": {"TOTAL_AMOUNT": "137.73"}}
    merged = apply_field_providers(layout, entry)
    assert merged["fields"]["POS_STAFF"] == "Sarah"
    assert merged["fields"]["TOTAL_AMOUNT"] == "137.73"
    assert entry["fields"] == {"TOTAL_AMOUNT": "137.73"}, "the caller's entry must not be mutated"


def test_provider_emitting_an_undeclared_key_fails():
    """`emits` is the contract validate checks placeholders against. A provider
    returning a key it never declared makes that check a lie."""
    layout = {"field_providers": [{"name": "probe_undeclared", "params": {}}]}
    with pytest.raises(FieldProviderError) as exc_info:
        apply_field_providers(layout, {"fields": {}})
    assert_diagnostic_error(exc_info.value)
    assert "POS_SURPRISE" in str(exc_info.value)


def test_emit_colliding_with_a_scored_column_is_rejected():
    """A derived presentation value must never be mistaken for extraction
    ground truth -- config/field_definitions.yml owns those column names."""
    with pytest.raises(FieldProviderError) as exc_info:

        @field_provider("probe_collision", params=frozenset(), emits=("TOTAL_AMOUNT",))
        def _collide(entry: dict, params: dict) -> dict:
            return {"TOTAL_AMOUNT": "0.00"}

    assert_diagnostic_error(exc_info.value)
    assert "TOTAL_AMOUNT" in str(exc_info.value)
    assert "probe_collision" not in field_provider_names(), (
        "a rejected registration must never reach the registry"
    )


def test_apply_field_providers_merges_multiple_providers():
    """Two providers with disjoint emits on one layout must both land --
    the positive case the collision test below exists to distinguish from."""
    layout = {
        "field_providers": [
            {"name": "probe_pos", "params": {}},
            {"name": "probe_payment", "params": {}},
        ]
    }
    entry = {"fields": {}}
    merged = apply_field_providers(layout, entry)
    assert merged["fields"] == {"POS_STAFF": "Sarah", "PAYMENT_METHOD": "EFTPOS"}
    assert merged is not entry
    assert merged["fields"] is not entry["fields"]


def test_apply_field_providers_rejects_two_providers_emitting_the_same_key():
    """A silent dict.update() overwrite here would make one provider's value
    vanish from the page with no error -- exactly the defect this defensive,
    merge-time check exists to catch for a caller that builds a layout dict
    by hand and never goes through validate_layout's own static check (see
    tests/layout_dsl/test_schema.py's
    test_field_providers_declaring_overlapping_emits_is_rejected_at_validate_time
    for that one)."""
    layout = {
        "field_providers": [
            {"name": "probe_pos", "params": {}},
            {"name": "probe_pos_dup", "params": {}},
        ]
    }
    with pytest.raises(FieldProviderError) as exc_info:
        apply_field_providers(layout, {"fields": {}})
    message = str(exc_info.value)
    assert "POS_STAFF" in message
    assert "probe_pos" in message and "probe_pos_dup" in message
    assert_diagnostic_error(message)


def test_apply_field_providers_with_no_providers_returns_an_unchanged_copy():
    layout = {"field_providers": []}
    entry = {"fields": {"TOTAL_AMOUNT": "1.00"}}
    merged = apply_field_providers(layout, entry)
    assert merged["fields"] == entry["fields"]
    assert merged is not entry


def test_apply_field_providers_rejects_an_unregistered_provider_name():
    layout = {"field_providers": [{"name": "no_such_provider", "params": {}}]}
    with pytest.raises(FieldProviderError) as exc_info:
        apply_field_providers(layout, {"fields": {}})
    message = str(exc_info.value)
    assert "no_such_provider" in message and "probe_pos" in message
    assert_diagnostic_error(message)


def test_get_field_provider_rejects_unknown_name_and_lists_known():
    with pytest.raises(FieldProviderError) as exc_info:
        get_field_provider("no_such_provider")
    message = str(exc_info.value)
    assert "no_such_provider" in message
    assert "probe_pos" in message
    assert_diagnostic_error(message)


def test_field_provider_names_includes_registered():
    assert "probe_pos" in field_provider_names()


def test_field_provider_rejects_duplicate_registration():
    with pytest.raises(FieldProviderError, match="already registered"):

        @field_provider("probe_pos", emits=("WHATEVER",))
        def _duplicate(entry: dict, params: dict) -> dict:
            return {}


def test_field_provider_emits_and_param_keys_return_declared_values():
    assert field_provider_emits("probe_pos") == ("POS_STAFF",)
    assert field_provider_param_keys("probe_pos") == frozenset()


def test_field_provider_emits_and_param_keys_are_empty_for_unknown_name():
    """Mirrors provider_param_keys' identical rationale in providers.py:
    schema.py's own unknown-provider check already reports this case with its
    own diagnostic, so these lookups degrade gracefully instead of raising."""
    assert field_provider_emits("no_such_provider") == ()
    assert field_provider_param_keys("no_such_provider") == frozenset()


# -- when: suppression against a provider-emitted field -----------------------
#
# The mechanism the receipt slip variants (Tasks 10/11) will rely on: a
# `when:` naming a value only a field provider derives, never ground truth,
# must still suppress/admit correctly -- proved by rendering through the real
# engine.render_body, not by calling is_present directly, since what matters
# here is that apply_field_providers runs before render_blocks ever sees the
# entry.

_ENGINE_DEFAULTS = {
    "role": "body",
    "color": "black",
    "align": "left",
    "bold": False,
    "family": "carlito",
    "line_advance": {"body": 44},
    "rule_thickness": 1,
    "rule_pad_above": 0,
    "rule_pad_below": 0,
    "rule_fill_char": "none",
    "spacer_height": 0,
    "pair_value_align": "left",
    "pair_min_gap": 0,
    "pair_separator": ": ",
    "table_header": True,
    "table_header_bold": True,
    "table_row_inset_y": 0,
    "table_cell_line_spacing": "row_height",
    "table_header_rule_top": True,
    "table_header_rule_gap": 16,
    "table_group_gap": 10,
    "table_fill_inset": 0,
    "table_dividers": [],
    "table_offset_y": 0,
    "table_capture": True,
    "table_sub_line_height": 0,
    "banner_text_color": "white",
    "banner_text_y": 0,
    "banner_role": "header",
    "panel_padding": 0,
    "panel_border_color": "black",
    "split_gap": 0,
    "split_divider_color": "black",
}
assert set(_ENGINE_DEFAULTS) == PARAMETER_DEFAULTS, sorted(PARAMETER_DEFAULTS - set(_ENGINE_DEFAULTS))


def _render(layout: dict, entry: dict) -> int:
    image = Image.new("RGB", (400, 400), "white")
    return render_body(
        layout,
        entry,
        layout_id="probe",
        layout_path="config/layouts/receipts.yml",
        draw=ImageDraw.Draw(image),
        region=Region(x=0, width=400),
        y=0,
    )


def _layout(when: str) -> dict:
    return {
        "field_providers": [{"name": "probe_pos", "params": {}}],
        "font_sizes": {"body": 32},
        "row_height": 40,
        "defaults": _ENGINE_DEFAULTS,
        "body": [{"type": "spacer", "height": 40, "when": when}],
    }


def test_when_admits_a_block_whose_field_is_a_provider_emitted_value():
    """POS_STAFF exists nowhere in `entry["fields"]` -- only probe_pos derives
    it -- yet the block is admitted, proving apply_field_providers ran first."""
    assert _render(_layout("POS_STAFF"), {"fields": {}}) == 40


def test_when_suppresses_a_block_whose_field_absent_even_with_a_provider_declared():
    """A field_providers: declaration does not make every field present --
    only the keys the provider actually emits."""
    assert _render(_layout("SOME_OTHER_FIELD"), {"fields": {}}) == 0


# -- receipt_pos: pinned derivation -------------------------------------------

# Captured from `generators/receipt.py`'s `_derive_receipt_details` /
# `_derive_receipt_number` while they still existed (Task 14 deleted them with
# the legacy renderer, so the parity test that compared the two has nothing
# left to compare against). These are the same digest slices and pool lookups
# the provider still performs, pinned here so a change to `pos_terminal`'s
# pools or to the hex slicing fails with a named case rather than only as an
# opaque page-hash difference in the receipt pixel snapshot.
_POS_BASELINE = {
    "CASE001": {
        "POS_TIME": "15:46",
        "POS_REGISTER": "07",
        "POS_STAFF": "Ethan",
        "RECEIPT_NUMBER": "R-CF444D",
    },
    # Re-pinned after the transaction-cap reseed changed these two receipts'
    # INVOICE_DATE, which feeds the digest. CASE001's date did not change and
    # its values did not either — evidence the digest slicing itself is intact
    # and only the inputs moved.
    "CASE002": {
        "POS_TIME": "15:12",
        "POS_REGISTER": "01",
        "POS_STAFF": "Jack",
        "RECEIPT_NUMBER": "R-853686",
    },
    "CASE055": {
        "POS_TIME": "11:06",
        "POS_REGISTER": "01",
        "POS_STAFF": "Jack",
        "RECEIPT_NUMBER": "R-B1EFE8",
    },
}


@pytest.mark.parametrize("case_id", sorted(_POS_BASELINE))
def test_receipt_pos_matches_the_pinned_derivation(case_id):
    entry = next(e for e in _RECEIPT_ENTRIES if e["case_id"] == case_id)
    derived = get_field_provider("receipt_pos")(entry, {})
    assert {key: derived[key] for key in _POS_BASELINE[case_id]} == _POS_BASELINE[case_id]


@pytest.mark.parametrize("entry", _RECEIPT_ENTRIES, ids=lambda e: e["case_id"])
def test_receipt_pos_stays_within_its_declared_pools(entry):
    """Every derived value lands inside the ranges `pos_terminal` declares."""
    from generators.payment_block import load_pos_pools

    pools = load_pos_pools()
    derived = get_field_provider("receipt_pos")(entry, {})
    hour, minute = (int(part) for part in derived["POS_TIME"].split(":"))
    assert pools["hour_min"] <= hour < pools["hour_min"] + pools["hour_span"]
    assert 0 <= minute < 60
    register = int(derived["POS_REGISTER"])
    assert pools["register_min"] <= register < pools["register_min"] + pools["register_span"]
    assert derived["POS_STAFF"] in pools["staff_names"]
    assert derived["RECEIPT_NUMBER"].startswith(pools["receipt_number_prefix"])
    digest = derived["RECEIPT_NUMBER"].removeprefix(pools["receipt_number_prefix"])
    assert len(digest) == pools["receipt_number_digest_length"]
    assert digest == digest.upper()


def test_receipt_pos_is_registered_with_its_declared_emits():
    assert "receipt_pos" in field_provider_names()
    assert field_provider_emits("receipt_pos") == (
        "POS_TIME",
        "POS_REGISTER",
        "POS_STAFF",
        "RECEIPT_NUMBER",
    )
    assert field_provider_param_keys("receipt_pos") == frozenset()


@pytest.mark.parametrize("provider", ["receipt_pos", "receipt_payment"])
def test_a_pools_key_param_is_now_rejected_rather_than_documented(provider):
    """Both providers always load the one pool they were ever going to load,
    so `pools_key` read as a switch and was not one. Neither declares it now,
    which means the schema rejects it if it is ever re-added -- the same
    standard applied to layout keys no code path reads."""
    from generators.layout_dsl.schema import LayoutSchemaError, validate_layout

    layout = {
        "content_width": 100,
        "defaults": dict.fromkeys(PARAMETER_DEFAULTS, "unused")
        | {"line_advance": {"unused": 0}, "family": "carlito"},
        "field_budgets": {},
        "field_providers": [{"name": provider, "params": {"pools_key": "pos_terminal"}}],
        "body": [{"type": "rule"}],
    }
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            layout, layout_id="probe", layout_path="config/layouts/receipts.yml", known_fields=set()
        )
    assert "pools_key" in str(exc_info.value)


def test_receipt_pos_runs_through_apply_field_providers():
    """The layout-facing path, not just direct provider invocation."""
    layout = {"field_providers": [{"name": "receipt_pos", "params": {}}]}
    entry = {"case_id": "CASE001", "fields": {"INVOICE_DATE": "08/04/2023"}}
    merged = apply_field_providers(layout, entry)
    direct = get_field_provider("receipt_pos")(entry, {})
    assert merged["fields"]["POS_TIME"] == direct["POS_TIME"]
    assert merged["fields"]["RECEIPT_NUMBER"] == direct["RECEIPT_NUMBER"]


# -- computed_totals ------------------------------------------------------------


def test_computed_totals_matches_the_legacy_subtraction():
    """Matches receipt.py:303's `str(Decimal(total) - Decimal(gst))`."""
    entry = {"fields": {"TOTAL_AMOUNT": "137.73", "GST_AMOUNT": "12.52"}}
    derived = get_field_provider("computed_totals")(entry, {})
    assert derived["SUBTOTAL_AMOUNT"] == "125.21"


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"TOTAL_AMOUNT": "137.73"},
        {"GST_AMOUNT": "12.52"},
        {"TOTAL_AMOUNT": "NOT_FOUND", "GST_AMOUNT": "12.52"},
        {"TOTAL_AMOUNT": "137.73", "GST_AMOUNT": "NOT_FOUND"},
        {"TOTAL_AMOUNT": "NOT_FOUND", "GST_AMOUNT": "NOT_FOUND"},
    ],
)
def test_computed_totals_emits_nothing_when_a_required_field_is_absent_or_not_found(fields):
    derived = get_field_provider("computed_totals")({"fields": fields}, {})
    assert derived == {}


def test_computed_totals_is_registered_with_its_declared_emits():
    assert "computed_totals" in field_provider_names()
    assert field_provider_emits("computed_totals") == ("SUBTOTAL_AMOUNT",)
    assert field_provider_param_keys("computed_totals") == frozenset()


def test_computed_totals_absent_case_does_not_violate_the_undeclared_emit_check():
    """`emits` is an upper bound, not an exact contract: apply_field_providers
    only rejects a KEY the provider returns that it never declared -- it does
    not require every declared key to appear in every call's result. A layout
    combining computed_totals with a NOT_FOUND GST_AMOUNT must merge cleanly,
    with no FieldProviderError and no SUBTOTAL_AMOUNT key in the result."""
    layout = {"field_providers": [{"name": "computed_totals", "params": {}}]}
    entry = {"fields": {"TOTAL_AMOUNT": "NOT_FOUND", "GST_AMOUNT": "NOT_FOUND"}}
    merged = apply_field_providers(layout, entry)
    assert "SUBTOTAL_AMOUNT" not in merged["fields"]


# -- receipt_payment: Phase A parity against derive_payment --------------------


@pytest.mark.parametrize("entry", _RECEIPT_ENTRIES, ids=lambda e: e["case_id"])
def test_receipt_payment_matches_derive_payment(entry):
    """Phase A parity: the provider must reproduce derive_payment's values
    exactly for every entry in the corpus -- including the linked ones, whose
    scheme comes from the bank statement rather than the weighted pool."""
    from generators.payment_block import derive_payment, load_link_index

    case_id, date = entry["case_id"], entry["fields"]["INVOICE_DATE"]
    legacy = derive_payment(
        case_id,
        date,
        entry["fields"]["TOTAL_AMOUNT"],
        get_field_provider("receipt_pos")(entry, {})["POS_TIME"],
        bank_description=load_link_index().get(f"{case_id}_{entry['layout']}"),
    )
    derived = get_field_provider("receipt_payment")(entry, {})

    assert derived["PAYMENT_KIND"] == legacy.kind
    assert derived["PAYMENT_METHOD"] == legacy.method
    assert derived["PAYMENT_SCHEME_DISPLAY"] == (legacy.scheme_display or "NOT_FOUND")
    assert derived["PAYMENT_ACCOUNT_TYPE"] == (legacy.account_type or "NOT_FOUND")
    assert derived["PAYMENT_ACQUIRER"] == (legacy.acquirer or "NOT_FOUND")
    assert derived["PAYMENT_AID"] == (legacy.aid or "NOT_FOUND")
    assert derived["PAYMENT_MASKED_PAN"] == (legacy.masked_pan or "NOT_FOUND")
    assert derived["PAYMENT_ENTRY_MODE"] == (legacy.entry_mode or "NOT_FOUND")
    assert derived["PAYMENT_PSN"] == (legacy.psn or "NOT_FOUND")
    assert derived["PAYMENT_ATC"] == (legacy.atc or "NOT_FOUND")
    assert derived["PAYMENT_TERMINAL_ID"] == (legacy.terminal_id or "NOT_FOUND")
    assert derived["PAYMENT_TRANSACTION_REF"] == (legacy.transaction_ref or "NOT_FOUND")
    assert derived["PAYMENT_TIMESTAMP"] == (legacy.timestamp or "NOT_FOUND")
    assert derived["PAYMENT_WALLET_LABEL"] == (legacy.wallet_label or "NOT_FOUND")
    assert derived["PAYMENT_TENDERED"] == (
        fmt_amount(legacy.tendered) if legacy.tendered is not None else "NOT_FOUND"
    )
    assert derived["PAYMENT_CHANGE"] == (
        fmt_amount(legacy.change) if legacy.change is not None else "NOT_FOUND"
    )


def test_receipt_payment_never_emits_a_purchase_total():
    """The slip's 'Purchase   AUD' line binds {TOTAL_AMOUNT} directly (see
    PaymentDetails' docstring in payment_block.py) -- a separate
    PAYMENT_PURCHASE_TOTAL key would be a second copy of a scored value that
    could drift from the field the benchmark scores."""
    assert "PAYMENT_PURCHASE_TOTAL" not in field_provider_emits("receipt_payment")


def test_receipt_payment_exercises_at_least_one_linked_receipt():
    """Every receipt in this corpus is linked (test_payment_block.py's
    test_link_index_covers_every_receipt_stem asserts 55/55), so the parity
    test above already exercises the linked path for all 55 -- this just
    proves the corpus is not accidentally empty of links."""
    from generators.payment_block import load_link_index

    index = load_link_index()
    linked = [e for e in _RECEIPT_ENTRIES if f"{e['case_id']}_{e['layout']}" in index]
    assert len(linked) == len(_RECEIPT_ENTRIES) == 55


def test_cash_receipts_suppress_the_card_keys(monkeypatch):
    """The three slip variants are selected by when:, so a cash payment must
    emit NOT_FOUND for every card key rather than an empty string.

    No entry in ground_truth/receipts.yml is actually cash: every one of the
    55 is linked to a bank transaction, and receipt_method_weights.Cash is 0
    precisely because of that -- test_payment_block.py's
    test_no_linked_receipt_is_cash asserts the same invariant. So this
    exercises the cash path the way test_payment_block.py's own
    _cash_pools()/_details_of_kind() do: a cash-weighted pool via a
    monkeypatched load_terminal_pools, and a fabricated case id absent from
    load_link_index() so derive_payment falls back to the weighted pool
    instead of a bank-forced scheme."""
    import generators.payment_block as payment_block_mod

    cash_pools = dict(payment_block_mod.load_terminal_pools())
    cash_pools["receipt_method_weights"] = {"Cash": 1}
    monkeypatch.setattr(payment_block_mod, "load_terminal_pools", lambda: cash_pools)

    entry = {
        "case_id": "CASE900",
        "layout": "receipt_thermal_80mm",
        "fields": {"INVOICE_DATE": "07/07/2024", "TOTAL_AMOUNT": "137.73"},
    }
    derived = get_field_provider("receipt_payment")(entry, {})
    assert derived["PAYMENT_KIND"] == "cash", "Cash is the only weighted method; must always be picked"
    assert derived["PAYMENT_AID"] == "NOT_FOUND"
    assert derived["PAYMENT_MASKED_PAN"] == "NOT_FOUND"
    assert derived["PAYMENT_SCHEME_DISPLAY"] == "NOT_FOUND"
    assert derived["PAYMENT_ACCOUNT_TYPE"] == "NOT_FOUND"
    assert derived["PAYMENT_ENTRY_MODE"] == "NOT_FOUND"
    assert derived["PAYMENT_PSN"] == "NOT_FOUND"
    assert derived["PAYMENT_ATC"] == "NOT_FOUND"
    assert derived["PAYMENT_TERMINAL_ID"] == "NOT_FOUND"
    assert derived["PAYMENT_TRANSACTION_REF"] == "NOT_FOUND"
    assert derived["PAYMENT_WALLET_LABEL"] == "NOT_FOUND"
    assert derived["PAYMENT_TENDERED"] != "NOT_FOUND"
    assert derived["PAYMENT_CHANGE"] != "NOT_FOUND"


def test_card_receipts_suppress_the_cash_and_wallet_keys():
    card = [
        e
        for e in _RECEIPT_ENTRIES
        if get_field_provider("receipt_payment")(e, {})["PAYMENT_KIND"]
        == "card"
    ]
    assert card, "the corpus must contain at least one card receipt for this test to mean anything"
    derived = get_field_provider("receipt_payment")(card[0], {})
    assert derived["PAYMENT_WALLET_LABEL"] == "NOT_FOUND"
    assert derived["PAYMENT_TENDERED"] == "NOT_FOUND"
    assert derived["PAYMENT_CHANGE"] == "NOT_FOUND"
    assert derived["PAYMENT_AID"] != "NOT_FOUND"


def test_receipt_payment_is_registered_with_its_declared_emits():
    assert "receipt_payment" in field_provider_names()
    assert field_provider_emits("receipt_payment") == (
        "PAYMENT_KIND",
        "PAYMENT_METHOD",
        "PAYMENT_SCHEME_DISPLAY",
        "PAYMENT_ACCOUNT_TYPE",
        "PAYMENT_ACQUIRER",
        "PAYMENT_AID",
        "PAYMENT_MASKED_PAN",
        "PAYMENT_ENTRY_MODE",
        "PAYMENT_PSN",
        "PAYMENT_ATC",
        "PAYMENT_TERMINAL_ID",
        "PAYMENT_TRANSACTION_REF",
        "PAYMENT_TIMESTAMP",
        "PAYMENT_WALLET_LABEL",
        "PAYMENT_TENDERED",
        "PAYMENT_CHANGE",
    )
    assert field_provider_param_keys("receipt_payment") == frozenset()


def test_receipt_payment_runs_through_apply_field_providers():
    """The layout-facing path, not just direct provider invocation."""
    layout = {"field_providers": [{"name": "receipt_payment", "params": {}}]}
    entry = _RECEIPT_ENTRIES[0]
    merged = apply_field_providers(layout, entry)
    direct = get_field_provider("receipt_payment")(entry, {})
    assert merged["fields"]["PAYMENT_KIND"] == direct["PAYMENT_KIND"]
    assert merged["fields"]["PAYMENT_TIMESTAMP"] == direct["PAYMENT_TIMESTAMP"]
