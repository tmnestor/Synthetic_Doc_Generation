"""Trust income schedule renderer — ATO-style grid with label codes.

Renders A4-format trust income schedules with ATO-style header,
structured label-code grid (e.g., label "U" for share of net income,
"Q" for franking credit).
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    draw_separator_line,
    draw_table,
    draw_text_center,
    draw_text_right,
    fmt_amount,
    load_font,
)


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
        bbox = font.getbbox(ch)
        char_w = bbox[2] - bbox[0]
        char_h = bbox[3] - bbox[1]
        cx = bx + (box_size - char_w) // 2
        cy = y + (box_size - char_h) // 2
        draw.text((cx, cy), ch, font=font, fill="black")


def render_trust_income_schedule(entry: dict, layout: dict) -> Image.Image:
    """Render a trust income schedule from ground truth and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered trust income schedule.
    """
    fields = entry["fields"]
    page_dims = layout.get("page_dimensions", {})
    width = page_dims.get("width", 2480)
    height = page_dims.get("height", 3508)
    margin = layout.get("margin", 120)
    right_edge = width - margin

    font_sizes = layout.get("font_sizes", {})
    colors = layout.get("colors", {})

    font_h = load_font(font_sizes.get("header", 40), bold=True)
    font_sub = load_font(font_sizes.get("subheader", 28), bold=True)
    font_b = load_font(font_sizes.get("body", 22))
    font_s = load_font(font_sizes.get("small", 18))
    font_lc = load_font(font_sizes.get("label_code", 26), bold=True)

    label_code_color = colors.get("label_code_color", "#0066CC")
    grid_line_color = colors.get("grid_line", "#CCCCCC")

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

                if fmt == "digit_boxes":
                    draw.text((margin, y), label, font=font_b, fill="black")
                    y += 36
                    _draw_digit_boxes(draw, value, margin + 20, y)
                    y += 56
                else:
                    draw.text((margin, y), label, font=font_s, fill="gray")
                    y += 28
                    draw.text((margin + 20, y), value, font=font_b, fill="black")
                    y += 40
            y += 10

        elif sec_type == "grid_section":
            cols = section.get("columns", [])
            kinded: list[dict] = []
            for i, col in enumerate(cols):
                if i == 0:
                    kind = "label_code"
                elif i == len(cols) - 1:
                    kind = "amount"
                else:
                    kind = "description"
                kinded.append({**col, "kind": kind})

            table_rows: list[dict] = []
            for row in section.get("rows", []):
                raw = str(fields.get(row.get("field", ""), ""))
                try:
                    value = fmt_amount(Decimal(raw))
                except Exception:  # noqa: BLE001
                    value = f"${raw}"
                table_rows.append(
                    {
                        "label_code": row.get("label_code", ""),
                        "description": row.get("description", ""),
                        "value": value,
                    }
                )

            y = draw_table(
                draw,
                x_left=margin,
                x_right=right_edge,
                y=y,
                title=section.get("title", ""),
                columns=kinded,
                rows=table_rows,
                total=None,
                font_sub=font_sub,
                font_body=font_b,
                font_small=font_s,
                font_label_code=font_lc,
                section_bg=colors.get("section_bg", "#F0F0F0"),
                header_row_bg="#E8E8E8",
                grid_line=grid_line_color,
                label_code_color=label_code_color,
            )

        elif sec_type == "separator":
            draw_separator_line(draw, margin, right_edge, y + 8, color=grid_line_color, width=1)
            y += section.get("height", 20)

        elif sec_type == "footer":
            footer_y = height - 60
            text = section.get("text", "")
            draw_text_center(draw, text, footer_y, width, font_s, fill="gray")

    return img
