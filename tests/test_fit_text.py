"""Tests for fit_text lossless fitting in generators/common.py."""

import pytest
from conftest import assert_diagnostic_error

from generators.common import FitError, FitResult, fit_text, load_font


# These test fit_text's strategy logic, not any particular typeface, so the
# family is incidental — but it is now required (no Python-side default, since
# the face is a layout decision), and measuring and fitting must agree on it.
_FAMILY = "carlito"


def _measure(text: str, size: int) -> int:
    bbox = load_font(size, family=_FAMILY).getbbox(text)
    return int(bbox[2] - bbox[0])


def test_fits_as_is_returns_nominal_single_line():
    text = "Coles"
    width = _measure(text, 20) + 50
    r = fit_text(text, width=width, fit="shrink", min_font=12, max_lines=1, nominal_size=20, family=_FAMILY)
    assert r == FitResult(lines=[text], size=20, line_height=load_font(20, family=_FAMILY).size)


def test_shrink_reduces_size_until_it_fits():
    text = "Nguyen & Associates Chartered Accountants"
    tight = _measure(text, 20) - 40  # too wide at 20
    r = fit_text(text, width=tight, fit="shrink", min_font=8, max_lines=1, nominal_size=20, family=_FAMILY)
    assert r.lines == [text]  # lossless: full string, one line
    assert r.size < 20  # shrunk
    assert _measure(text, r.size) <= tight  # actually fits


def test_shrink_raises_fiterror_below_floor():
    text = "Nguyen & Associates Chartered Accountants Pty Ltd"
    impossible = _measure(text, 8) - 5  # cannot fit even at floor 8
    with pytest.raises(FitError):
        fit_text(text, width=impossible, fit="shrink", min_font=8, max_lines=1, nominal_size=20, family=_FAMILY)


def test_wrap_splits_into_allowed_lines():
    text = "Nguyen and Associates Chartered Accountants"
    width = _measure("Nguyen and Associates", 20) + 10
    r = fit_text(text, width=width, fit="wrap", min_font=20, max_lines=3, nominal_size=20, family=_FAMILY)
    assert " ".join(r.lines) == text  # lossless: words preserved in order
    assert len(r.lines) <= 3
    assert all(_measure(line, 20) <= width for line in r.lines)


def test_wrap_raises_when_exceeds_max_lines():
    text = "Nguyen and Associates Chartered Accountants Group"
    width = _measure("Nguyen", 20) + 5
    with pytest.raises(FitError):
        fit_text(text, width=width, fit="wrap", min_font=20, max_lines=2, nominal_size=20, family=_FAMILY)


def test_shrink_then_wrap_prefers_shrink_then_wraps():
    text = "Nguyen and Associates Chartered Accountants"
    width = _measure("Nguyen and Associates", 20) + 10
    r = fit_text(text, width=width, fit="shrink_then_wrap", min_font=10, max_lines=2, nominal_size=20, family=_FAMILY)
    assert " ".join(r.lines) == text
    assert len(r.lines) <= 2


def test_impossible_fit_raises_four_element_diagnostic():
    text = "Nguyen and Associates Chartered Accountants Group Pty Limited"
    width = _measure("Ng", 10)
    with pytest.raises(FitError) as exc:
        fit_text(text, width=width, fit="shrink_then_wrap", min_font=10, max_lines=2, nominal_size=20, family=_FAMILY)
    assert_diagnostic_error(str(exc.value))
