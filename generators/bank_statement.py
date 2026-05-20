"""Bank statement renderer — Big 4 Australian banks.

Per-bank renderers (CBA, Westpac, NAB, ANZ) dispatched via layout['renderer'] key.
Each renderer encodes the bank's visual DNA: header style, column layout, row
separators, balance formatting, and footer structure.
"""

from collections.abc import Callable
from decimal import Decimal

from PIL import Image, ImageDraw

from generators.common import (
    draw_separator_line,
    draw_text_right,
    fmt_amount,
    load_font,
)


# -- Shared utilities ---------------------------------------------------------


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


# -- CBA Renderer -------------------------------------------------------------


def render_cba(entry: dict, layout: dict) -> Image.Image:
    """Render a Commonwealth Bank statement.

    Visual DNA: dark navy bank name, horizontal rules framing column headers,
    'Withdrawal'/'Deposit' columns, $ amounts, footer with transaction types.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout config with 'page_dimensions', 'font_sizes', etc.

    Returns:
        PIL Image of the rendered CBA bank statement.
    """
    dims = layout["page_dimensions"]
    width, height = dims["width"], dims["height"]
    margin = layout["margin"]
    font_sizes = layout["font_sizes"]
    row_height = layout["row_height"]
    fields = entry["fields"]

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_header = load_font(font_sizes["header"], bold=True)
    font_body = load_font(font_sizes["body"])
    font_body_bold = load_font(font_sizes["body"], bold=True)
    font_footer = load_font(font_sizes["footer"])

    right_edge = width - margin
    y = margin

    # -- Bank name and legal lines --
    bank_color = layout.get("bank_name_color", "#12107D")
    draw.text((margin, y), "Commonwealth Bank", font=font_header, fill=bank_color)
    y += 45

    legal_lines = [
        "Commonwealth Bank of Australia",
        "ABN 48 123 456 789 AFSL and",
        "Australian credit licence 234567",
    ]
    for line in legal_lines:
        draw.text((margin, y), line, font=font_footer, fill="#666666")
        y += 16
    y += 30

    # -- Account details --
    payer = fields.get("PAYER_NAME", "")
    date_range = fields.get("STATEMENT_DATE_RANGE", "")

    draw.text((margin, y), f"Account Holder: {payer}", font=font_body, fill="black")
    y += 30
    if date_range:
        parts = date_range.split(" - ")
        if len(parts) == 2:
            draw.text(
                (margin, y),
                f"Statement Period: {parts[0].strip()} to {parts[1].strip()}",
                font=font_body,
                fill="black",
            )
        y += 30
    y += 20

    # -- Column positions --
    # Text columns left-aligned, numeric columns right-aligned
    col_date_x = margin
    col_desc_x = margin + 200
    col_withdrawal_right = right_edge - 420
    col_deposit_right = right_edge - 210
    col_balance_right = right_edge

    # -- Column header bar --
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 8

    headers = layout.get("column_headers", ["Date", "Description", "Withdrawal", "Deposit", "Balance"])
    draw.text((col_date_x, y), headers[0], font=font_body_bold, fill="black")
    draw.text((col_desc_x, y), headers[1], font=font_body_bold, fill="black")
    draw_text_right(draw, headers[2], x_right=col_withdrawal_right, y=y, font=font_body_bold)
    draw_text_right(draw, headers[3], x_right=col_deposit_right, y=y, font=font_body_bold)
    draw_text_right(draw, headers[4], x_right=col_balance_right, y=y, font=font_body_bold)
    y += 28
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 12

    # -- Transactions --
    txns = _parse_transactions(fields)
    txns = _compute_running_balances(txns, fields.get("ACCOUNT_BALANCE", "0"))

    # Opening balance row
    if layout.get("show_opening_balance") and txns:
        opening_balance = txns[0]["balance"]
        # Reverse the first txn to get opening
        first_debit = Decimal(txns[0]["debit"]) if txns[0]["debit"] != "NOT_FOUND" else Decimal("0")
        first_credit = Decimal(txns[0]["credit"]) if txns[0]["credit"] != "NOT_FOUND" else Decimal("0")
        opening = opening_balance - first_credit + first_debit
        draw.text((col_desc_x, y), "Opening Balance", font=font_body, fill="black")
        draw_text_right(draw, fmt_amount(opening), x_right=col_balance_right, y=y, font=font_body)
        y += row_height

    for txn in txns:
        draw.text((col_date_x, y), txn["date"], font=font_body, fill="black")

        # Truncate description to fit column
        desc = txn["description"]
        max_desc_width = col_withdrawal_right - col_desc_x - 220
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_width and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_desc_x, y), desc, font=font_body, fill="black")

        if txn["debit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                fmt_amount(Decimal(txn["debit"])),
                x_right=col_withdrawal_right,
                y=y,
                font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                fmt_amount(Decimal(txn["credit"])),
                x_right=col_deposit_right,
                y=y,
                font=font_body,
            )
        if "balance" in txn:
            draw_text_right(
                draw,
                fmt_amount(txn["balance"]),
                x_right=col_balance_right,
                y=y,
                font=font_body,
            )
        y += row_height

    # -- Bottom rule --
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 40

    # -- Footer --
    if layout.get("show_footer_transaction_types"):
        draw.text((margin, y), "TRANSACTION TYPES:", font=font_body_bold, fill="black")
        y += 28
        txn_types = [
            "EFTPOS — Electronic Funds Transfer at Point of Sale",
            "BPAY — Bill Payment",
            "DD — Direct Debit",
            "VISA DEBIT — Visa card purchase",
            "ATM — Automated Teller Machine withdrawal",
        ]
        for desc in txn_types:
            draw.text((margin, y), desc, font=font_footer, fill="#666666")
            y += 16
        y += 20
        draw.text((margin, y), "CommBank.com.au  |  13 2221", font=font_footer, fill="#666666")

    return img


