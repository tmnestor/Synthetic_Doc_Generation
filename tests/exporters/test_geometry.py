"""Tests for draw-time bounding-box capture."""

import pytest

from generators.exporters.geometry import BoxRecorder, rescale_vertical


def test_records_a_box_normalised_to_the_page() -> None:
    recorder = BoxRecorder(width=1000, height=2000)
    recorder.record("TOTAL_AMOUNT", (100, 200, 500, 300))
    assert recorder.as_dict() == {"TOTAL_AMOUNT": [0.1, 0.1, 0.5, 0.15]}


def test_line_item_members_are_indexed() -> None:
    recorder = BoxRecorder(width=100, height=100)
    recorder.record("LINE_ITEM_DESCRIPTIONS[0]", (0, 0, 50, 10))
    recorder.record("LINE_ITEM_DESCRIPTIONS[1]", (0, 10, 50, 20))
    assert set(recorder.as_dict()) == {
        "LINE_ITEM_DESCRIPTIONS[0]",
        "LINE_ITEM_DESCRIPTIONS[1]",
    }


def test_coordinates_stay_within_the_unit_square() -> None:
    recorder = BoxRecorder(width=100, height=100)
    recorder.record("SUPPLIER_NAME", (-5, -5, 120, 120))
    assert recorder.as_dict()["SUPPLIER_NAME"] == [0.0, 0.0, 1.0, 1.0]


def test_duplicate_field_is_rejected() -> None:
    """Two boxes for one field means the renderer drew it twice — ambiguous truth."""
    recorder = BoxRecorder(width=100, height=100)
    recorder.record("TOTAL_AMOUNT", (0, 0, 10, 10))
    with pytest.raises(ValueError) as exc:
        recorder.record("TOTAL_AMOUNT", (20, 20, 30, 30))
    assert "TOTAL_AMOUNT" in str(exc.value)


def test_zero_dimension_page_is_rejected() -> None:
    with pytest.raises(ValueError) as exc:
        BoxRecorder(width=0, height=100)
    assert "width" in str(exc.value)


def test_rescale_vertical_is_a_noop_when_heights_match() -> None:
    boxes = {"TOTAL_AMOUNT": [0.1, 0.2, 0.5, 0.3]}
    assert rescale_vertical(boxes, old_height=1000, new_height=1000) == boxes


def test_rescale_vertical_corrects_y_after_a_crop() -> None:
    # Captured against an oversized 4000px canvas; the real page is 2000px
    # (cropped to content) -- a box drawn at absolute y=[400, 440] should now
    # read as fractions of 2000, not 4000.
    recorder = BoxRecorder(width=640, height=4000)
    recorder.record("TOTAL_AMOUNT", (40, 400, 600, 440))
    rescaled = rescale_vertical(recorder.as_dict(), old_height=4000, new_height=2000)
    left, top, right, bottom = rescaled["TOTAL_AMOUNT"]
    assert left == 40 / 640
    assert right == 600 / 640
    assert top == pytest.approx(400 / 2000)
    assert bottom == pytest.approx(440 / 2000)


def test_rescale_vertical_clamps_results_into_the_unit_square() -> None:
    # A box near the bottom of the oversized canvas can rescale past 1.0
    # once the true (smaller) page height is known -- must still clamp.
    boxes = {"FOOTER": [0.0, 0.9, 0.5, 0.95]}
    rescaled = rescale_vertical(boxes, old_height=4000, new_height=1000)
    assert rescaled["FOOTER"] == [0.0, 1.0, 0.5, 1.0]


def test_rescale_vertical_does_not_mutate_the_input() -> None:
    boxes = {"TOTAL_AMOUNT": [0.1, 0.2, 0.5, 0.3]}
    rescale_vertical(boxes, old_height=4000, new_height=2000)
    assert boxes == {"TOTAL_AMOUNT": [0.1, 0.2, 0.5, 0.3]}
