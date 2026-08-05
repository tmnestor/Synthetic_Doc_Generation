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

from generators.exporters.geometry import BoxRecorder

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
    recorder: "BoxRecorder | None" = None,
    field: str | None = None,
    prefix: str | None = None,
    prefix_field: str | None = None,
) -> int:
    """Left-align `text` at x, fitting it to its budget. Returns the advanced y.

    `line_spacing` overrides the per-line vertical advance (e.g. the layout's
    line_height); when None the font's own height is used. Advancing by a
    caller-supplied line_spacing keeps the single-line case pixel-identical to
    the pre-fit renderer while multi-line wrap pushes following content down.

    `recorder`/`field` are optional draw-time bounding-box capture (opt-in):
    when both are given, the drawn extent is recorded against `field`.

    `prefix`/`prefix_field` are an additional, independent opt-in capture: when
    `text` begins with the literal `prefix` (e.g. a "2x " quantity marker
    concatenated onto a line-item description before fitting), the prefix's
    own sub-box -- measured on the first rendered line, at the font size the
    fit actually chose -- is recorded against `prefix_field`. This never draws
    anything extra; it only measures where the already-drawn prefix landed.
    Silently skipped (no record, no error) if the first rendered line does not
    start with `prefix` -- this should not happen for current callers, since
    word-wrap never splits an unspaced prefix away from its own first word,
    but a future caller passing a prefix containing a space could hit it.
    """
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    spacing = line_spacing if line_spacing is not None else r.line_height
    top = y
    max_width = 0
    for line in r.lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = font.getbbox(line)
        max_width = max(max_width, int(bbox[2] - bbox[0]))
        y += spacing
    if recorder is not None and field is not None:
        recorder.record(field, (x, top, x + max_width, y))
    if recorder is not None and prefix_field is not None and prefix and r.lines:
        if r.lines[0].startswith(prefix):
            prefix_bbox = font.getbbox(prefix)
            prefix_w = int(prefix_bbox[2] - prefix_bbox[0])
            prefix_h = int(prefix_bbox[3] - prefix_bbox[1])
            recorder.record(prefix_field, (x, top, x + prefix_w, top + prefix_h))
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
    recorder: "BoxRecorder | None" = None,
    field: str | None = None,
) -> int:
    """Center `text` within canvas_width, fitting it to its budget. Returns advanced y.

    See draw_fitted_left for `line_spacing` semantics and the optional
    `recorder`/`field` draw-time bounding-box capture.
    """
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    spacing = line_spacing if line_spacing is not None else r.line_height
    top = y
    left = canvas_width
    right = 0
    for line in r.lines:
        bbox = font.getbbox(line)
        w = int(bbox[2] - bbox[0])
        x = (canvas_width - w) // 2
        draw.text((x, y), line, font=font, fill=fill)
        left = min(left, x)
        right = max(right, x + w)
        y += spacing
    if recorder is not None and field is not None:
        recorder.record(field, (left, top, right, y))
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
    recorder: "BoxRecorder | None" = None,
    field: str | None = None,
) -> int:
    """Right-align `text` to x_right, fitting it to its budget. Returns advanced y.

    See draw_fitted_left for `line_spacing` semantics and the optional
    `recorder`/`field` draw-time bounding-box capture.
    """
    r = _fit_from_budget(text, budget, nominal_size, mono=mono, bold=bold)
    font = load_font(r.size, mono=mono, bold=bold)
    spacing = line_spacing if line_spacing is not None else r.line_height
    top = y
    left = x_right
    for line in r.lines:
        bbox = font.getbbox(line)
        w = int(bbox[2] - bbox[0])
        draw.text((x_right - w, y), line, font=font, fill=fill)
        left = min(left, x_right - w)
        y += spacing
    if recorder is not None and field is not None:
        recorder.record(field, (left, top, x_right, y))
    return y


def draw_text_left(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    font: Font,
    fill: str = "black",
    *,
    recorder: "BoxRecorder | None" = None,
    field: str | None = None,
) -> None:
    """Draw text left-aligned at (x, y).

    `recorder`/`field` are optional draw-time bounding-box capture (opt-in):
    when both are given, the drawn extent is recorded against `field`.
    """
    draw.text((x, y), text, font=font, fill=fill)
    if recorder is not None and field is not None and text:
        bbox = font.getbbox(text)
        text_width = int(bbox[2] - bbox[0])
        text_height = int(bbox[3] - bbox[1])
        recorder.record(field, (x, y, x + text_width, y + text_height))


