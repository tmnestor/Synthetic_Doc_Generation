"""Startup validation for a layout's `body:` tree.

Every layout is fully checked before any rendering begins, per CLAUDE.md's
fail-fast rule: unknown primitives, missing keys, unknown field references and
unregistered row providers all fail here with a four-element diagnostic.
"""

from generators.layout_dsl.binding import referenced_fields
from generators.layout_dsl.providers import provider_names

# `frame` and `grouping` are independent axes describing a table's row style.
#
# `frame` -- how rows and the header are decorated:
#   ruled    -- rule lines above/below the header.
#   bordered -- a bordered header box + interior column dividers, a rule
#               above every row but the first.
#   filled   -- a `fill_color` rectangle drawn behind the header bar and
#               behind each group's dedicated date row (NAB's light-blue bar).
#   plain    -- no header or row decoration at all.
#
# `grouping` -- how repeated transaction dates are handled:
#   none          -- dates repeat on every row.
#   dedicated_row -- a separate bold date sub-header row is inserted whenever
#                    the date changes (CBA's "grouped").
#   inline        -- the repeated date is blanked within the row and the row
#                    above a new group is ruled/bordered, without consuming a
#                    row of its own (Westpac premium's "bordered_grouped").
FRAMES = ("ruled", "bordered", "filled", "plain")
GROUPINGS = ("none", "dedicated_row", "inline")

# primitive -> (required keys, optional keys)
PRIMITIVES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # `content` and `from_layout` are mutually exclusive alternatives, not two
    # independent optional keys — see the "exactly one of" check in
    # _validate_block. Neither is in `required` because the choice between
    # them is validated there, with a diagnostic naming both options.
    "text": (
        (),
        ("content", "from_layout", "role", "align", "color", "field", "bold", "suppress_if_equals"),
    ),
    "pair": (("label", "value"), ("role", "color", "field")),
    "block": (("lines",), ("role", "color", "heading")),
    "rule": ((), ("color", "thickness", "pad_above", "pad_below")),
    "spacer": ((), ("height",)),
    "panel": (("children",), ("border_color", "padding", "height")),
    "split": (("children",), ("gap", "divider", "divider_color")),
    "banner": (
        ("height", "color"),
        ("content", "from_layout", "text_color", "role", "text_y", "bold"),
    ),
    "table": (
        ("rows", "columns", "frame", "grouping"),
        (
            "params",
            "row_height",
            "header",
            "header_height",
            "dividers",
            "fill_color",
            "fill_inset",
            "fill_height",
            "label_inset_y",
            "group_gap",
            "synthetic_row_placement",
            "header_rule_top",
            "header_rule_gap",
        ),
    ),
}

_CONTAINERS = ("panel", "split")

# Where a provider's leading synthetic row (opening_balance / brought_forward)
# renders relative to `grouping: dedicated_row`'s first date sub-header row:
# "leading" (default) renders it first, ahead of any group header -- CBA's
# Opening Balance. "after_first_group_header" defers it until that header has
# been drawn -- NAB's Brought-forward row, which sits *under* the first date.
SYNTHETIC_ROW_PLACEMENTS = ("leading", "after_first_group_header")


class LayoutSchemaError(RuntimeError):
    """Raised when a layout body fails structural validation."""


def _err(what: str, *, layout_path: str, key_path: str, expected: str, recover: str) -> LayoutSchemaError:
    """Build a four-element fail-fast diagnostic error.

    Args:
        what: What is wrong.
        layout_path: Path to the offending layout YAML.
        key_path: Dotted path to the offending key inside that file.
        expected: What a valid value looks like.
        recover: One-line remediation.

    Returns:
        The constructed error.
    """
    return LayoutSchemaError(
        "Invalid layout body.\n"
        f"  What:     {what}\n"
        f"  Where:    {layout_path} -> {key_path}\n"
        f"  Expected: {expected}\n"
        f"  Recover:  {recover}"
    )


