"""Shared utilities for synthetic document generation.

Font loading, text drawing helpers, ABN/GST validation, and image degradation.
"""

import io
import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

Font = ImageFont.FreeTypeFont | ImageFont.ImageFont

_FONT_CACHE: dict[tuple[int, bool, bool, bool], Font] = {}

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
