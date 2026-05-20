"""Receipt renderer — Australian POS and EFTPOS formats.

Renders PIL images from ground truth YAML entries using layout configs.
Supports thermal (80mm/57mm), letterhead, and hospitality formats.
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    draw_line_item,
    draw_separator,
    draw_text_center,
    fmt_amount,
    load_font,
)


def _parse_line_items(fields: dict) -> list[dict]:
    """Parse pipe-delimited line item fields."""
    descs = fields.get("LINE_ITEM_DESCRIPTIONS", "").split("|")
    qtys = fields.get("LINE_ITEM_QUANTITIES", "").split("|")
    prices = fields.get("LINE_ITEM_PRICES", "").split("|")
    totals = fields.get("LINE_ITEM_TOTAL_PRICES", "").split("|")

    items = []
    for i in range(len(descs)):
        items.append(
            {
                "description": descs[i].strip() if i < len(descs) else "",
                "quantity": qtys[i].strip() if i < len(qtys) else "1",
                "price": prices[i].strip() if i < len(prices) else "",
                "total": totals[i].strip() if i < len(totals) else "",
            }
        )
    return items


def render_receipt(entry: dict, layout: dict) -> Image.Image:
    """Render a receipt image from ground truth entry and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered receipt.
    """
    fields = entry["fields"]
    width = layout.get("width", 640)
    margin = layout.get("margin", 40)
    line_h = layout.get("line_height", 36)

    is_mono = layout.get("font_family", "mono") == "mono"
    font_size = layout.get("font_size", 20)
    font = load_font(font_size, mono=is_mono)
    font_bold = load_font(font_size, mono=is_mono, bold=True)

    max_h = 4000
    img = Image.new("RGB", (width, max_h), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    for section in layout.get("sections", []):
        sec_type = section.get("type")

        if sec_type == "header":
            draw_text_center(draw, fields.get("SUPPLIER_NAME", ""), y, width, font_bold)
            y += line_h
            addr = fields.get("BUSINESS_ADDRESS", "")
            if addr:
                draw_text_center(draw, addr, y, width, font)
                y += line_h
            abn = fields.get("BUSINESS_ABN", "")
            if abn:
                draw_text_center(draw, f"ABN: {abn}", y, width, font)
                y += line_h
            y += line_h // 2

        elif sec_type == "separator":
            draw_separator(draw, y, width, margin, font)
            y += line_h

        elif sec_type == "title":
            text = section.get("text", "")
            draw_text_center(draw, text, y, width, font_bold)
            y += line_h
            inv_date = fields.get("INVOICE_DATE", "")
            if inv_date:
                draw.text((margin, y), f"Date: {inv_date}", font=font, fill="black")
                y += line_h

        elif sec_type == "metadata":
            inv_date = fields.get("INVOICE_DATE", "")
            if inv_date:
                draw.text((margin, y), f"Date: {inv_date}", font=font, fill="black")
                y += line_h

        elif sec_type == "line_items":
            items = _parse_line_items(fields)
            for item in items:
                desc = item["description"]
                qty = item["quantity"]
                total = item["total"]
                if qty and qty != "1":
                    desc = f"{qty}x {desc}"
                amount_str = fmt_amount(Decimal(total)) if total else ""
                draw_line_item(draw, desc, amount_str, y, font, margin, width)
                y += line_h

        elif sec_type == "totals":
            draw_separator(draw, y, width, margin, font)
            y += line_h
            total = fields.get("TOTAL_AMOUNT", "")
            gst = fields.get("GST_AMOUNT", "")
            is_inclusive = fields.get("IS_GST_INCLUDED", "false") == "true"

            if gst:
                if is_inclusive:
                    subtotal = str(Decimal(total) - Decimal(gst))
                    draw_line_item(draw, "Subtotal", fmt_amount(Decimal(subtotal)), y, font, margin, width)
                    y += line_h
                draw_line_item(draw, "GST", fmt_amount(Decimal(gst)), y, font, margin, width)
                y += line_h
            draw_line_item(draw, "TOTAL", fmt_amount(Decimal(total)), y, font_bold, margin, width)
            y += line_h
            if is_inclusive:
                draw_text_center(draw, "Total price includes GST", y, width, font)
                y += line_h

        elif sec_type == "payment":
            draw.text((margin, y), "EFTPOS", font=font, fill="black")
            y += line_h

        elif sec_type == "footer":
            text = section.get("text", "")
            y += line_h // 2
            draw_text_center(draw, text, y, width, font)
            y += line_h

        elif sec_type == "gst_statement":
            text = section.get("text", "Total price includes GST")
            draw_text_center(draw, text, y, width, font)
            y += line_h

        # YAML layout aliases — map to canonical renderer section types
        elif sec_type == "itemized":
            # Treat as line_items
            items = _parse_line_items(fields)
            for item in items:
                desc = item["description"]
                qty = item["quantity"]
                total = item["total"]
                if qty and qty != "1":
                    desc = f"{qty}x {desc}"
                amount_str = fmt_amount(Decimal(total)) if total else ""
                draw_line_item(draw, desc, amount_str, y, font, margin, width)
                y += line_h

        elif sec_type == "total":
            # Treat single total row (label from section, value from fields)
            name = section.get("name", "")
            label = section.get("label", "")
            if name == "total" or name == "fuel_cost":
                total = fields.get("TOTAL_AMOUNT", "")
                if total:
                    try:
                        draw_line_item(
                            draw, label or "TOTAL", fmt_amount(Decimal(total)), y, font_bold, margin, width
                        )
                    except Exception:  # noqa: BLE001
                        draw_line_item(draw, label or "TOTAL", total, y, font_bold, margin, width)
                    y += line_h
            elif name == "tax" or name == "gst":
                gst = fields.get("GST_AMOUNT", "")
                if gst:
                    try:
                        draw_line_item(
                            draw, label or "GST", fmt_amount(Decimal(gst)), y, font, margin, width
                        )
                    except Exception:  # noqa: BLE001
                        draw_line_item(draw, label or "GST", gst, y, font, margin, width)
                    y += line_h

        elif sec_type == "content":
            # Skip auxiliary content fields (date, time, ref, etc.) — no-op
            pass

    y += margin
    img = img.crop((0, 0, width, min(y, max_h)))
    return img
