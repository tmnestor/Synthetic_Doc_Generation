"""Registry and runner for the Augraphy phase pipeline.

Only the augmentations this project actually declares are registered. An
allow-list rather than a passthrough to Augraphy's whole catalogue is
deliberate: it turns a YAML typo into a startup diagnostic naming the valid
options, and it documents which of Augraphy's ~30 effects were chosen and why
the rest were not (see the exclusions in config/generation_config.yml).
"""

import contextlib
import tempfile
from collections.abc import Callable

import numpy as np
from PIL import Image

from generators.degradation.tiers import Tier

try:
    from augraphy import (
        AugraphyPipeline,
        Folding,
        InkBleed,
        LightingGradient,
        LowInkRandomLines,
        ShadowCast,
    )
except ImportError as err:  # pragma: no cover - environment failure, not logic
    raise ImportError(
        "Augraphy is not installed.\n"
        f"  What:     document degradation needs augraphy, which failed to import: {err}.\n"
        "  Where:    environment.yml -> dependencies.pip\n"
        "  Expected: augraphy==8.2.6 installed WITHOUT its declared dependencies, "
        "since it requires `opencv-python` (the full GUI build) which would displace "
        "the pinned opencv-python-headless. numpy must also be <=2.4, the ceiling "
        "numba imposes.\n"
        "  Recover:  conda env update -n synthetic -f environment.yml --prune, then "
        "`pip uninstall -y opencv-python && pip install --no-deps augraphy==8.2.6` "
        "if the full opencv was pulled in."
    ) from err

# YAML name -> Augraphy class. Deliberately excludes DirtyRollers and
# BadPhotoCopy (photocopier damage, not phone photography) and every geometric
# augmentation (camera.py owns geometry).
#
# LowInkRandomLines is what makes the quality screen's FADED criterion real.
# InkBleed was standing in for it, but InkBleed spreads and darkens ink -- that
# is smudging, and labelling it "faded" made the ground truth describe
# something the images did not show. LowInkRandomLines drops patchy horizontal
# bands out of the print, which is what a failing thermal printer produces and
# what "faded or patchy" actually means.
AUGMENTATIONS: dict[str, Callable[..., object]] = {
    "InkBleed": InkBleed,
    "LightingGradient": LightingGradient,
    "LowInkRandomLines": LowInkRandomLines,
    "ShadowCast": ShadowCast,
    "Folding": Folding,
}

# YAML key -> the constructor keyword each Augraphy class expects. The YAML
# uses short, readable names; Augraphy's own parameter names are longer and
# inconsistent between classes. Verified against augraphy 8.2.6 -- if the pin
# ever moves, re-check with:
#   inspect.signature(InkBleed.__init__).parameters
_PARAM_NAMES: dict[str, dict[str, str]] = {
    "InkBleed": {"intensity": "intensity_range", "kernel": "kernel_size"},
    "LightingGradient": {"max_brightness": "max_brightness", "direction": "direction"},
    "LowInkRandomLines": {"count": "count_range", "consistent": "use_consistent_lines"},
    "ShadowCast": {"side": "shadow_side", "opacity": "shadow_opacity_range"},
    # gradient_width is how wide the fold zone is, as a fraction of page width.
    # At Augraphy's default (0.1, 0.2) the crease is a narrow band of fine
    # speckle, and the heavy tier's camera -- blur up to 1.3, noise sigma up to
    # 8, JPEG down to 50 -- erases exactly that fine detail. The fold was being
    # drawn and then destroyed, which is why the screen's CREASE recall of 0.07
    # was correct perception of something no longer there. Widening the zone
    # gives the camera something coarse enough to survive it.
    #
    # gradient_height, the fold's depth, is deliberately NOT exposed. Augraphy
    # implements depth geometrically: past about 0.3 it tears the page open and
    # fills the gap with backdrop_color, which on a receipt wipes out the whole
    # amounts column. That fails the standard every tier here is held to --
    # hard to read, never impossible -- so the knob is not offered.
    "Folding": {
        "fold_count": "fold_count",
        "fold_noise": "fold_noise",
        "gradient_width": "gradient_width",
    },
}

# InkBleed wants a (w, h) kernel; the YAML declares a single int, since a
# non-square ink-bleed kernel has no physical meaning.
_SQUARE_KERNEL_KEYS = frozenset({"kernel_size"})


class AugmentationError(RuntimeError):
    """Raised when a tier names an augmentation that is not registered."""


