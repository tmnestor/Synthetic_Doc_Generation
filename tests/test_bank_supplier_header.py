"""Bank statements must follow the brand-vs-supplier pattern credit-card
statements used before Stage 4 deleted that document type.

Two defects this locks down:

1. Each bank renderer hard-coded its letterhead brand as a Python string
   literal (``"Commonwealth Bank"`` etc.), shadowing the layout YAML — a
   "YAML is the single source of truth" violation. The header text must come
   from the layout's ``logo_text`` key.
2. ``SUPPLIER_NAME`` was never drawn, so a statement whose content supplier
   differs from the letterhead brand (50 of 55 in the corpus) silently
   contradicted the visible page. The supplier must be rendered as a
   secondary line whenever it differs from ``layout["bank"]`` (and
   suppressed when it matches, to avoid duplication).
"""

from pathlib import Path

import pytest
import yaml
from PIL import ImageDraw

from generators.bank_statement import render_bank_statement
from generators.layout_budgets import field_budget
from generators.loader import load_ground_truth, load_layout_registry

_LP = "config/layouts/bank_statements.yml"


def _canonical_bank_names() -> dict:
    """Layout-prefix (== banks-pool code) -> canonical supplier name."""
    pools = yaml.safe_load(Path("config/data_pools.yml").read_text())
    return {b["code"]: b["name"] for b in pools["banks"]}


# One representative layout per renderer family (cba / westpac / nab / anz).
_REPRESENTATIVE_LAYOUTS = ["cba_standard", "westpac_standard", "nab_classic", "anz_standard"]


def _layouts() -> dict:
    return load_layout_registry(Path(_LP))


def _entries() -> dict:
    return load_ground_truth(Path("ground_truth/bank_statements.yml"))


def _entry_for_layout(layout_id: str) -> tuple[str, dict]:
    for case_id, entry in _entries().items():
        if entry.get("layout") == layout_id:
            entry = dict(entry)
            entry["fields"] = dict(entry["fields"])
            entry["case_id"] = str(case_id)
            return str(case_id), entry
    raise AssertionError(f"no ground-truth entry uses layout {layout_id!r}")


def _capture_drawn_text(monkeypatch) -> list[str]:
    """Spy on ImageDraw.text, recording every string drawn to any canvas."""
    drawn: list[str] = []
    original = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *args, **kwargs):  # noqa: ANN001
        drawn.append(text)
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    return drawn


@pytest.mark.parametrize("layout_id", _REPRESENTATIVE_LAYOUTS)
def test_header_brand_reads_from_layout_logo_text(layout_id, monkeypatch):
    """The header string must be the layout's logo_text, not a Python literal."""
    layout = dict(_layouts()[layout_id])
    layout["logo_text"] = "SENTINEL_BRAND_XYZ"
    _, entry = _entry_for_layout(layout_id)

    drawn = _capture_drawn_text(monkeypatch)
    render_bank_statement(entry, layout)

    assert "SENTINEL_BRAND_XYZ" in drawn, (
        f"{layout_id} header ignored layout['logo_text'] — brand is still hard-coded"
    )


@pytest.mark.parametrize("layout_id", _REPRESENTATIVE_LAYOUTS)
def test_supplier_name_rendered_when_it_differs_from_bank(layout_id):
    """SUPPLIER_NAME must be drawn (and geometry-recorded) when it is neither the
    legal bank name nor the drawn logo_text letterhead."""
    layout = _layouts()[layout_id]
    _, entry = _entry_for_layout(layout_id)
    entry["fields"]["SUPPLIER_NAME"] = "Distinct Supplier Pty Ltd"
    assert entry["fields"]["SUPPLIER_NAME"] not in (layout["bank"], layout["logo_text"])  # precondition

    geometry: dict = {}
    render_bank_statement(entry, layout, geometry_out=geometry)

    assert "SUPPLIER_NAME" in geometry["boxes"], (
        f"{layout_id} did not render SUPPLIER_NAME — the content supplier is invisible on the page"
    )


