"""Terminal-block config loading, derivation, and rendering (local-only).

The slip itself is no longer drawn by Python: `render_payment_block` was
deleted in the layout-DSL migration and the three variants (card, wallet,
cash) are now `when:`-guarded blocks in config/layouts/receipts.yml. The
rendering tests below therefore drive the DSL body directly, through
`generators.receipt.render_receipt` for the corpus cases and through a
provider-free layout with injected PAYMENT_* fields for the cash variant,
which the corpus itself can never reach (Cash carries weight 0).
"""

import copy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error
from PIL import Image, ImageDraw

from generators.layout_budgets import field_budget
from generators.layout_dsl.context import Region
from generators.layout_dsl.engine import render_body
from generators.layout_dsl.field_providers import receipt_payment, receipt_pos
from generators.loader import load_ground_truth, load_layout_registry
from generators.payment_block import (
    derive_payment,
    load_link_index,
    load_terminal_pools,
    method_from_bank_description,
)
from generators.receipt import render_receipt


def _pos_time(case_id, fields):
    """POS time for an entry, via the same provider the layout body uses."""
    return receipt_pos({"case_id": str(case_id), "fields": fields}, {})["POS_TIME"]

_POOLS = Path("config/data_pools.yml")
_LAYOUTS_PATH = Path("config/layouts/receipts.yml")

# The TOTAL_AMOUNT every slip test derives against. PaymentDetails carries no
# purchase total of its own, so the tests that render a slip supply this as the
# entry's TOTAL_AMOUNT — the same value the body's `Purchase   AUD` line binds.
_SLIP_TOTAL = "137.73"

_REQUIRED = [
    "receipt_method_weights",
    "acquirers",
    "schemes",
    "wallets",
    "entry_modes",
    "cash_tender_step",
    "cash_extra_notes",
]


def _write_pools(tmp_path: Path, mutate) -> Path:
    """Copy the real pools file, apply `mutate` to payment_terminal, write it out."""
    data = yaml.safe_load(_POOLS.read_text())
    mutate(data["payment_terminal"])
    out = tmp_path / "data_pools.yml"
    out.write_text(yaml.safe_dump(data))
    return out


def test_loads_real_pools_file():
    pools = load_terminal_pools(_POOLS)
    for key in _REQUIRED:
        assert key in pools, f"{key} missing from payment_terminal"


def test_every_scheme_has_required_subkeys():
    schemes = load_terminal_pools(_POOLS)["schemes"]
    assert schemes
    for name, scheme in schemes.items():
        for sub in ("display", "aid", "pan_digits", "account_types"):
            assert sub in scheme, f"scheme {name} missing {sub}"
        assert scheme["account_types"], f"scheme {name} has empty account_types"


def test_every_weighted_method_resolves():
    pools = load_terminal_pools(_POOLS)
    known = set(pools["schemes"]) | set(pools["wallets"]) | {"Cash"}
    assert set(pools["receipt_method_weights"]) <= known


@pytest.mark.parametrize("key", _REQUIRED)
def test_missing_required_key_is_four_element_diagnostic(tmp_path, key):
    path = _write_pools(tmp_path, lambda pt: pt.pop(key))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert key in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_missing_payment_terminal_block_is_diagnostic(tmp_path):
    data = yaml.safe_load(_POOLS.read_text())
    del data["payment_terminal"]
    path = tmp_path / "data_pools.yml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert_diagnostic_error(exc_info.value)


def test_scheme_missing_subkey_is_diagnostic(tmp_path):
    def drop_aid(pt):
        pt["schemes"] = copy.deepcopy(pt["schemes"])
        del pt["schemes"]["Visa"]["aid"]

    path = _write_pools(tmp_path, drop_aid)
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert "aid" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_unknown_weighted_method_is_diagnostic(tmp_path):
    path = _write_pools(tmp_path, lambda pt: pt["receipt_method_weights"].update({"Bitcoin": 5}))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert "Bitcoin" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


# A zero weight is now valid (it disables a method explicitly). The replacement
# coverage lives in test_zero_weight_is_allowed_but_all_zero_is_not and
# test_negative_weight_is_rejected.


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_terminal_pools(tmp_path / "nope.yml")


