"""Invoice renderer — ATO-compliant Australian tax invoices.

Renders A4-format tax invoices with mandatory ATO fields:
1. "Tax Invoice" header  2. Seller identity  3. ABN
4. Issue date  5. Item descriptions with qty/price
6. GST amount  7. Taxable sale extent
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    draw_fitted_left,
    draw_text_right,
    fmt_amount,
    load_font,
)
from generators.layout_budgets import field_budget

_LAYOUT_PATH = "config/layouts/invoices.yml"


def _parse_line_items(fields: dict) -> list[dict]:
    """Parse pipe-delimited line item fields into list of dicts."""
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


def _normalize_layout(layout: dict) -> dict:
    """Flatten nested layout YAML structure into a flat working copy.

    Converts:
      - page_dimensions.width/height  -> page_width, page_height
      - font_sizes.header/body/subheader -> font_size_header, font_size_body, font_size_small

    Does not mutate the original layout dict.
    """
    flat = dict(layout)

    page_dims = layout.get("page_dimensions", {})
    if page_dims and "page_width" not in flat:
        flat["page_width"] = page_dims.get("width", 2480)
        flat["page_height"] = page_dims.get("height", 3508)

    font_sizes = layout.get("font_sizes", {})
    if font_sizes:
        flat.setdefault("font_size_header", font_sizes.get("header", 28))
        flat.setdefault("font_size_body", font_sizes.get("body", 22))
        flat.setdefault("font_size_small", font_sizes.get("subheader", font_sizes.get("body", 18)))

    # content width for constraining table/box right edge
    margin_val = layout.get("margin", 100)
    flat.setdefault("content_width", flat.get("page_width", 2480) - 2 * margin_val)

    return flat


def render_invoice(entry: dict, layout: dict) -> Image.Image:
    """Render an ATO-compliant tax invoice from ground truth and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered invoice.
    """
    layout = _normalize_layout(layout)
    fields = entry["fields"]
    layout_id = entry.get("layout", "")
    width = layout.get("page_width", 2480)
    height = layout.get("page_height", 3508)
    margin = layout.get("margin", 150)
    content_width = layout.get("content_width", width - 2 * margin)
    right_edge = margin + content_width

    size_body = layout.get("font_size_body", 22)
    size_small = layout.get("font_size_small", 18)
    font_h = load_font(layout.get("font_size_header", 32), bold=True)
    font_b = load_font(size_body)
    font_s = load_font(size_small)

    def _b(field: str) -> dict:
        return field_budget(layout, layout_id, field, layout_path=_LAYOUT_PATH)

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = margin

    for section in layout.get("sections", []):
        sec_type = section.get("type")

        if sec_type == "title":
            text = section.get("text", "Tax Invoice")
            draw.text((margin, y), text, font=font_h, fill="black")
            y += 80

        elif sec_type == "seller_details":
            draw.text((margin, y), fields.get("SUPPLIER_NAME", ""), font=font_b, fill="black")
            y += 48
            draw.text((margin, y), fields.get("BUSINESS_ADDRESS", ""), font=font_s, fill="black")
            y += 40
            abn = fields.get("BUSINESS_ABN", "")
            draw.text((margin, y), f"ABN: {abn}", font=font_s, fill="black")
            y += 64

        elif sec_type == "invoice_metadata":
            draw.text(
                (margin, y),
                f"Date: {fields.get('INVOICE_DATE', '')}",
                font=font_s,
                fill="black",
            )
            y += 52

        elif sec_type == "buyer_details":
            payer = fields.get("PAYER_NAME", "")
            if payer:
                draw.text((margin, y), "Bill To:", font=font_s, fill="gray")
                y += 40
                draw.text((margin, y), payer, font=font_b, fill="black")
                y += 44
                addr = fields.get("PAYER_ADDRESS", "")
                if addr:
                    draw.text((margin, y), addr, font=font_s, fill="black")
                    y += 44
                y += 28

        elif sec_type in (
            "line_items_table",
            "line_items_table_taxable",
            "line_items_table_gst_free",
        ):
            items = _parse_line_items(fields)
            col_x = {
                "description": margin,
                "qty": margin + 900,
                "price": margin + 1050,
                "gst": margin + 1300,
                "total": margin + 1550,
            }
            row_h = 52
            use_borders = section.get("borders", False)

            if use_borders:
                draw.rectangle(
                    [(margin, y), (right_edge, y + row_h)],
                    fill="#F0F0F0",
                    outline="#CCCCCC",
                )
            draw.text((col_x["description"], y + 12), "Description", font=font_s, fill="black")
            draw.text((col_x["qty"], y + 12), "Qty", font=font_s, fill="black")
            draw.text((col_x["price"], y + 12), "Price", font=font_s, fill="black")
            draw.text((col_x["total"], y + 12), "Total", font=font_s, fill="black")
            y += row_h

            for item in items:
                if use_borders:
                    draw.rectangle(
                        [(margin, y), (right_edge, y + row_h)],
                        outline="#CCCCCC",
                    )
                draw_fitted_left(
                    draw,
                    item["description"],
                    col_x["description"],
                    y + 12,
                    budget=_b("LINE_ITEM_DESC"),
                    nominal_size=size_small,
                )
                draw.text((col_x["qty"], y + 12), item["quantity"], font=font_s, fill="black")
                if item["price"]:
                    draw_text_right(
                        draw,
                        fmt_amount(Decimal(item["price"])),
                        col_x["price"] + 200,
                        y + 12,
                        font_s,
                    )
                if item["total"]:
                    draw_text_right(
                        draw,
                        fmt_amount(Decimal(item["total"])),
                        col_x["total"] + 200,
                        y + 12,
                        font_s,
                    )
                y += row_h
            y += 20

        elif sec_type == "totals":
            gst_display = section.get("gst_display", "separate")
            total = fields.get("TOTAL_AMOUNT", "0")
            gst = fields.get("GST_AMOUNT", "0")

            totals_x = right_edge - 400
            if gst_display == "separate":
                subtotal = str(Decimal(total) - Decimal(gst))
                draw.text((totals_x, y), "Subtotal:", font=font_s, fill="black")
                draw_text_right(draw, fmt_amount(Decimal(subtotal)), right_edge, y, font_s)
                y += 44
                draw.text((totals_x, y), "GST (10%):", font=font_s, fill="black")
                draw_text_right(draw, fmt_amount(Decimal(gst)), right_edge, y, font_s)
                y += 44
            draw.text((totals_x, y), "Total:", font=font_h, fill="black")
            draw_text_right(draw, fmt_amount(Decimal(total)), right_edge, y, font_h)
            y += 64

            if gst_display == "inclusive":
                draw.text(
                    (totals_x, y),
                    "Total price includes GST",
                    font=font_s,
                    fill="gray",
                )
                y += 40

        # YAML layout aliases — map native YAML section types to renderer logic
        elif sec_type == "header":
            # Invoice title header (e.g. "TAX INVOICE")
            text = section.get("text", "TAX INVOICE")
            draw.text((margin, y), text, font=font_h, fill="black")
            y += 80

        elif sec_type == "section":
            # Named section — dispatch by section name
            sec_name = section.get("name", "")
            if sec_name == "seller_details":
                y = draw_fitted_left(
                    draw,
                    fields.get("SUPPLIER_NAME", ""),
                    margin,
                    y,
                    budget=_b("SUPPLIER_NAME"),
                    nominal_size=size_body,
                    line_spacing=48,
                )
                y = draw_fitted_left(
                    draw,
                    fields.get("BUSINESS_ADDRESS", ""),
                    margin,
                    y,
                    budget=_b("BUSINESS_ADDRESS"),
                    nominal_size=size_small,
                    line_spacing=40,
                )
                abn = fields.get("BUSINESS_ABN", "")
                y = draw_fitted_left(
                    draw,
                    f"ABN: {abn}",
                    margin,
                    y,
                    budget=_b("ABN_LINE"),
                    nominal_size=size_small,
                    line_spacing=64,
                )
            elif sec_name == "buyer_details":
                payer = fields.get("PAYER_NAME", "")
                if payer:
                    draw.text((margin, y), "Bill To:", font=font_s, fill="gray")
                    y += 40
                    y = draw_fitted_left(
                        draw,
                        payer,
                        margin,
                        y,
                        budget=_b("PAYER_NAME"),
                        nominal_size=size_body,
                        line_spacing=44,
                    )
                    addr = fields.get("PAYER_ADDRESS", "")
                    if addr:
                        y = draw_fitted_left(
                            draw,
                            addr,
                            margin,
                            y,
                            budget=_b("PAYER_ADDRESS"),
                            nominal_size=size_small,
                            line_spacing=44,
                        )
                    y += 28
            elif sec_name == "invoice_metadata":
                draw.text(
                    (margin, y),
                    f"Date: {fields.get('INVOICE_DATE', '')}",
                    font=font_s,
                    fill="black",
                )
                y += 52
            # Other sections (payment_terms, delivery_details) are rendered as labels
            else:
                label = section.get("label", "")
                if label:
                    draw.text((margin, y), label, font=font_s, fill="gray")
                    y += 40

        elif sec_type == "table":
            # Named table — dispatch by table name to line_items renderer
            items = _parse_line_items(fields)
            col_x = {
                "description": margin,
                "qty": margin + 900,
                "price": margin + 1050,
                "total": margin + 1550,
            }
            row_h = 52
            # Column header row
            draw.rectangle(
                [(margin, y), (right_edge, y + row_h)],
                fill="#F0F0F0",
            )
            draw.text((col_x["description"], y + 12), "Description", font=font_s, fill="black")
            draw.text((col_x["qty"], y + 12), "Qty", font=font_s, fill="black")
            draw.text((col_x["price"], y + 12), "Unit Price", font=font_s, fill="black")
            draw.text((col_x["total"], y + 12), "Total", font=font_s, fill="black")
            y += row_h
            for item in items:
                draw_fitted_left(
                    draw,
                    item["description"],
                    col_x["description"],
                    y + 12,
                    budget=_b("LINE_ITEM_DESC"),
                    nominal_size=size_small,
                )
                draw.text((col_x["qty"], y + 12), item["quantity"], font=font_s, fill="black")
                if item["price"]:
                    try:
                        draw_text_right(
                            draw,
                            fmt_amount(Decimal(item["price"])),
                            col_x["price"] + 200,
                            y + 12,
                            font_s,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                if item["total"]:
                    try:
                        draw_text_right(
                            draw,
                            fmt_amount(Decimal(item["total"])),
                            col_x["total"] + 200,
                            y + 12,
                            font_s,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                y += row_h
            y += 20

        elif sec_type == "separator":
            # Horizontal separator line
            draw.line([(margin, y + 8), (right_edge, y + 8)], fill="#CCCCCC", width=1)
            y += section.get("height", 20)

        elif sec_type == "label":
            text = section.get("text", "")
            if text:
                draw.text((margin, y), text, font=font_s, fill="gray")
                y += section.get("height", 24)

        elif sec_type == "footer":
            pass  # Footer is decorative, not rendered

    return img
