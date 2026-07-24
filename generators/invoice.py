"""Invoice renderer — ATO-compliant Australian tax invoices.

Renders A4-format tax invoices with mandatory ATO fields:
1. "Tax Invoice" header  2. Seller identity  3. ABN
4. Issue date  5. Item descriptions with qty/price
6. GST amount  7. Taxable sale extent
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    capture_label_prefixed_value,
    draw_fitted_left,
    draw_text_left,
    draw_text_right,
    fmt_amount,
    load_font,
)
from generators.exporters.geometry import BoxRecorder
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


def render_invoice(entry: dict, layout: dict, *, geometry_out: dict | None = None) -> Image.Image:
    """Render an ATO-compliant tax invoice from ground truth and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.
        geometry_out: Optional dict (opt-in); when given, populated in place
            with {"width", "height", "boxes"} describing each captured
            field's normalised bounding box on the rendered page.

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
    recorder = BoxRecorder(width, height) if geometry_out is not None else None
    # Some layouts (e.g. tax_invoice_mixed) render the same LINE_ITEM_* list
    # into more than one "table" section (taxable / tax-free split display).
    # Only the first table is captured — the ground truth has one value per
    # line item, so a second draw of the same field has no distinct box of
    # its own and would collide with the first in the recorder.
    line_item_tables_seen = 0

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
            inv_date = fields.get("INVOICE_DATE", "")
            draw.text(
                (margin, y),
                f"Date: {inv_date}",
                font=font_s,
                fill="black",
            )
            capture_label_prefixed_value(
                draw, "Date: ", inv_date, margin, y, font_s, recorder=recorder, field="INVOICE_DATE"
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

            for i, item in enumerate(items):
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
                    recorder=recorder,
                    field=f"LINE_ITEM_DESCRIPTIONS[{i}]",
                )
                draw_text_left(
                    draw,
                    item["quantity"],
                    col_x["qty"],
                    y + 12,
                    font_s,
                    recorder=recorder,
                    field=f"LINE_ITEM_QUANTITIES[{i}]",
                )
                if item["price"]:
                    draw_text_right(
                        draw,
                        fmt_amount(Decimal(item["price"])),
                        col_x["price"] + 200,
                        y + 12,
                        font_s,
                        recorder=recorder,
                        field=f"LINE_ITEM_PRICES[{i}]",
                    )
                if item["total"]:
                    draw_text_right(
                        draw,
                        fmt_amount(Decimal(item["total"])),
                        col_x["total"] + 200,
                        y + 12,
                        font_s,
                        recorder=recorder,
                        field=f"LINE_ITEM_TOTAL_PRICES[{i}]",
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
                draw_text_right(
                    draw,
                    fmt_amount(Decimal(gst)),
                    right_edge,
                    y,
                    font_s,
                    recorder=recorder,
                    field="GST_AMOUNT",
                )
                y += 44
            draw.text((totals_x, y), "Total:", font=font_h, fill="black")
            draw_text_right(
                draw,
                fmt_amount(Decimal(total)),
                right_edge,
                y,
                font_h,
                recorder=recorder,
                field="TOTAL_AMOUNT",
            )
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
                    recorder=recorder,
                    field="SUPPLIER_NAME",
                )
                y = draw_fitted_left(
                    draw,
                    fields.get("BUSINESS_ADDRESS", ""),
                    margin,
                    y,
                    budget=_b("BUSINESS_ADDRESS"),
                    nominal_size=size_small,
                    line_spacing=40,
                    recorder=recorder,
                    field="BUSINESS_ADDRESS",
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
                    recorder=recorder,
                    field="BUSINESS_ABN",
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
                        recorder=recorder,
                        field="PAYER_NAME",
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
                            recorder=recorder,
                            field="PAYER_ADDRESS",
                        )
                    y += 28
            elif sec_name == "invoice_metadata":
                inv_date = fields.get("INVOICE_DATE", "")
                draw.text(
                    (margin, y),
                    f"Date: {inv_date}",
                    font=font_s,
                    fill="black",
                )
                capture_label_prefixed_value(
                    draw, "Date: ", inv_date, margin, y, font_s, recorder=recorder, field="INVOICE_DATE"
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
            capture_this_table = line_item_tables_seen == 0
            line_item_tables_seen += 1
            for i, item in enumerate(items):
                draw_fitted_left(
                    draw,
                    item["description"],
                    col_x["description"],
                    y + 12,
                    budget=_b("LINE_ITEM_DESC"),
                    nominal_size=size_small,
                    recorder=recorder if capture_this_table else None,
                    field=f"LINE_ITEM_DESCRIPTIONS[{i}]",
                )
                draw_text_left(
                    draw,
                    item["quantity"],
                    col_x["qty"],
                    y + 12,
                    font_s,
                    recorder=recorder if capture_this_table else None,
                    field=f"LINE_ITEM_QUANTITIES[{i}]",
                )
                if item["price"]:
                    try:
                        draw_text_right(
                            draw,
                            fmt_amount(Decimal(item["price"])),
                            col_x["price"] + 200,
                            y + 12,
                            font_s,
                            recorder=recorder if capture_this_table else None,
                            field=f"LINE_ITEM_PRICES[{i}]",
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
                            recorder=recorder if capture_this_table else None,
                            field=f"LINE_ITEM_TOTAL_PRICES[{i}]",
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

    if recorder is not None and geometry_out is not None:
        geometry_out["width"] = width
        geometry_out["height"] = height
        geometry_out["boxes"] = recorder.as_dict()

    return img
