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


def test_unmapped_parameter_is_a_diagnostic_not_a_bare_keyerror():
    """The trap for whoever next reaches for an Augraphy knob.

    Augraphy's parameter names are longer and less consistent than the YAML's,
    so every one has to be mapped by hand. An unmapped key used to raise a bare
    KeyError naming only the key -- no file, no list of what IS accepted, and no
    hint that the mapping table is where to look.
    """
    tier = _tier(paper=[{"augmentation": "Folding", "gradient_height": [0.3, 0.4]}])
    with pytest.raises(AugmentationError) as exc:
        apply_augraphy(_page(), tier, seed=1)

    message = str(exc.value)
    assert_diagnostic_error(message)
    assert "gradient_height" in message
    assert "gradient_width" in message, "must list the parameters that ARE accepted"
    assert "_PARAM_NAMES" in message, "must say where the mapping lives"


def test_the_fold_width_is_configurable():
    """Regression guard on the CREASE fix.

    The crease was invisible in finished photographs because gradient_width sat
    at Augraphy's default, drawing a narrow band of fine speckle that the heavy
    tier's blur, noise and JPEG then erased. If this parameter stops reaching
    Augraphy the fold silently narrows again and the screen's CREASE recall
    collapses back to near zero -- with nothing failing to say so.
    """
    narrow = apply_augraphy(
        _page(),
        _tier(paper=[{"augmentation": "Folding", "fold_count": 1, "gradient_width": [0.1, 0.15]}]),
        seed=11,
    )
    wide = apply_augraphy(
        _page(),
        _tier(paper=[{"augmentation": "Folding", "fold_count": 1, "gradient_width": [0.5, 0.6]}]),
        seed=11,
    )

    assert np.array(narrow).shape == np.array(wide).shape
    assert not np.array_equal(np.array(narrow), np.array(wide)), (
        "gradient_width did not reach Augraphy: the two folds are identical"
    )


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
