"""Draw-time bounding-box capture for the DocILE export.

The Pillow renderers already know where every field is drawn; this records
those pixel boxes and normalises them to relative [left, top, right, bottom]
coordinates in [0, 1], as DocILE requires (spec section 5).
"""


class BoxRecorder:
    """Collect field bounding boxes while a document is rendered."""

    def __init__(self, width: int, height: int) -> None:
        """Initialise a recorder for one page.

        Args:
            width: Page width in pixels.
            height: Page height in pixels.

        Raises:
            ValueError: If either dimension is not positive.
        """
        if width <= 0:
            msg = (
                f"BoxRecorder width must be positive, got {width}. "
                f"Remediation: pass the rendered image's pixel width."
            )
            raise ValueError(msg)
        if height <= 0:
            msg = (
                f"BoxRecorder height must be positive, got {height}. "
                f"Remediation: pass the rendered image's pixel height."
            )
            raise ValueError(msg)

        self.width = width
        self.height = height
        self._boxes: dict[str, list[float]] = {}

    def record(self, field: str, box: tuple[int, int, int, int]) -> None:
        """Record one field's pixel box, normalised to the page.

        Args:
            field: The source column name, suffixed '[i]' for line-item
                members, e.g. 'LINE_ITEM_DESCRIPTIONS[0]'.
            box: Pixel coordinates as (left, top, right, bottom).

        Raises:
            ValueError: If this field already has a recorded box.
        """
        if field in self._boxes:
            msg = (
                f"Field '{field}' already has a recorded box "
                f"{self._boxes[field]}. A field drawn twice has no unambiguous "
                f"ground-truth location. Remediation: give the second occurrence "
                f"a distinct field key, or suppress the duplicate draw call."
            )
            raise ValueError(msg)

        left, top, right, bottom = box
        self._boxes[field] = [
            _clamp(left / self.width),
            _clamp(top / self.height),
            _clamp(right / self.width),
            _clamp(bottom / self.height),
        ]

    def as_dict(self) -> dict[str, list[float]]:
        """Return the recorded boxes.

        Returns:
            Mapping of field key to [left, top, right, bottom] in [0, 1].
        """
        return dict(self._boxes)


def rescale_vertical(
    boxes: dict[str, list[float]], *, old_height: int, new_height: int
) -> dict[str, list[float]]:
    """Correct normalised y-coordinates after a page is cropped post-hoc.

    Receipts render onto an oversized canvas (unknown final length up front)
    and crop to content afterwards; boxes captured against the oversized
    canvas need their vertical fractions rescaled to the final, cropped page
    height. Horizontal fractions are unaffected — width never changes.

    Args:
        boxes: Normalised boxes as returned by `BoxRecorder.as_dict()`,
            captured while `old_height` was the recorder's page height.
        old_height: The page height (px) the boxes were normalised against.
        new_height: The actual final page height (px) after cropping.

    Returns:
        A new mapping with the same field keys and corrected y-coordinates.
    """
    if old_height == new_height:
        return dict(boxes)
    factor = old_height / new_height
    return {
        field: [left, _clamp(top * factor), right, _clamp(bottom * factor)]
        for field, (left, top, right, bottom) in boxes.items()
    }


def _clamp(value: float) -> float:
    """Clamp a normalised coordinate into [0, 1].

    Args:
        value: A coordinate that may fall outside the page.

    Returns:
        The coordinate, bounded to the unit interval and rounded to 6 places.
    """
    return round(min(max(value, 0.0), 1.0), 6)
