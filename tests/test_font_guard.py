"""Guard: fit measurement must use a vendored face, never a system font.

`load_font` no longer has a system fallback at all, so the family registry is
the first line of defence and these tests cover the second: a caller who builds
an `ImageFont` itself and hands it to measurement.
"""

import pytest
from PIL import ImageFont

from generators.common import (
    FONT_FAMILIES,
    FontFamilyError,
    FontSourceError,
    assert_bundled_font,
    load_font,
)


@pytest.mark.parametrize("family", sorted(FONT_FAMILIES))
def test_every_vendored_family_loads_and_passes_guard(family):
    assert_bundled_font(load_font(20, family=family))  # vendored -> no raise


def test_system_font_fails_guard():
    system = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
    with pytest.raises(FontSourceError) as exc:
        assert_bundled_font(system)
    msg = str(exc.value)
    assert "not a bundled font" in msg.lower()  # what
    assert "fonts" in msg.lower()  # where
    assert "Carlito" in msg  # what it should look like
    assert "load_font" in msg  # how to recover


def test_unknown_family_fails_fast_with_a_diagnostic():
    """The fallback is gone, so a typo'd family must fail rather than degrade."""
    with pytest.raises(FontFamilyError) as exc:
        load_font(20, family="helvetica")
    msg = str(exc.value)
    assert "not a vendored font family" in msg  # what
    assert "config/layouts" in msg  # where
    assert "carlito" in msg  # what it should look like
    assert "FONT_FAMILIES" in msg  # how to recover
