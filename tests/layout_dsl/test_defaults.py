import re
from pathlib import Path

import pytest

from generators.layout_dsl.defaults import PARAMETER_DEFAULTS, DefaultsError, resolve_param
from generators.layout_dsl.schema import LayoutSchemaError, validate_layout
from conftest import assert_diagnostic_error

LAYOUT = {"defaults": {"color": "#000000", "align": "left", "bold": False}}
KW = {"layout_id": "receipt_thermal_80mm", "layout_path": "config/layouts/receipts.yml"}


def test_block_key_wins_over_defaults():
    assert resolve_param({"color": "#12107D"}, LAYOUT, "color", **KW) == "#12107D"


def test_defaults_supply_an_absent_block_key():
    assert resolve_param({}, LAYOUT, "color", **KW) == "#000000"


def test_falsy_default_is_not_treated_as_absent():
    """`bold: false` is a real configured value, not a missing key. A truthiness
    test here would silently fall through to the fail-fast branch."""
    assert resolve_param({}, LAYOUT, "bold", **KW) is False


def test_missing_default_fails_with_a_four_element_diagnostic():
    with pytest.raises(DefaultsError) as exc_info:
        resolve_param({}, LAYOUT, "role", **KW)
    assert_diagnostic_error(exc_info.value)
    message = str(exc_info.value)
    assert "config/layouts/receipts.yml" in message
    assert "receipt_thermal_80mm.defaults.role" in message


def test_block_key_override_wins_when_it_differs_from_the_default_name():
    """A per-block override under its own short YAML key must win over the
    layout default even when `PARAMETER_DEFAULTS` namespaces the two names
    differently -- e.g. a panel's `padding:` block key vs. its
    `panel_padding` layout default.

    This is the exact bug Task 3's first pass introduced: calling
    `resolve_param(block, layout, "panel_padding", ...)` with no `block_key`
    looked for `block["panel_padding"]`, which no panel block ever sets (the
    YAML key stays `padding:`), so it silently fell through to the shared
    layout default. The pixel snapshot caught it on NAB's real
    `group_gap: 0` / `fill_inset: 2` overrides, both of which differ from
    their shared defaults and would have rendered wrong.
    """
    layout = {"defaults": {"panel_padding": 0}}
    block = {"padding": 18}
    assert resolve_param(block, layout, "panel_padding", block_key="padding", **KW) == 18


def test_block_key_falls_through_to_the_default_when_absent():
    """When `block_key` differs from `key` and the block doesn't set it, the
    layout default (looked up under `key`, not `block_key`) still applies."""
    layout = {"defaults": {"panel_padding": 0}}
    assert resolve_param({}, layout, "panel_padding", block_key="padding", **KW) == 0


def test_parameter_defaults_covers_all_primitive_get_sites():
    """Every layout-parameter `.get()`/`resolve_param()` call in the primitive
    files must resolve through a name in `PARAMETER_DEFAULTS`.

    Keyed off the *receiver* -- the dict a call reads from -- not the bare key
    name. `block.get(...)` and `resolve_param(block, ...)` read layout
    configuration written by a layout author in YAML (as does `sub_line`, a
    table column's nested sub-line spec); `row.get(...)` reads provider-set
    row *data* and is never checked here -- `row` is simply absent from
    `LAYOUT_RECEIVERS`, rather than its keys ("bold", "date") being excluded
    by name. Excluding by key name would also silence the guard on `bold`'s
    *legitimate* block-level use in `draw_text_block`/`draw_banner` -- exactly
    the anti-pattern two earlier Task 2 review rounds caught. See
    `test_row_data_never_resolves_through_the_layout` for the companion check
    that `row` never gains a `resolve_param` call in the first place: routing
    row data through a layout's `defaults:` is a real bug Task 3's first pass
    introduced (`row["bold"]` silently resolved through the layout, green
    only because every bank layout happened to seed `bold: false`).

    Every `resolve_param(receiver, ctx.layout, "key", ...)` call site already
    passes the literal `PARAMETER_DEFAULTS` name as `key` -- namespacing, where
    a block's own YAML key differs, lives in the separate `block_key=`
    argument, not in `key` -- so no key-name translation table is needed here
    (unlike the pre-Task-3 `.get()` calls this test used to map through a
    hand-maintained `KEY_TO_DEFAULTS`, which could silently go stale). The one
    surviving parameter-shaped `.get()` call is `block.get("params", {})`: a
    table's own params passthrough to its row provider, not a pixel decision
    -- named explicitly in `NON_PARAMETER_BLOCK_KEYS` rather than silently
    ignored.
    """
    LAYOUT_RECEIVERS = {"block", "sub_line"}
    NON_PARAMETER_BLOCK_KEYS = {"params"}

    primitives_dir = Path(__file__).parent.parent.parent / "generators" / "layout_dsl"
    primitive_files = [
        primitives_dir / "primitives_text.py",
        primitives_dir / "primitives_table.py",
        primitives_dir / "primitives_container.py",
    ]
    content = "\n".join(f.read_text() for f in primitive_files)

    get_pattern = re.compile(r'(\w+)\.get\("([^"]+)",')
    resolve_param_pattern = re.compile(r'resolve_param\(\s*(\w+)\s*,\s*ctx\.layout\s*,\s*"([^"]+)"')

    missing = {}
    for receiver, key in get_pattern.findall(content):
        if receiver not in LAYOUT_RECEIVERS or key in NON_PARAMETER_BLOCK_KEYS:
            continue
        missing[f"{receiver}.get({key!r}, ...)"] = (
            "layout-parameter .get() call not yet converted to resolve_param"
        )
    for receiver, key in resolve_param_pattern.findall(content):
        if receiver not in LAYOUT_RECEIVERS:
            continue
        if key not in PARAMETER_DEFAULTS:
            missing[f"resolve_param({receiver}, ..., {key!r})"] = "not in PARAMETER_DEFAULTS"

    assert not missing, "Parameters lack PARAMETER_DEFAULTS coverage:\n" + "\n".join(
        f"  {k}: {v}" for k, v in sorted(missing.items())
    )


