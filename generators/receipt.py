"""Receipt renderer — Australian POS and EFTPOS formats.

Renders PIL images from ground truth YAML entries using layout configs.
Supports thermal (80mm/57mm), letterhead, and hospitality formats.
ATO-compliant: TAX INVOICE heading, per-item GST indicators, proper GST breakdown.
"""

import hashlib
from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    draw_line_item,
    draw_separator,
    draw_text_center,
    draw_text_right,
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


def _derive_receipt_number(case_id: str, invoice_date: str) -> str:
    """Derive a deterministic receipt number from case ID and invoice date.

    Args:
        case_id: The case identifier (e.g. "CASE001").
        invoice_date: Invoice date string (e.g. "08/04/2023").

    Returns:
        Receipt number string like "R-8A3F1D".
    """
    raw = f"{case_id}:{invoice_date}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:6].upper()
    return f"R-{digest}"


def render_receipt(entry: dict, layout: dict) -> Image.Image:
    """Render a receipt image from ground truth entry and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered receipt.
    """
    fields = entry["fields"]
    case_id = entry.get("case_id", "")
    width = layout.get("width", 640)
    margin = layout.get("margin", 40)
    line_h = layout.get("line_height", 36)

    is_mono = layout.get("font_family", "mono") == "mono"
    font_size = layout.get("font_size", 20)
    font = load_font(font_size, mono=is_mono)
    font_bold = load_font(font_size, mono=is_mono, bold=True)

    is_gst_included = fields.get("IS_GST_INCLUDED", "false") == "true"

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
            phone = fields.get("BUSINESS_PHONE", "")
            if phone:
                draw_text_center(draw, f"Ph: {phone}", y, width, font)
                y += line_h
            y += line_h // 4

        elif sec_type == "tax_invoice_label":
            draw.text((margin, y), "TAX INVOICE", font=font_bold, fill="black")
            y += line_h

        elif sec_type == "receipt_meta":
            inv_date = fields.get("INVOICE_DATE", "")
            receipt_num = _derive_receipt_number(case_id, inv_date)
            if inv_date:
                draw.text((margin, y), f"Date: {inv_date}", font=font, fill="black")
            draw_text_right(draw, f"Receipt: {receipt_num}", x_right=width - margin, y=y, font=font)
            y += line_h

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

        elif sec_type in ("line_items", "itemized"):
            items = _parse_line_items(fields)
            for item in items:
                desc = item["description"]
                qty = item["quantity"]
                total = item["total"]
                if qty and qty != "1":
                    desc = f"{qty}x {desc}"
                if is_gst_included:
                    desc = f"{desc} *"
                amount_str = fmt_amount(Decimal(total)) if total else ""
                draw_line_item(draw, desc, amount_str, y, font, margin, width)
                y += line_h

        elif sec_type == "gst_legend":
            draw.text((margin, y), "* Includes GST", font=font, fill="black")
            y += line_h

        elif sec_type == "totals":
            total = fields.get("TOTAL_AMOUNT", "")
            gst = fields.get("GST_AMOUNT", "")

            if gst and total:
                subtotal_ex = str(Decimal(total) - Decimal(gst))
                draw_line_item(
                    draw, "Subtotal (ex. GST)", fmt_amount(Decimal(subtotal_ex)), y, font, margin, width
                )
                y += line_h
                draw_line_item(draw, "GST (10%)", fmt_amount(Decimal(gst)), y, font, margin, width)
                y += line_h
            draw_line_item(draw, "TOTAL", fmt_amount(Decimal(total)), y, font_bold, margin, width)
            y += line_h

        elif sec_type == "payment":
            method = fields.get("PAYMENT_METHOD", "EFTPOS")
            draw.text((margin, y), method, font=font, fill="black")
            y += line_h

        elif sec_type == "footer":
            text = section.get("text", "")
            y += line_h // 4
            draw_text_center(draw, text, y, width, font)
            y += line_h

        elif sec_type == "gst_statement":
            text = section.get("text", "Total price includes GST")
            draw_text_center(draw, text, y, width, font)
            y += line_h

        elif sec_type == "total":
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
