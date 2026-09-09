"""Unit tests for generators/degradation/labels.py.

No rendering happens here. Every case builds a provenance dict by hand, so the
whole file runs in milliseconds -- which matters, because these are the paths
where a wrong answer is silent: a mislabelled image does not crash, it just
scores a correct model answer as wrong.

The boundary cases are the point. A threshold rule is the only thing standing
between "the tier could have tilted this image" and "this image is tilted", so
the value exactly on the threshold, just under it, and just over it all get an
explicit test.
"""

from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error

from generators.degradation.labels import DefectLabelError, defects_for, load_defect_labels

CONFIG = Path("config/generation_config.yml")


def provenance(**overrides):
    """A degraded image's provenance, with defect-free defaults."""
    base = {
        "tier": "moderate",
        "augmentations": [],
        "foreshorten": 0.0,
        "rotation_deg": 0.0,
        "foreshortened_edge": "top",
        "blur_sigma": 0.0,
        "noise_sigma": 0.0,
        "jpeg_quality": 100,
    }
    return {**base, **overrides}


def write_config(tmp_path, rules, filename="quality_ground_truth.jsonl"):
    """Write a minimal config carrying just the defect_labels block."""
    path = tmp_path / "generation_config.yml"
    path.write_text(
        yaml.safe_dump({"document_degradation": {"defect_labels": {"rules": rules, "filename": filename}}})
    )
    return path


# --------------------------------------------------------------------------
# Threshold boundaries
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("drawn", "expected"),
    [(0.59, False), (0.60, True), (0.61, True)],
    ids=["just under", "exactly on", "just over"],
)
def test_at_least_is_inclusive_at_the_threshold(drawn, expected):
    rules = {"blur": {"drawn": "blur_sigma", "at_least": 0.60}}
    assert defects_for(provenance(blur_sigma=drawn), rules)["blur"] is expected


@pytest.mark.parametrize(
    ("drawn", "expected"),
    [(69, True), (70, True), (71, False)],
    ids=["under", "exactly on", "over"],
)
def test_at_most_is_inclusive_at_the_threshold(drawn, expected):
    """jpeg_quality runs the other way: lower quality means more blocking."""
    rules = {"speckle": {"drawn": "jpeg_quality", "at_most": 70}}
    assert defects_for(provenance(jpeg_quality=drawn), rules)["speckle"] is expected


@pytest.mark.parametrize("degrees", [-9.0, 9.0])
def test_rotation_is_compared_on_magnitude_not_sign(degrees):
    """Which way the page leans is not something any question asks about."""
    rules = {"tilt": {"drawn": "rotation_deg_abs", "at_least": 5.0}}
    assert defects_for(provenance(rotation_deg=degrees), rules)["tilt"] is True


def test_a_tier_that_allows_a_defect_does_not_by_itself_label_one():
    """The whole reason provenance is recorded.

    A heavy-tier image drawing 3.9 degrees from a [-14, 14] range is not a
    tilted document, and labelling it one would mark a correct model answer
    wrong.
    """
    rules = {"tilt": {"drawn": "rotation_deg_abs", "at_least": 5.0}}
    heavy_but_straight = provenance(tier="heavy", rotation_deg=3.9)
    assert defects_for(heavy_but_straight, rules)["tilt"] is False


# --------------------------------------------------------------------------
# Categorical and compound rules
# --------------------------------------------------------------------------


def test_augmentation_rule_reads_the_tiers_phase_list():
    rules = {"crease": {"augmentation": "Folding"}}
    assert defects_for(provenance(augmentations=["Folding"]), rules)["crease"] is True
    assert defects_for(provenance(augmentations=["InkBleed"]), rules)["crease"] is False


def test_any_of_is_true_when_a_single_clause_is():
    rules = {
        "speckle": {
            "any_of": [
                {"drawn": "noise_sigma", "at_least": 3.0},
                {"drawn": "jpeg_quality", "at_most": 70},
            ]
        }
    }
    assert defects_for(provenance(noise_sigma=4.0), rules)["speckle"] is True
    assert defects_for(provenance(jpeg_quality=60), rules)["speckle"] is True
    assert defects_for(provenance(noise_sigma=1.0, jpeg_quality=95), rules)["speckle"] is False


