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

# Arrangements a taxpayer actually produces.
#
# All three keep every receipt readable, and that is the point. Someone
# photographing receipts is trying to SUBSTANTIATE an expense: they lay the
# receipts out so the business name, the date and the total can be seen. They
# do not stack them.
#
# A `piled` arrangement existed here and was removed. It buried the totals of
# the receipts underneath -- modelling a taxpayer working against their own
# interest, which is not a hard case, just a wrong one. `overlap_fraction` is
# capped low for the same reason: receipts placed close together touch at their
# margins, where a receipt carries "Thank you for shopping with us" rather than
# an amount.
ARRANGEMENTS = ("side_by_side", "grid", "overlapping")


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


def compose_folded(
    page: Image.Image,
    *,
    fold_position: float,
    fold_angle_deg: float,
    rng: np.random.Generator,
) -> tuple[Image.Image, dict]:
    """Fold one long receipt across itself, so it reads as two pieces of paper.

    This is the hard negative the whole exercise turns on. A four-up grid of
    receipts is an obvious MULTIPLE and scoring 1.0 on it proves nothing; a
    folded supermarket receipt is a genuine SINGLE that looks like two, it
    happens constantly, and it is what a naive detector gets wrong.

    Not a collage, despite living here: it produces ONE document. It lives
    beside `compose_collage` because the two exist for the same question and
    return the same provenance shape, so `_render_collages` can treat them
    alike and the label falls out of `document_count` either way.

    The fold is modelled the way a real one photographs: the far half is
    slightly darker, because it lies at a different angle to the light, and the
    crease is a hard edge rather than a blur. That darker band is the cue a
    detector is most likely to misread as a gap between two receipts, which is
    exactly what makes it worth rendering.

    Args:
        page: One rendered receipt, ideally a long one.
        fold_position: Where along the height to fold, 0.0-1.0. Around 0.5 is
            the classic in-half fold; further out gives the short flap that
            reads most convincingly as a second, smaller receipt.
        fold_angle_deg: How far the folded half is turned relative to the rest.
            Zero is a flat fold; a few degrees is a real one lying on a table.
        rng: Seeded generator.

    Returns:
        `(plate, provenance)` in `compose_collage`'s shape, with
        `document_count` of 1 and a `fold` block recording what was drawn.

    Raises:
        ValueError: `fold_position` is not strictly inside the page.
    """
    if not 0.05 < fold_position < 0.95:
        raise ValueError(
            f"fold_position {fold_position!r} is outside the page.\n"
            f"  What:        a fold at or beyond an edge produces no visible crease.\n"
            f"  Where:       eval_set.collage.hard_negatives, folded_long_receipt.\n"
            f"  Expected:    a fraction strictly between 0.05 and 0.95, e.g. 0.45.\n"
            f"  Recover:     move the fold inside the page."
        )

    page = page.convert("RGBA")
    width, height = page.size
    split = int(height * fold_position)

    near = page.crop((0, 0, width, split))
    far = page.crop((0, split, width, height))

    # The far half lies at a different angle to the light. Darkening it is what
    # makes the crease read as a fold rather than a cut.
    shade = float(rng.uniform(0.82, 0.93))
    far_pixels = np.array(far).astype(np.float32)
    far_pixels[:, :, :3] *= shade
    far = Image.fromarray(np.clip(far_pixels, 0, 255).astype(np.uint8), "RGBA")

    # Rotate the far half about the CREASE, not about its own centre.
    #
    # Centre-rotation swings the far half's top edge away from the fold and
    # leaves a gap, which renders as two separate receipts lying near each
    # other -- a MULTIPLE, labelled SINGLE. That is the worst possible mistake
    # here, because this image exists precisely to be a SINGLE that merely
    # LOOKS like two. Caught by looking at a render; nothing in the provenance
    # would have shown it.
    #
    # PIL rotates about the image centre and then expands, so the crease point
    # moves. Rather than trust a sign convention, track where it went: the
    # original top-centre is mapped through the same rotation and the paste is
    # offset to put it back on the fold line.
    far_w, far_h = far.size
    far = far.rotate(fold_angle_deg, resample=Image.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))

    radians = np.deg2rad(fold_angle_deg)
    cos, sin = np.cos(radians), np.sin(radians)
    # Crease point relative to the far half's centre, before rotation.
    vx, vy = 0.0, -far_h / 2.0
    crease_x = far.width / 2.0 + (vx * cos + vy * sin)
    crease_y = far.height / 2.0 + (-vx * sin + vy * cos)

    near_crease_x = width / 2.0
    plate_w = int(max(width, far.width) + abs(near_crease_x - crease_x) + 2)
    plate_h = int(split + far.height + 2)
    plate = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))

    near_left = int((plate_w - width) / 2)
    plate.paste(near, (near_left, 0), near)
    # Put the far half's crease point exactly where the near half's bottom edge
    # centre is, so the two halves meet along the fold.
    far_left = int(near_left + near_crease_x - crease_x)
    far_top = int(split - crease_y)
    plate.paste(far, (far_left, far_top), far)

    provenance = {
        "document_count": 1,
        "arrangement": "folded",
        "overlap_fraction": 0.0,
        "overlap_requested": 0.0,
        "fold": {
            "position": float(fold_position),
            "angle_deg": float(fold_angle_deg),
            "far_half_shade": shade,
        },
        "placements": [
            {"left": near_left, "top": 0, "width": width, "height": split, "rotation_deg": 0.0},
            {
                "left": far_left,
                "top": far_top,
                "width": far.width,
                "height": far.height,
                "rotation_deg": float(fold_angle_deg),
            },
        ],
    }
    return plate, provenance


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
            pages are drawn on top, so a later receipt covers an earlier one.
        arrangement: One of `ARRANGEMENTS`.
        overlap_fraction: How much of a slot neighbouring receipts may intrude
            into, 0.0 (clear gaps) up to the configured ceiling. Drawn per plate by
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
    # with a gap; at the configured ceiling they touch and intrude slightly
    # into one another's margins.
    #
    # The ceiling is deliberately low and enforced in config rather than here,
    # because "how much may a receipt cover its neighbour?" is a question about
    # the domain, not about layout. Past roughly a fifth, the receipt
    # underneath starts losing its total -- and a taxpayer photographing
    # receipts to substantiate a claim lays them out so the totals show.
    effective_overlap = overlap_fraction
    jitter = 0.08 if arrangement == "overlapping" else 0.03

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
        # Both recorded, because the LABEL must be derived from what was
        # actually used, never from the config range that permitted it.
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