# --- printed slip wording / cash_tender_step / cash_extra_notes ----------------


def _body_strings(layout):
    """Every literal string a layout's body draws (labels and templates)."""
    out = []
    for block in layout["body"]:
        for key in ("content", "label"):
            if isinstance(block.get(key), str):
                out.append(block[key])
    return out


# The slip's fixed wording, pinned against the page that prints it. These used
# to be `payment_terminal` keys in config/data_pools.yml as well, and nothing
# read them: two files declaring the same strings, held together only by a
# test. They now live once, in the `body:` tree of config/layouts/receipts.yml,
# and this is the assertion that they are what an operator expects to see —
# 'Purchase   AUD' keeps its three spaces, 'APPROVED' keeps its response code.
_SLIP_WORDING = (
    "CUSTOMER COPY",
    "Retain copy for your records",
    "APPROVED   00",
    "Purchase   AUD",
    "CASH TENDERED",
    "CHANGE",
    "AID: ",
    "Card: ",
    "Terminal ID: ",
    "Transaction Ref: ",
    "CONTACTLESS - ",
)


def test_the_receipt_body_prints_the_expected_slip_wording():
    drawn = _body_strings(load_layout_registry(_LAYOUTS_PATH)["receipt_thermal_80mm"])
    for text in _SLIP_WORDING:
        assert any(line.startswith(text) for line in drawn), (
            f"no receipt body block prints {text!r}"
        )
    assert "PSN: {PAYMENT_PSN}, ATC: {PAYMENT_ATC}" in drawn


def test_payment_terminal_declares_no_printed_slip_wording():
    """`payment_terminal` holds sampled values only; fixed wording is chrome.

    Re-adding a `customer_copy_text`/`slip_labels`-style key here would put a
    second copy of a printed string in a second file, which is what this
    sweep removed.
    """
    cfg = load_terminal_pools(_POOLS)
    for dead in (
        "contactless_label",
        "customer_copy_text",
        "approved_text",
        "response_code",
        "retain_text",
        "cash",
        "slip_labels",
    ):
        assert dead not in cfg, f"payment_terminal.{dead} is printed wording, not a sampled pool"


@pytest.mark.parametrize("key", ["cash_tender_step", "cash_extra_notes"])
@pytest.mark.parametrize("bad", [0, -1, "5", 1.5, True])
def test_cash_step_and_extra_notes_reject_non_positive_ints(tmp_path, key, bad):
    path = _write_pools(tmp_path, lambda pt: pt.update({key: bad}))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert_diagnostic_error(exc_info.value)


def test_cash_tender_step_drives_the_note_denomination():
    """A pools override with a larger step must change the derived tender."""
    cfg = dict(load_terminal_pools(_POOLS))
    cfg["receipt_method_weights"] = {"Cash": 1}
    cfg["cash_tender_step"] = 20
    for i in range(1, 30):
        d = derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33", pools=cfg)
        if d.kind == "cash":
            assert d.tendered % Decimal("20") == 0
            return
    raise AssertionError("no cash case found")


# --- Derivation ---------------------------------------------------------------


def _details(case="CASE001", date="07/07/2024", total="137.73", time_str="10:33"):
    return derive_payment(case, date, total, time_str)


def test_derivation_is_deterministic():
    assert _details() == _details()


def test_different_cases_differ():
    assert _details(case="CASE001") != _details(case="CASE002")


def test_kind_matches_method():
    pools = load_terminal_pools(_POOLS)
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.method == "Cash":
            assert d.kind == "cash"
        elif d.method in pools["wallets"]:
            assert d.kind == "wallet"
        else:
            assert d.kind == "card"
            assert d.method in pools["schemes"]


def test_all_methods_appear_across_the_corpus():
    """The weighted pool must actually produce every configured method."""
    pools = load_terminal_pools(_POOLS)
    seen = {
        derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33").method
        for i in range(1, 56)
    }
    assert seen <= set(pools["receipt_method_weights"])
    assert len(seen) >= 4, f"weighted pool produced too little variety: {seen}"


