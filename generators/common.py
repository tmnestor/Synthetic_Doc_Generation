"""Shared utilities for synthetic document generation.

Font loading, text drawing helpers, ABN/GST validation, and image degradation.
"""

import io
import random
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont

_FONT_CACHE: dict[tuple[int, bool, bool, bool], Font] = {}

# Maps id(font) -> Path it was loaded from, so fit measurement can assert it is
# using the bundled DejaVu face rather than a silent system fallback.
_FONT_SOURCE: dict[int, Path] = {}


class FontSourceError(RuntimeError):
    """Raised when a font used for measurement is not the bundled DejaVu face."""


# Bundled fonts directory (committed to repo for cross-platform consistency)
_BUNDLED_FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"

# Font search paths — bundled first, then platform-specific fallbacks
_SANS_PATHS = [
    _BUNDLED_FONTS_DIR / "DejaVuSans.ttf",
    Path("/System/Library/Fonts/Helvetica.ttc"),  # macOS
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),  # Linux
]
_SANS_BOLD_PATHS = [
    _BUNDLED_FONTS_DIR / "DejaVuSans-Bold.ttf",
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
_MONO_PATHS = [
    _BUNDLED_FONTS_DIR / "DejaVuSansMono.ttf",
    Path("/System/Library/Fonts/Menlo.ttc"),  # macOS
    Path("/System/Library/Fonts/SFMono-Regular.otf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
]
_MONO_BOLD_PATHS = [
    _BUNDLED_FONTS_DIR / "DejaVuSansMono-Bold.ttf",
    Path("/System/Library/Fonts/Menlo.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
]


def load_font(
    size: int,
    *,
    mono: bool = False,
    bold: bool = False,
    italic: bool = False,
) -> Font:
    """Load a font with bundled-first fallbacks and caching.

    Searches bundled fonts/ directory first for cross-platform consistency,
    then falls back to platform-specific system fonts.

    Args:
        size: Font size in points.
        mono: Use monospace font family.
        bold: Use bold weight.
        italic: Use italic style (best-effort).

    Returns:
        Loaded PIL font object.

    Raises:
        FileNotFoundError: No usable font found in bundled or system paths.
    """
    key = (size, mono, bold, italic)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    if mono:
        paths = _MONO_BOLD_PATHS if bold else _MONO_PATHS
    else:
        paths = _SANS_BOLD_PATHS if bold else _SANS_PATHS

    font: Font | None = None
    for p in paths:
        if p.exists():
            try:
                font = ImageFont.truetype(str(p), size)
                _FONT_SOURCE[id(font)] = p
                break
            except OSError:
                continue

    if font is None:
        searched = "\n  ".join(str(p) for p in paths)
        raise FileNotFoundError(
            f"No usable font found (mono={mono}, bold={bold}).\n"
            f"Searched paths:\n  {searched}\n"
            f"Fix: ensure the fonts/ directory exists at {_BUNDLED_FONTS_DIR} "
            f"with DejaVuSans*.ttf files."
        ) from None

    _FONT_CACHE[key] = font
    return font


def font_source_path(font: Font) -> Path | None:
    """Return the file a font was loaded from, or None if unknown."""
    return _FONT_SOURCE.get(id(font))


def assert_bundled_font(font: Font) -> None:
    """Fail loud if `font` was not loaded from the bundled fonts/ directory.

    load_font() silently falls back to system fonts when a bundled file is
    missing; measuring against a system font would diverge Mac<->PROD and
    silently corrupt fit decisions. This enforces the bundled-first guarantee.

    Raises:
        FontSourceError: the font is not a bundled DejaVu face.
    """
    src = font_source_path(font)
    if src is not None and _BUNDLED_FONTS_DIR in src.parents:
        return
    raise FontSourceError(
        "Font used for measurement is not a bundled font.\n"
        f"  What:     fit measurement requires a bundled DejaVu face; got {src}.\n"
        f"  Where:    bundled fonts directory {_BUNDLED_FONTS_DIR}\n"
        "  Expected: fonts/DejaVuSans.ttf (and -Bold / Mono variants) present so\n"
        "            load_font() resolves bundled-first, not a system fallback.\n"
        "  Recover:  restore/reinstall the fonts/ directory from the repo, then rerun."
    )


FitStrategy = str  # one of: "shrink", "wrap", "shrink_then_wrap"
_FIT_STRATEGIES = ("shrink", "wrap", "shrink_then_wrap")


@dataclass(frozen=True)
class FitResult:
    """Lossless render plan for a field: the full string laid out to fit its box."""

    lines: list[str]
    size: int
    line_height: int


class FitError(RuntimeError):
    """Raised when a string cannot fit its box even at the font floor / max lines."""


def _text_width(text: str, size: int, *, mono: bool, bold: bool) -> int:
    """Pixel width of `text` at `size`, measured against the bundled font."""
    font = load_font(size, mono=mono, bold=bold)
    assert_bundled_font(font)
    bbox = font.getbbox(text)
    return int(bbox[2] - bbox[0])


def _fit_error_message(text: str, *, width: int, min_font: int, max_lines: int, fit: str) -> str:
    """Four-element diagnostic body (caller prepends entry/field context)."""
    return (
        "string cannot fit its box losslessly.\n"
        f"  What:     {text!r} exceeds width {width}px at min_font {min_font} "
        f"across max_lines {max_lines} (fit={fit}).\n"
        "  Where:    the field's `field_budgets` entry in its config/layouts/*.yml.\n"
        "  Expected: width >= measured, or larger max_lines, or lower min_font; "
        "fit one of shrink|wrap|shrink_then_wrap.\n"
        "  Recover:  raise `width` (or `max_lines`) for this field in the layout YAML; "
        "never truncate the string."
    )


def _wrap_to_width(text: str, *, width: int, size: int, mono: bool, bold: bool) -> list[str] | None:
    """Greedy word-wrap at `size`.

    Returns lines each within `width`, or None if a single word cannot fit
    (caller treats None as unfittable — never splits a word / truncates).
    """
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        if _text_width(word, size, mono=mono, bold=bold) > width:
            return None  # unbreakable word wider than the box
        candidate = word if not current else f"{current} {word}"
        if _text_width(candidate, size, mono=mono, bold=bold) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(
    text: str,
    *,
    width: int,
    fit: FitStrategy,
    min_font: int,
    max_lines: int,
    nominal_size: int,
    mono: bool = False,
    bold: bool = False,
) -> FitResult:
    """Compute a lossless layout of `text` fitting within `width` px.

    Never truncates. Applies the field's `fit` strategy and raises FitError if
    the full string cannot fit even at the font floor across max_lines.

    Args:
        text: The full string to lay out (rendered verbatim).
        width: Horizontal box in pixels the string must fit within.
        fit: Strategy — "shrink", "wrap", or "shrink_then_wrap".
        min_font: Smallest font size shrinking may reach.
        max_lines: Lines the field may occupy.
        nominal_size: The field's default font size.
        mono: Measure with the monospace family.
        bold: Measure with the bold weight.

    Returns:
        FitResult with the laid-out lines, chosen size, and line height.

    Raises:
        FitError: the string cannot fit losslessly.
        ValueError: unknown fit strategy.
    """
    if fit not in _FIT_STRATEGIES:
        raise ValueError(f"unknown fit strategy {fit!r}; allowed: {_FIT_STRATEGIES}")

    def line_height(size: int) -> int:
        fnt = load_font(size, mono=mono, bold=bold)
        return int(fnt.size) if isinstance(fnt, ImageFont.FreeTypeFont) else size

    # Fits as-is at nominal size on one line -> unchanged (day-one path).
    if _text_width(text, nominal_size, mono=mono, bold=bold) <= width:
        return FitResult(lines=[text], size=nominal_size, line_height=line_height(nominal_size))

    if fit == "shrink":
        for size in range(nominal_size - 1, min_font - 1, -1):
            if _text_width(text, size, mono=mono, bold=bold) <= width:
                return FitResult(lines=[text], size=size, line_height=line_height(size))
        raise FitError(
            _fit_error_message(text, width=width, min_font=min_font, max_lines=max_lines, fit=fit)
        )

    if fit == "wrap":
        lines = _wrap_to_width(text, width=width, size=nominal_size, mono=mono, bold=bold)
        if lines is None or len(lines) > max_lines:
            raise FitError(
                _fit_error_message(text, width=width, min_font=min_font, max_lines=max_lines, fit=fit)
            )
        return FitResult(lines=lines, size=nominal_size, line_height=line_height(nominal_size))

    if fit == "shrink_then_wrap":
        for size in range(nominal_size, min_font - 1, -1):
            if _text_width(text, size, mono=mono, bold=bold) <= width:
                return FitResult(lines=[text], size=size, line_height=line_height(size))
            wrapped = _wrap_to_width(text, width=width, size=size, mono=mono, bold=bold)
            if wrapped is not None and len(wrapped) <= max_lines:
                return FitResult(lines=wrapped, size=size, line_height=line_height(size))
        raise FitError(
            _fit_error_message(text, width=width, min_font=min_font, max_lines=max_lines, fit=fit)
        )

    raise ValueError(f"unhandled fit strategy {fit!r}")


def _fit_from_budget(text: str, budget: dict, nominal_size: int, *, mono: bool, bold: bool) -> FitResult:
    """Run fit_text using a field's budget dict (width/fit/min_font/max_lines)."""
    return fit_text(
        text,
        width=budget["width"],
        fit=budget["fit"],
        min_font=budget["min_font"],
        max_lines=budget["max_lines"],
        nominal_size=nominal_size,
        mono=mono,
        bold=bold,
    )


def draw_fitted_left(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    *,
    budget: dict,
    nominal_size: int,
    mono: bool = False,
    bold: bool = False,
    fill: str = "black",
    line_spacing: int | None = None,
) -> int:
    """Left-align `text` at x, fitting it to its budget. Returns the advanced y.

    `line_spacing` overrides the per-line vertical advance (e.g. the layout's
    line_height); when None the font's own height is used. Advancing by a
    caller-supplied line_spacing keeps the single-line case pixel-identical to
    the pre-fit renderer while multi-line wrap pushes following content down.
    """
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    spacing = line_spacing if line_spacing is not None else r.line_height
    for line in r.lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += spacing
    return y


def draw_fitted_center(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    canvas_width: int,
    *,
    budget: dict,
    nominal_size: int,
    mono: bool = False,
    bold: bool = False,
    fill: str = "black",
    line_spacing: int | None = None,
) -> int:
    """Center `text` within canvas_width, fitting it to its budget. Returns advanced y.

    See draw_fitted_left for `line_spacing` semantics.
    """
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    spacing = line_spacing if line_spacing is not None else r.line_height
    for line in r.lines:
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        draw.text(((canvas_width - w) // 2, y), line, font=font, fill=fill)
        y += spacing
    return y


def draw_fitted_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    x_right: int,
    y: int,
    *,
    budget: dict,
    nominal_size: int,
    mono: bool = False,
    bold: bool = False,
    fill: str = "black",
    line_spacing: int | None = None,
) -> int:
    """Right-align `text` to x_right, fitting it to its budget. Returns advanced y.

    See draw_fitted_left for `line_spacing` semantics.
    """
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    spacing = line_spacing if line_spacing is not None else r.line_height
    for line in r.lines:
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        draw.text((x_right - w, y), line, font=font, fill=fill)
        y += spacing
    return y


def draw_text_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    x_right: int,
    y: int,
    font: Font,
    fill: str = "black",
) -> None:
    """Draw text right-aligned to x_right."""
    bbox = font.getbbox(text)
    text_width = bbox[2] - bbox[0]
    draw.text((x_right - text_width, y), text, font=font, fill=fill)


def draw_text_center(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    width: int,
    font: Font,
    fill: str = "black",
) -> None:
    """Draw text centered within given width."""
    bbox = font.getbbox(text)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), text, font=font, fill=fill)


def draw_separator(
    draw: ImageDraw.ImageDraw,
    y: int,
    width: int,
    margin: int,
    font: Font,
    fill: str = "black",
) -> None:
    """Draw a dashed separator line."""
    dash_bbox = font.getbbox("-")
    dash_width = int(dash_bbox[2] - dash_bbox[0])
    count = (width - 2 * margin) // dash_width
    dash = "-" * count
    draw.text((margin, y), dash, font=font, fill=fill)


def draw_separator_line(
    draw: ImageDraw.ImageDraw,
    x1: int,
    x2: int,
    y: int,
    color: str = "black",
    width: int = 1,
) -> None:
    """Draw a thin horizontal rule from x1 to x2 at vertical position y.

    Args:
        draw: PIL ImageDraw object.
        x1: Left x coordinate.
        x2: Right x coordinate.
        y: Vertical position.
        color: Line color (hex or name).
        width: Line width in pixels.
    """
    draw.line([(x1, y), (x2, y)], fill=color, width=width)


def draw_line_item(
    draw: ImageDraw.ImageDraw,
    desc: str,
    amount: str,
    y: int,
    font: Font,
    margin: int,
    width: int,
    fill: str = "black",
) -> None:
    """Draw a receipt line item: left-aligned description, right-aligned amount."""
    draw.text((margin, y), desc, font=font, fill=fill)
    draw_text_right(draw, amount, x_right=width - margin, y=y, font=font, fill=fill)


def fmt_amount(amount: Decimal | float | int) -> str:
    """Format a numeric amount as $X,XXX.XX."""
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${d:,.2f}"


# --- ABN Validation (ATO algorithm) ---

_ABN_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]


