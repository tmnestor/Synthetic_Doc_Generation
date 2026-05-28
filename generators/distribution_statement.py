"""Distribution statement renderer — custom LMM-friendly design.

Renders A4-format distribution statements with clean professional letterhead,
clearly labelled dollar-amount rows with generous spacing.
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    draw_separator_line,
    draw_text_center,
    draw_text_right,
    fmt_amount,
    load_font,
)


def render_distribution_statement(entry: dict, layout: dict) -> Image.Image:
    """Render a distribution statement from ground truth and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered distribution statement.
    """
    fields = entry["fields"]
    page_dims = layout.get("page_dimensions", {})
    width = page_dims.get("width", 2480)
    height = page_dims.get("height", 3508)
    margin = layout.get("margin", 140)
    right_edge = width - margin

    font_sizes = layout.get("font_sizes", {})
    colors = layout.get("colors", {})

    font_h = load_font(font_sizes.get("header", 44), bold=True)
    font_sub = load_font(font_sizes.get("subheader", 28), bold=True)
    font_b = load_font(font_sizes.get("body", 22))
    font_s = load_font(font_sizes.get("small", 18))

    header_color = colors.get("header_color", "#1A1A2E")
    accent_color = colors.get("accent_color", "#16213E")
    line_color = colors.get("line_color", "#CCCCCC")

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    for section in layout.get("sections", []):
        sec_type = section.get("type")

        if sec_type == "letterhead":
            title = section.get("title", "Statement of Distribution")
            subtitle = section.get("subtitle", "")
            draw.text((margin, y), title, font=font_h, fill=header_color)
            y += 60
            if subtitle:
                draw.text((margin, y), subtitle, font=font_sub, fill=accent_color)
                y += 44
            # Accent line under letterhead
            draw_separator_line(draw, margin, right_edge, y, color=header_color, width=3)
            y += section.get("height", 120) - 100

        elif sec_type == "spacer":
            y += section.get("height", 30)

        elif sec_type == "section":
            title = section.get("title", "")
            if title:
                draw.text((margin, y), title, font=font_sub, fill=accent_color)
                y += 40

            for field_def in section.get("fields", []):
                label = field_def.get("label", "")
                field_key = field_def.get("field", "")
                value = str(fields.get(field_key, ""))
                fmt = field_def.get("format", "text")

                if fmt == "amount":
                    draw.text((margin + 20, y), label, font=font_b, fill="black")
                    try:
                        formatted = fmt_amount(Decimal(value))
                    except Exception:  # noqa: BLE001
                        formatted = f"${value}"
                    draw_text_right(draw, formatted, right_edge, y, font_b)
                    # Dotted underline for amount fields
                    draw_separator_line(
                        draw,
                        margin + 20,
                        right_edge,
                        y + 34,
                        color=line_color,
                        width=1,
                    )
                    y += 52

                else:
                    draw.text((margin + 20, y), f"{label}:", font=font_s, fill="gray")
                    y += 26
                    draw.text((margin + 40, y), value, font=font_b, fill="black")
                    y += 38

            y += 16

        elif sec_type == "separator":
            draw_separator_line(draw, margin, right_edge, y + 8, color=line_color, width=1)
            y += section.get("height", 20)

        elif sec_type == "declaration":
            text = section.get("text", "")
            if text:
                # Word-wrap the declaration text
                words = text.split()
                lines: list[str] = []
                current_line = ""
                for word in words:
                    test = f"{current_line} {word}".strip()
                    bbox = font_s.getbbox(test)
                    if bbox[2] - bbox[0] > right_edge - margin - 40:
                        lines.append(current_line)
                        current_line = word
                    else:
                        current_line = test
                if current_line:
                    lines.append(current_line)
                for line in lines:
                    draw.text((margin + 20, y), line, font=font_s, fill="#555555")
                    y += 28
                y += 20

        elif sec_type == "footer":
            footer_y = height - 60
            text = section.get("text", "")
            draw_text_center(draw, text, footer_y, width, font_s, fill="gray")

    return img
