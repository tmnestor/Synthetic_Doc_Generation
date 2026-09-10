"""Collage plates: several receipts, one camera.

The image-quality screen asks whether a picture holds one document or several.
These build the images that answer is scored against, so what matters here is
not that a plate looks pretty but that:

  * every receipt actually lands on it -- a receipt clipped away silently makes
    a two-document plate a one-document plate while the label still says two;
  * the plate is TRANSPARENT where there is no paper, because that is what lets
    the single-page camera supply the desk and one perspective;
  * the provenance records what was DRAWN, since the ground-truth label is
    derived from it rather than from the config range.
"""

import numpy as np
import pytest
from PIL import Image

from conftest import assert_diagnostic_error
from generators.degradation.collage import ARRANGEMENTS, compose_collage

ROTATION = (-15.0, 15.0)


def receipts(*heights, width=240):
    """Stand-in receipts: tall narrow strips of differing length."""
    return [Image.new("RGB", (width, h), "white") for h in heights]


def compose(pages, arrangement="side_by_side", overlap=0.0, seed=7):
    return compose_collage(
        pages,
        arrangement=arrangement,
        overlap_fraction=overlap,
        rotation_deg=ROTATION,
        rng=np.random.default_rng(seed),
    )


class TestThePlate:
    @pytest.mark.parametrize("arrangement", ARRANGEMENTS)
    def test_every_arrangement_produces_a_transparent_plate(self, arrangement):
        plate, _ = compose(receipts(600, 900, 450), arrangement=arrangement, overlap=0.3)

        assert plate.mode == "RGBA"
        alpha = np.array(plate)[:, :, 3]
        assert (alpha == 0).any(), "no transparent background: the camera has no desk to show"
        assert (alpha > 0).any(), "no opaque region: no receipts landed"

    @pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
    def test_the_plate_holds_as_much_paper_as_it_was_given(self, count):
        """The failure this guards: a receipt placed off-canvas is invisible,
        and the plate is then labelled MULTIPLE while showing one document."""
        pages = receipts(*([700] * count))
        plate, provenance = compose(pages, arrangement="grid")

        opaque = (np.array(plate)[:, :, 3] > 0).sum()
        one_receipt = 240 * 700
        # Rotation costs some area to interpolation at the edges; well under
        # half a receipt of slack, so a missing page cannot hide in it.
        assert opaque > one_receipt * count * 0.6
        assert provenance["document_count"] == count

    def test_a_single_page_still_works(self):
        """Not a collage, but the boundary. It must not crash or need a
        special case at the call site."""
        plate, provenance = compose(receipts(800))

        assert provenance["document_count"] == 1
        assert (np.array(plate)[:, :, 3] > 0).any()


class TestArrangementsDiffer:
    def test_overlapping_is_not_piled(self):
        """They were the same code path once. Two config names for one
        behaviour is a choice the operator does not actually have."""
        pages = receipts(600, 900, 450)
        over, _ = compose(pages, arrangement="overlapping", overlap=0.4)
        piled, _ = compose(pages, arrangement="piled", overlap=0.4)

        assert np.array(over).tobytes() != np.array(piled).tobytes()

    def test_piled_is_tighter_than_overlapping(self):
        pages = receipts(600, 900, 450)
        over, _ = compose(pages, arrangement="overlapping", overlap=0.4)
        piled, _ = compose(pages, arrangement="piled", overlap=0.4)

        assert piled.width * piled.height < over.width * over.height

    def test_side_by_side_is_one_row(self):
        plate, _ = compose(receipts(700, 700, 700), arrangement="side_by_side")

        assert plate.width > plate.height, "three receipts in a row should be wide"

    def test_more_overlap_makes_a_smaller_plate(self):
        pages = receipts(700, 700, 700)
        loose, _ = compose(pages, arrangement="overlapping", overlap=0.0)
        tight, _ = compose(pages, arrangement="overlapping", overlap=0.6)

        assert tight.width < loose.width


class TestProvenance:
    def test_it_records_what_was_drawn_not_what_was_asked(self):
        """`piled` deepens the overlap it is given. The label must reflect the
        plate that exists, not the config range that permitted it."""
        _, provenance = compose(receipts(600, 600), arrangement="piled", overlap=0.4)

        assert provenance["overlap_requested"] == 0.4
        assert provenance["overlap_fraction"] > 0.4

    def test_every_placement_is_recorded(self):
        _, provenance = compose(receipts(600, 900, 450), arrangement="grid")

        assert len(provenance["placements"]) == 3
        for placement in provenance["placements"]:
            assert set(placement) == {"left", "top", "width", "height", "rotation_deg"}

    def test_receipts_are_rotated_independently(self):
        """A plate where every receipt is turned by the same angle looks like
        one rotated document, not several."""
        _, provenance = compose(receipts(*([700] * 5)), arrangement="grid")

        angles = [p["rotation_deg"] for p in provenance["placements"]]
        assert len(set(angles)) > 1

    def test_the_recorded_angle_is_the_angle_actually_applied(self):
        """The angle was drawn TWICE -- once to rotate, once to report -- so
        the provenance carried angles that had been applied to nothing. The
        test above did not catch it, because the reported angles still differed
        from each other; only comparing them to the pixels does.

        A page rotated by t with expand=True grows to
        w|cos t| + h|sin t| by w|sin t| + h|cos t|, so the recorded angle
        predicts the recorded size. If they were drawn separately they will not
        agree.
        """
        _, provenance = compose(receipts(*([700] * 4)), arrangement="grid")

        for placement in provenance["placements"]:
            radians = np.deg2rad(placement["rotation_deg"])
            cos, sin = abs(np.cos(radians)), abs(np.sin(radians))
            expected_w = 240 * cos + 700 * sin
            expected_h = 240 * sin + 700 * cos
            assert abs(placement["width"] - expected_w) <= 2, (
                f"recorded angle {placement['rotation_deg']:.2f} predicts width "
                f"{expected_w:.0f}, but the page is {placement['width']}"
            )
            assert abs(placement["height"] - expected_h) <= 2

    def test_the_same_seed_gives_the_same_plate(self):
        """Regeneration has to be reproducible, or a disputed label cannot be
        re-examined."""
        first, prov_a = compose(receipts(600, 900), seed=42)
        second, prov_b = compose(receipts(600, 900), seed=42)

        assert np.array(first).tobytes() == np.array(second).tobytes()
        assert prov_a == prov_b


