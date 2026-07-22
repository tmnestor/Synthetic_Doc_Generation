"""Trust tax return renderer — ATO NAT 0660 inspired layout.

Renders A4-format trust tax returns with ATO-style grey header bar,
item numbers, digit boxes for TFN/ABN, and structured distribution table.
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    Font,
    draw_fitted_left,
    draw_fitted_right,
    draw_separator_line,
    draw_text_center,
    draw_text_right,
    fmt_amount,
    load_font,
)
from generators.layout_budgets import field_budget

_LAYOUT_PATH = "config/layouts/trust_returns.yml"


def _budget(layout: dict, layout_id: str, field: str) -> dict:
    """Look up a field budget for a trust return layout."""
    return field_budget(layout, layout_id, field, layout_path=_LAYOUT_PATH)


def _draw_digit_boxes(
    draw: ImageDraw.ImageDraw,
    value: str,
    x: int,
    y: int,
    box_size: int = 36,
    gap: int = 4,
    font_size: int = 20,
) -> None:
    """Draw individual digit boxes for TFN/ABN display."""
    font = load_font(font_size, mono=True)
    digits = value.replace(" ", "")
    for i, ch in enumerate(digits):
        bx = x + i * (box_size + gap)
        draw.rectangle([(bx, y), (bx + box_size, y + box_size)], outline="#999999", width=1)
        # Center digit in box
        bbox = font.getbbox(ch)
        char_w = bbox[2] - bbox[0]
        char_h = bbox[3] - bbox[1]
        cx = bx + (box_size - char_w) // 2
        cy = y + (box_size - char_h) // 2
        draw.text((cx, cy), ch, font=font, fill="black")
        # Add spacing gap after groups of 3 (for TFN) or 2,3,3,3 (for ABN)
        if value.replace(" ", "") == digits and i in (2, 5) and len(digits) == 9:
            pass  # TFN grouping handled by gap


def _draw_amount_field(
    draw: ImageDraw.ImageDraw,
    label: str,
    amount_str: str,
    x: int,
    y: int,
    right_edge: int,
    font_label: Font,
    layout: dict,
    layout_id: str,
    nominal_size: int,
    item_number: str | None = None,
) -> int:
    """Draw a labelled amount field with optional item number."""
    if item_number:
        font_item = load_font(24, bold=True)
        draw.text((x, y + 2), item_number, font=font_item, fill="#333333")
        draw.text((x + 60, y + 2), label, font=font_label, fill="black")
    else:
        draw.text((x, y + 2), label, font=font_label, fill="black")

    try:
        formatted = fmt_amount(Decimal(amount_str))
    except Exception:  # noqa: BLE001
        formatted = f"${amount_str}"
    draw_fitted_right(
        draw,
        formatted,
        right_edge,
        y + 2,
        budget=_budget(layout, layout_id, "AMOUNT_VALUE"),
        nominal_size=nominal_size,
    )
    return y + 48


def render_trust_return(entry: dict, layout: dict) -> Image.Image:
    """Render a trust tax return from ground truth and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered trust return.
    """
    fields = entry["fields"]
    page_dims = layout.get("page_dimensions", {})
    width = page_dims.get("width", 2480)
    height = page_dims.get("height", 3508)
    margin = layout.get("margin", 120)
    right_edge = width - margin
    layout_id = entry.get("layout", "")

    font_sizes = layout.get("font_sizes", {})
    colors = layout.get("colors", {})

    font_h = load_font(font_sizes.get("header", 40), bold=True)
    font_sub = load_font(font_sizes.get("subheader", 28), bold=True)
    font_b = load_font(font_sizes.get("body", 22))
    font_s = load_font(font_sizes.get("small", 18))

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    for section in layout.get("sections", []):
        sec_type = section.get("type")

        if sec_type == "header_bar":
            bar_h = section.get("height", 100)
            bg = colors.get("header_bg", "#4A4A4A")
            fg = colors.get("header_text", "#FFFFFF")
            draw.rectangle([(0, y), (width, y + bar_h)], fill=bg)
            draw.text((margin, y + 15), section.get("text", ""), font=font_h, fill=fg)
            subtext = section.get("subtext", "")
            if subtext:
                draw_text_right(draw, subtext, right_edge, y + 20, font_sub, fill=fg)
            y += bar_h

        elif sec_type == "spacer":
            y += section.get("height", 40)

        elif sec_type == "section":
            title = section.get("title", "")
            if title:
                sec_bg = colors.get("section_bg", "#F0F0F0")
                draw.rectangle([(margin, y), (right_edge, y + 44)], fill=sec_bg)
                draw.text((margin + 12, y + 8), title, font=font_sub, fill="black")
                y += 56

            for field_def in section.get("fields", []):
                label = field_def.get("label", "")
                field_key = field_def.get("field", "")
                value = str(fields.get(field_key, ""))
                fmt = field_def.get("format", "text")
                item_num = field_def.get("item_number")

                if fmt == "digit_boxes":
                    draw.text((margin, y), label, font=font_b, fill="black")
                    y += 36
                    _draw_digit_boxes(draw, value, margin + 20, y)
                    y += 56

                elif fmt == "amount":
                    y = _draw_amount_field(
                        draw,
                        label,
                        value,
                        margin,
                        y,
                        right_edge,
                        font_b,
                        layout,
                        layout_id,
                        font_sizes.get("body", 22),
                        item_number=item_num,
                    )

                else:
                    draw.text((margin, y), label, font=font_s, fill="gray")
                    y += 28
                    y = draw_fitted_left(
                        draw,
                        value,
                        margin + 20,
                        y,
                        budget=_budget(layout, layout_id, "TEXT_VALUE"),
                        nominal_size=font_sizes.get("body", 22),
                        line_spacing=40,
                    )

            y += 10

        elif sec_type == "separator":
            draw_separator_line(draw, margin, right_edge, y + 8, color="#CCCCCC", width=1)
            y += section.get("height", 30)

        elif sec_type == "footer":
            footer_y = height - 60
            text = section.get("text", "")
            draw_text_center(draw, text, footer_y, width, font_s, fill="gray")

    return img