def validate_abn(abn: str) -> bool:
    """Validate an Australian Business Number using the ATO checksum algorithm.

    Args:
        abn: ABN string, with or without spaces (e.g. "53 004 085 616" or "53004085616").

    Returns:
        True if checksum is valid.
    """
    digits_str = abn.replace(" ", "")
    if len(digits_str) != 11 or not digits_str.isdigit():
        return False
    digits = [int(d) for d in digits_str]
    digits[0] -= 1  # Subtract 1 from first digit per ATO algorithm
    total = sum(d * w for d, w in zip(digits, _ABN_WEIGHTS, strict=True))
    return total % 89 == 0


def generate_abn() -> str:
    """Generate a valid 11-digit ABN with correct checksum.

    Returns:
        ABN formatted as "XX XXX XXX XXX".
    """
    base = [random.randint(0, 9) for _ in range(9)]
    for d0 in range(1, 10):
        for d1 in range(0, 10):
            digits = [d0, d1, *base]
            test = digits.copy()
            test[0] -= 1
            total = sum(d * w for d, w in zip(test, _ABN_WEIGHTS, strict=True))
            if total % 89 == 0:
                s = "".join(str(d) for d in digits)
                return f"{s[:2]} {s[2:5]} {s[5:8]} {s[8:11]}"
    msg = "Failed to generate valid ABN"
    raise RuntimeError(msg)


