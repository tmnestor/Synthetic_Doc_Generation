"""Tests for the fit-aware draw helpers in generators/common.py."""

from PIL import Image, ImageDraw

from generators.common import (
    draw_fitted_center,
    draw_fitted_left,
    draw_fitted_right,
    load_font,
)


# Incidental to these helpers' geometry assertions, but now required.
_FAMILY = "carlito"


def _measure(text: str, size: int) -> int:
    bbox = load_font(size, family=_FAMILY).getbbox(text)
    return int(bbox[2] - bbox[0])


def _draw():
    img = Image.new("RGB", (400, 200), "white")
    return img, ImageDraw.Draw(img)


SHRINK = {"width": 300, "fit": "shrink", "min_font": 8, "max_lines": 1}


def test_fitted_left_returns_advanced_y():
    _, d = _draw()
    y = draw_fitted_left(d, "Coles", x=10, y=20, budget=SHRINK, nominal_size=20, family=_FAMILY)
    assert y > 20


def test_fitted_center_wraps_and_advances_more_for_two_lines():
    _, d = _draw()
    two_words = "alpha beta"
    wrap_budget = {
        "width": _measure(two_words, 20) + 6,
        "fit": "wrap",
        "min_font": 20,
        "max_lines": 2,
    }
    y_one = draw_fitted_center(d, "alpha", y=0, canvas_width=400, budget=SHRINK, nominal_size=20, family=_FAMILY)
    y_two = draw_fitted_center(
        d, "alpha beta gamma", y=0, canvas_width=400, budget=wrap_budget, nominal_size=20,
        family=_FAMILY,
    )
    assert y_two > y_one  # two wrapped lines advance further than one


def test_fitted_right_draws_within_canvas():
    _, d = _draw()
    y = draw_fitted_right(d, "$1,234.56", x_right=390, y=30, budget=SHRINK, nominal_size=20, family=_FAMILY)
    assert y > 30