def validate_body(
    body: list,
    *,
    layout_id: str,
    layout_path: str,
    known_fields: set[str],
) -> None:
    """Validate a layout's body tree, recursing into containers.

    Args:
        body: The layout's `body:` list of block dicts.
        layout_id: Layout id, used in diagnostics.
        layout_path: Path to the layout YAML, used in diagnostics.
        known_fields: Field names the document type may reference.

    Raises:
        LayoutSchemaError: On any structural or reference problem.
    """
    if not isinstance(body, list):
        raise _err(
            f"layout '{layout_id}' body is {type(body).__name__}, not a list.",
            layout_path=layout_path,
            key_path=f"{layout_id}.body",
            expected="a list of block mappings, each with a 'type' key.",
            recover=f"make {layout_id}.body a YAML list.",
        )
    _validate_blocks(
        body,
        layout_id=layout_id,
        layout_path=layout_path,
        known_fields=known_fields,
        key_path=f"{layout_id}.body",
    )


def _validate_blocks(
    blocks: list, *, layout_id: str, layout_path: str, known_fields: set[str], key_path: str
) -> None:
    """Validate a list of blocks at one nesting level."""
    for index, block in enumerate(blocks):
        here = f"{key_path}[{index}]"
        if not isinstance(block, dict):
            raise _err(
                f"block is {type(block).__name__}, not a mapping.",
                layout_path=layout_path,
                key_path=here,
                expected='a mapping such as {type: text, content: "{PAYER_NAME}"}.',
                recover="replace the entry with a block mapping.",
            )
        _validate_block(
            block, layout_id=layout_id, layout_path=layout_path, known_fields=known_fields, key_path=here
        )


def _validate_block(
    block: dict, *, layout_id: str, layout_path: str, known_fields: set[str], key_path: str
) -> None:
    """Validate one block and recurse into any children."""
    kind = block.get("type")
    if kind is None:
        raise _err(
            "block has no 'type' key.",
            layout_path=layout_path,
            key_path=key_path,
            expected=f"type: one of {sorted(PRIMITIVES)}.",
            recover="add a type: key naming the primitive to render.",
        )
    if kind not in PRIMITIVES:
        raise _err(
            f"unknown primitive '{kind}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.type",
            expected=f"one of {sorted(PRIMITIVES)}.",
            recover="use a supported primitive, or add one to PRIMITIVES in "
            "generators/layout_dsl/schema.py.",
        )

    required, optional = PRIMITIVES[kind]
    missing = [key for key in required if key not in block]
    if missing:
        raise _err(
            f"'{kind}' block missing required key(s): {missing}.",
            layout_path=layout_path,
            key_path=key_path,
            expected=f"required {list(required)}; optional {list(optional)}.",
            recover=f"add {missing} to the {kind} block.",
        )
    allowed = set(required) | set(optional) | {"type", "when"}
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise _err(
            f"'{kind}' block has unknown key(s): {unknown}.",
            layout_path=layout_path,
            key_path=key_path,
            expected=f"only {sorted(allowed)}.",
            recover=f"remove {unknown}, or add them to PRIMITIVES in generators/layout_dsl/schema.py.",
        )

    if kind in ("text", "banner"):
        has_content = "content" in block
        has_from_layout = "from_layout" in block
        if has_content == has_from_layout:
            raise _err(
                f"'{kind}' block sets "
                + (
                    "both 'content' and 'from_layout'."
                    if has_content
                    else "neither 'content' nor 'from_layout'."
                ),
                layout_path=layout_path,
                key_path=key_path,
                expected="exactly one of: content: '{FIELD}' (an entry-field template) or "
                "from_layout: <layout_key> (a layout value read literally).",
                recover="set 'content:' or 'from_layout:', not both or neither.",
            )

    _validate_references(block, layout_path=layout_path, known_fields=known_fields, key_path=key_path)

    if kind == "table":
        _validate_table(block, layout_path=layout_path, key_path=key_path)
    if kind in _CONTAINERS:
        _validate_children(
            block,
            layout_id=layout_id,
            layout_path=layout_path,
            known_fields=known_fields,
            key_path=key_path,
        )


