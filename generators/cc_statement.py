"""Credit card statement renderer.

Renders PIL images from ground truth YAML entries using layout registry configs.
Modelled after generators/bank_statement.py with CC-specific additions:
summary box (balance, credit limit, available credit, minimum payment, due date),
single Amount column instead of separate debit/credit columns.
"""

from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    draw_text_right,
    fmt_amount,
    load_font,
)


def _normalize_layout(layout: dict) -> dict:
    """Flatten nested layout YAML structure into a flat working copy.

    Converts:
      - page_dimensions.width/height  -> page_width, page_height
      - font_sizes.header/body/subheader -> font_size_header, font_size_body, font_size_small
      - header.background_color -> header.background
      - columns (list) -> columns (dict keyed by column name)

    Does not mutate the original layout dict.
    """
    flat = dict(layout)

    # page dimensions
    page_dims = layout.get("page_dimensions", {})
    if page_dims and "page_width" not in flat:
        flat["page_width"] = page_dims.get("width", 2480)
        flat["page_height"] = page_dims.get("height", 3508)

    # font sizes
    font_sizes = layout.get("font_sizes", {})
    if font_sizes:
        flat.setdefault("font_size_header", font_sizes.get("header", 28))
        flat.setdefault("font_size_body", font_sizes.get("body", 20))
        flat.setdefault("font_size_small", font_sizes.get("subheader", font_sizes.get("header", 16)))

    # content width for constraining table/box right edge
    margin_val = layout.get("margin", 100)
    flat.setdefault("content_width", flat.get("page_width", 2480) - 2 * margin_val)

    # header background_color → background
    header = layout.get("header", {})
    if header and "background" not in header:
        flat["header"] = dict(header)
        flat["header"]["background"] = header.get("background_color", "#FFFFFF")

    # columns list → dict keyed by column name
    cols = layout.get("columns", [])
    if isinstance(cols, list):
        flat["columns"] = {col["name"]: col for col in cols}

    return flat


def _parse_hex_color(hex_str: str) -> tuple[int, int, int]:
    """Parse '#RRGGBB' to (R, G, B) tuple."""
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _parse_transactions(fields: dict) -> list[dict]:
    """Parse pipe-delimited transaction fields into a list of transaction dicts.

    For CC statements only TRANSACTION_AMOUNTS_PAID is used — there is no
    separate received/credit column.
    """
    dates = fields.get("TRANSACTION_DATES", "").split("|")
    descs = fields.get("TRANSACTION_DESCRIPTIONS", "").split("|")
    amounts = fields.get("TRANSACTION_AMOUNTS_PAID", "").split("|")

    txns = []
    for i in range(len(dates)):
        txn = {
            "date": dates[i].strip() if i < len(dates) else "",
            "description": descs[i].strip() if i < len(descs) else "",
            "amount": amounts[i].strip() if i < len(amounts) else "NOT_FOUND",
        }
        txns.append(txn)
    return txns