def _build(spec: dict, *, tier_name: str, phase: str) -> object:
    """Instantiate one augmentation from its YAML spec.

    Args:
        spec: The YAML mapping, carrying `augmentation:` plus its parameters.
        tier_name: Owning tier's name, for diagnostics.
        phase: "ink" or "paper", for diagnostics.

    Returns:
        The constructed Augraphy augmentation.

    Raises:
        AugmentationError: No `augmentation:` key, or an unregistered name.
    """
    name = spec.get("augmentation")
    if name is None:
        raise AugmentationError(
            "Invalid augmentation spec.\n"
            f"  What:     a {phase}-phase entry of tier '{tier_name}' has no "
            f"'augmentation:' key, so there is nothing to construct.\n"
            f"  Where:    config/generation_config.yml -> "
            f"document_degradation.tiers[{tier_name}].{phase}\n"
            f"  Expected: every entry to name one of {sorted(AUGMENTATIONS)}, e.g.\n"
            "              {augmentation: InkBleed, intensity: [0.05, 0.15], kernel: 3}\n"
            f"  Recover:  add an 'augmentation:' key to the {phase} entry."
        )

    factory = AUGMENTATIONS.get(str(name))
    if factory is None:
        raise AugmentationError(
            "Unknown augmentation.\n"
            f"  What:     tier '{tier_name}' names '{name}' in its {phase} phase, "
            f"which is not registered.\n"
            f"  Where:    config/generation_config.yml -> "
            f"document_degradation.tiers[{tier_name}].{phase}\n"
            f"  Expected: one of {sorted(AUGMENTATIONS)}.\n"
            "  Recover:  use a registered augmentation, or add the class to "
            "AUGMENTATIONS in generators/degradation/augment.py."
        )

    mapping = _PARAM_NAMES[str(name)]
    kwargs: dict[str, object] = {}
    for key, value in spec.items():
        if key == "augmentation":
            continue
        if key not in mapping:
            raise AugmentationError(
                "Unknown augmentation parameter.\n"
                f"  What:     tier '{tier_name}' passes '{key}' to {name}, which is not "
                f"mapped to any of its constructor arguments.\n"
                f"  Where:    config/generation_config.yml -> "
                f"document_degradation.tiers[{tier_name}].{phase}\n"
                f"  Expected: one of {sorted(mapping)}.\n"
                f"  Recover:  use a mapped parameter, or add '{key}' to _PARAM_NAMES['{name}'] "
                f"in generators/degradation/augment.py after checking the real argument name "
                f"with inspect.signature({name}.__init__).parameters."
            )
        param = mapping[key]
        if param in _SQUARE_KERNEL_KEYS:
            kwargs[param] = (int(value), int(value))
        elif isinstance(value, list):
            kwargs[param] = tuple(value)  # Augraphy wants tuples for its *_range params
        else:
            kwargs[param] = value
    return factory(**kwargs)


def apply_augraphy(image: Image.Image, tier: Tier, seed: int) -> Image.Image:
    """Apply a tier's ink and paper phases to the flat page.

    Runs before any warp: these model damage to the paper itself, which must
    then be warped *with* the page rather than painted across a tilted photo.

    Args:
        image: The clean, flat rendered page.
        tier: The severity tier supplying the phase specs.
        seed: Seed making this tier's output reproducible.

    Returns:
        The augmented page, at the same dimensions as the input.

    Raises:
        AugmentationError: A phase entry is malformed or names an unknown
            augmentation.
    """
    ink = [_build(spec, tier_name=tier.name, phase="ink") for spec in tier.ink]
    paper = [_build(spec, tier_name=tier.name, phase="paper") for spec in tier.paper]

    if not ink and not paper:
        return image.copy()

    pipeline = AugraphyPipeline(
        ink_phase=ink,
        paper_phase=paper,
        post_phase=[],
        save_outputs=False,
        log=False,
        random_seed=seed,
    )
    # Augraphy samples from NumPy's global RNG in places its own random_seed
    # does not reach, so both are set. This is the one spot where global random
    # state is unavoidable; it is contained here and covered by a byte-identity
    # test.
    np.random.seed(seed)

    # AugraphyPipeline.__call__ unconditionally writes its input into
    # `os.getcwd()/augraphy_cache/` -- a 30-file ring buffer, written whatever
    # `save_outputs` says, with no setting to disable or relocate it. Running
    # in a throwaway directory sends it somewhere harmless.
    #
    # This is containment, not tidiness. Augraphy's PageBorder, BleedThrough
    # and BookBinding *read* from that cache, so a pipeline including them
    # would composite whatever images the last run happened to leave behind --
    # output depending on directory state rather than on the seed. None of our
    # four registered augmentations read it, but pointing the cache at a fresh
    # empty directory each call makes that structurally true rather than
    # true-by-inspection.
    with tempfile.TemporaryDirectory() as cache_dir, contextlib.chdir(cache_dir):
        result = pipeline(np.array(image.convert("RGB")))
    return Image.fromarray(np.asarray(result, dtype=np.uint8), "RGB")
