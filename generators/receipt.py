"""Receipt renderer — Australian POS and EFTPOS formats.

Renders PIL images from ground truth YAML entries using layout configs.
Supports thermal (80mm/57mm), letterhead, and hospitality formats.
"""

import hashlib
from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    capture_label_prefixed_value,
    draw_fitted_center,
    draw_fitted_left,
    draw_fitted_right,
    draw_line_item,
    draw_separator,
    draw_text_center,
    draw_text_right,
    fmt_amount,
    load_font,
)
from generators.exporters.geometry import BoxRecorder, rescale_vertical
from generators.layout_budgets import field_budget
from generators.payment_block import derive_payment, load_link_index, render_payment_block

_LAYOUT_PATH = "config/layouts/receipts.yml"

_STAFF_NAMES = [
    "Sarah",
    "James",
    "Emma",
    "Liam",
    "Olivia",
    "Noah",
    "Chloe",
    "Jack",
    "Mia",
    "Ethan",
    "Ava",
    "Will",
    "Sophie",
    "Ben",
    "Isla",
    "Tom",
]


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


def _derive_receipt_details(case_id: str, invoice_date: str) -> dict:
    """Derive deterministic POS details from case ID and invoice date.

    Generates time, register number, and staff name using a hash so the same
    case always produces the same values. Payment values come from
    generators.payment_block.derive_payment, which consumes a later slice of
    the same digest.

    Args:
        case_id: The case identifier (e.g. "CASE001").
        invoice_date: Invoice date string (e.g. "08/04/2023").

    Returns:
        Dict with keys: time, register, staff.
    """
    raw = f"{case_id}:pos:{invoice_date}"
    digest = hashlib.sha256(raw.encode()).hexdigest()

    # Time: HH:MM between 08:00-19:59
    hour = 8 + int(digest[0:2], 16) % 12
    minute = int(digest[2:4], 16) % 60
    time_str = f"{hour:02d}:{minute:02d}"

    # Register: 01-08
    register = 1 + int(digest[4:6], 16) % 8
    register_str = f"{register:02d}"

    # Staff name
    staff_idx = int(digest[6:8], 16) % len(_STAFF_NAMES)
    staff = _STAFF_NAMES[staff_idx]

    return {
        "time": time_str,
        "register": register_str,
        "staff": staff,
    }


