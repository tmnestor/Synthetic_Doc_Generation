"""Tier config loads from YAML only, and every omission fails with a diagnostic."""

from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error

from generators.degradation.tiers import Tier, TierConfigError, load_tiers

VALID_TIER = {
    "name": "light",
    "suffix": "v1",
    "ink": [{"augmentation": "InkBleed", "intensity": [0.05, 0.15], "kernel": 3}],
    "paper": [{"augmentation": "LightingGradient", "max_brightness": 255, "direction": 90}],
    "warp": {"foreshorten": [0.01, 0.03], "rotation_deg": [-3, 3], "margin": [0.05, 0.10]},
    "camera": {"blur": [0.2, 0.5], "noise_sigma": [1, 3], "jpeg": [85, 95]},
}


def _write(tmp_path: Path, block: object) -> Path:
    path = tmp_path / "generation_config.yml"
    path.write_text(yaml.safe_dump({"receipt_degradation": block}))
    return path


def test_loads_the_real_project_config():
    tiers = load_tiers(Path("config/generation_config.yml"))
    assert [t.name for t in tiers] == ["light", "moderate", "heavy"]
    assert [t.suffix for t in tiers] == ["v1", "v2", "v3"]
    assert all(isinstance(t, Tier) for t in tiers)


def test_missing_block_is_a_diagnostic(tmp_path):
    path = tmp_path / "generation_config.yml"
    path.write_text(yaml.safe_dump({"output_dir": "output"}))
    with pytest.raises(TierConfigError) as exc:
        load_tiers(path)
    assert_diagnostic_error(str(exc.value))
    assert "receipt_degradation" in str(exc.value)


def test_empty_tier_list_is_a_diagnostic(tmp_path):
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, {"tiers": []}))
    assert_diagnostic_error(str(exc.value))


@pytest.mark.parametrize("missing", ["name", "suffix", "ink", "paper", "warp", "camera"])
def test_missing_tier_key_is_a_diagnostic(tmp_path, missing):
    tier = {k: v for k, v in VALID_TIER.items() if k != missing}
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, {"tiers": [tier]}))
    assert_diagnostic_error(str(exc.value))
    assert missing in str(exc.value)


def test_duplicate_suffix_is_a_diagnostic(tmp_path):
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, {"tiers": [VALID_TIER, dict(VALID_TIER, name="other")]}))
    assert_diagnostic_error(str(exc.value))
    assert "v1" in str(exc.value)


def test_tier_that_is_not_a_mapping_is_a_diagnostic(tmp_path):
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, {"tiers": ["light"]}))
    assert_diagnostic_error(str(exc.value))
