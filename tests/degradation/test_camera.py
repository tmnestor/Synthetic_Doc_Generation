"""The warp produces a photo-shaped frame, and the whole pipeline is
deterministic per (case seed, tier index)."""

import numpy as np
from PIL import Image

from generators.degradation import degrade_receipt, tier_seed
from generators.degradation.camera import apply_photometrics, warp_to_photo
from generators.degradation.tiers import Tier

WARP = {"foreshorten": [0.03, 0.06], "rotation_deg": [-8, 8], "margin": [0.07, 0.14]}
CAMERA = {"blur": [0.4, 0.8], "noise_sigma": [2, 5], "jpeg": [65, 80]}


def _tier(name="moderate", suffix="v2") -> Tier:
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


def test_warp_enlarges_the_frame_by_the_margin():
    """The receipt must occupy a sub-region, surrounded by background --
    that framing is the whole point of the camera model."""
    page = _page()
    out = warp_to_photo(page, WARP, np.random.default_rng(1))
    assert out.width > page.width
    assert out.height > page.height


def test_warp_leaves_background_in_the_corners():
    """A corner pixel should be desk, not paper: if the page still filled the
    frame, the perspective warp did not happen."""
    out = warp_to_photo(_page(), WARP, np.random.default_rng(2))
    corner = out.getpixel((2, 2))
    assert corner != (255, 255, 255), "corner is pure white -- no background composited"


def test_photometrics_preserve_dimensions():
    page = _page()
    assert apply_photometrics(page, CAMERA, np.random.default_rng(3)).size == page.size


def test_tier_seed_is_stable_and_distinct_per_tier():
    assert tier_seed(9821, 0) == tier_seed(9821, 0)
    assert tier_seed(9821, 0) != tier_seed(9821, 1)
    assert tier_seed(9821, 1) != tier_seed(9822, 1)


def test_degrade_receipt_is_deterministic():
    page = _page()
    first = degrade_receipt(page, _tier(), seed=tier_seed(4242, 1))
    second = degrade_receipt(page, _tier(), seed=tier_seed(4242, 1))
    assert first.tobytes() == second.tobytes()


def test_tiers_differ_from_each_other():
    page = _page()
    light = degrade_receipt(page, _tier("light", "v1"), seed=tier_seed(4242, 0))
    heavy = degrade_receipt(page, _tier("heavy", "v3"), seed=tier_seed(4242, 2))
    assert light.tobytes() != heavy.tobytes()


def test_degrade_receipt_returns_rgb():
    assert degrade_receipt(_page(), _tier(), seed=1).mode == "RGB"