def render_receipt(entry: dict, layout: dict, *, geometry_out: dict | None = None) -> Image.Image:
    """Render a receipt image from ground truth entry and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.
        geometry_out: Optional dict (opt-in); when given, populated in place
            with {"width", "height", "boxes"} describing each captured
            field's normalised bounding box on the rendered page.

    Returns:
        PIL Image of the rendered receipt.
    """
    fields = entry["fields"]
    case_id = entry.get("case_id", "")
    layout_id = entry.get("layout", "")
    width = layout.get("width", 640)
    margin = layout.get("margin", 40)
    line_h = layout.get("line_height", 36)

    is_mono = "mono" in layout.get("font_family", "monospace")
    font_size = layout.get("font_size", 20)
    font = load_font(font_size, mono=is_mono)
    font_bold = load_font(font_size, mono=is_mono, bold=True)

    inv_date = fields.get("INVOICE_DATE", "")
    pos_details = _derive_receipt_details(case_id, inv_date)

    max_h = 4000
    img = Image.new("RGB", (width, max_h), "white")
    draw = ImageDraw.Draw(img)
    y = margin
    recorder = BoxRecorder(width, max_h) if geometry_out is not None else None

    for section in layout.get("sections", []):
        sec_type = section.get("type")

        if sec_type == "header":
            y = draw_fitted_center(
                draw,
                fields.get("SUPPLIER_NAME", ""),
                y,
                width,
                budget=field_budget(layout, layout_id, "SUPPLIER_NAME", layout_path=_LAYOUT_PATH),
                nominal_size=font_size,
                mono=is_mono,
                bold=True,
                line_spacing=line_h,
                recorder=recorder,
                field="SUPPLIER_NAME",
            )
            addr = fields.get("BUSINESS_ADDRESS", "")
            if addr:
                y = draw_fitted_center(
                    draw,
                    addr,
                    y,
                    width,
                    budget=field_budget(layout, layout_id, "BUSINESS_ADDRESS", layout_path=_LAYOUT_PATH),
                    nominal_size=font_size,
                    mono=is_mono,
                    line_spacing=line_h,
                    recorder=recorder,
                    field="BUSINESS_ADDRESS",
                )
            abn = fields.get("BUSINESS_ABN", "")
            if abn:
                y = draw_fitted_center(
                    draw,
                    f"ABN: {abn}",
                    y,
                    width,
                    budget=field_budget(layout, layout_id, "ABN_LINE", layout_path=_LAYOUT_PATH),
                    nominal_size=font_size,
                    mono=is_mono,
                    line_spacing=line_h,
                    recorder=recorder,
                    field="BUSINESS_ABN",
                )
            phone = fields.get("BUSINESS_PHONE", "")
            if phone:
                y = draw_fitted_center(
                    draw,
                    f"Ph: {phone}",
                    y,
                    width,
                    budget=field_budget(layout, layout_id, "PHONE", layout_path=_LAYOUT_PATH),
                    nominal_size=font_size,
                    mono=is_mono,
                    line_spacing=line_h,
                )
            y += line_h // 4

        elif sec_type == "receipt_meta":
            receipt_num = _derive_receipt_number(case_id, inv_date)
            # Line 1: Date + Time
            if inv_date:
                draw.text((margin, y), f"Date: {inv_date}", font=font, fill="black")
                capture_label_prefixed_value(
                    draw, "Date: ", inv_date, margin, y, font, recorder=recorder, field="INVOICE_DATE"
                )
            draw_text_right(draw, f"Time: {pos_details['time']}", x_right=width - margin, y=y, font=font)
            y += line_h
            # Line 2: Register + Staff + Receipt #
            draw.text(
                (margin, y),
                f"Reg: {pos_details['register']}  Staff: {pos_details['staff']}",
                font=font,
                fill="black",
            )
            draw_text_right(draw, f"#{receipt_num}", x_right=width - margin, y=y, font=font)
            y += line_h

        elif sec_type == "separator":
            draw_separator(draw, y, width, margin, font)
            y += line_h

        elif sec_type == "title":
            text = section.get("text", "")
            draw_text_center(draw, text, y, width, font_bold)
            y += line_h
            if inv_date:
                draw.text((margin, y), f"Date: {inv_date}", font=font, fill="black")
                capture_label_prefixed_value(
                    draw, "Date: ", inv_date, margin, y, font, recorder=recorder, field="INVOICE_DATE"
                )
                y += line_h

        elif sec_type == "metadata":
            if inv_date:
                draw.text((margin, y), f"Date: {inv_date}", font=font, fill="black")
                capture_label_prefixed_value(
                    draw, "Date: ", inv_date, margin, y, font, recorder=recorder, field="INVOICE_DATE"
                )
                y += line_h

        elif sec_type in ("line_items", "itemized"):
            items = _parse_line_items(fields)
            for i, item in enumerate(items):
                desc = item["description"]
                qty = item["quantity"]
                total = item["total"]
                qty_prefix = None
                if qty and qty != "1":
                    qty_prefix = f"{qty}x "
                    desc = f"{qty_prefix}{desc}"
                amount_str = f"{Decimal(total):,.2f}" if total else ""
                draw_fitted_left(
                    draw,
                    desc,
                    margin,
                    y,
                    budget=field_budget(layout, layout_id, "LINE_ITEM_DESC", layout_path=_LAYOUT_PATH),
                    nominal_size=font_size,
                    mono=is_mono,
                    line_spacing=line_h,
                    recorder=recorder,
                    field=f"LINE_ITEM_DESCRIPTIONS[{i}]",
                    prefix=qty_prefix,
                    prefix_field=f"LINE_ITEM_QUANTITIES[{i}]" if qty_prefix else None,
                )
                draw_fitted_right(
                    draw,
                    amount_str,
                    width - margin,
                    y,
                    budget=field_budget(layout, layout_id, "LINE_ITEM_AMOUNT", layout_path=_LAYOUT_PATH),
                    nominal_size=font_size,
                    mono=is_mono,
                    line_spacing=line_h,
                    recorder=recorder,
                    field=f"LINE_ITEM_TOTAL_PRICES[{i}]",
                )
                y += line_h

        elif sec_type == "totals":
            total = fields.get("TOTAL_AMOUNT", "")
            gst = fields.get("GST_AMOUNT", "")

            if gst and total:
                subtotal_ex = str(Decimal(total) - Decimal(gst))
                draw_line_item(draw, "SUBTOTAL", f"{Decimal(subtotal_ex):,.2f}", y, font, margin, width)
                y += line_h
                draw_line_item(
                    draw,
                    "GST",
                    f"{Decimal(gst):,.2f}",
                    y,
                    font,
                    margin,
                    width,
                    recorder=recorder,
                    amount_field="GST_AMOUNT",
                )
                y += line_h
            draw_line_item(
                draw,
                "TOTAL",
                fmt_amount(Decimal(total)),
                y,
                font_bold,
                margin,
                width,
                recorder=recorder,
                amount_field="TOTAL_AMOUNT",
            )
            y += line_h

        elif sec_type == "payment":
            # A linked receipt's scheme comes from its bank row; `.get` leaves an
            # unlinked receipt on the weighted pool.
            details = derive_payment(
                case_id,
                inv_date,
                fields.get("TOTAL_AMOUNT", "0"),
                pos_details["time"],
                bank_description=load_link_index().get(f"{case_id}_{layout_id}"),
            )
            y = render_payment_block(
                draw,
                details,
                y,
                layout=layout,
                layout_id=layout_id,
                width=width,
                margin=margin,
                line_h=line_h,
                font=font,
                font_bold=font_bold,
                font_size=font_size,
                is_mono=is_mono,
            )

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
                            draw,
                            label or "TOTAL",
                            fmt_amount(Decimal(total)),
                            y,
                            font_bold,
                            margin,
                            width,
                            recorder=recorder,
                            amount_field="TOTAL_AMOUNT",
                        )
                    except Exception:  # noqa: BLE001
                        draw_line_item(
                            draw,
                            label or "TOTAL",
                            total,
                            y,
                            font_bold,
                            margin,
                            width,
                            recorder=recorder,
                            amount_field="TOTAL_AMOUNT",
                        )
                    y += line_h
            elif name == "tax" or name == "gst":
                gst = fields.get("GST_AMOUNT", "")
                if gst:
                    try:
                        draw_line_item(
                            draw,
                            label or "GST",
                            fmt_amount(Decimal(gst)),
                            y,
                            font,
                            margin,
                            width,
                            recorder=recorder,
                            amount_field="GST_AMOUNT",
                        )
                    except Exception:  # noqa: BLE001
                        draw_line_item(
                            draw,
                            label or "GST",
                            gst,
                            y,
                            font,
                            margin,
                            width,
                            recorder=recorder,
                            amount_field="GST_AMOUNT",
                        )
                    y += line_h

        elif sec_type == "content":
            # Skip auxiliary content fields (date, time, ref, etc.) — no-op
            pass

    y += margin
    final_height = min(y, max_h)
    img = img.crop((0, 0, width, final_height))

    if recorder is not None and geometry_out is not None:
        geometry_out["width"] = width
        geometry_out["height"] = final_height
        geometry_out["boxes"] = rescale_vertical(
            recorder.as_dict(), old_height=max_h, new_height=final_height
        )

    return img