def _draw_header(
    draw: ImageDraw.ImageDraw,
    layout: dict,
    fields: dict,
    width: int,
) -> int:
    """Draw the colored bank header bar. Returns Y position after header."""
    header_cfg = layout["header"]
    bg = _parse_hex_color(header_cfg["background"])
    fg = _parse_hex_color(header_cfg["color"])
    h = header_cfg.get("height", 120)

    draw.rectangle([(0, 0), (width, h)], fill=bg)

    font = load_font(layout.get("font_size_header", 28), bold=True)
    draw.text(
        (layout.get("margin", 100), (h - 48) // 2),
        header_cfg["logo_text"],
        font=font,
        fill=fg,
    )

    return h


def _draw_account_info(
    draw: ImageDraw.ImageDraw,
    y: int,
    layout: dict,
    fields: dict,
) -> int:
    """Draw payer name and statement period. Returns Y after section."""
    margin = layout.get("margin", 100)
    font = load_font(layout.get("font_size_body", 20))
    font_small = load_font(layout.get("font_size_small", 16))
    line_h = 50

    payer = fields.get("PAYER_NAME", "")
    if payer:
        draw.text((margin, y), payer, font=font, fill="black")
        y += line_h

    date_range = fields.get("STATEMENT_DATE_RANGE", "")
    if date_range:
        draw.text(
            (margin, y),
            f"Statement Period: {date_range}",
            font=font_small,
            fill="black",
        )
        y += line_h

    supplier = fields.get("SUPPLIER_NAME", "")
    if supplier and supplier != layout.get("bank", ""):
        draw.text((margin, y), supplier, font=font_small, fill="gray")
        y += line_h

    return y + 20


def _draw_summary_box(
    draw: ImageDraw.ImageDraw,
    y: int,
    layout: dict,
    fields: dict,
) -> int:
    """Draw CC-specific summary box showing balance, limits, and payment info.

    Renders a light-grey bordered box containing key account summary fields:
    closing balance, credit limit, available credit, minimum payment, and
    payment due date.

    Returns Y after the summary box.
    """
    margin = layout.get("margin", 100)
    page_width = layout.get("page_width", 2480)
    font_small = load_font(layout.get("font_size_small", 16), bold=True)
    font_body = load_font(layout.get("font_size_body", 20))

    content_width = layout.get("content_width", page_width - 2 * margin)
    box_x0 = margin
    box_x1 = margin + content_width
    box_y0 = y
    line_h = 56
    padding = 20

    closing_balance_str = fields.get("ACCOUNT_BALANCE", "")
    credit_limit_str = fields.get("CREDIT_LIMIT", "")
    minimum_payment_str = fields.get("MINIMUM_PAYMENT", "")
    payment_due_date = fields.get("PAYMENT_DUE_DATE", "")

    # Compute available credit
    available_credit_str = ""
    if closing_balance_str and credit_limit_str:
        try:
            available = Decimal(credit_limit_str) - Decimal(closing_balance_str)
            available_credit_str = fmt_amount(available)
        except Exception:  # noqa: BLE001
            available_credit_str = ""

    summary_rows: list[tuple[str, str]] = []
    if closing_balance_str:
        try:
            summary_rows.append(("Closing Balance", fmt_amount(Decimal(closing_balance_str))))
        except Exception:  # noqa: BLE001
            summary_rows.append(("Closing Balance", closing_balance_str))
    if credit_limit_str:
        try:
            summary_rows.append(("Credit Limit", fmt_amount(Decimal(credit_limit_str))))
        except Exception:  # noqa: BLE001
            summary_rows.append(("Credit Limit", credit_limit_str))
    if available_credit_str:
        summary_rows.append(("Available Credit", available_credit_str))
    if minimum_payment_str:
        try:
            summary_rows.append(("Minimum Payment", fmt_amount(Decimal(minimum_payment_str))))
        except Exception:  # noqa: BLE001
            summary_rows.append(("Minimum Payment", minimum_payment_str))
    if payment_due_date:
        summary_rows.append(("Payment Due Date", payment_due_date))

    box_height = padding * 2 + len(summary_rows) * line_h + 10
    box_y1 = box_y0 + box_height

    draw.rectangle([(box_x0, box_y0), (box_x1, box_y1)], fill="#F8F8F8", outline="#AAAAAA")

    # Title
    draw.text((box_x0 + padding, box_y0 + padding), "Account Summary", font=font_small, fill="black")
    row_y = box_y0 + padding + line_h

    right_edge = box_x1 - padding
    for label, value in summary_rows:
        draw.text((box_x0 + padding, row_y), label, font=font_body, fill="#333333")
        draw_text_right(draw, value, x_right=right_edge, y=row_y, font=font_body)
        row_y += line_h

    return box_y1 + 20


def _draw_column_headers(
    draw: ImageDraw.ImageDraw,
    y: int,
    layout: dict,
) -> int:
    """Draw table column headers. Returns Y after headers."""
    columns = layout["columns"]
    font = load_font(layout.get("font_size_small", 16), bold=True)

    margin = layout.get("margin", 100)
    content_width = layout.get("content_width", layout.get("page_width", 2480) - 2 * margin)
    right_edge = margin + content_width
    draw.rectangle(
        [(margin, y), (right_edge, y + 50)],
        fill="#F0F0F0",
    )

    for col_key, col_cfg in columns.items():
        draw.text(
            (col_cfg["x"], y + 10),
            col_cfg.get("header", col_key),
            font=font,
            fill="black",
        )
    return y + 55


def _draw_transactions(
    draw: ImageDraw.ImageDraw,
    y: int,
    layout: dict,
    txns: list[dict],
) -> int:
    """Draw CC transaction rows with a single Amount column. Returns Y after last row."""
    columns = layout["columns"]
    row_h = layout.get("row_height", 45)
    font = load_font(layout.get("font_size_body", 20))
    borders = layout.get("borders", False)
    margin = layout.get("margin", 100)
    content_width = layout.get("content_width", layout.get("page_width", 2480) - 2 * margin)
    right_edge = margin + content_width

    for txn in txns:
        if borders:
            draw.rectangle(
                [(margin, y), (right_edge, y + row_h)],
                outline="#CCCCCC",
            )

        if "date" in columns:
            draw.text(
                (columns["date"]["x"], y + 14),
                txn["date"],
                font=font,
                fill="black",
            )

        desc_col = columns.get("description", {})
        if desc_col:
            draw.text(
                (desc_col["x"], y + 14),
                txn["description"],
                font=font,
                fill="black",
            )

        amount = txn.get("amount", "NOT_FOUND")
        if "amount" in columns and amount != "NOT_FOUND":
            amount_col = columns["amount"]
            try:
                amount_fmt = fmt_amount(Decimal(amount))
            except Exception:  # noqa: BLE001
                amount_fmt = amount
            draw_text_right(
                draw,
                amount_fmt,
                x_right=amount_col["x"] + amount_col["width"],
                y=y + 14,
                font=font,
            )

        y += row_h

    return y


def render_cc_statement(entry: dict, layout: dict) -> Image.Image:
    """Render a credit card statement image from ground truth entry and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered credit card statement.
    """
    layout = _normalize_layout(layout)
    width = layout.get("page_width", 2480)
    height = layout.get("page_height", 3508)
    fields = entry["fields"]

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    y = _draw_header(draw, layout, fields, width)
    y = _draw_account_info(draw, y + 30, layout, fields)
    y = _draw_summary_box(draw, y, layout, fields)
    y = _draw_column_headers(draw, y + 10, layout)

    txns = _parse_transactions(fields)
    _draw_transactions(draw, y + 5, layout, txns)

    return img