def _validate_references(block: dict, *, layout_path: str, known_fields: set[str], key_path: str) -> None:
    """Check every {FIELD} placeholder and `when:` field is a known field."""
    texts: list[str] = []
    for key in ("content", "label", "value", "heading"):
        if isinstance(block.get(key), str):
            texts.append(block[key])
    for line in block.get("lines", []) or []:
        if isinstance(line, str):
            texts.append(line)

    for text in texts:
        for name in referenced_fields(text):
            if name not in known_fields:
                raise _err(
                    f"unknown field reference '{{{name}}}'.",
                    layout_path=layout_path,
                    key_path=key_path,
                    expected=f"a field defined for this document type: {sorted(known_fields)}.",
                    recover=f"fix the field name, or add '{name}' to config/field_definitions.yml.",
                )

    when = block.get("when")
    if when is not None and when not in known_fields:
        raise _err(
            f"'when' references unknown field '{when}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.when",
            expected=f"a field defined for this document type: {sorted(known_fields)}.",
            recover=f"fix the field name, or add '{when}' to config/field_definitions.yml.",
        )


def _validate_table(block: dict, *, layout_path: str, key_path: str) -> None:
    """Check a table's provider, row style, and column definitions."""
    rows = block["rows"]
    if rows not in provider_names():
        raise _err(
            f"unknown row provider '{rows}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.rows",
            expected=f"one of {provider_names()}.",
            recover="set rows: to a registered provider, or register one with "
            "@row_provider in generators/layout_dsl/providers.py.",
        )

    frame = block["frame"]
    if frame not in FRAMES:
        raise _err(
            f"unknown frame '{frame}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.frame",
            expected=f"one of {list(FRAMES)}.",
            recover=f"set frame: to one of {list(FRAMES)}.",
        )

    grouping = block["grouping"]
    if grouping not in GROUPINGS:
        raise _err(
            f"unknown grouping '{grouping}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.grouping",
            expected=f"one of {list(GROUPINGS)}.",
            recover=f"set grouping: to one of {list(GROUPINGS)}.",
        )

    if frame == "filled" and "fill_color" not in block:
        raise _err(
            "frame: filled requires fill_color, which this table block does not set.",
            layout_path=layout_path,
            key_path=f"{key_path}.fill_color",
            expected='a hex color string, e.g. fill_color: "#E8F0FE".',
            recover=f"add fill_color: to the table block, or use a different frame ({list(FRAMES)}).",
        )
    if frame != "filled" and "fill_color" in block:
        raise _err(
            f"fill_color is set but frame is '{frame}', which never draws it.",
            layout_path=layout_path,
            key_path=f"{key_path}.fill_color",
            expected="fill_color only alongside frame: filled.",
            recover="remove fill_color, or set frame: filled.",
        )

    for filled_only_key in ("fill_height", "fill_inset"):
        if frame != "filled" and filled_only_key in block:
            raise _err(
                f"{filled_only_key} is set but frame is '{frame}', which never reads it — only "
                "frame: filled draws a fill for it to adjust.",
                layout_path=layout_path,
                key_path=f"{key_path}.{filled_only_key}",
                expected=f"{filled_only_key} only alongside frame: filled.",
                recover=f"remove {filled_only_key}, or set frame: filled.",
            )

    if grouping != "dedicated_row" and "group_gap" in block:
        raise _err(
            "group_gap is set but grouping is not 'dedicated_row', which never reads it — "
            "only dedicated_row inserts date sub-header rows with a gap between them.",
            layout_path=layout_path,
            key_path=f"{key_path}.group_gap",
            expected="group_gap only alongside grouping: dedicated_row.",
            recover="remove group_gap, or set grouping: dedicated_row.",
        )

    if "synthetic_row_placement" in block:
        if grouping != "dedicated_row":
            raise _err(
                "synthetic_row_placement is set but grouping is not 'dedicated_row', which "
                "never reads it — there is no group header for a synthetic row to be placed "
                "relative to.",
                layout_path=layout_path,
                key_path=f"{key_path}.synthetic_row_placement",
                expected="synthetic_row_placement only alongside grouping: dedicated_row.",
                recover="remove synthetic_row_placement, or set grouping: dedicated_row.",
            )
        if block["synthetic_row_placement"] not in SYNTHETIC_ROW_PLACEMENTS:
            raise _err(
                f"unknown synthetic_row_placement {block['synthetic_row_placement']!r}.",
                layout_path=layout_path,
                key_path=f"{key_path}.synthetic_row_placement",
                expected=f"one of {list(SYNTHETIC_ROW_PLACEMENTS)}.",
                recover=f"set synthetic_row_placement: to one of {list(SYNTHETIC_ROW_PLACEMENTS)}.",
            )

    if frame != "bordered" and "dividers" in block:
        raise _err(
            f"dividers is set but frame is '{frame}', which never draws them — only "
            "frame: bordered cuts the header/body into columns with dividers.",
            layout_path=layout_path,
            key_path=f"{key_path}.dividers",
            expected="dividers only alongside frame: bordered.",
            recover="remove dividers, or set frame: bordered.",
        )

    for ruled_only_key in ("header_rule_top", "header_rule_gap"):
        if frame != "ruled" and ruled_only_key in block:
            raise _err(
                f"{ruled_only_key} is set but frame is '{frame}', which never draws a header rule "
                "to adjust — only frame: ruled draws one.",
                layout_path=layout_path,
                key_path=f"{key_path}.{ruled_only_key}",
                expected=f"{ruled_only_key} only alongside frame: ruled.",
                recover=f"remove {ruled_only_key}, or set frame: ruled.",
            )

    columns = block["columns"]
    if not isinstance(columns, list) or not columns:
        raise _err(
            "table has no columns.",
            layout_path=layout_path,
            key_path=f"{key_path}.columns",
            expected="a non-empty list of {key, label, align, x|x_right} mappings.",
            recover="add at least one column.",
        )
    for index, column in enumerate(columns):
        for required in ("key", "label"):
            if not isinstance(column, dict) or required not in column:
                raise _err(
                    f"column {index} missing '{required}'.",
                    layout_path=layout_path,
                    key_path=f"{key_path}.columns[{index}]",
                    expected="{key: date, label: Date, align: left, x: 0}.",
                    recover=f"add {required}: to the column.",
                )
        sub_line = column.get("sub_line")
        if sub_line is not None and (not isinstance(sub_line, dict) or "key" not in sub_line):
            raise _err(
                f"column {index} sub_line is missing 'key'.",
                layout_path=layout_path,
                key_path=f"{key_path}.columns[{index}].sub_line",
                expected="{key: reference, role: sub_description, color: '#999999', "
                "offset_y: 34, height: 32} — only 'key' is required.",
                recover="add key: to the column's sub_line, naming the row field it reads.",
            )
        if "x" not in column and "x_right" not in column:
            raise _err(
                f"column {index} has neither 'x' nor 'x_right'.",
                layout_path=layout_path,
                key_path=f"{key_path}.columns[{index}]",
                expected="x: <offset from region left> or x_right: <offset from region right>.",
                recover="add x: or x_right: to position the column.",
            )

    for index, divider in enumerate(block.get("dividers", [])):
        if not isinstance(divider, dict) or ("x" not in divider and "x_right" not in divider):
            raise _err(
                f"divider {index} has neither 'x' nor 'x_right'.",
                layout_path=layout_path,
                key_path=f"{key_path}.dividers[{index}]",
                expected="x: <offset from region left> or x_right: <offset from region right>.",
                recover="add x: or x_right: to position the divider, e.g. {x_right: -320}.",
            )


