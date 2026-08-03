"""Parameter resolution for layout primitives.

Resolution order is block key -> the layout's `defaults:` -> fail fast. There is
deliberately no fourth step: a Python literal supplying a value YAML omitted is
exactly what CLAUDE.md's "every config key is required" rule forbids, and it is
how `role`, `color`, `align` and 28 other pixel decisions came to live in Python
rather than in the layout files.
"""

# Every parameter a primitive may read. schema.py asserts a layout's `defaults:`
# covers all of them, so an omission fails at startup rather than at whichever
# block first happens to need it.
PARAMETER_DEFAULTS: frozenset[str] = frozenset(
    {
        "role",
        "color",
        "align",
        "bold",
        "line_advance",
        "mono",
        "rule_thickness",
        "rule_pad_above",
        "rule_pad_below",
        "rule_fill_char",
        "spacer_height",
        "pair_value_align",
        "pair_min_gap",
        "table_header",
        "table_header_rule_top",
        "table_header_rule_gap",
        "table_group_gap",
        "table_fill_inset",
        "table_dividers",
        "table_offset_y",
        "table_capture",
        "banner_text_color",
        "banner_role",
        "panel_padding",
        "panel_border_color",
        "split_gap",
        "split_divider_color",
    }
)


class DefaultsError(RuntimeError):
    """Raised when neither a block nor its layout supplies a parameter."""


_SENTINEL = object()


def resolve_param(block: dict, layout: dict, key: str, *, layout_id: str, layout_path: str) -> object:
    """Resolve one primitive parameter.

    Args:
        block: The block dict, whose own key wins if present.
        layout: The resolved layout dict, carrying a `defaults:` mapping.
        key: The parameter name, e.g. "color".
        layout_id: Layout id, used in the diagnostic.
        layout_path: Path to the layout YAML, used in the diagnostic.

    Returns:
        The block's value if it carries `key`, otherwise the layout default.

    Raises:
        DefaultsError: If neither supplies `key`.
    """
    value = block.get(key, _SENTINEL)
    if value is not _SENTINEL:
        return value

    default = layout.get("defaults", {}).get(key, _SENTINEL)
    if default is not _SENTINEL:
        return default

    raise DefaultsError(
        "Missing layout default.\n"
        f"  What:     no value for '{key}' on this block, and layout "
        f"'{layout_id}' declares no default for it.\n"
        f"  Where:    {layout_path} -> {layout_id}.defaults.{key}\n"
        f"  Expected: a defaults: mapping covering every parameter, e.g.\n"
        f"              defaults:\n"
        f"                {key}: <value>\n"
        f"  Recover:  add '{key}:' under {layout_id}.defaults, or set it on "
        f"the block itself when it varies block to block."
    )