def test_labels_keep_declaration_order():
    """The order the config declares is the order the record carries, so a
    diff of two ground-truth files stays readable."""
    rules = {
        "blur": {"drawn": "blur_sigma", "at_least": 0.6},
        "shadow": {"augmentation": "ShadowCast"},
        "crease": {"augmentation": "Folding"},
    }
    assert list(defects_for(provenance(), rules)) == ["blur", "shadow", "crease"]


# --------------------------------------------------------------------------
# Fail-fast paths
# --------------------------------------------------------------------------


def test_missing_block_is_diagnosed(tmp_path):
    path = tmp_path / "generation_config.yml"
    path.write_text(yaml.safe_dump({"document_degradation": {"tiers": []}}))
    with pytest.raises(DefectLabelError) as exc_info:
        load_defect_labels(path)
    assert_diagnostic_error(str(exc_info.value))


def test_empty_rules_are_diagnosed(tmp_path):
    with pytest.raises(DefectLabelError) as exc_info:
        load_defect_labels(write_config(tmp_path, {}))
    assert_diagnostic_error(str(exc_info.value))


def test_missing_filename_is_diagnosed(tmp_path):
    path = tmp_path / "generation_config.yml"
    path.write_text(
        yaml.safe_dump(
            {"document_degradation": {"defect_labels": {"rules": {"blur": {"augmentation": "X"}}}}}
        )
    )
    with pytest.raises(DefectLabelError) as exc_info:
        load_defect_labels(path)
    assert_diagnostic_error(str(exc_info.value))


def test_a_threshold_rule_without_a_threshold_is_diagnosed(tmp_path):
    """`drawn:` with nothing to compare against would quietly never fire."""
    rules = {"blur": {"drawn": "blur_sigma"}}
    with pytest.raises(DefectLabelError) as exc_info:
        load_defect_labels(write_config(tmp_path, rules))
    message = str(exc_info.value)
    assert_diagnostic_error(message)
    assert "blur_sigma" in message


def test_a_rule_naming_no_known_form_is_diagnosed(tmp_path):
    rules = {"blur": {"whenever": "it looks bad"}}
    with pytest.raises(DefectLabelError) as exc_info:
        load_defect_labels(write_config(tmp_path, rules))
    assert_diagnostic_error(str(exc_info.value))


def test_an_empty_any_of_is_diagnosed(tmp_path):
    with pytest.raises(DefectLabelError) as exc_info:
        load_defect_labels(write_config(tmp_path, {"speckle": {"any_of": []}}))
    assert_diagnostic_error(str(exc_info.value))


def test_a_rule_reading_an_unrecorded_value_is_diagnosed():
    """A config/generator mismatch must name the gap, not label everything false."""
    rules = {"glare": {"drawn": "glare_intensity", "at_least": 0.5}}
    with pytest.raises(DefectLabelError) as exc_info:
        defects_for(provenance(), rules)
    message = str(exc_info.value)
    assert_diagnostic_error(message)
    assert "glare_intensity" in message, "the error must name the value that is missing"


# --------------------------------------------------------------------------
# Against the real config
# --------------------------------------------------------------------------


def test_the_shipped_config_loads_and_labels_a_clean_provenance_false():
    rules, filename = load_defect_labels(CONFIG)
    assert filename.endswith(".jsonl")
    clean = provenance(tier="clean", augmentations=[])
    assert not any(defects_for(clean, rules).values())


def test_every_shipped_rule_is_decidable_from_recorded_provenance():
    """Guards the seam between camera.py's provenance and the config's rules:
    add a rule reading a value nobody records and this fails immediately."""
    rules, _ = load_defect_labels(CONFIG)
    defects_for(provenance(), rules)