# --- TFN Validation (ATO algorithm) ---

_TFN_WEIGHTS = [1, 4, 3, 7, 5, 8, 6, 9, 10]


def validate_tfn(tfn: str) -> bool:
    """Validate an Australian Tax File Number using the ATO checksum algorithm.

    Args:
        tfn: TFN string, with or without spaces (e.g. "123 456 789" or "123456789").

    Returns:
        True if checksum is valid.
    """
    digits_str = tfn.replace(" ", "")
    if len(digits_str) != 9 or not digits_str.isdigit():
        return False
    digits = [int(d) for d in digits_str]
    total = sum(d * w for d, w in zip(digits, _TFN_WEIGHTS, strict=True))
    return total % 11 == 0


def generate_tfn() -> str:
    """Generate a valid 9-digit TFN with correct checksum.

    Returns:
        TFN formatted as "XXX XXX XXX".
    """
    base = [random.randint(0, 9) for _ in range(7)]
    for d0 in range(1, 10):
        for d1 in range(0, 10):
            digits = [*base, d0, d1]
            total = sum(d * w for d, w in zip(digits, _TFN_WEIGHTS, strict=True))
            if total % 11 == 0:
                s = "".join(str(d) for d in digits)
                return f"{s[:3]} {s[3:6]} {s[6:9]}"
    msg = "Failed to generate valid TFN"
    raise RuntimeError(msg)