def test_row_data_never_resolves_through_the_layout():
    """Provider row data must stay on `row.get(...)` and never route through
    `resolve_param`.

    `row["bold"]`/`row["date"]` are facts a row provider stamps onto its own
    data (e.g. NAB's "Carried forward" row, or ANZ's mixed-weight "BALANCE
    BROUGHT FORWARD" row), not layout configuration an author writes in YAML.
    Resolving them through a layout's `defaults:` is a real bug a green pixel
    snapshot does not, by itself, catch: every bank layout happens to seed
    `bold: false`, so a silently-wrong resolution renders identically to a
    correct one until some layout's default differs. This is exactly what
    Task 3's first pass shipped (`_cell_bold`/`_validate_bold_spec` calling
    `resolve_param(row, ...)`) -- caught in review, not by any automated
    check, which is why this test now exists.
    """
    primitives_dir = Path(__file__).parent.parent.parent / "generators" / "layout_dsl"
    content = (primitives_dir / "primitives_table.py").read_text()
    assert not re.search(r"resolve_param\(\s*row\s*,", content), (
        "found resolve_param(row, ...): provider row data must stay on row.get(), "
        "never resolve through the layout's defaults:"
    )


def test_incomplete_defaults_block_is_rejected():
    layout = {"defaults": {"color": "#000000"}, "body": [], "font_sizes": {"body": 32}}
    with pytest.raises(LayoutSchemaError) as exc_info:
        validate_layout(
            layout, layout_id="probe", layout_path="config/layouts/receipts.yml", known_fields=set()
        )
    assert_diagnostic_error(exc_info.value)
    assert "align" in str(exc_info.value)


def test_bank_layouts_cover_every_parameter_name():
    """Guards against adding a parameter to PARAMETER_DEFAULTS and forgetting to
    seed it in the shipped layouts — validate would then fail only at render.

    Kept alongside the widened check below: this one names the file whose
    layouts have carried `defaults:` since Task 3, so a bank-only regression
    still fails under its own name.
    """
    from generators.loader import load_layout_registry

    registry = load_layout_registry(Path("config/layouts/bank_statements.yml"))
    for layout_id, layout in registry.items():
        missing = PARAMETER_DEFAULTS - set(layout.get("defaults", {}))
        assert not missing, f"bank_statements.yml -> {layout_id} missing defaults: {sorted(missing)}"


def test_all_layouts_cover_every_parameter_name():
    """The check above was scoped to bank_statements.yml because receipts and
    invoices had no `defaults:` yet. All three carry it now (Tasks 14 and 15),
    so every declarative layout in the repo is covered."""
    from generators.loader import load_layout_registry

    for name in ("bank_statements", "receipts", "invoices"):
        registry = load_layout_registry(Path(f"config/layouts/{name}.yml"))
        assert registry, f"{name}.yml declares no layouts"
        for layout_id, layout in registry.items():
            missing = PARAMETER_DEFAULTS - set(layout.get("defaults", {}))
            assert not missing, f"{name}.yml -> {layout_id} missing defaults: {sorted(missing)}"