def _validate_children(
    block: dict, *, layout_id: str, layout_path: str, known_fields: set[str], key_path: str
) -> None:
    """Recurse into a container's children.

    `panel` takes a flat list of blocks; `split` takes a list of such lists,
    one per column.
    """
    children = block["children"]
    if block["type"] == "split":
        if not isinstance(children, list) or len(children) < 2:
            raise _err(
                "split needs at least two child columns.",
                layout_path=layout_path,
                key_path=f"{key_path}.children",
                expected="a list of at least two lists of blocks.",
                recover="add a second column, or use panel for a single column.",
            )
        for index, column in enumerate(children):
            _validate_blocks(
                column,
                layout_id=layout_id,
                layout_path=layout_path,
                known_fields=known_fields,
                key_path=f"{key_path}.children[{index}]",
            )
    else:
        _validate_blocks(
            children,
            layout_id=layout_id,
            layout_path=layout_path,
            known_fields=known_fields,
            key_path=f"{key_path}.children",
        )


def validate_layout(layout: dict, *, layout_id: str, layout_path: str, known_fields: set[str]) -> None:
    """Validate a whole layout: its body tree plus geometry-dependent checks.

    Adds the two checks that need the surrounding layout and cannot be made
    from the body alone — column budgets against column geometry, and nested
    container widths against their parent.

    Args:
        layout: The resolved layout dict, carrying `body`, `content_width`,
            and `field_budgets`.
        layout_id: Layout id, used in diagnostics.
        layout_path: Path to the layout YAML, used in diagnostics.
        known_fields: Field names the document type may reference.

    Raises:
        LayoutSchemaError: On any structural, reference, or geometry problem.
    """
    for key, example in (("body", "a list of block mappings"), ("content_width", "1600")):
        if key not in layout:
            raise _err(
                f"layout '{layout_id}' has no '{key}' key.",
                layout_path=layout_path,
                key_path=f"{layout_id}.{key}",
                expected=f"{key}: {example}.",
                recover=f"add a '{key}:' key to {layout_id}, or do not pass this layout "
                f"to validate_layout.",
            )

    validate_body(layout["body"], layout_id=layout_id, layout_path=layout_path, known_fields=known_fields)
    content_width = int(layout["content_width"])
    _validate_geometry(
        layout["body"],
        layout=layout,
        layout_path=layout_path,
        width=content_width,
        key_path=f"{layout_id}.body",
    )


