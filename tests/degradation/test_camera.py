"""The warp produces a photo-shaped frame, the pipeline is deterministic per
(case seed, tier index), and every drawn value is reported back.

The provenance tests matter as much as the image ones. Nothing downstream can
tell whether a recorded rotation is the rotation that was actually applied, so
if provenance ever drifts from the transform it describes, every quality label
built on it is quietly wrong and no test of the images would notice.
"""

import numpy as np
import pytest
from PIL import Image

from generators.degradation import compose_clean, degrade_document, tier_seed
from generators.degradation.camera import apply_photometrics, warp_to_photo
from generators.degradation.tiers import Tier

WARP = {"foreshorten": [0.03, 0.06], "rotation_deg": [-8, 8], "margin": [0.07, 0.14]}
CAMERA = {"blur": [0.4, 0.8], "noise_sigma": [2, 5], "jpeg": [65, 80]}
FLAT = {"foreshorten": [0.0, 0.0], "rotation_deg": [0.0, 0.0], "margin": [0.07, 0.14]}


def _tier(name="moderate", suffix="moderate") -> Tier:
    return Tier(
        name=name,
        suffix=suffix,
        ink=[{"augmentation": "InkBleed", "intensity": [0.15, 0.30], "kernel": 5}],
        paper=[{"augmentation": "LightingGradient", "max_brightness": 245, "direction": 45}],
        warp=WARP,
        camera=CAMERA,
    )


def _page() -> Image.Image:
    arr = np.full((300, 200, 3), 250, dtype=np.uint8)
    arr[80:95, 20:180] = 15
    return Image.fromarray(arr)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def test_warp_enlarges_the_frame_by_the_margin():
    """The document must occupy a sub-region, surrounded by background --
    that framing is the whole point of the camera model."""
    page = _page()
    out, _ = warp_to_photo(page, WARP, np.random.default_rng(1))
    assert out.width > page.width
    assert out.height > page.height


def test_warp_leaves_background_in_the_corners():
    """A corner pixel should be desk, not paper: if the page still filled the
    frame, the perspective warp did not happen."""
    out, _ = warp_to_photo(_page(), WARP, np.random.default_rng(2))
    corner = out.getpixel((2, 2))
    assert corner != (255, 255, 255), "corner is pure white -- no background composited"


def test_photometrics_preserve_dimensions():
    page = _page()
    out, _ = apply_photometrics(page, CAMERA, np.random.default_rng(3))
    assert out.size == page.size


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(8))
def test_warp_reports_values_inside_the_declared_range(seed):
    """The seam between what a tier permits and what an image got."""
    _, prov = warp_to_photo(_page(), WARP, np.random.default_rng(seed))
    lo, hi = WARP["rotation_deg"]
    assert lo <= prov["rotation_deg"] <= hi
    lo, hi = WARP["foreshorten"]
    assert lo <= prov["foreshorten"] <= hi
    assert prov["foreshortened_edge"] in {"top", "right", "bottom", "left"}


@pytest.mark.parametrize("seed", range(8))
def test_photometrics_report_values_inside_the_declared_range(seed):
    _, prov = apply_photometrics(_page(), CAMERA, np.random.default_rng(seed))
    for key, config_key in (("blur_sigma", "blur"), ("noise_sigma", "noise_sigma")):
        lo, hi = CAMERA[config_key]
        assert lo <= prov[key] <= hi, f"{key} outside its declared range"
    lo, hi = CAMERA["jpeg"]
    assert lo <= prov["jpeg_quality"] <= hi


def test_reported_rotation_is_the_rotation_applied():
    """Guards provenance drifting from the transform it claims to describe.

    Rotating by the reported angle and by its negation cannot both produce the
    same frame unless the angle is ~0, so a provenance value that had no effect
    on the image would fail here.
    """
    page = _page()
    frame, prov = warp_to_photo(page, WARP, np.random.default_rng(11))
    assert abs(prov["rotation_deg"]) > 0.5, "seed drew a near-zero angle; test says nothing"

    mirrored = dict(WARP, rotation_deg=[-prov["rotation_deg"], -prov["rotation_deg"]])
    other, _ = warp_to_photo(page, mirrored, np.random.default_rng(11))
    assert frame.tobytes() != other.tobytes()


def test_degrade_document_provenance_names_the_tiers_augmentations():
    tier = _tier()
    _, prov = degrade_document(_page(), tier, seed=7)
    assert prov["tier"] == tier.name
    assert prov["augmentations"] == ["InkBleed", "LightingGradient"]


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_tier_seed_is_stable_and_distinct_per_tier():
    assert tier_seed(9821, 0) == tier_seed(9821, 0)
    assert tier_seed(9821, 0) != tier_seed(9821, 1)
    assert tier_seed(9821, 1) != tier_seed(9822, 1)


def test_degrade_document_is_deterministic():
    page = _page()
    first, first_prov = degrade_document(page, _tier(), seed=tier_seed(4242, 1))
    second, second_prov = degrade_document(page, _tier(), seed=tier_seed(4242, 1))
    assert first.tobytes() == second.tobytes()
    assert first_prov == second_prov, "same seed must report the same drawn values"


def test_tiers_differ_from_each_other():
    page = _page()
    a, _ = degrade_document(page, _tier("moderate", "moderate"), seed=tier_seed(4242, 0))
    b, _ = degrade_document(page, _tier("heavy", "heavy"), seed=tier_seed(4242, 1))
    assert a.tobytes() != b.tobytes()


def test_degrade_document_returns_rgb():
    frame, _ = degrade_document(_page(), _tier(), seed=1)
    assert frame.mode == "RGB"


# --------------------------------------------------------------------------
# The clean composite
# --------------------------------------------------------------------------


def test_compose_clean_frames_the_page_without_distorting_it():
    """Clean means "photographed but undamaged": same desk background, no
    geometry. Without the background the corpus lets a model separate clean
    from degraded without reading the document at all."""
    page = _page()
    frame, prov = compose_clean(page, FLAT, seed=5)
    assert frame.mode == "RGB"
    assert frame.width > page.width and frame.height > page.height
    assert prov["rotation_deg"] == 0.0
    assert prov["foreshorten"] == 0.0


def test_compose_clean_reports_no_defect_bearing_values():
    _, prov = compose_clean(_page(), FLAT, seed=5)
    assert prov["tier"] == "clean"
    assert prov["augmentations"] == []
    assert prov["blur_sigma"] == 0.0
    assert prov["noise_sigma"] == 0.0


def test_clean_provenance_carries_the_same_keys_as_a_degraded_one():
    """Both are labelled by one code path, so a missing key would raise mid-run
    on whichever half rendered second."""
    _, clean = compose_clean(_page(), FLAT, seed=5)
    _, degraded = degrade_document(_page(), _tier(), seed=5)
    assert set(clean) == set(degraded)


def test_compose_clean_leaves_the_document_legible():
    """The dark bar drawn on the page must survive unblurred: if the clean
    copy picked up photometrics, it is no longer the negative class."""
    frame, _ = compose_clean(_page(), FLAT, seed=5)
    darkest = min(frame.convert("L").getdata())
    assert darkest < 40, "the printed bar is gone or washed out on a clean render"
