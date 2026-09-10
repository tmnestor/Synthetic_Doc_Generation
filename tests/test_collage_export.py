"""The collage half of the eval-set export: config, labels, rotation.

The layout functions are covered in tests/degradation/test_collage.py. These
cover what sits between them and the corpus -- the config the operator writes,
the label the screen is scored against, and the one derived value that a plate
gets wrong if nobody thinks about it.

No rendering here. Everything below is a second, so it runs on every change
rather than only when someone rebuilds a corpus.
"""

from pathlib import Path

import pytest
import yaml

from conftest import assert_diagnostic_error
from generators.degradation.collage import ARRANGEMENTS
from generators.eval_set import _effective_rotation, _quality_record, load_eval_set_config

CONFIG = Path("config/generation_config.yml")

VALID_COLLAGE = {
    "enabled": True,
    "seed": 20260910,
    "count": 90,
    "documents_per_image": [2, 5],
    "arrangements": list(ARRANGEMENTS),
    "overlap_fraction": [0.0, 0.55],
    "per_document_rotation_deg": [-18, 18],
    "hard_negatives": {"folded_long_receipt": {"count": 30}},
}


def write_config(tmp_path, collage):
    """The shipped config with its collage block replaced."""
    data = yaml.safe_load(CONFIG.read_text())
    if collage is None:
        data["eval_set"].pop("collage", None)
    else:
        data["eval_set"]["collage"] = collage
    path = tmp_path / "generation_config.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


class TestShippedConfig:
    def test_the_committed_config_validates(self):
        cfg = load_eval_set_config(CONFIG)

        assert cfg["collage"]["enabled"] is True
        assert cfg["collage"]["seed"], "plates must regenerate identically"

    def test_the_seed_is_declared_in_yaml_not_defaulted_in_python(self):
        """A Python-side default would let the config look complete while the
        seed came from somewhere else, and a corpus nobody can regenerate is a
        corpus whose labels cannot be disputed."""
        cfg = load_eval_set_config(CONFIG)

        assert isinstance(cfg["collage"]["seed"], int)


class TestConfigRejections:
    def test_a_missing_block_is_refused(self, tmp_path):
        with pytest.raises(ValueError) as exc_info:
            load_eval_set_config(write_config(tmp_path, None))

        assert_diagnostic_error(str(exc_info.value))

    @pytest.mark.parametrize("key", sorted(VALID_COLLAGE))
    def test_every_key_is_required(self, tmp_path, key):
        """Required even when disabled, so turning collages back on is a
        one-word change rather than archaeology."""
        collage = {k: v for k, v in VALID_COLLAGE.items() if k != key}

        with pytest.raises(ValueError) as exc_info:
            load_eval_set_config(write_config(tmp_path, collage))

        message = str(exc_info.value)
        assert_diagnostic_error(message)
        assert key in message

    def test_an_unknown_arrangement_is_refused(self, tmp_path):
        collage = {**VALID_COLLAGE, "arrangements": ["side_by_side", "scattered"]}

        with pytest.raises(ValueError) as exc_info:
            load_eval_set_config(write_config(tmp_path, collage))

        message = str(exc_info.value)
        assert_diagnostic_error(message)
        assert "scattered" in message

    def test_a_single_document_plate_is_refused(self, tmp_path):
        """documents_per_image starting at 1 would label a one-receipt plate
        MULTIPLE -- teaching the screen the opposite of the truth."""
        collage = {**VALID_COLLAGE, "documents_per_image": [1, 4]}

        with pytest.raises(ValueError) as exc_info:
            load_eval_set_config(write_config(tmp_path, collage))

        assert_diagnostic_error(str(exc_info.value))

    def test_an_empty_range_is_refused(self, tmp_path):
        collage = {**VALID_COLLAGE, "documents_per_image": [5, 2]}

        with pytest.raises(ValueError) as exc_info:
            load_eval_set_config(write_config(tmp_path, collage))

        assert_diagnostic_error(str(exc_info.value))

    def test_dropping_the_folded_hard_negative_is_refused(self, tmp_path):
        """Without it every collage is an obvious MULTIPLE, the screen scores
        near 1.0, and the measurement means nothing. Worth failing the build
        over, because the resulting number LOOKS like a good result."""
        collage = {**VALID_COLLAGE, "hard_negatives": {"distractor_object": {"count": 10}}}

        with pytest.raises(ValueError) as exc_info:
            load_eval_set_config(write_config(tmp_path, collage))

        message = str(exc_info.value)
        assert_diagnostic_error(message)
        assert "folded_long_receipt" in message


class TestCompositionLabel:
    RULES = {}

    def record(self, provenance):
        return _quality_record(
            "x.png", "receipt", {"tier": "clean", "augmentations": [], **provenance}, self.RULES
        )

    def test_several_documents_are_multiple(self):
        assert self.record({"document_count": 3})["composition"] == "MULTIPLE"

    def test_one_document_is_single(self):
        assert self.record({"document_count": 1})["composition"] == "SINGLE"

    def test_an_ordinary_image_is_labelled_single_explicitly(self):
        """By VALUE, never by omission. Absent has to keep meaning 'this corpus
        predates the label', which is what makes the screen report NOT SCORED
        rather than a number -- so a corpus that HAS been labelled must say
        SINGLE out loud."""
        record = self.record({})

        assert record["composition"] == "SINGLE"
        assert "composition" in record

    def test_it_is_not_a_defect(self):
        """Composition answers a different question with a different remedy:
        split the image, not re-photograph it. Folding it into the defect rules
        is the conflation the screen's prompt already refuses."""
        record = self.record({"document_count": 4})

        assert "composition" not in record["defects"]


class TestEffectiveRotation:
    def test_a_single_document_reports_its_own_rotation(self):
        assert _effective_rotation({"rotation_deg": 7.5}) == 7.5

    def test_a_plate_reports_its_most_turned_receipt(self):
        """The tilt label is `rotation_deg_abs at_least 5.0`. A plate sitting
        square with its receipts at 15 degrees would otherwise record ~0 and be
        labelled tilt-free while every receipt in it is visibly crooked."""
        provenance = {
            "rotation_deg": 1.0,
            "placements": [
                {"rotation_deg": 2.0},
                {"rotation_deg": 15.0},
                {"rotation_deg": -4.0},
            ],
        }

        assert _effective_rotation(provenance) == 16.0

    def test_it_keeps_the_sign_of_the_largest_turn(self):
        provenance = {"rotation_deg": 0.0, "placements": [{"rotation_deg": -17.0}, {"rotation_deg": 3.0}]}

        assert _effective_rotation(provenance) == -17.0

    def test_plate_rotation_compounds_with_the_receipt_s_own(self):
        """Both turns are real and they add: a receipt at 10 degrees on a plate
        photographed at 10 degrees is 20 degrees off square in the image."""
        provenance = {"rotation_deg": 10.0, "placements": [{"rotation_deg": 10.0}]}

        assert _effective_rotation(provenance) == 20.0

    def test_no_placements_falls_back_rather_than_failing(self):
        assert _effective_rotation({"rotation_deg": 3.0, "placements": []}) == 3.0