def test_masked_pan_width_matches_scheme_pan_digits():
    pools = load_terminal_pools(_POOLS)
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.kind == "cash":
            assert d.masked_pan == ""
            continue
        expected_digits = pools["schemes"][d.scheme_name]["pan_digits"]
        assert len(d.masked_pan) == expected_digits
        assert d.masked_pan[-4:].isdigit()
        assert set(d.masked_pan[:-4]) == {"x"}


def test_account_type_comes_from_its_own_scheme():
    pools = load_terminal_pools(_POOLS)
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.kind == "cash":
            continue
        assert d.account_type in pools["schemes"][d.scheme_name]["account_types"]


def test_timestamp_is_twelve_hour_rendering_of_receipt_meta_time():
    d = derive_payment("CASE001", "07/07/2024", "137.73", "13:33")
    assert d.timestamp == "07 Jul 2024 at 01:33 PM"
    d_am = derive_payment("CASE001", "07/07/2024", "137.73", "09:05")
    assert d_am.timestamp == "07 Jul 2024 at 09:05 AM"


def test_cash_change_is_tendered_minus_total_and_tender_exceeds_total():
    for case in [f"CASE{i:03d}" for i in range(1, 200)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.kind != "cash":
            continue
        assert d.tendered > Decimal("137.73")
        assert d.change == d.tendered - Decimal("137.73")
        assert d.tendered % Decimal("5") == 0


def test_exact_multiple_of_five_still_gives_change():
    """A total that is already a round note must never render CHANGE 0.00."""
    for case in [f"CASE{i:03d}" for i in range(1, 200)]:
        d = derive_payment(case, "07/07/2024", "25.00", "10:33")
        if d.kind == "cash":
            assert d.change > 0


def test_card_details_have_no_cash_values():
    for case in [f"CASE{i:03d}" for i in range(1, 56)]:
        d = derive_payment(case, "07/07/2024", "137.73", "10:33")
        if d.kind != "cash":
            assert d.tendered is None and d.change is None
            assert d.aid and d.psn and d.atc and d.terminal_id and d.transaction_ref


def test_derive_payment_carries_no_purchase_total_of_its_own():
    """The printed 'Purchase   AUD' amount must never diverge from TOTAL_AMOUNT.

    The body binds {TOTAL_AMOUNT} directly, so PaymentDetails deliberately
    holds no derived copy for it to drift from — the structural version of
    the invariant `test_purchase_total_is_the_scored_total_verbatim` used to
    assert about a field nothing read.
    """
    d = derive_payment("CASE001", "07/07/2024", _SLIP_TOTAL, "10:33")
    assert not hasattr(d, "purchase_total")


# --- Rendering ----------------------------------------------------------------


def _payment_fields(details):
    """The PAYMENT_* fields `receipt_payment` would emit for `details`.

    Built from the dataclass rather than by calling the provider, so a variant
    the corpus can never produce (cash) can still be driven through the body.
    """
    from generators.layout_dsl.field_providers import _amount_or_not_found, _or_not_found

    return {
        "PAYMENT_KIND": details.kind,
        "PAYMENT_METHOD": details.method,
        "PAYMENT_SCHEME_DISPLAY": _or_not_found(details.scheme_display),
        "PAYMENT_ACCOUNT_TYPE": _or_not_found(details.account_type),
        "PAYMENT_ACQUIRER": _or_not_found(details.acquirer),
        "PAYMENT_AID": _or_not_found(details.aid),
        "PAYMENT_MASKED_PAN": _or_not_found(details.masked_pan),
        "PAYMENT_ENTRY_MODE": _or_not_found(details.entry_mode),
        "PAYMENT_PSN": _or_not_found(details.psn),
        "PAYMENT_ATC": _or_not_found(details.atc),
        "PAYMENT_TERMINAL_ID": _or_not_found(details.terminal_id),
        "PAYMENT_TRANSACTION_REF": _or_not_found(details.transaction_ref),
        "PAYMENT_TIMESTAMP": _or_not_found(details.timestamp),
        "PAYMENT_WALLET_LABEL": _or_not_found(details.wallet_label),
        "PAYMENT_TENDERED": _amount_or_not_found(details.tendered),
        "PAYMENT_CHANGE": _amount_or_not_found(details.change),
    }


def _slip_blocks(layout):
    """Just the body's terminal-slip blocks — those guarded on a PAYMENT_* key."""
    return [block for block in layout["body"] if str(block.get("when", "")).startswith("PAYMENT_")]


def _render_lines(details, layout_id="receipt_thermal_80mm"):
    """Render only the slip blocks onto a scratch canvas; return (image, new_y).

    Drives the real `body:` tree through the engine with the provider chain
    switched off and the PAYMENT_* fields injected directly, which is the only
    way to exercise a variant the corpus cannot reach.
    """
    layout = dict(load_layout_registry(_LAYOUTS_PATH)[layout_id])
    layout["field_providers"] = []
    layout["body"] = _slip_blocks(layout)
    img = Image.new("RGB", (layout["width"], 1200), "white")
    draw = ImageDraw.Draw(img)
    entry = {
        "case_id": "CASE001",
        "layout": layout_id,
        "fields": {"TOTAL_AMOUNT": _SLIP_TOTAL, **_payment_fields(details)},
    }
    new_y = render_body(
        layout,
        entry,
        layout_id=layout_id,
        layout_path=str(_LAYOUTS_PATH),
        draw=draw,
        region=Region(x=layout["margin"], width=layout["content_width"]),
        y=20,
    )
    return img, new_y


def _ink_rows(img, from_y, to_y):
    """Count rows containing non-white pixels — a proxy for lines drawn."""
    px = img.load()
    rows = 0
    for y in range(from_y, to_y):
        if any(px[x, y] != (255, 255, 255) for x in range(img.width)):
            rows += 1
    return rows


def _cash_pools():
    """Pools with cash re-enabled.

    The shipped corpus sets `Cash: 0` because every receipt is linked to a bank
    transaction, but the cash rendering path stays live for future unlinked
    receipts — so it is exercised against an explicitly cash-weighted pool
    rather than against the corpus.
    """
    cfg = dict(load_terminal_pools(_POOLS))
    cfg["receipt_method_weights"] = {"Cash": 1}
    return cfg


def _details_of_kind(kind):
    pools = _cash_pools() if kind == "cash" else None
    for i in range(1, 400):
        d = derive_payment(f"CASE{i:03d}", "07/07/2024", _SLIP_TOTAL, "10:33", pools=pools)
        if d.kind == kind:
            return d
    raise AssertionError(f"no {kind} case found")


def test_card_block_is_taller_than_cash_block():
    _, card_y = _render_lines(_details_of_kind("card"))
    _, cash_y = _render_lines(_details_of_kind("cash"))
    assert card_y > cash_y, "card terminal block must print more lines than cash"


def test_cash_block_draws_only_two_lines():
    """Cash advances exactly two line heights (tendered + change), nothing more."""
    layout = load_layout_registry(_LAYOUTS_PATH)["receipt_thermal_80mm"]
    img, new_y = _render_lines(_details_of_kind("cash"))
    assert _ink_rows(img, 0, new_y) > 0
    assert new_y - 20 == 2 * layout["defaults"]["line_advance"]["body"]


def _force_cash(monkeypatch):
    """Make the receipt_payment provider derive a cash payment for any entry.

    Two things stand between the corpus and the cash slip, and both must go:
    every receipt is linked, so its scheme comes from the bank row rather than
    the weighted pool; and `Cash` carries weight 0 in that pool anyway. This
    patches the link index the provider consults and the pool `derive_payment`
    loads, leaving everything else -- the body, the crop, the budgets -- real.
    """
    import generators.layout_dsl.field_providers as providers_mod
    import generators.payment_block as payment_mod

    monkeypatch.setattr(providers_mod, "load_link_index", dict)
    monkeypatch.setattr(payment_mod, "load_terminal_pools", _cash_pools)


def _spy_drawn_text(monkeypatch):
    """Record every (y, text) PIL is asked to draw, and still draw it."""
    drawn: list[tuple[int, str]] = []
    original = ImageDraw.ImageDraw.text

    def _record(self, xy, text, *args, **kwargs):
        drawn.append((int(xy[1]), str(text)))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", _record)
    return drawn


@pytest.mark.parametrize("layout_id", sorted(load_layout_registry(_LAYOUTS_PATH)))
def test_a_whole_cash_receipt_page_renders_on_every_layout(layout_id, monkeypatch):
    """The cash slip's only whole-page oracle.

    `_render_lines` above draws the two cash blocks onto a scratch canvas with
    the provider chain switched off. What it cannot see is the page: a cash
    payment suppresses every `when: PAYMENT_AID` block, collapsing the slip
    from roughly twenty lines to two, and that collapse meets the surrounding
    rules and spacers and then `render_receipt`'s crop-to-content height. No
    corpus receipt reaches this and the legacy renderer that could have been
    an oracle is deleted, so this drives the real body through the real
    renderer with the pool patched, and asserts the two labels actually land
    on the cropped page rather than below its bottom edge.
    """
    _force_cash(monkeypatch)
    layout = load_layout_registry(_LAYOUTS_PATH)[layout_id]
    case_id, entry = next(iter(load_ground_truth(Path("ground_truth/receipts.yml")).items()))
    entry = dict(entry)
    entry["case_id"] = str(case_id)
    entry["layout"] = layout_id

    # The patch must actually have taken, or every assertion below is vacuous.
    assert receipt_payment(entry, {})["PAYMENT_KIND"] == "cash"

    drawn = _spy_drawn_text(monkeypatch)
    img = render_receipt(entry, layout)

    labels = {text: y for y, text in drawn}
    assert "CASH TENDERED" in labels, sorted(labels)
    assert "CHANGE" in labels
    # Drawn *and* kept: render_receipt crops to end_y + margin, so a slip drawn
    # past the crop would leave these assertions passing on an invisible line.
    assert labels["CASH TENDERED"] < img.height
    assert labels["CHANGE"] < img.height
    # The card-only lines are suppressed, not merely absent from this entry.
    assert not any(text.startswith("Terminal ID:") for _, text in drawn)
    assert "APPROVED   00" not in labels


def test_a_cash_receipt_page_is_shorter_than_the_same_receipt_paid_by_card(monkeypatch):
    """The collapse is real, and it is the crop that shows it."""
    layout_id = "receipt_thermal_80mm"
    layout = load_layout_registry(_LAYOUTS_PATH)[layout_id]
    case_id, entry = next(iter(load_ground_truth(Path("ground_truth/receipts.yml")).items()))
    entry = dict(entry)
    entry["case_id"] = str(case_id)
    entry["layout"] = layout_id

    card_height = render_receipt(entry, layout).height
    _force_cash(monkeypatch)
    cash_height = render_receipt(entry, layout).height
    assert cash_height < card_height


def test_block_renders_for_every_layout_and_method():
    """No layout/method combination may raise (FitError included)."""
    layouts = load_layout_registry(_LAYOUTS_PATH)
    for layout_id in layouts:
        for i in range(1, 60):
            d = derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33")
            _render_lines(d, layout_id=layout_id)


def test_every_corpus_receipt_renders_under_every_layout():
    """Broader fit guard than the per-block one above: whole pages, real data.

    The corpus assigns one layout per receipt, so a fit failure that only
    appears when a long supplier name lands on the narrowest layout would
    otherwise go unseen until a reseed happened to pair them.
    """
    layouts = load_layout_registry(_LAYOUTS_PATH)
    for case_id, entry in load_ground_truth(Path("ground_truth/receipts.yml")).items():
        for layout_id, layout in layouts.items():
            candidate = dict(entry)
            candidate["case_id"] = str(case_id)
            candidate["layout"] = layout_id
            render_receipt(candidate, layout)  # must not raise


def test_every_layout_has_payment_budgets():
    layouts = load_layout_registry(_LAYOUTS_PATH)
    for lid, layout in layouts.items():
        for field in ("PAYMENT_ACQUIRER", "PAYMENT_LINE"):
            field_budget(layout, lid, field, layout_path=str(_LAYOUTS_PATH))


def _entry_of_kind(kind):
    """First ground-truth receipt whose derived payment is `kind`."""
    for case_id, entry in load_ground_truth(Path("ground_truth/receipts.yml")).items():
        fields = entry["fields"]
        d = derive_payment(
            case_id, fields["INVOICE_DATE"], fields["TOTAL_AMOUNT"], _pos_time(case_id, fields)
        )
        if d.kind == kind:
            out = dict(entry)
            out["case_id"] = case_id
            return out, d
    raise AssertionError(f"no ground-truth receipt derives kind {kind}")


def test_receipt_render_grows_by_the_block():
    """Rendering with the payment section must add the block's lines.

    Compares against the same entry rendered with the slip blocks stripped
    from its layout body, so the assertion measures the block itself rather
    than a fixed pixel threshold (receipt heights vary with line-item count).

    Only the card path is exercised through the corpus: every receipt is linked
    to a bank transaction, so no ground-truth receipt is cash. The cash block's
    height is covered directly by test_cash_block_draws_only_two_lines.
    """
    layouts = load_layout_registry(_LAYOUTS_PATH)
    for kind, min_lines in (("card", 12),):
        entry, _ = _entry_of_kind(kind)
        layout = layouts[entry["layout"]]
        slip = _slip_blocks(layout)
        assert slip, "the receipt body declares no PAYMENT_*-guarded blocks"
        stripped = dict(layout)
        stripped["body"] = [block for block in layout["body"] if block not in slip]
        advance = layout["defaults"]["line_advance"]["body"]
        with_block = render_receipt(entry, layout).height
        without_block = render_receipt(entry, stripped).height
        grew = with_block - without_block
        assert grew >= min_lines * advance, (
            f"{kind} block added {grew}px, expected at least {min_lines} lines of {advance}px"
        )


def test_receipt_module_has_no_hardcoded_methods():
    import generators.receipt as receipt_mod

    assert not hasattr(receipt_mod, "_PAYMENT_METHODS")


# --- Bank-link consistency -----------------------------------------------------

_LINKS_PATH = Path("ground_truth/transaction_links.yml")


def test_bank_description_maps_to_scheme():
    cfg = load_terminal_pools(_POOLS)
    assert method_from_bank_description("EFTPOS SQ *PRIME Alexandria AUS", cfg) == "EFTPOS"
    assert (
        method_from_bank_description("VISA DEBIT PURCHASE SQ *RAVENSDALE AU", cfg) == "Visa Debit"
    )
    assert (
        method_from_bank_description("MASTERCARD DEBIT HARROWGATE L AU", cfg)
        == "Mastercard Debit"
    )


def test_longest_prefix_wins():
    """A longer, more specific prefix must beat a shorter one."""
    cfg = dict(load_terminal_pools(_POOLS))
    cfg["bank_description_methods"] = {
        "MASTERCARD": "Mastercard",
        "MASTERCARD DEBIT": "Mastercard Debit",
    }
    assert method_from_bank_description("MASTERCARD DEBIT FOO", cfg) == "Mastercard Debit"
    assert method_from_bank_description("MASTERCARD FOO", cfg) == "Mastercard"


def test_unmapped_description_is_four_element_diagnostic():
    cfg = load_terminal_pools(_POOLS)
    with pytest.raises(ValueError) as exc_info:
        method_from_bank_description("BITCOIN TRANSFER SATOSHI", cfg)
    assert "BITCOIN TRANSFER SATOSHI" in str(exc_info.value)
    assert_diagnostic_error(exc_info.value)


def test_mapped_schemes_exist():
    cfg = load_terminal_pools(_POOLS)
    for scheme_name in cfg["bank_description_methods"].values():
        assert scheme_name in cfg["schemes"], f"{scheme_name} is not a configured scheme"


def test_debit_schemes_are_configured():
    schemes = load_terminal_pools(_POOLS)["schemes"]
    assert schemes["Visa Debit"]["display"] == "VISA DEBIT"
    assert schemes["Mastercard Debit"]["display"] == "MASTERCARD DEBIT"
    for name in ("Visa Debit", "Mastercard Debit"):
        assert set(schemes[name]["account_types"]) == {"CHQ", "SAV"}


def test_zero_weight_is_allowed_but_all_zero_is_not(tmp_path):
    """Cash: 0 must be accepted; a pool with no positive weight must not."""
    path = _write_pools(tmp_path, lambda pt: pt["receipt_method_weights"].update({"Cash": 0}))
    assert load_terminal_pools(path)["receipt_method_weights"]["Cash"] == 0

    def zero_all(pt):
        pt["receipt_method_weights"] = dict.fromkeys(pt["receipt_method_weights"], 0)

    second = tmp_path / "b"
    second.mkdir()  # _write_pools writes into this directory; it must exist first
    path2 = _write_pools(second, zero_all)
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path2)
    assert_diagnostic_error(exc_info.value)