@pytest.mark.parametrize("layout_id", _REPRESENTATIVE_LAYOUTS)
def test_supplier_name_suppressed_only_when_it_equals_drawn_logo_text(layout_id):
    """Suppress the supplier line only when the supplier is already drawn verbatim
    as the letterhead (logo_text) — never merely because it equals the legal bank
    name, which is a different string from what the header renders."""
    layout = _layouts()[layout_id]
    _, entry = _entry_for_layout(layout_id)
    entry["fields"]["SUPPLIER_NAME"] = layout["logo_text"]

    geometry: dict = {}
    render_bank_statement(entry, layout, geometry_out=geometry)

    assert "SUPPLIER_NAME" not in geometry["boxes"], (
        f"{layout_id} drew SUPPLIER_NAME even though it equals the drawn logo_text — duplicate"
    )


@pytest.mark.parametrize("layout_id", _REPRESENTATIVE_LAYOUTS)
def test_supplier_name_drawn_when_it_equals_legal_bank_but_not_logo_text(layout_id):
    """Benchmark guarantee: a supplier equal to the legal bank name (but not the
    short drawn logo_text) must still be rendered — the legal name is not on the
    page otherwise, so a VLM scored against SUPPLIER_NAME could never extract it."""
    layout = _layouts()[layout_id]
    if layout["bank"] == layout["logo_text"]:
        pytest.skip("legal name equals logo_text for this layout")
    _, entry = _entry_for_layout(layout_id)
    entry["fields"]["SUPPLIER_NAME"] = layout["bank"]

    geometry: dict = {}
    render_bank_statement(entry, layout, geometry_out=geometry)

    assert "SUPPLIER_NAME" in geometry["boxes"], (
        f"{layout_id} did not render a supplier equal to the legal bank name — unextractable"
    )


def test_every_corpus_supplier_name_is_extractable_on_the_page():
    """The whole corpus: every non-empty SUPPLIER_NAME must appear on the rendered
    page (recorded as its own box, or already present verbatim as the logo_text
    letterhead). If it is not on the page, a VLM cannot extract it and the
    benchmark is unscoreable."""
    layouts = _layouts()
    for case_id, entry in _entries().items():
        entry["case_id"] = str(case_id)
        layout = layouts[entry["layout"]]
        supplier = entry["fields"].get("SUPPLIER_NAME", "")
        if not supplier or supplier == "NOT_FOUND":
            continue
        geometry: dict = {}
        render_bank_statement(entry, layout, geometry_out=geometry)
        on_page = "SUPPLIER_NAME" in geometry["boxes"] or supplier == layout["logo_text"]
        assert on_page, (
            f"{case_id}: SUPPLIER_NAME {supplier!r} is not on the page "
            f"(logo_text={layout['logo_text']!r}) — unextractable for VLM benchmarking"
        )


def test_supplier_name_is_consistent_with_the_layout_bank_across_corpus():
    """Ground-truth invariant: a CBA-layout statement must carry a CBA supplier,
    never ANZ. SUPPLIER_NAME must be the canonical bank name implied by the
    layout (its prefix maps to a banks-pool code)."""
    names = _canonical_bank_names()
    for case_id, entry in _entries().items():
        code = entry["layout"].split("_")[0]  # cba / westpac / nab / anz
        expected = names[code]
        actual = entry["fields"]["SUPPLIER_NAME"]
        assert actual == expected, (
            f"{case_id}: layout {entry['layout']!r} implies supplier {expected!r} "
            f"but SUPPLIER_NAME is {actual!r} — bank inconsistent with layout"
        )


def test_every_bank_layout_has_a_supplier_name_budget():
    """Fit-safety: SUPPLIER_NAME is a fitted field, so every layout needs its budget."""
    for lid, layout in _layouts().items():
        budget = field_budget(layout, lid, "SUPPLIER_NAME", layout_path=_LP)  # must not raise
        assert budget["max_lines"] >= 1
