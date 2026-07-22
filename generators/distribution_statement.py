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
    draw_fitted_left,
    draw_fitted_right,
    draw_separator_line,
    draw_table,
    draw_text_center,
    draw_text_right,
    fmt_amount,
    load_font,
)
from generators.layout_budgets import field_budget

_LAYOUT_PATH = "config/layouts/distribution_statements.yml"


def _budget(layout: dict, layout_id: str, field: str) -> dict:
    """Look up a field budget for a distribution statement layout."""
    return field_budget(layout, layout_id, field, layout_path=_LAYOUT_PATH)


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
    font_s: Font,
    accent: str,
    budget: dict,
    nominal_size: int,
) -> int:
    """Draw one column of a two_column section; return its bottom y."""
    title = block.get("title", "")
    if title:
        draw.text((x, y), title, font=font_sub, fill=accent)
        y += 40
    for fd in block.get("fields", []):
        draw.text((x, y), f"{fd.get('label', '')}:", font=font_s, fill="gray")
        y += 26
        y = draw_fitted_left(
            draw,
            str(fields.get(fd.get("field", ""), "")),
            x + 20,
            y,
            budget=budget,
            nominal_size=nominal_size,
            line_spacing=38,
        )
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
    layout_id = entry.get("layout", "")

    font_sizes = layout.get("font_sizes", {})
    colors = layout.get("colors", {})

    font_h = load_font(font_sizes.get("header", 44), bold=True)
    font_sub = load_font(font_sizes.get("subheader", 28), bold=True)
    font_b = load_font(font_sizes.get("body", 22))
    font_s = load_font(font_sizes.get("small", 18))
    font_lc = load_font(font_sizes.get("label_code", 26), bold=True)

    header_color = colors.get("header_color", "#1A1A2E")
    accent_color = colors.get("accent_color", "#16213E")
    line_color = colors.get("line_color", "#CCCCCC")

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    for section in layout.get("sections", []):
        sec_type = section.get("type")

        if sec_type == "letterhead":
            draw.text((margin, y), section.get("title", ""), font=font_h, fill=header_color)
            y += 60
            subtitle = section.get("subtitle", "")
            if subtitle:
                draw.text((margin, y), subtitle, font=font_sub, fill=accent_color)
                y += 44
            draw_separator_line(draw, margin, right_edge, y, color=header_color, width=3)
            y += section.get("height", 120) - 100

        elif sec_type == "header_bar":
            bar_h = section.get("height", 100)
            bg = colors.get("header_bg", "#0B6E6E")
            fg = colors.get("header_text", "#FFFFFF")
            draw.rectangle([(0, y), (width, y + bar_h)], fill=bg)
            draw.text((margin, y + 15), section.get("text", ""), font=font_h, fill=fg)
            subtext = section.get("subtext", "")
            if subtext:
                draw_text_right(draw, subtext, right_edge, y + 20, font_sub, fill=fg)
            y += bar_h

        elif sec_type == "spacer":
            y += section.get("height", 30)

        elif sec_type == "section":
            title = section.get("title", "")
            if title:
                draw.text((margin, y), title, font=font_sub, fill=accent_color)
                y += 40
            for fd in section.get("fields", []):
                label = fd.get("label", "")
                value = str(fields.get(fd.get("field", ""), ""))
                if fd.get("format") == "amount":
                    draw.text((margin + 20, y), label, font=font_b, fill="black")
                    draw_fitted_right(
                        draw,
                        _fmt(value),
                        right_edge,
                        y,
                        budget=_budget(layout, layout_id, "AMOUNT_VALUE"),
                        nominal_size=font_sizes.get("body", 22),
                    )
                    draw_separator_line(draw, margin + 20, right_edge, y + 34, color=line_color, width=1)
                    y += 52
                else:
                    draw.text((margin + 20, y), f"{label}:", font=font_s, fill="gray")
                    y += 26
                    y = draw_fitted_left(
                        draw,
                        value,
                        margin + 40,
                        y,
                        budget=_budget(layout, layout_id, "TEXT_VALUE"),
                        nominal_size=font_sizes.get("body", 22),
                        line_spacing=38,
                    )
            y += 16

        elif sec_type == "two_column":
            mid = (margin + right_edge) // 2
            start_y = y
            body_size = font_sizes.get("body", 22)
            y_left = _draw_column_block(
                draw,
                section.get("left", {}),
                fields,
                start_y,
                margin,
                font_sub,
                font_s,
                accent_color,
                _budget(layout, layout_id, "COLUMN_TEXT_LEFT"),
                body_size,
            )
            y_right = _draw_column_block(
                draw,
                section.get("right", {}),
                fields,
                start_y,
                mid + 20,
                font_sub,
                font_s,
                accent_color,
                _budget(layout, layout_id, "COLUMN_TEXT_RIGHT"),
                body_size,
            )
            y = max(y_left, y_right) + 16

        elif sec_type == "table":
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
                body_size=font_sizes.get("body", 22),
                font_small=font_s,
                font_label_code=font_lc,
                section_bg=colors.get("section_bg", "#F0F0F0"),
                header_row_bg=colors.get("header_row", "#E8E8E8"),
                grid_line=line_color,
                label_code_color=colors.get("label_code_color", "#0066CC"),
                desc_budget=_budget(layout, layout_id, "DESC_COL"),
                amount_budget=_budget(layout, layout_id, "TABLE_AMOUNT"),
            )

        elif sec_type == "letter_meta":
            date_field = section.get("date_field", "")
            if date_field:
                draw_fitted_right(
                    draw,
                    str(fields.get(date_field, "")),
                    right_edge,
                    y,
                    budget=_budget(layout, layout_id, "AMOUNT_VALUE"),
                    nominal_size=font_sizes.get("body", 22),
                )
                y += 44
            for fkey in section.get("addressee_fields", []):
                y = draw_fitted_left(
                    draw,
                    str(fields.get(fkey, "")),
                    margin,
                    y,
                    budget=_budget(layout, layout_id, "ADDRESSEE_VALUE"),
                    nominal_size=font_sizes.get("body", 22),
                    line_spacing=34,
                )
            y += 16
            salutation = section.get("salutation", "")
            if salutation:
                y = draw_fitted_left(
                    draw,
                    _subst(salutation, fields),
                    margin,
                    y,
                    budget=_budget(layout, layout_id, "ADDRESSEE_VALUE"),
                    nominal_size=font_sizes.get("body", 22),
                    line_spacing=44,
                )

        elif sec_type == "letter_body":
            for para in section.get("paragraphs", []):
                y = _draw_paragraph(draw, _subst(para, fields), y, margin, right_edge, font_b)
                y += 18

        elif sec_type == "separator":
            draw_separator_line(draw, margin, right_edge, y + 8, color=line_color, width=1)
            y += section.get("height", 20)

        elif sec_type == "declaration":
            text = section.get("text", "")
            if text:
                y = _draw_paragraph(draw, text, y, margin + 20, right_edge - 20, font_s, fill="#555555")
                y += 20

        elif sec_type == "signature_block":
            y += section.get("gap", 30)
            for line in section.get("lines", []):
                y = draw_fitted_left(
                    draw,
                    _subst(line, fields),
                    margin,
                    y,
                    budget=_budget(layout, layout_id, "ADDRESSEE_VALUE"),
                    nominal_size=font_sizes.get("body", 22),
                    line_spacing=40,
                )

        elif sec_type == "footer":
            draw_text_center(draw, section.get("text", ""), height - 60, width, font_s, fill="gray")

    return img
