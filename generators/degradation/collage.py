"""Lay several receipts on one plate, for the image-quality screen's
COMPOSITION question.

Taxpayers photograph several receipts spread on a table in one shot, and
downstream extraction handles those badly. The screen asks whether a picture
holds one document or several; this builds the images that answer is scored
against.

WHAT THIS PRODUCES. One RGBA canvas with the receipts placed on a TRANSPARENT
background -- not a finished photograph. ``camera.warp_to_photo`` then takes
that canvas exactly as it takes a single page: it supplies the desk, applies
one perspective to the whole plate, and derives a drop shadow from the alpha,
so each receipt gets its own shadow without this module drawing one. One
camera, one perspective, which is what a photograph of a table is.

RECEIPTS ONLY. Invoices always arrive as full pages, one per photograph, so a
mixed plate is a case that does not occur and would only teach the screen
something it will never be asked.
"""

from dataclasses import dataclass

import numpy as np
from PIL import Image

# Arrangements, in the order a taxpayer is likely to produce them. `piled` is
# the hard one and `grid` the easy one; a set of only grids would score well
# and prove nothing.
ARRANGEMENTS = ("side_by_side", "grid", "overlapping", "piled")


@dataclass(frozen=True)
class Placement:
    """Where one receipt ended up, in plate coordinates."""

    left: int
    top: int
    width: int
    height: int
    rotation_deg: float


def _rotate_page(page: Image.Image, degrees: float) -> Image.Image:
    """Rotate a page about its centre, expanding the canvas to fit.

    `expand=True` keeps the corners, so a rotated receipt is not clipped into a
    square. The fill is transparent rather than white: white corners would read
    as paper and turn one rotated receipt into something that looks like two.
    """
    return page.convert("RGBA").rotate(degrees, resample=Image.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))


def _slot_grid(count: int) -> tuple[int, int]:
    """Columns and rows for *count* receipts, favouring a wide plate.

    Photographs of a table are landscape more often than not, and a 4-up plate
    reads more naturally as 2x2 than 1x4.
    """
    columns = int(np.ceil(np.sqrt(count)))
    rows = int(np.ceil(count / columns))
    return columns, rows


def compose_collage(
    pages: list[Image.Image],
    *,
    arrangement: str,
    overlap_fraction: float,
    rotation_deg: tuple[float, float],
    rng: np.random.Generator,
) -> tuple[Image.Image, dict]:
    """Place several receipts on one transparent plate.

    Args:
        pages: The rendered receipts, at least one. Order is z-order: later
            pages are drawn on top, which is what makes `piled` look piled.
        arrangement: One of `ARRANGEMENTS`.
        overlap_fraction: How much of a slot neighbouring receipts may intrude
            into, 0.0 (clear gaps) to ~0.7 (heavily piled). Drawn per plate by
            the caller, recorded here as what was actually used.
        rotation_deg: `(min, max)` for each receipt's own rotation. Per
            receipt, not per plate -- a plate where every receipt is turned by
            the same angle looks like one rotated document, not several.
        rng: Seeded generator. All randomness is drawn from it.

    Returns:
        `(plate, provenance)`. The plate is RGBA with transparent background,
        ready for `camera.warp_to_photo`. The provenance records
        `document_count`, the arrangement, the overlap actually drawn and every
        placement -- because the LABEL is derived from what was drawn, never
        from the config range. A range of [0.0, 0.7] can draw 0.02, and that is
        not an overlapping collage.

    Raises:
        ValueError: No pages, or an unknown arrangement.
    """
    if not pages:
        raise ValueError(
            "compose_collage needs at least one page.\n"
            "  What:        an empty page list was passed.\n"
            "  Where:       the caller building this plate.\n"
            "  Expected:    one or more rendered receipts.\n"
            "  Recover:     draw the documents before composing the plate."
        )
    if arrangement not in ARRANGEMENTS:
        raise ValueError(
            f"Unknown collage arrangement {arrangement!r}.\n"
            f"  What:        no layout is defined for that name.\n"
            f"  Where:       eval_set.collage.arrangements in generation_config.yml.\n"
            f"  Expected:    one of {list(ARRANGEMENTS)}.\n"
            f"  Recover:     correct the name, or add the arrangement here."
        )

    # Drawn ONCE, then used for both the rotation and the record. Drawing twice
    # -- once to rotate, once to report -- puts angles in the provenance that
    # were never applied to anything, which is the same failure as labelling an
    # image from the config range instead of the draw.
    angles = [float(rng.uniform(*rotation_deg)) for _ in pages]
    rotated = [_rotate_page(page, angle) for page, angle in zip(pages, angles, strict=True)]

    # Slot size from the largest receipt, so nothing is clipped by a neighbour's
    # slot. Receipts vary in length by a lot -- a short café receipt beside a
    # long supermarket one is a case worth having, not a problem to normalise
    # away.
    slot_w = max(page.width for page in rotated)
    slot_h = max(page.height for page in rotated)

    if arrangement == "side_by_side":
        columns, rows = len(rotated), 1
    else:
        columns, rows = _slot_grid(len(rotated))

    # Overlap pulls the slots together. At 0.0 the receipts sit in clean cells
    # with a gap; at 0.7 they intrude deep into each other.
    #
    # `piled` is not `overlapping` with a bigger number. A pile is receipts
    # pushed towards one another into a heap, so it takes the overlap it was
    # given and adds to it, and jitters hard enough that the underlying grid
    # stops being visible. Without that the two arrangements render identically
    # and the config offers a choice that does not exist.
    effective_overlap = overlap_fraction
    jitter = 0.03
    if arrangement == "overlapping":
        jitter = 0.08
    elif arrangement == "piled":
        effective_overlap = min(0.75, overlap_fraction + 0.25)
        jitter = 0.18

    step_x = int(slot_w * (1.0 - effective_overlap))
    step_y = int(slot_h * (1.0 - effective_overlap))

    plate_w = step_x * (columns - 1) + slot_w
    plate_h = step_y * (rows - 1) + slot_h
    plate = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))

    placements: list[Placement] = []
    for index, page in enumerate(rotated):
        column, row = index % columns, index // columns
        # Centre the receipt in its slot, then jitter, so a plate does not look
        # like a form with fields filled in.
        left = column * step_x + (slot_w - page.width) // 2
        top = row * step_y + (slot_h - page.height) // 2
        left += int(rng.uniform(-slot_w * jitter, slot_w * jitter))
        top += int(rng.uniform(-slot_h * jitter, slot_h * jitter))
        left = int(np.clip(left, 0, max(0, plate_w - page.width)))
        top = int(np.clip(top, 0, max(0, plate_h - page.height)))

        # `page` as its own mask: paste only where the receipt is opaque, so an
        # earlier receipt shows through a later one's transparent corners.
        plate.paste(page, (left, top), page)
        placements.append(Placement(left, top, page.width, page.height, angles[index]))

    provenance = {
        "document_count": len(pages),
        "arrangement": arrangement,
        # Both, because they differ for `piled` and the LABEL must be derived
        # from what was actually used, not from what was asked for.
        "overlap_fraction": float(effective_overlap),
        "overlap_requested": float(overlap_fraction),
        "placements": [
            {
                "left": p.left,
                "top": p.top,
                "width": p.width,
                "height": p.height,
                "rotation_deg": p.rotation_deg,
            }
            for p in placements
        ],
    }
    return plate, provenance