def test_negative_weight_is_rejected(tmp_path):
    path = _write_pools(tmp_path, lambda pt: pt["receipt_method_weights"].update({"Cash": -1}))
    with pytest.raises(ValueError) as exc_info:
        load_terminal_pools(path)
    assert_diagnostic_error(exc_info.value)


def test_link_index_covers_every_receipt_stem():
    index = load_link_index(_LINKS_PATH)
    entries = load_ground_truth(Path("ground_truth/receipts.yml"))
    for case_id, entry in entries.items():
        assert f"{case_id}_{entry['layout']}" in index
    assert len(index) == 55, f"expected 55 receipt links, got {len(index)}"


def test_link_index_excludes_invoices():
    index = load_link_index(_LINKS_PATH)
    assert not [stem for stem in index if "invoice" in stem or "tax_" in stem]


def test_link_index_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_link_index(tmp_path / "nope.yml")


def test_bank_description_forces_the_scheme():
    d = derive_payment(
        "CASE001",
        "07/07/2024",
        "137.73",
        "10:33",
        bank_description="VISA DEBIT PURCHASE SQ *RAVENSDALE Alexandria AU",
    )
    assert d.scheme_name == "Visa Debit"
    assert d.scheme_display == "VISA DEBIT"
    assert d.kind in ("card", "wallet")
    assert d.kind != "cash", "a linked receipt can never be cash"


