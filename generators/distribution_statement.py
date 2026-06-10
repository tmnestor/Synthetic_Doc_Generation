"""Distribution statement renderer — six trustee-produced layouts.

Renders A4 distribution statements across accounting-software, tabular, and
trustee-letter archetypes. Every layout exposes the same scalar fields; only
structure, styling, and label wording differ. Section types are interpreted
from the layout YAML (the single source of truth).
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    Font,
    draw_separator_line,
    draw_table,
    draw_text_center,
    draw_text_right,
    fmt_amount,
    load_font,
)


def _subst(text: str, fields: dict) -> str:
    """Replace {FIELD_KEY} placeholders with field values (text/identity only)."""
    out = text
    for key, value in fields.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _fmt(value: str) -> str:
    """Format a raw decimal string as $X,XXX.XX, falling back gracefully."""
    try:
        return fmt_amount(Decimal(value))
    except Exception:  # noqa: BLE001
        return f"${value}"


def _draw_paragraph(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    x_left: int,
    x_right: int,
    font: Font,
    fill: str = "black",
) -> int:
    """Word-wrap and draw a paragraph; return the y below it."""
    line = ""
    for word in text.split():
        test = f"{line} {word}".strip()
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] > x_right - x_left and line:
            draw.text((x_left, y), line, font=font, fill=fill)
            y += 32
            line = word
        else:
            line = test
    if line:
        draw.text((x_left, y), line, font=font, fill=fill)
        y += 32
    return y


def _draw_column_block(
    draw: ImageDraw.ImageDraw,
    block: dict,
    fields: dict,
    y: int,
    x: int,
    font_sub: Font,
    font_b: Font,
    font_s: Font,
    accent: str,
) -> int:
    """Draw one column of a two_column section; return its bottom y."""
    title = block.get("title", "")
    if title:
        draw.text((x, y), title, font=font_sub, fill=accent)
        y += 40
    for fd in block.get("fields", []):
        draw.text((x, y), f"{fd.get('label', '')}:", font=font_s, fill="gray")
        y += 26
        draw.text((x + 20, y), str(fields.get(fd.get("field", ""), "")), font=font_b, fill="black")
        y += 38
    return y


def render_distribution_statement(entry: dict, layout: dict) -> Image.Image:
    """Render a distribution statement from ground truth and layout config.

    Args:
        entry: Ground truth YAML entry with a 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered distribution statement.
    """
    fields = entry["fields"]
    page_dims = layout.get("page_dimensions", {})
    width = page_dims.get("width", 1600)
    height = page_dims.get("height", 3508)
    margin = layout.get("margin", 140)
    right_edge = width - margin

    fs = layout.get("font_sizes", {})
    colors = layout.get("colors", {})

    font_h = load_font(fs.get("header", 44), bold=True)
    font_sub = load_font(fs.get("subheader", 28), bold=True)
    font_b = load_font(fs.get("body", 22))
    font_s = load_font(fs.get("small", 18))
    font_lc = load_font(fs.get("label_code", 26), bold=True)

    header_color = colors.get("header_color", "#1A1A2E")
    accent_color = colors.get("accent_color", "#16213E")
    line_color = colors.get("line_color", "#CCCCCC")

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    for section in layout.get("sections", []):
        st = section.get("type")

        if st == "letterhead":
            draw.text((margin, y), section.get("title", ""), font=font_h, fill=header_color)
            y += 60
            subtitle = section.get("subtitle", "")
            if subtitle:
                draw.text((margin, y), subtitle, font=font_sub, fill=accent_color)
                y += 44
            draw_separator_line(draw, margin, right_edge, y, color=header_color, width=3)
            y += section.get("height", 120) - 100

        elif st == "header_bar":
            bar_h = section.get("height", 100)
            bg = colors.get("header_bg", "#0B6E6E")
            fg = colors.get("header_text", "#FFFFFF")
            draw.rectangle([(0, y), (width, y + bar_h)], fill=bg)
            draw.text((margin, y + 15), section.get("text", ""), font=font_h, fill=fg)
            subtext = section.get("subtext", "")
            if subtext:
                draw_text_right(draw, subtext, right_edge, y + 22, font_sub, fill=fg)
            y += bar_h + 20

        elif st == "spacer":
            y += section.get("height", 30)

        elif st == "section":
            title = section.get("title", "")
            if title:
                draw.text((margin, y), title, font=font_sub, fill=accent_color)
                y += 40
            for fd in section.get("fields", []):
                label = fd.get("label", "")
                value = str(fields.get(fd.get("field", ""), ""))
                if fd.get("format") == "amount":
                    draw.text((margin + 20, y), label, font=font_b, fill="black")
                    draw_text_right(draw, _fmt(value), right_edge, y, font_b)
                    draw_separator_line(draw, margin + 20, right_edge, y + 34, color=line_color, width=1)
                    y += 52
                else:
                    draw.text((margin + 20, y), f"{label}:", font=font_s, fill="gray")
                    y += 26
                    draw.text((margin + 40, y), value, font=font_b, fill="black")
                    y += 38
            y += 16

        elif st == "two_column":
            mid = (margin + right_edge) // 2
            start_y = y
            y_left = _draw_column_block(
                draw,
                section.get("left", {}),
                fields,
                start_y,
                margin,
                font_sub,
                font_b,
                font_s,
                accent_color,
            )
            y_right = _draw_column_block(
                draw,
                section.get("right", {}),
                fields,
                start_y,
                mid + 20,
                font_sub,
                font_b,
                font_s,
                accent_color,
            )
            y = max(y_left, y_right) + 16

        elif st == "table":
            rows = [
                {
                    "label_code": r.get("label_code", ""),
                    "description": r.get("description", ""),
                    "value": _fmt(str(fields.get(r.get("field", ""), ""))),
                }
                for r in section.get("rows", [])
            ]
            total = None
            tr = section.get("total_row")
            if tr is not None:
                total = {
                    "description": tr.get("label", ""),
                    "value": _fmt(str(fields.get(tr.get("field", ""), ""))),
                }
            y = draw_table(
                draw,
                x_left=margin,
                x_right=right_edge,
                y=y,
                title=section.get("title", ""),
                columns=section.get("columns", []),
                rows=rows,
                total=total,
                font_sub=font_sub,
                font_body=font_b,
                font_small=font_s,
                font_label_code=font_lc,
                section_bg=colors.get("section_bg", "#F0F0F0"),
                header_row_bg=colors.get("header_row", "#E8E8E8"),
                grid_line=line_color,
                label_code_color=colors.get("label_code_color", "#0066CC"),
            )

        elif st == "letter_meta":
            date_field = section.get("date_field", "")
            if date_field:
                draw_text_right(draw, str(fields.get(date_field, "")), right_edge, y, font_b)
                y += 44
            for fkey in section.get("addressee_fields", []):
                draw.text((margin, y), str(fields.get(fkey, "")), font=font_b, fill="black")
                y += 34
            y += 16
            salutation = section.get("salutation", "")
            if salutation:
                draw.text((margin, y), _subst(salutation, fields), font=font_b, fill="black")
                y += 44

        elif st == "letter_body":
            for para in section.get("paragraphs", []):
                y = _draw_paragraph(draw, _subst(para, fields), y, margin, right_edge, font_b)
                y += 18

        elif st == "separator":
            draw_separator_line(draw, margin, right_edge, y + 8, color=line_color, width=1)
            y += section.get("height", 20)

        elif st == "declaration":
            text = section.get("text", "")
            if text:
                y = _draw_paragraph(draw, text, y, margin + 20, right_edge - 20, font_s, fill="#555555")
                y += 20

        elif st == "signature_block":
            y += section.get("gap", 30)
            for line in section.get("lines", []):
                draw.text((margin, y), _subst(line, fields), font=font_b, fill="black")
                y += 40

        elif st == "footer":
            draw_text_center(draw, section.get("text", ""), height - 60, width, font_s, fill="gray")

    return img
