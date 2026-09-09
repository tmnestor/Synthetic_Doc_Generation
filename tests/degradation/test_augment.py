"""The augmentation registry rejects unknown names at build time, and the
augmented output is deterministic for a given seed."""

import numpy as np
import pytest
from conftest import assert_diagnostic_error
from PIL import Image

from generators.degradation.augment import AUGMENTATIONS, AugmentationError, apply_augraphy
from generators.degradation.tiers import Tier


def _tier(ink=None, paper=None) -> Tier:
    return Tier(
        name="probe",
        suffix="vX",
        ink=ink if ink is not None else [],
        paper=paper if paper is not None else [],
        warp={},
        camera={},
    )


def _page() -> Image.Image:
    """A small page with real ink on it -- a blank image augments to itself."""
    arr = np.full((240, 180, 3), 250, dtype=np.uint8)
    arr[60:70, 20:160] = 20
    arr[110:120, 20:160] = 20
    return Image.fromarray(arr)


def test_registry_exposes_the_tier_augmentations():
    for name in ("InkBleed", "LightingGradient", "ShadowCast", "Folding"):
        assert name in AUGMENTATIONS


def test_photocopier_augmentations_are_not_registered():
    """Excluded by design -- they model a different damage story."""
    assert "DirtyRollers" not in AUGMENTATIONS
    assert "BadPhotoCopy" not in AUGMENTATIONS


def test_unknown_augmentation_is_a_diagnostic():
    tier = _tier(ink=[{"augmentation": "Sepia", "intensity": 1}])
    with pytest.raises(AugmentationError) as exc:
        apply_augraphy(_page(), tier, seed=1)
    assert_diagnostic_error(str(exc.value))
    assert "Sepia" in str(exc.value)
    assert "InkBleed" in str(exc.value)  # lists what IS registered


def test_spec_without_an_augmentation_key_is_a_diagnostic():
    with pytest.raises(AugmentationError) as exc:
        apply_augraphy(_page(), _tier(ink=[{"intensity": 1}]), seed=1)
    assert_diagnostic_error(str(exc.value))


def test_same_seed_gives_identical_output():
    tier = _tier(ink=[{"augmentation": "InkBleed", "intensity": [0.2, 0.4], "kernel": 3}])
    first = apply_augraphy(_page(), tier, seed=7)
    second = apply_augraphy(_page(), tier, seed=7)
    assert first.tobytes() == second.tobytes()


def test_augmentation_changes_the_image():
    tier = _tier(ink=[{"augmentation": "InkBleed", "intensity": [0.3, 0.5], "kernel": 5}])
    page = _page()
    assert apply_augraphy(page, tier, seed=3).tobytes() != page.tobytes()


def test_empty_phases_pass_the_image_through_unchanged():
    page = _page()
    assert apply_augraphy(page, _tier(), seed=1).size == page.size


def test_dimensions_are_preserved():
    """Ground truth is value-F1, but a size change would break the warp's
    source quad, which assumes the augmented page is the original size."""
    tier = _tier(
        ink=[{"augmentation": "InkBleed", "intensity": [0.2, 0.3], "kernel": 3}],
        paper=[{"augmentation": "LightingGradient", "max_brightness": 245, "direction": 45}],
    )
    page = _page()
    assert apply_augraphy(page, tier, seed=5).size == page.size