def test_forced_scheme_keeps_hash_derived_values():
    """Only the scheme changes; the rest of the slip stays hash-derived."""
    plain = derive_payment("CASE007", "07/07/2024", "137.73", "10:33")
    forced = derive_payment(
        "CASE007", "07/07/2024", "137.73", "10:33", bank_description="EFTPOS FOO AUS"
    )
    assert forced.psn == plain.psn
    assert forced.atc == plain.atc
    assert forced.terminal_id == plain.terminal_id
    assert forced.transaction_ref == plain.transaction_ref
    assert forced.timestamp == plain.timestamp
    assert forced.acquirer == plain.acquirer


def test_account_type_belongs_to_the_forced_scheme():
    cfg = load_terminal_pools(_POOLS)
    for i in range(1, 60):
        d = derive_payment(
            f"CASE{i:03d}",
            "07/07/2024",
            "137.73",
            "10:33",
            bank_description="VISA DEBIT PURCHASE FOO AU",
        )
        assert d.account_type in cfg["schemes"]["Visa Debit"]["account_types"]


def test_wallet_presentation_keeps_the_bank_scheme():
    """A wallet presentation must not change the scheme the bank row names."""
    details = [
        derive_payment(
            f"CASE{i:03d}",
            "07/07/2024",
            "137.73",
            "10:33",
            bank_description="VISA DEBIT PURCHASE FOO AU",
        )
        for i in range(1, 200)
    ]
    presented = [d for d in details if d.kind == "wallet"]
    assert presented, "no wallet presentation occurred across 199 cases"
    for d in presented:
        assert d.scheme_name == "Visa Debit"
        assert d.scheme_display == "VISA DEBIT"
        assert d.wallet_label
        assert d.entry_mode == load_terminal_pools(_POOLS)["entry_modes"]["wallet"]
    assert len(presented) < len(details) / 2, "wallets must stay a minority presentation"


