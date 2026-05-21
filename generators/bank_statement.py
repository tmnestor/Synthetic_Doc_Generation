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


def _fmt_amount_plain(amount: Decimal | float | int) -> str:
    """Format amount without $ prefix (Westpac style: 1,234.56)."""
    return fmt_amount(amount).lstrip("$")


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

    date_grouping = layout.get("date_grouping", False)
    current_date_group = ""
    for txn in txns:
        if date_grouping:
            # Date-grouped: date on its own row when date changes
            if txn["date"] != current_date_group:
                if current_date_group:
                    y += 10  # Gap between date groups
                current_date_group = txn["date"]
                draw.text((col_date_x, y), txn["date"], font=font_body, fill="black")
                y += row_height
        else:
            # Flat: date on every transaction row
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

    Visual DNA: red 'Westpac' logo top-left, bordered table with cell borders,
    'Date of Transaction' / 'Debits' / 'Credits (-)' headers, date grouping
    (premium), no $ prefix on amounts, page numbers.

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

    # -- Westpac logo (top-left, red) --
    logo_color = layout.get("logo_color", "#C41E3A")
    draw.text((margin, y), "Westpac", font=font_header, fill=logo_color)

    # -- Page number (top-right) --
    draw_text_right(draw, "Page 1 of 1", x_right=right_edge, y=y, font=font_footer, fill="#666666")
    y += 50

    # -- Rewards section (premium variant) --
    payer = fields.get("PAYER_NAME", "")
    date_range = fields.get("STATEMENT_DATE_RANGE", "")

    if layout.get("show_rewards_section"):
        y += 10
        rewards_top = y
        rewards_height = 170
        rewards_mid_x = margin + (right_edge - margin) // 2

        # Outer border
        draw.rectangle([(margin, rewards_top), (right_edge, rewards_top + rewards_height)], outline="black")
        # Vertical divider
        draw.line(
            [(rewards_mid_x, rewards_top), (rewards_mid_x, rewards_top + rewards_height)], fill="black"
        )

        # Left: Points summary
        ry = rewards_top + 8
        draw.text((margin + 10, ry), "Rewards Points Balance Summary", font=font_body_bold, fill="black")
        ry += 26
        for label, val in [
            ("Opening Balance", "345,678"),
            ("Points Earned", "12,456"),
            ("Bonus Points Earned", "0"),
            ("Points Redeemed", "0"),
            ("Closing Balance", "358,134"),
            ("Points Status", "Available"),
        ]:
            draw.text((margin + 10, ry), label, font=font_small, fill="black")
            draw_text_right(draw, val, x_right=rewards_mid_x - 15, y=ry, font=font_small)
            ry += 20
            draw.line([(margin, ry - 2), (rewards_mid_x, ry - 2)], fill="#CCCCCC")

        # Right: Message
        draw.text(
            (rewards_mid_x + 10, rewards_top + 8),
            "A message from Rewards",
            font=font_body_bold,
            fill="black",
        )

        y = rewards_top + rewards_height + 8
        draw.text(
            (margin, y),
            "To find out more about how Rewards Points are earned, go to the Rewards website.",
            font=font_small,
            fill="#666666",
        )
        y += 30

    y += 20

    # -- Section header --
    section_title = (
        "Westpac Premium Card\u00ae transactions"
        if layout.get("show_rewards_section")
        else "Transaction Details"
    )
    draw.text((margin, y), section_title, font=font_body_bold, fill="black")
    y += 30
    draw.text((margin, y), payer, font=font_body, fill="black")
    y += 22
    if date_range:
        draw.text((margin, y), f"Statement Period: {date_range}", font=font_small, fill="#666666")
        y += 22
    y += 10

    # -- Column positions for bordered table --
    col_date_right = margin + 200
    col_desc_right = right_edge - 320
    col_debit_right = right_edge - 160
    col_borders = [col_date_right, col_desc_right, col_debit_right]

    # -- Column header row (bordered) --
    header_h = 48
    draw.rectangle([(margin, y), (right_edge, y + header_h)], outline="black")
    for col_x in col_borders:
        draw.line([(col_x, y), (col_x, y + header_h)], fill="black")

    draw.text((margin + 8, y + 6), "Date of", font=font_body_bold, fill="black")
    draw.text((margin + 8, y + 24), "Transaction", font=font_body_bold, fill="black")
    draw.text((col_date_right + 8, y + 14), "Description", font=font_body_bold, fill="black")
    draw_text_right(draw, "Debits", x_right=col_debit_right - 8, y=y + 14, font=font_body_bold)
    draw_text_right(draw, "Credits (-)", x_right=right_edge - 8, y=y + 14, font=font_body_bold)
    y += header_h

    # -- Transactions (bordered table body) --
    txns = _parse_transactions(fields)
    table_body_start = y
    date_grouping = layout.get("date_grouping", False)
    current_date_group = ""

    for txn in txns:
        is_new_date = txn["date"] != current_date_group

        if date_grouping:
            if is_new_date:
                if current_date_group:
                    # Horizontal border between date groups
                    draw.line([(margin, y), (right_edge, y)], fill="black")
                current_date_group = txn["date"]
                draw.text((margin + 8, y + 6), txn["date"], font=font_body, fill="black")
        else:
            # Flat: border between every row, date on each
            if txn != txns[0]:
                draw.line([(margin, y), (right_edge, y)], fill="black")
            draw.text((margin + 8, y + 6), txn["date"], font=font_body, fill="black")

        # Description
        desc = txn["description"]
        max_desc_w = col_desc_right - col_date_right - 16
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_w and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_date_right + 8, y + 6), desc, font=font_body, fill="black")

        # Amounts (no $ prefix — Westpac style)
        if txn["debit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                _fmt_amount_plain(Decimal(txn["debit"])),
                x_right=col_debit_right - 8,
                y=y + 6,
                font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                _fmt_amount_plain(Decimal(txn["credit"])),
                x_right=right_edge - 8,
                y=y + 6,
                font=font_body,
            )

        y += row_height

    # -- Table outer borders and vertical column lines --
    draw.line([(margin, y), (right_edge, y)], fill="black")
    draw.line([(margin, table_body_start), (margin, y)], fill="black")
    draw.line([(right_edge, table_body_start), (right_edge, y)], fill="black")
    for col_x in col_borders:
        draw.line([(col_x, table_body_start), (col_x, y)], fill="black")

    return img


