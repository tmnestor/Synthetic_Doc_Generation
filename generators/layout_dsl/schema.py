"""Startup validation for a layout's `body:` tree.

Every layout is fully checked before any rendering begins, per CLAUDE.md's
fail-fast rule: unknown primitives, missing keys, unknown field references and
unregistered row providers all fail here with a four-element diagnostic.
"""

from generators.layout_dsl.binding import referenced_fields
from generators.layout_dsl.providers import provider_names

ROW_STYLES = ("ruled", "bordered", "grouped", "plain")

# primitive -> (required keys, optional keys)
PRIMITIVES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "text": (("content",), ("role", "align", "color", "field")),
    "pair": (("label", "value"), ("role", "color", "field")),
    "block": (("lines",), ("role", "color", "heading")),
    "rule": ((), ("color", "thickness", "pad_above", "pad_below")),
    "spacer": ((), ("height",)),
    "panel": (("children",), ("border_color", "padding", "height")),
    "split": (("children",), ("gap",)),
    "table": (("rows", "columns"), ("row_style", "params", "row_height", "header")),
}

_CONTAINERS = ("panel", "split")


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

    style = block.get("row_style", "plain")
    if style not in ROW_STYLES:
        raise _err(
            f"unknown row_style '{style}'.",
            layout_path=layout_path,
            key_path=f"{key_path}.row_style",
            expected=f"one of {list(ROW_STYLES)}.",
            recover="set row_style to a supported style.",
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
        if "x" not in column and "x_right" not in column:
            raise _err(
                f"column {index} has neither 'x' nor 'x_right'.",
                layout_path=layout_path,
                key_path=f"{key_path}.columns[{index}]",
                expected="x: <offset from region left> or x_right: <offset from region right>.",
                recover="add x: or x_right: to position the column.",
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
    """Recursively check budgets and container widths against available space."""
    for index, block in enumerate(blocks):
        here = f"{key_path}[{index}]"
        kind = block["type"]

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
