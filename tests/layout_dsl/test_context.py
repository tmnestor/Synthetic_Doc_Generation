import pytest

from generators.layout_dsl.context import Region

from conftest import assert_diagnostic_error


def test_indent_narrows_and_shifts():
    region = Region(x=100, width=1600)
    inner = region.indent(20)
    assert inner.x == 120
    assert inner.width == 1580


def test_indent_applies_right_inset():
    inner = Region(x=100, width=1600).indent(20, 30)
    assert inner.x == 120
    assert inner.width == 1550


def test_divide_splits_evenly_with_gap():
    left, right = Region(x=100, width=1000).divide(2, gap=40)
    assert left.x == 100
    assert left.width == 480
    assert right.x == 620
    assert right.width == 480


def test_divide_rejects_gap_wider_than_region():
    with pytest.raises(ValueError, match="gap"):
        Region(x=0, width=50).divide(2, gap=100)


def test_right_edge():
    assert Region(x=100, width=1600).right == 1700


def test_divide_last_column_reaches_region_right():
    """Floor division drops up to n-1 px, so the last column never reaches the
    right edge. Westpac's only split is 1600 // 2 = 800 (exact), which is why
    this was never seen; any odd width or 3+ columns hits it."""
    columns = Region(x=100, width=1001).divide(3, gap=0)
    assert columns[-1].right == 1101
    assert sum(c.width for c in columns) == 1001


def test_divide_widths_places_explicit_columns():
    """Invoice totals occupy a fixed 400px column at the page's right edge,
    which equal division cannot express -- this is the exact-fit boundary:
    sum(widths) == region.width."""
    left, right = Region(x=100, width=1700).divide_widths([1300, 400], gap=0)
    assert (left.x, left.width) == (100, 1300)
    assert (right.x, right.width) == (1400, 400)
    assert right.right == 1800


def test_divide_widths_steps_by_width_plus_gap_like_divide():
    """Consistency with `divide`: each column's x is the previous column's
    right edge plus the gap, not a fraction of it."""
    left, right = Region(x=0, width=100).divide_widths([30, 30], gap=10)
    assert (left.x, left.width) == (0, 30)
    assert (right.x, right.width) == (40, 30)
    assert right.right == 70  # 30 + 10 + 30, well inside the 100px region


def test_divide_widths_rejects_a_sum_that_overflows_the_region():
    with pytest.raises(ValueError) as exc_info:
        Region(x=0, width=100).divide_widths([80, 80], gap=0)
    assert_diagnostic_error(exc_info.value)


def test_divide_widths_accepts_a_sum_exactly_equal_to_the_region():
    """Boundary: sum(widths) + gap * (n - 1) == self.width must not raise."""
    columns = Region(x=0, width=70).divide_widths([30, 30], gap=10)
    assert columns[-1].right == 70


@pytest.mark.parametrize(
    "call",
    [lambda: Region(x=0, width=100).indent(60, 60), lambda: Region(x=0, width=10).divide(20, gap=5)],
)
def test_region_errors_are_diagnostic(call):
    with pytest.raises(ValueError) as exc_info:
        call()
    assert_diagnostic_error(exc_info.value)