def _column_anchor(column: dict, width: int) -> int:
    """Resolve a column's anchor as an offset from the region's left edge."""
    return int(column["x"]) if "x" in column else width + int(column["x_right"])


def _validate_geometry(blocks: list, *, layout: dict, layout_path: str, width: int, key_path: str) -> None:
    """Recursively check budgets, container widths, and layout-key references."""
    for index, block in enumerate(blocks):
        here = f"{key_path}[{index}]"
        kind = block["type"]

        # `from_layout` and `suppress_if_equals` (text/banner) each hold a
        # layout key name directly (not a `{FIELD}` template) — check the
        # key actually exists here, where the layout dict is in scope, since
        # `_validate_references` only knows entry fields. Each is validated
        # against its own value at its own key_path — do not conflate the
        # two: `from_layout`'s value never lives in `content`.
        if "from_layout" in block:
            key = block["from_layout"]
            if key not in layout:
                raise _err(
                    f"'from_layout' names layout key '{key}', which this layout does not define.",
                    layout_path=layout_path,
                    key_path=f"{here}.from_layout",
                    expected=f"a key present in the layout, e.g. {key}: <value>.",
                    recover=f"add '{key}:' to the layout, or fix the key name.",
                )
        suppress_key = block.get("suppress_if_equals")
        if suppress_key is not None and suppress_key not in layout:
            raise _err(
                f"'suppress_if_equals' names layout key '{suppress_key}', which this layout "
                "does not define.",
                layout_path=layout_path,
                key_path=f"{here}.suppress_if_equals",
                expected=f"a key present in the layout, e.g. {suppress_key}: <value>.",
                recover=f"add '{suppress_key}:' to the layout, or fix the key name.",
            )

        if kind == "table":
            _validate_column_budgets(
                block, layout=layout, layout_path=layout_path, width=width, key_path=here
            )
        elif kind == "panel":
            padding = int(block.get("padding", 0))
            inner = width - 2 * padding
            if inner < 1:
                raise _err(
                    f"panel padding {padding} leaves width {inner} inside a {width}px region.",
                    layout_path=layout_path,
                    key_path=f"{here}.padding",
                    expected=f"padding below {width // 2}, e.g. padding: 10.",
                    recover="reduce the panel's padding, or widen content_width.",
                )
            declared = block.get("height")
            if declared is not None and int(declared) < 2 * padding:
                raise _err(
                    f"panel declares height {int(declared)} but its padding alone needs {2 * padding}px.",
                    layout_path=layout_path,
                    key_path=f"{here}.height",
                    expected=f"height >= {2 * padding}, or padding <= {int(declared) // 2}.",
                    recover="raise the panel's height, or reduce its padding.",
                )
            _validate_geometry(
                block["children"],
                layout=layout,
                layout_path=layout_path,
                width=inner,
                key_path=f"{here}.children",
            )
        elif kind == "split":
            columns = block["children"]
            gap = int(block.get("gap", 0))
            inner = (width - gap * (len(columns) - 1)) // len(columns)
            if inner < 1:
                raise _err(
                    f"split of {len(columns)} columns with gap {gap} leaves column "
                    f"width {inner} inside a {width}px region.",
                    layout_path=layout_path,
                    key_path=f"{here}.gap",
                    expected=f"gap below {width // max(len(columns) - 1, 1)}, e.g. gap: 30.",
                    recover="reduce the gap or the column count.",
                )
            for column_index, child_blocks in enumerate(columns):
                _validate_geometry(
                    child_blocks,
                    layout=layout,
                    layout_path=layout_path,
                    width=inner,
                    key_path=f"{here}.children[{column_index}]",
                )