def test_unlinked_receipt_falls_back_to_the_weighted_pick():
    """Without a description the derivation is byte-identical to before."""
    d = derive_payment("CASE001", "07/07/2024", "137.73", "10:33")
    assert d.method in load_terminal_pools(_POOLS)["receipt_method_weights"]


def test_cash_never_appears_now_that_its_weight_is_zero():
    for i in range(1, 200):
        d = derive_payment(f"CASE{i:03d}", "07/07/2024", "137.73", "10:33")
        assert d.method != "Cash", "Cash weight is 0, so it must never be picked"


def test_every_linked_receipt_matches_its_bank_row():
    """The invariant this whole change exists to establish."""
    cfg = load_terminal_pools(_POOLS)
    index = load_link_index(_LINKS_PATH)
    entries = load_ground_truth(Path("ground_truth/receipts.yml"))

    mismatches = []
    for case_id, entry in entries.items():
        fields = entry["fields"]
        stem = f"{case_id}_{entry['layout']}"
        description = index[stem]
        d = derive_payment(
            case_id,
            fields["INVOICE_DATE"],
            fields["TOTAL_AMOUNT"],
            _pos_time(case_id, fields),
            bank_description=description,
        )
        expected = method_from_bank_description(description, cfg)
        if d.scheme_name != expected:
            mismatches.append(f"{stem}: bank={expected} receipt={d.scheme_name}")

    assert not mismatches, (
        f"{len(mismatches)} receipts disagree with their bank row: {mismatches[:5]}"
    )


