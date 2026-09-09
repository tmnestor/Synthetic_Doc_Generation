"""Document degradation: Augraphy paper damage, then a camera-scan warp.

Receipts and invoices are both degraded. An earlier revision degraded receipts
only, reasoning that they are the only type users photograph; that is no longer
the scope, because the quality screen must judge a photographed invoice as
readily as a photographed receipt, and scanned invoices arrive creased,
shadowed and skewed too. Which types are degraded is declared in
`eval_set.degrade_types:` -- this package degrades whatever it is handed.

Ordering is load-bearing. Augraphy's ink and paper phases run on the flat page,
before the warp, because a crease belongs to the paper and must be warped *with*
it; painting one flat across an already-tilted photo would read as a defect in
the image rather than in the document. Blur, sensor noise and JPEG blocking run
after, because they are artefacts of the camera and the file.

Every entry point returns provenance alongside the image: the values actually
drawn for that image, which is what the quality-screen ground truth is derived
from. A tier's declared range says what *could* happen; only the drawn value
says what did.
"""

import numpy as np
from PIL import Image

from generators.degradation.augment import AugmentationError, apply_augraphy
from generators.degradation.camera import apply_photometrics, warp_to_photo
from generators.degradation.tiers import Tier, TierConfigError, load_tiers

__all__ = [
    "AugmentationError",
    "Tier",
    "TierConfigError",
    "compose_clean",
    "degrade_document",
    "load_tiers",
    "tier_seed",
]

# Multiplier spacing each tier's seed far apart in the generator's sequence, so
# tier 0 and tier 1 of the same case share no draws.
_TIER_STRIDE = 100_003  # prime, to avoid collisions with round case seeds

# Stands in for JPEG quality on an image that was never JPEG-encoded. The clean
# copy is written as PNG, so it has no blocking artefacts at all; 100 keeps the
# provenance shape uniform and reads as "no compression" against any threshold.
_NO_JPEG = 100


def tier_seed(base_seed: int, tier_index: int) -> int:
    """Derive a tier's seed from the case seed and the tier's position.

    Args:
        base_seed: The ground-truth entry's `degradation_seed`.
        tier_index: The tier's index in the declared list.

    Returns:
        A seed unique to this (case, tier) pair and stable across runs.
    """
    return base_seed * _TIER_STRIDE + tier_index


def degrade_document(image: Image.Image, tier: Tier, seed: int) -> tuple[Image.Image, dict]:
    """Degrade one clean render to one tier's severity.

    Args:
        image: The clean rendered document.
        tier: The severity tier to apply.
        seed: Seed for this (case, tier) pair -- see `tier_seed`.

    Returns:
        A (frame, provenance) pair. The frame is an RGB image of the document
        as photographed on a desk. The provenance carries every value drawn for
        this image plus the names of the augmentations its tier declared, which
        together decide its quality-screen labels.

    Raises:
        AugmentationError: The tier names an unregistered augmentation.
    """
    augmented = apply_augraphy(image, tier, seed)
    rng = np.random.default_rng(seed)
    warped, warp_provenance = warp_to_photo(augmented, tier.warp, rng)
    frame, camera_provenance = apply_photometrics(warped, tier.camera, rng)
    provenance = {
        "tier": tier.name,
        "augmentations": [spec["augmentation"] for spec in (*tier.ink, *tier.paper)],
        **warp_provenance,
        **camera_provenance,
    }
    return frame, provenance


def compose_clean(image: Image.Image, clean_warp: dict, seed: int) -> tuple[Image.Image, dict]:
    """Composite an undegraded render onto the same desk background.

    A clean image that is a bare white page, when every degraded image is a page
    on a desk, lets a model separate the two on background alone -- scoring well
    without ever looking at the document. Running the clean copy through the same
    camera compositing removes that shortcut: clean then means "photographed but
    undamaged" rather than "not photographed".

    No ink or paper phase and no photometrics run here. Those are the defects.

    Args:
        image: The clean rendered document.
        clean_warp: `document_degradation.clean_camera.warp` -- zero rotation
            and zero foreshortening, with a non-zero margin so the page sits in
            a frame rather than filling it.
        seed: The case's degradation seed.

    Returns:
        A (frame, provenance) pair, the provenance carrying the same keys a
        degraded image's does so both can be labelled by one code path. Every
        defect-bearing value is zero, and the augmentation list is empty.
    """
    rng = np.random.default_rng(seed)
    frame, warp_provenance = warp_to_photo(image.convert("RGB"), clean_warp, rng)
    provenance = {
        "tier": "clean",
        "augmentations": [],
        **warp_provenance,
        "blur_sigma": 0.0,
        "noise_sigma": 0.0,
        "jpeg_quality": _NO_JPEG,
    }
    return frame, provenance
