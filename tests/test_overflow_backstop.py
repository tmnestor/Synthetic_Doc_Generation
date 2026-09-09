"""Overflow backstop: render each entry and collect FitError violations."""

from conftest import assert_diagnostic_error

from generators.common import FitError
from generators.overflow_check import (
    OverflowError_,
    build_overflow_error,
    check_overflow,
)

_GT = {"CASE001": {"layout": "L", "fields": {}}, "CASE002": {"layout": "L", "fields": {}}}
_LAYOUTS = {"L": {"width": 1}}


def _bad_renderer(entry, layout):
    raise FitError("string cannot fit")


def _ok_renderer(entry, layout):
    return None


def test_collects_all_violations_without_raising():
    violations = check_overflow(_GT, _LAYOUTS, _bad_renderer)
    assert len(violations) == 2
    assert "CASE001" in violations[0]


def test_no_violations_when_render_ok():
    assert check_overflow(_GT, _LAYOUTS, _ok_renderer) == []


def test_skips_entries_with_unknown_layout():
    gt = {"CASE001": {"layout": "MISSING", "fields": {}}}
    assert check_overflow(gt, _LAYOUTS, _bad_renderer) == []


def test_build_overflow_error_is_four_element_diagnostic():
    err = build_overflow_error(["CASE001 / L: too long"])
    assert isinstance(err, OverflowError_)
    assert_diagnostic_error(str(err))


def test_validate_passes_on_current_ground_truth():
    """The shipped documents all fit losslessly; validate must exit 0."""
    from typer.testing import CliRunner

    from generators.pipeline import app

    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 0, result.output