def test_no_linked_receipt_is_cash():
    index = load_link_index(_LINKS_PATH)
    for case_id, entry in load_ground_truth(Path("ground_truth/receipts.yml")).items():
        fields = entry["fields"]
        d = derive_payment(
            case_id,
            fields["INVOICE_DATE"],
            fields["TOTAL_AMOUNT"],
            _pos_time(case_id, fields),
            bank_description=index[f"{case_id}_{entry['layout']}"],
        )
        assert d.kind != "cash"


def test_renderer_actually_consults_the_link_index(monkeypatch):
    """End-to-end: the bank scheme reaches the page, not just the dataclass.

    Renders a case whose linked scheme differs from the scheme it would pick
    unlinked, with the link index live and then stubbed empty. If the renderer
    ignored the links, both renders would be byte-identical.
    """
    import hashlib

    import generators.layout_dsl.field_providers as providers_mod

    cfg = load_terminal_pools(_POOLS)
    index = load_link_index(_LINKS_PATH)
    layouts = load_layout_registry(_LAYOUTS_PATH)

    target = None
    for case_id, entry in load_ground_truth(Path("ground_truth/receipts.yml")).items():
        fields = entry["fields"]
        args = (
            case_id,
            fields["INVOICE_DATE"],
            fields["TOTAL_AMOUNT"],
            _pos_time(case_id, fields),
        )
        unlinked = derive_payment(*args)
        linked = derive_payment(*args, bank_description=index[f"{case_id}_{entry['layout']}"])
        if unlinked.scheme_name != linked.scheme_name:
            target = (case_id, entry, linked)
            break
    assert target, "no case distinguishes linked from unlinked derivation"

    case_id, entry, linked = target
    entry = dict(entry)
    entry["case_id"] = case_id
    layout = layouts[entry["layout"]]

    wired = hashlib.sha256(render_receipt(entry, layout).tobytes()).hexdigest()
    # The link lookup moved out of the renderer and into the receipt_payment
    # field provider, so that is the module whose `load_link_index` is stubbed.
    monkeypatch.setattr(providers_mod, "load_link_index", dict)
    unwired = hashlib.sha256(render_receipt(entry, layout).tobytes()).hexdigest()

    assert wired != unwired, "renderer ignores transaction_links.yml"
    expected = cfg["schemes"][
        method_from_bank_description(index[f"{case_id}_{entry['layout']}"], cfg)
    ]["display"]
    assert linked.scheme_display == expected


def test_validate_passes_on_the_shipped_corpus():
    from typer.testing import CliRunner

    from generators.pipeline import app

    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 0, result.output


def test_validate_reports_unmapped_bank_descriptions(monkeypatch):
    """A link the mapping cannot resolve must fail validation, not render wrongly."""
    from typer.testing import CliRunner

    import generators.pipeline as pipeline_mod
    from generators.pipeline import app

    monkeypatch.setattr(
        pipeline_mod,
        "load_link_index",
        lambda: {"CASE001_receipt_fuel": "BITCOIN TRANSFER SATOSHI"},
    )
    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 1
    assert "CASE001_receipt_fuel" in result.output
    assert "BITCOIN TRANSFER SATOSHI" in result.output