# -- Dispatch -----------------------------------------------------------------


def render_westpac(entry: dict, layout: dict) -> Image.Image:
    """Render a Westpac bank statement.

    Visual DNA: red 'Westpac' logo top-right, 'Date of Transaction' column,
    dense multi-line layout, 'Debits'/'Credits ()' headers, page numbers.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout config with rendering parameters.

    Returns:
        PIL Image of the rendered Westpac bank statement.
    """
    dims = layout["page_dimensions"]
    width, height = dims["width"], dims["height"]
    margin = layout["margin"]
    font_sizes = layout["font_sizes"]
    row_height = layout["row_height"]
    fields = entry["fields"]

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_header = load_font(font_sizes["header"], bold=True)
    font_body = load_font(font_sizes["body"])
    font_body_bold = load_font(font_sizes["body"], bold=True)
    font_small = load_font(font_sizes.get("sub_description", 13))
    font_footer = load_font(font_sizes["footer"])

    right_edge = width - margin
    y = margin

    # -- Westpac logo (top-right, red) --
    logo_color = layout.get("logo_color", "#C41E3A")
    draw_text_right(draw, "Westpac", x_right=right_edge, y=y, font=font_header, fill=logo_color)
    y += 50

    # -- Page number (top-right) --
    draw_text_right(draw, "Page 1 of 1", x_right=right_edge, y=y, font=font_footer, fill="#666666")
    y += 30

    # -- Account info --
    payer = fields.get("PAYER_NAME", "")
    date_range = fields.get("STATEMENT_DATE_RANGE", "")
    supplier = fields.get("SUPPLIER_NAME", "Westpac")

    if layout.get("show_rewards_section"):
        draw.text((margin, y), "Rewards Points Balance Summary", font=font_body_bold, fill="black")
        y += 30
        draw.text((margin, y), "Available Points: 12,456", font=font_small, fill="#666666")
        y += 25
        draw_separator_line(draw, margin, right_edge, y, color="#CCCCCC")
        y += 20

    draw.text((margin, y), f"{supplier}: Premium CardII transactions", font=font_body_bold, fill="black")
    y += 30
    draw.text((margin, y), payer, font=font_body, fill="black")
    y += 25
    if date_range:
        draw.text((margin, y), f"Statement Period: {date_range}", font=font_small, fill="#666666")
        y += 25
    y += 15

    # -- Column positions --
    col_date_x = margin
    col_desc_x = margin + 220
    col_debit_right = right_edge - 260
    col_credit_right = right_edge

    # -- Column headers --
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 6
    draw.text((col_date_x, y), "Date of", font=font_body_bold, fill="black")
    y_sub = y + 20
    draw.text((col_date_x, y_sub), "Transaction", font=font_body_bold, fill="black")
    draw.text((col_desc_x, y), "Description", font=font_body_bold, fill="black")
    draw_text_right(draw, "Debits", x_right=col_debit_right, y=y, font=font_body_bold)
    draw_text_right(draw, "Credits ()", x_right=col_credit_right, y=y, font=font_body_bold)
    y = y_sub + 22
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 8

    # -- Transactions (dense) --
    txns = _parse_transactions(fields)

    for txn in txns:
        draw.text((col_date_x, y), txn["date"], font=font_body, fill="black")

        # Truncate description to fit
        desc = txn["description"]
        max_desc_w = col_debit_right - col_desc_x - 180
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_w and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_desc_x, y), desc, font=font_body, fill="black")

        if txn["debit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                fmt_amount(Decimal(txn["debit"])),
                x_right=col_debit_right,
                y=y,
                font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                fmt_amount(Decimal(txn["credit"])),
                x_right=col_credit_right,
                y=y,
                font=font_body,
            )
        y += row_height

    # -- Bottom rule --
    draw_separator_line(draw, margin, right_edge, y, color="black")

    return img


def render_nab(entry: dict, layout: dict) -> Image.Image:
    """NAB renderer stub — replaced in Task 5."""
    raise NotImplementedError("NAB renderer not yet implemented")


def render_anz(entry: dict, layout: dict) -> Image.Image:
    """ANZ renderer stub — replaced in Task 6."""
    raise NotImplementedError("ANZ renderer not yet implemented")


_BANK_RENDERERS: dict[str, Callable[..., Image.Image]] = {
    "cba": render_cba,
    "westpac": render_westpac,
    "nab": render_nab,
    "anz": render_anz,
}


def render_bank_statement(entry: dict, layout: dict) -> Image.Image:
    """Render a bank statement image from ground truth entry and layout config.

    Dispatches to the per-bank renderer based on layout['renderer'].

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout registry entry with 'renderer' key.

    Returns:
        PIL Image of the rendered bank statement.
    """
    renderer_key = layout.get("renderer")
    if renderer_key not in _BANK_RENDERERS:
        valid = sorted(_BANK_RENDERERS.keys())
        msg = (
            f"Unknown renderer '{renderer_key}' in layout. "
            f"Expected one of {valid}. "
            f"Check the 'renderer' key in config/layouts/bank_statements.yml."
        )
        raise ValueError(msg)
    return _BANK_RENDERERS[renderer_key](entry, layout)