def capture_label_prefixed_value(
    draw: ImageDraw.ImageDraw,
    label: str,
    value: str,
    x: int,
    y: int,
    font: Font,
    *,
    recorder: "BoxRecorder | None" = None,
    field: str | None = None,
) -> None:
    """Record the box of `value` as drawn immediately after `label` at (x, y).

    Draws nothing itself -- the caller must already have drawn the combined
    `f"{label}{value}"` string as a single `draw.text` call (so glyph shaping
    matches exactly what is on the page; this function never changes pixels).
    It only measures where the `value` substring landed, so a label+value
    string like "Date: 02/03/2023" can carry a ground-truth box for the value
    alone ("02/03/2023"), excluding the label ("Date: ").

    `recorder`/`field` are optional (opt-in): when both are given and `value`
    is non-empty, the value's extent is recorded against `field`.

    Args:
        draw: PIL ImageDraw object (used only for `textlength` measurement).
        label: The literal label text preceding `value` (e.g. "Date: ").
        value: The value substring whose box should be recorded.
        x: The x position the combined `f"{label}{value}"` string was drawn at.
        y: The y position the combined string was drawn at.
        font: The font the combined string was drawn with.
    """
    if recorder is None or field is None or not value:
        return
    label_width = draw.textlength(label, font=font)
    bbox = font.getbbox(value)
    value_width = int(bbox[2] - bbox[0])
    value_height = int(bbox[3] - bbox[1])
    left = int(x + label_width)
    recorder.record(field, (left, y, left + value_width, y + value_height))


def draw_text_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    x_right: int,
    y: int,
    font: Font,
    fill: str = "black",
    *,
    recorder: "BoxRecorder | None" = None,
    field: str | None = None,
) -> None:
    """Draw text right-aligned to x_right.

    `recorder`/`field` are optional draw-time bounding-box capture (opt-in):
    when both are given, the drawn extent is recorded against `field`.
    """
    bbox = font.getbbox(text)
    text_width = int(bbox[2] - bbox[0])
    text_height = int(bbox[3] - bbox[1])
    left = x_right - text_width
    draw.text((left, y), text, font=font, fill=fill)
    if recorder is not None and field is not None:
        recorder.record(field, (left, y, x_right, y + text_height))


def draw_text_center(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    width: int,
    font: Font,
    fill: str = "black",
    *,
    recorder: "BoxRecorder | None" = None,
    field: str | None = None,
) -> None:
    """Draw text centered within given width.

    `recorder`/`field` are optional draw-time bounding-box capture (opt-in):
    when both are given, the drawn extent is recorded against `field`.
    """
    bbox = font.getbbox(text)
    text_width = int(bbox[2] - bbox[0])
    text_height = int(bbox[3] - bbox[1])
    x = (width - text_width) // 2
    draw.text((x, y), text, font=font, fill=fill)
    if recorder is not None and field is not None:
        recorder.record(field, (x, y, x + text_width, y + text_height))


def draw_separator(
    draw: ImageDraw.ImageDraw,
    y: int,
    width: int,
    margin: int,
    font: Font,
    fill: str = "black",
    char: str = "-",
) -> None:
    """Draw a separator line made of a repeated glyph (a dash, by default)."""
    dash_bbox = font.getbbox(char)
    dash_width = int(dash_bbox[2] - dash_bbox[0])
    count = (width - 2 * margin) // dash_width
    dash = char * count
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
    *,
    recorder: "BoxRecorder | None" = None,
    amount_field: str | None = None,
) -> None:
    """Draw a receipt line item: left-aligned description, right-aligned amount.

    `desc` is always a static label at every current call site (e.g. "SUBTOTAL",
    "GST", "TOTAL"), never a ground-truth field, so only the amount cell is
    capturable. `recorder`/`amount_field` are optional (opt-in): when both are
    given, the amount's drawn extent is recorded against `amount_field`.
    """
    draw.text((margin, y), desc, font=font, fill=fill)
    draw_text_right(
        draw,
        amount,
        x_right=width - margin,
        y=y,
        font=font,
        fill=fill,
        recorder=recorder,
        field=amount_field,
    )


def fmt_amount(amount: Decimal | float | int) -> str:
    """Format a numeric amount as $X,XXX.XX."""
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${d:,.2f}"


# --- ABN Validation (Australian Business Number checksum) ---

_ABN_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]


def validate_abn(abn: str) -> bool:
    """Validate an Australian Business Number using the official checksum algorithm.

    Args:
        abn: ABN string, with or without spaces (e.g. "53 004 085 616" or "53004085616").

    Returns:
        True if checksum is valid.
    """
    digits_str = abn.replace(" ", "")
    if len(digits_str) != 11 or not digits_str.isdigit():
        return False
    digits = [int(d) for d in digits_str]
    digits[0] -= 1  # Subtract 1 from first digit, per the published algorithm
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