# --- GST Calculation ---


def calculate_gst_inclusive(total: Decimal) -> tuple[Decimal, Decimal]:
    """Calculate GST from a GST-inclusive total.

    GST = total / 11 (rounded to 2dp).
    Ex-GST = total - GST.

    Args:
        total: GST-inclusive total amount.

    Returns:
        (gst_amount, ex_gst_amount) both rounded to 2 decimal places.
    """
    gst = (total / Decimal("11")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ex_gst = total - gst
    return gst, ex_gst


def calculate_gst_exclusive(subtotal: Decimal) -> tuple[Decimal, Decimal]:
    """Calculate GST from an ex-GST subtotal.

    GST = subtotal * 0.10.
    Total = subtotal + GST.

    Args:
        subtotal: Ex-GST subtotal.

    Returns:
        (gst_amount, gst_inclusive_total) both rounded to 2 decimal places.
    """
    gst = (subtotal * Decimal("0.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = subtotal + gst
    return gst, total


# --- Default degradation parameters ---

DEFAULT_DEGRADATION_PARAMS: dict[str, list[float]] = {
    "paper_tint_alpha": [0.03, 0.08],
    "contrast_factor": [0.85, 0.95],
    "brightness_factor": [0.90, 1.00],
    "blur_radius": [0.3, 0.8],
    "rotation_degrees": [0.5, 2.0],
    "noise_density": [0.001, 0.005],
    "jpeg_quality": [70, 85],
}


def draw_table(
    draw: ImageDraw.ImageDraw,
    *,
    x_left: int,
    x_right: int,
    y: int,
    title: str,
    columns: list[dict],
    rows: list[dict],
    total: dict | None,
    font_sub: Font,
    body_size: int,
    font_small: Font,
    font_label_code: Font,
    section_bg: str,
    header_row_bg: str,
    grid_line: str,
    label_code_color: str,
    desc_budget: dict,
    amount_budget: dict,
    row_h: int = 52,
) -> int:
    """Draw a bordered component table and return the new y coordinate.

    Fit-safe: each row's description wraps within its column and grows the row
    height (matching cc_statement.py's `_draw_transactions` row-growth), keeping
    the label code and amount on the first line and never colliding downward; the
    amount cell shrinks to fit its column. Presentation-only: callers pass
    pre-formatted string values plus the description/amount pixel budgets.

    Args:
        columns: each {"header", "width", "kind"} where kind is one of
            "label_code" | "description" | "amount".
        rows: each {"label_code", "description", "value"} (value pre-formatted).
        total: optional {"description", "value"} appended as a final row (flows
            through the same fit-safe per-row loop).
        body_size: nominal font size for description and amount cells.
        desc_budget: fit budget (width/fit/min_font/max_lines) for descriptions.
        amount_budget: fit budget (width/fit/min_font/max_lines) for amounts.

    Returns:
        The y coordinate below the table.
    """
    if title:
        draw.rectangle([(x_left, y), (x_right, y + 44)], fill=section_bg)
        draw.text((x_left + 12, y + 8), title, font=font_sub, fill="black")
        y += 56

    offsets: list[int] = []
    cx = x_left
    for col in columns:
        offsets.append(cx)
        cx += col.get("width", 400)

    draw.rectangle([(x_left, y), (x_right, y + row_h)], fill=header_row_bg)
    for col, ox in zip(columns, offsets, strict=True):
        draw.text((ox + 8, y + 12), col.get("header", ""), font=font_small, fill="black")
    y += row_h

    all_rows = list(rows)
    if total is not None:
        all_rows.append(
            {"label_code": "", "description": total.get("description", ""), "value": total.get("value", "")}
        )

    for row in all_rows:
        desc = row.get("description", "")
        # Fit the description first so a wrapped description grows the row height,
        # keeping the label code/amount on the first line and never colliding downward.
        desc_fit = fit_text(
            desc,
            width=desc_budget["width"],
            fit=desc_budget["fit"],
            min_font=desc_budget["min_font"],
            max_lines=desc_budget["max_lines"],
            nominal_size=body_size,
        )
        this_row_h = row_h * len(desc_fit.lines)

        draw_separator_line(draw, x_left, x_right, y, color=grid_line, width=1)
        for col, ox in zip(columns, offsets, strict=True):
            kind = col.get("kind", "description")
            if kind == "label_code":
                code = row.get("label_code", "")
                if code:
                    draw.text((ox + 30, y + 12), code, font=font_label_code, fill=label_code_color)
            elif kind == "amount":
                # amount text is right-anchored to x_right - 20, regardless of this column's offset
                draw_fitted_right(
                    draw,
                    row.get("value", ""),
                    x_right - 20,
                    y + 14,
                    budget=amount_budget,
                    nominal_size=body_size,
                )
            else:
                draw_fitted_left(
                    draw,
                    desc,
                    ox + 8,
                    y + 14,
                    budget=desc_budget,
                    nominal_size=body_size,
                    line_spacing=row_h,
                )
        y += this_row_h

    draw_separator_line(draw, x_left, x_right, y, color=grid_line, width=1)
    return y + 20


def degrade_image(
    img: Image.Image,
    seed: int,
    params: dict[str, list[float]] | None = None,
) -> Image.Image:
    """Apply deterministic degradation to simulate a phone photo of a printed document.

    Pipeline: paper tint -> contrast -> brightness -> blur -> rotation -> noise -> JPEG.

    Args:
        img: Source PIL image.
        seed: Random seed for deterministic degradation.
        params: Override degradation parameter ranges. Each key maps to [min, max].

    Returns:
        Degraded PIL image.
    """
    rng = random.Random(seed)
    p = {**DEFAULT_DEGRADATION_PARAMS, **(params or {})}

    result = img.convert("RGB")

    # 1. Paper tint (off-white / yellowed overlay)
    alpha = rng.uniform(p["paper_tint_alpha"][0], p["paper_tint_alpha"][1])
    tint = Image.new("RGB", result.size, (245, 240, 220))
    result = Image.blend(result, tint, alpha)

    # 2. Contrast reduction
    factor = rng.uniform(p["contrast_factor"][0], p["contrast_factor"][1])
    result = ImageEnhance.Contrast(result).enhance(factor)

    # 3. Brightness variation
    factor = rng.uniform(p["brightness_factor"][0], p["brightness_factor"][1])
    result = ImageEnhance.Brightness(result).enhance(factor)

    # 4. Gaussian blur
    radius = rng.uniform(p["blur_radius"][0], p["blur_radius"][1])
    result = result.filter(ImageFilter.GaussianBlur(radius=radius))

    # 5. Rotation
    angle = rng.uniform(p["rotation_degrees"][0], p["rotation_degrees"][1])
    angle = angle if rng.random() > 0.5 else -angle
    result = result.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255)
    )

    # 6. Salt-and-pepper noise
    density = rng.uniform(p["noise_density"][0], p["noise_density"][1])
    arr = np.array(result)
    np_rng = np.random.default_rng(seed)
    mask = np_rng.random(arr.shape[:2])
    arr[mask < density / 2] = 0  # salt
    arr[mask > 1 - density / 2] = 255  # pepper
    result = Image.fromarray(arr)

    # 7. JPEG compression artifacts
    quality = int(rng.uniform(p["jpeg_quality"][0], p["jpeg_quality"][1]))
    buf = io.BytesIO()
    result.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    result = Image.open(buf).copy()

    return result