class TestRejections:
    def test_no_pages_is_a_diagnostic_error(self):
        with pytest.raises(ValueError) as exc_info:
            compose([])

        assert_diagnostic_error(str(exc_info.value))

    def test_an_unknown_arrangement_names_the_valid_ones(self):
        with pytest.raises(ValueError) as exc_info:
            compose(receipts(600), arrangement="scattered")

        message = str(exc_info.value)
        assert_diagnostic_error(message)
        assert "side_by_side" in message


class TestFoldedReceipt:
    """One receipt that looks like two -- the hard negative that decides
    whether measuring COMPOSITION is worth anything.

    A four-up grid is an obvious MULTIPLE and scoring 1.0 on it proves nothing.
    A folded supermarket receipt is a genuine SINGLE that reads as two pieces
    of paper, it happens constantly, and it is what a naive detector gets
    wrong.
    """

    def fold(self, position=0.45, angle=6.0, seed=3, height=1400):
        from generators.degradation.collage import compose_folded

        page = Image.new("RGB", (240, height), "white")
        return compose_folded(
            page, fold_position=position, fold_angle_deg=angle, rng=np.random.default_rng(seed)
        )

    def test_it_is_one_document(self):
        """The label falls out of this. Getting it wrong makes the corpus teach
        the opposite of what it is for."""
        _, provenance = self.fold()

        assert provenance["document_count"] == 1

    def test_the_halves_are_joined_at_the_crease(self):
        """The bug this replaced: the far half was rotated about its own centre,
        which swung its top edge away from the fold and left a transparent gap.
        That renders as two separate receipts lying near each other -- a
        MULTIPLE, labelled SINGLE, which is the worst error this corpus could
        contain. Nothing in the provenance showed it; only the pixels do.
        """
        for angle in (-12.0, -6.0, 0.0, 6.0, 12.0):
            plate, _ = self.fold(angle=angle)
            opaque_rows = np.where((np.array(plate)[:, :, 3] > 0).any(axis=1))[0]

            spanned = np.arange(opaque_rows.min(), opaque_rows.max() + 1)
            missing = set(spanned.tolist()) - set(opaque_rows.tolist())
            assert not missing, (
                f"at {angle} degrees the fold leaves {len(missing)} blank row(s) "
                f"between the halves, so it reads as two receipts"
            )

    def test_the_far_half_is_shaded(self):
        """A fold shows as a tonal step, because the two halves lie at
        different angles to the light. Without it the crease reads as a cut."""
        _, provenance = self.fold()

        assert 0.8 <= provenance["fold"]["far_half_shade"] < 1.0

    def test_the_provenance_records_the_fold_that_was_drawn(self):
        _, provenance = self.fold(position=0.62, angle=-9.0)

        assert provenance["fold"]["position"] == 0.62
        assert provenance["fold"]["angle_deg"] == -9.0
        assert provenance["arrangement"] == "folded"

    def test_it_reads_like_a_collage_to_the_caller(self):
        """Same provenance shape as compose_collage, so the render pass can
        treat both alike and the label falls out of document_count."""
        _, folded = self.fold()
        _, collaged = compose(receipts(600, 900))

        assert set(folded) >= set(collaged)

    @pytest.mark.parametrize("position", [0.0, 0.04, 0.96, 1.0])
    def test_a_fold_outside_the_page_is_refused(self, position):
        with pytest.raises(ValueError) as exc_info:
            self.fold(position=position)

        assert_diagnostic_error(str(exc_info.value))


def test_the_plate_survives_the_single_page_camera():
    """The whole design rests on this: a collage is handed to the SAME
    warp_to_photo a single page uses, so it gets one perspective and one desk,
    and the drop shadow falls under each receipt from the alpha channel without
    that function knowing there is more than one document."""
    from generators.degradation.camera import warp_to_photo

    plate, _ = compose(receipts(600, 900, 450), arrangement="overlapping", overlap=0.3)
    warp = {"foreshorten": [0.05, 0.12], "rotation_deg": [-6, 6], "margin": [0.10, 0.18]}

    frame, provenance = warp_to_photo(plate, warp, np.random.default_rng(1))

    assert frame.mode == "RGB", "the camera returns a finished photograph"
    assert frame.size > plate.size, "the desk is larger than the plate"
    # Desk pixels in the corner, not transparent black: the background arrived.
    corner = np.array(frame)[:8, :8]
    assert corner.mean() > 60
    assert {"foreshorten", "rotation_deg", "foreshortened_edge"} <= set(provenance)
