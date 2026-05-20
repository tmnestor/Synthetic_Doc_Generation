"""Bank statement renderer — Big 4 Australian banks.

Renders PIL images from ground truth YAML entries using layout registry configs.
Cherry-picked and refactored from scripts/generate_bank_statements.py.
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
    """Parse pipe-delimited transaction fields into a list of transaction dicts."""
    dates = fields.get("TRANSACTION_DATES", "").split("|")
    descs = fields.get("TRANSACTION_DESCRIPTIONS", "").split("|")
    debits = fields.get("TRANSACTION_AMOUNTS_PAID", "").split("|")
    credits = fields.get("TRANSACTION_AMOUNTS_RECEIVED", "").split("|")

    txns = []
    for i in range(len(dates)):
        txn = {
            "date": dates[i].strip() if i < len(dates) else "",
            "description": descs[i].strip() if i < len(descs) else "",
            "debit": debits[i].strip() if i < len(debits) else "NOT_FOUND",
            "credit": credits[i].strip() if i < len(credits) else "NOT_FOUND",
        }
        txns.append(txn)
    return txns


def _compute_running_balances(txns: list[dict], closing_balance: str) -> list[dict]:
    """Compute running balances working backward from closing balance."""
    try:
        balance = Decimal(closing_balance)
    except Exception:  # noqa: BLE001
        balance = Decimal("0")

    for txn in reversed(txns):
        txn["balance"] = balance
        debit = Decimal(txn["debit"]) if txn["debit"] != "NOT_FOUND" else Decimal("0")
        credit = Decimal(txn["credit"]) if txn["credit"] != "NOT_FOUND" else Decimal("0")
        balance = balance + debit - credit
    return txns


def _draw_header(
    draw: ImageDraw.ImageDraw,
    layout: dict,
    fields: dict,
    width: int,
) -> int:
    """Draw the bank header bar. Returns Y position after header."""
    header_cfg = layout["header"]
    bg = _parse_hex_color(header_cfg["background"])
    fg = _parse_hex_color(header_cfg["color"])
    h = header_cfg.get("height", 120)

    draw.rectangle([(0, 0), (width, h)], fill=bg)

    font = load_font(layout.get("font_size_header", 28), bold=True)
    draw.text(
        (layout.get("margin", 100), (h - 28) // 2),
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
    """Draw account holder name and statement period. Returns Y after section."""
    margin = layout.get("margin", 100)
    font = load_font(layout.get("font_size_body", 20))
    font_small = load_font(layout.get("font_size_small", 16))
    line_h = 35

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


def _draw_column_headers(
    draw: ImageDraw.ImageDraw,
    y: int,
    layout: dict,
) -> int:
    """Draw table column headers. Returns Y after headers."""
    columns = layout["columns"]
    font = load_font(layout.get("font_size_small", 16), bold=True)

    margin = layout.get("margin", 100)
    page_width = layout.get("page_width", 2480)
    draw.rectangle(
        [(margin, y), (page_width - margin, y + 35)],
        fill="#F0F0F0",
    )

    for col_key, col_cfg in columns.items():
        draw.text(
            (col_cfg["x"], y + 5),
            col_cfg.get("header", col_key),
            font=font,
            fill="black",
        )
    return y + 40


def _draw_transactions(
    draw: ImageDraw.ImageDraw,
    y: int,
    layout: dict,
    txns: list[dict],
) -> int:
    """Draw transaction rows. Returns Y after last row."""
    columns = layout["columns"]
    row_h = layout.get("row_height", 45)
    font = load_font(layout.get("font_size_body", 20))
    borders = layout.get("borders", False)
    margin = layout.get("margin", 100)
    page_width = layout.get("page_width", 2480)

    for txn in txns:
        if borders:
            draw.rectangle(
                [(margin, y), (page_width - margin, y + row_h)],
                outline="#CCCCCC",
            )

        if "date" in columns:
            draw.text(
                (columns["date"]["x"], y + 8),
                txn["date"],
                font=font,
                fill="black",
            )
        if "txn_date" in columns:
            draw.text(
                (columns["txn_date"]["x"], y + 8),
                txn["date"],
                font=font,
                fill="black",
            )

        desc_col = columns.get("description", {})
        if desc_col:
            draw.text(
                (desc_col["x"], y + 8),
                txn["description"],
                font=font,
                fill="black",
            )

        if "debit" in columns and txn["debit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                fmt_amount(Decimal(txn["debit"])),
                x_right=columns["debit"]["x"] + columns["debit"]["width"],
                y=y + 8,
                font=font,
            )

        if "credit" in columns and txn["credit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                fmt_amount(Decimal(txn["credit"])),
                x_right=columns["credit"]["x"] + columns["credit"]["width"],
                y=y + 8,
                font=font,
            )

        if "balance" in columns and "balance" in txn:
            balance_str = fmt_amount(txn["balance"])
            balance_col = columns["balance"]
            draw_text_right(
                draw,
                balance_str,
                x_right=balance_col["x"] + balance_col["width"],
                y=y + 8,
                font=font,
            )

        y += row_h

    return y


def render_bank_statement(entry: dict, layout: dict) -> Image.Image:
    """Render a bank statement image from ground truth entry and layout config.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with rendering config.

    Returns:
        PIL Image of the rendered bank statement.
    """
    layout = _normalize_layout(layout)
    width = layout.get("page_width", 2480)
    height = layout.get("page_height", 3508)
    fields = entry["fields"]

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    y = _draw_header(draw, layout, fields, width)
    y = _draw_account_info(draw, y + 30, layout, fields)
    y = _draw_column_headers(draw, y, layout)

    txns = _parse_transactions(fields)
    txns = _compute_running_balances(txns, fields.get("ACCOUNT_BALANCE", "0"))

    _draw_transactions(draw, y + 5, layout, txns)

    return img
