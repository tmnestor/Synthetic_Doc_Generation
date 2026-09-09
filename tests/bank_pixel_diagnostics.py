"""Shared pixel-diff diagnostics for the bank pixel-snapshot net.

Used by both `test_bank_pixel_snapshot.py` (to explain a hash mismatch when
the permanent guard fails) and `regenerate_bank_pixel_snapshot.py` (to report,
before writing anything, exactly which cases a re-bless would change and
why). Factored out rather than duplicated so the two call sites can never
give a human two different explanations of the same mismatch.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

from generators.bank_statement import render_via_dsl


def overlapping_fields(
    geometry: dict, bbox_px: tuple[int, int, int, int], width: int, height: int
) -> list[str]:
    """Names of recorded fields whose normalised box intersects a pixel bbox."""
    left, top, right, bottom = (
        bbox_px[0] / width,
        bbox_px[1] / height,
        bbox_px[2] / width,
        bbox_px[3] / height,
    )
    hits = []
    for field, (fl, ft, fr, fb) in geometry.items():
        if fl < right and fr > left and ft < bottom and fb > top:
            hits.append(field)
    return sorted(hits)


def explain_hash_mismatch(
    key: str, layout_id: str, layout: dict, entry: dict, current: Image.Image, reference_dir: Path
) -> str:
    """Explain why `current`'s hash differs from what's on record for `key`.

    Diffs `current` against `reference_dir/{key}.png` and reports differing
    pixel count, bounding box, and any recorded field boxes the bbox
    overlaps — or explicitly says it overlaps none, which is the signature
    of a defect in chrome/rules/fills rather than a field's own rendering
    (e.g. the CBA stray-row-rule bug this net was built to catch).

    Falls back to a plain "no reference found" message when there is
    nothing to diff against (e.g. a ground-truth entry added since the last
    capture, or this is the very first capture).
    """
    ref_path = reference_dir / f"{key}.png"
    if not ref_path.exists():
        return f"{key}: no reference PNG at {ref_path} (new entry, or never captured)."

    reference = Image.open(ref_path).convert("RGB")
    current_rgb = current.convert("RGB")
    if current_rgb.size != reference.size:
        return f"{key}: page size changed, {reference.size} -> {current_rgb.size}."

    diff = ImageChops.difference(current_rgb, reference)
    bbox = diff.getbbox()
    if bbox is None:
        # Hash differs but pixels don't - only possible if tobytes() picked up
        # something outside the RGB plane (e.g. a mode/palette difference).
        return (
            f"{key}: sha256 changed but RGB pixel content is identical to the reference — check image mode."
        )

    diff_mask = np.array(diff).any(axis=-1)
    n_diff = int(diff_mask.sum())

    geometry_out: dict = {}
    render_via_dsl(entry, layout, layout_id, geometry_out=geometry_out)
    fields = overlapping_fields(geometry_out["boxes"], bbox, *current_rgb.size)
    field_note = (
        f"overlaps fields {fields}" if fields else "overlaps no recorded field (chrome/rule/fill region)"
    )

    return f"{key}: {n_diff} px differ, bbox={bbox} ({field_note}). Reference: {ref_path}"