def render_nab(entry: dict, layout: dict) -> Image.Image:
    """Render a National Australia Bank statement.

    Visual DNA: light blue header bar and date-group rows, 'Particulars' column,
    date grouping with bold date headers, brought-forward/carried-forward rows,
    reference numbers with dotted leaders, balance with 'Cr' suffix.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout config with rendering parameters.

    Returns:
        PIL Image of the rendered NAB bank statement.
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
    header_color = _parse_hex_color(layout.get("header_bar_color", "#E8F0FE"))
    balance_suffix = layout.get("balance_suffix", "Cr")
    y = margin

    # -- Bank name header --
    draw.text((margin, y), "NAB Classic Banking", font=font_header, fill="#003366")
    y += 50

    # -- Account Details box --
    box_top = y
    payer = fields.get("PAYER_NAME", "")
    draw.rectangle([(margin, y), (right_edge, y + 100)], outline="#003366", width=2)
    y += 12
    draw.text((margin + 15, y), "Account Details", font=font_body_bold, fill="black")
    y += 25
    draw.text((margin + 15, y), payer, font=font_body, fill="black")
    draw_text_right(draw, "BSB Number", x_right=right_edge - 250, y=y, font=font_small, fill="#666666")
    draw_text_right(draw, "082-456", x_right=right_edge - 15, y=y, font=font_body, fill="black")
    y += 22
    draw_text_right(draw, "Account Number", x_right=right_edge - 250, y=y, font=font_small, fill="#666666")
    draw_text_right(draw, "98-765-4321", x_right=right_edge - 15, y=y, font=font_body, fill="black")
    y = box_top + 120

    # -- Section header --
    draw.text((margin, y), "Transaction Details (continued)", font=font_body_bold, fill="black")
    y += 35

    # -- Column header bar (light blue background) --
    draw.rectangle([(margin, y), (right_edge, y + 30)], fill=header_color)

    col_date_x = margin + 10
    col_desc_x = margin + 160
    col_debit_right = right_edge - 380
    col_credit_right = right_edge - 190
    col_balance_right = right_edge - 10

    draw.text((col_date_x, y + 5), "Date", font=font_body_bold, fill="black")
    draw.text((col_desc_x, y + 5), "Particulars", font=font_body_bold, fill="black")
    draw_text_right(draw, "Debits", x_right=col_debit_right, y=y + 5, font=font_body_bold)
    draw_text_right(draw, "Credits", x_right=col_credit_right, y=y + 5, font=font_body_bold)
    draw_text_right(draw, "Balance", x_right=col_balance_right, y=y + 5, font=font_body_bold)
    y += 35

    # -- Transactions with date grouping --
    txns = _parse_transactions(fields)
    txns = _compute_running_balances(txns, fields.get("ACCOUNT_BALANCE", "0"))

    # Pre-compute opening balance for "Brought forward"
    opening = Decimal("0")
    if layout.get("show_brought_forward") and txns:
        first_debit = Decimal(txns[0]["debit"]) if txns[0]["debit"] != "NOT_FOUND" else Decimal("0")
        first_credit = Decimal(txns[0]["credit"]) if txns[0]["credit"] != "NOT_FOUND" else Decimal("0")
        opening = txns[0]["balance"] - first_credit + first_debit

    current_date_group = ""
    brought_forward_rendered = False
    for txn in txns:
        # Date grouping: bold date header when date changes
        if layout.get("date_grouping") and txn["date"] != current_date_group:
            current_date_group = txn["date"]
            # Light blue date group row
            draw.rectangle([(margin, y), (right_edge, y + row_height - 2)], fill=header_color)
            draw.text((col_date_x, y + 4), txn["date"], font=font_body_bold, fill="black")
            y += row_height

            # "Brought forward" appears under the first date group header
            if not brought_forward_rendered and layout.get("show_brought_forward"):
                brought_forward_rendered = True
                draw.text((col_desc_x + 20, y + 4), "Brought forward", font=font_body, fill="black")
                draw_text_right(
                    draw,
                    f"{fmt_amount(opening)} {balance_suffix}",
                    x_right=col_balance_right,
                    y=y + 4,
                    font=font_body,
                )
                y += row_height

        # Indented transaction description
        desc = txn["description"]
        max_desc_w = col_debit_right - col_desc_x - 200
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_w and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_desc_x + 20, y + 4), desc, font=font_body, fill="black")

        # Reference number with dotted leader (if enabled)
        if layout.get("show_references"):
            ref_num = str(hash(txn["description"]) % 10**10).zfill(10)
            ref_text = f"Ref: {ref_num}"
            dots = "." * 40
            draw.text((col_desc_x + 20, y + 22), f"{ref_text}{dots}", font=font_small, fill="#999999")

        if txn["debit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                fmt_amount(Decimal(txn["debit"])),
                x_right=col_debit_right,
                y=y + 4,
                font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            draw_text_right(
                draw,
                fmt_amount(Decimal(txn["credit"])),
                x_right=col_credit_right,
                y=y + 4,
                font=font_body,
            )
        if "balance" in txn:
            draw_text_right(
                draw,
                f"{fmt_amount(txn['balance'])} {balance_suffix}",
                x_right=col_balance_right,
                y=y + 4,
                font=font_body,
            )

        ref_extra = 20 if layout.get("show_references") else 0
        y += row_height + ref_extra

    # -- Carried forward --
    if layout.get("show_brought_forward") and txns:
        draw.text((col_desc_x, y), "Carried forward", font=font_body_bold, fill="black")
        draw_text_right(
            draw,
            f"{fmt_amount(Decimal(fields.get('ACCOUNT_BALANCE', '0')))} {balance_suffix}",
            x_right=col_balance_right,
            y=y,
            font=font_body_bold,
        )

    return img


def render_anz(entry: dict, layout: dict) -> Image.Image:
    """Render an ANZ bank statement.

    Visual DNA: blue header bar, 'Transaction Description' column, DR/CR balance
    suffixes, BALANCE BROUGHT FORWARD opening, totals row at bottom.

    Args:
        entry: Ground truth YAML entry with 'fields' dict.
        layout: Layout config with rendering parameters.

    Returns:
        PIL Image of the rendered ANZ bank statement.
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
    font_small = load_font(font_sizes.get("sub_description", 14))
    font_footer = load_font(font_sizes["footer"])

    right_edge = width - margin
    header_color = _parse_hex_color(layout.get("header_color", "#0061B5"))
    suffix_dr = layout.get("balance_suffix_debit", "DR")
    suffix_cr = layout.get("balance_suffix_credit", "CR")
    y = margin

    # -- Blue header bar --
    draw.rectangle([(0, 0), (width, 80)], fill=header_color)
    draw.text((margin, 20), "ANZ", font=font_header, fill="white")

    # -- Account info --
    y = 100
    payer = fields.get("PAYER_NAME", "")

    draw_text_right(
        draw, "Account number    0000-00000", x_right=right_edge, y=y, font=font_small, fill="#666666"
    )
    y += 25
    draw.text((margin, y), "Transaction Details", font=font_body_bold, fill="black")
    y += 35

    # -- Column header with underline --
    col_date_x = margin
    col_desc_x = margin + 200
    col_debit_right = right_edge - 400
    col_credit_right = right_edge - 200
    col_balance_right = right_edge

    draw.text((col_date_x, y), "Date", font=font_body_bold, fill="black")
    draw.text((col_desc_x, y), "Transaction Description", font=font_body_bold, fill="black")
    draw_text_right(draw, "Debits", x_right=col_debit_right, y=y, font=font_body_bold)
    draw_text_right(draw, "Credits", x_right=col_credit_right, y=y, font=font_body_bold)
    draw_text_right(draw, "Balance", x_right=col_balance_right, y=y, font=font_body_bold)
    y += 28
    draw_separator_line(draw, margin, right_edge, y, color="black")
    y += 10

    # -- Transactions --
    txns = _parse_transactions(fields)
    txns = _compute_running_balances(txns, fields.get("ACCOUNT_BALANCE", "0"))

    def _format_balance(bal: Decimal) -> str:
        """Format balance with DR/CR suffix."""
        if bal >= 0:
            return f"{fmt_amount(bal)} {suffix_cr}"
        return f"{fmt_amount(abs(bal))} {suffix_dr}"

    # BALANCE BROUGHT FORWARD
    if layout.get("show_brought_forward") and txns:
        first_debit = Decimal(txns[0]["debit"]) if txns[0]["debit"] != "NOT_FOUND" else Decimal("0")
        first_credit = Decimal(txns[0]["credit"]) if txns[0]["credit"] != "NOT_FOUND" else Decimal("0")
        opening = txns[0]["balance"] - first_credit + first_debit
        draw.text((col_desc_x, y), "BALANCE BROUGHT FORWARD", font=font_body_bold, fill="black")
        draw_text_right(draw, _format_balance(opening), x_right=col_balance_right, y=y, font=font_body)
        y += row_height

    total_debits = Decimal("0")
    total_credits = Decimal("0")

    for txn in txns:
        draw.text((col_date_x, y), txn["date"], font=font_body, fill="black")

        desc = txn["description"]
        max_desc_w = col_debit_right - col_desc_x - 220
        bbox = font_body.getbbox(desc)
        while bbox[2] - bbox[0] > max_desc_w and len(desc) > 10:
            desc = desc[:-1]
            bbox = font_body.getbbox(desc)
        draw.text((col_desc_x, y), desc, font=font_body, fill="black")

        if txn["debit"] != "NOT_FOUND":
            debit_val = Decimal(txn["debit"])
            total_debits += debit_val
            draw_text_right(
                draw,
                fmt_amount(debit_val),
                x_right=col_debit_right,
                y=y,
                font=font_body,
            )
        if txn["credit"] != "NOT_FOUND":
            credit_val = Decimal(txn["credit"])
            total_credits += credit_val
            draw_text_right(
                draw,
                fmt_amount(credit_val),
                x_right=col_credit_right,
                y=y,
                font=font_body,
            )
        if "balance" in txn:
            draw_text_right(
                draw,
                _format_balance(txn["balance"]),
                x_right=col_balance_right,
                y=y,
                font=font_body,
            )
        y += row_height

    # -- Totals row --
    if layout.get("show_totals_row"):
        draw_separator_line(draw, margin, right_edge, y, color="black")
        y += 8
        draw.text((col_desc_x, y), "Totals at end of period", font=font_body_bold, fill="black")
        draw_text_right(draw, fmt_amount(total_debits), x_right=col_debit_right, y=y, font=font_body_bold)
        draw_text_right(draw, fmt_amount(total_credits), x_right=col_credit_right, y=y, font=font_body_bold)

    return img


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