def _validate_column_budgets(
    block: dict, *, layout: dict, layout_path: str, width: int, key_path: str
) -> None:
    """Check each budgeted column's declared width fits its column geometry.

    The budget is validated, never derived: a mismatch is an authoring error the
    operator must fix in YAML, so the intended width stays visible in the file.
    """
    budgets = layout.get("field_budgets", {})
    columns = block["columns"]
    anchors = sorted(_column_anchor(column, width) for column in columns)

    for index, column in enumerate(columns):
        name = column.get("budget")
        if name is None:
            continue
        if name not in budgets:
            raise _err(
                f"column {index} names budget '{name}', which the layout does not define.",
                layout_path=layout_path,
                key_path=f"{key_path}.columns[{index}].budget",
                expected=f"a key present in field_budgets: {sorted(budgets)}.",
                recover=f"add '{name}: {{width, fit, min_font, max_lines}}' to field_budgets.",
            )

        anchor = _column_anchor(column, width)
        following = [value for value in anchors if value > anchor]
        available = (min(following) if following else width) - anchor
        declared = int(budgets[name]["width"])
        if declared > available:
            raise _err(
                f"column {index} budget '{name}' declares width {declared}px but only "
                f"{available}px is available before the next column.",
                layout_path=layout_path,
                key_path=f"{key_path}.columns[{index}]",
                expected=f"field_budgets.{name}.width <= {available}.",
                recover=f"set field_budgets.{name}.width to {available} or less, or move "
                f"the following column right.",
            )
