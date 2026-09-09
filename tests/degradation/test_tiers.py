"""Tier config loads from YAML only, and every omission fails with a diagnostic.

Tiers are declared per document type. That is not decoration: every tier value
is in pixels, and a receipt is 440x674 against an invoice's 1900x3508, so one
shared list made `heavy` mean two different severities. The tests below pin the
two properties that keeps honest -- each type gets its own values, and every
type declares the same rungs.
"""

from pathlib import Path

import pytest
import yaml
from conftest import assert_diagnostic_error

from generators.degradation.tiers import Tier, TierConfigError, load_tiers

VALID_TIER = {
    "name": "moderate",
    "suffix": "moderate",
    "ink": [{"augmentation": "InkBleed", "intensity": [0.05, 0.15], "kernel": 3}],
    "paper": [{"augmentation": "LightingGradient", "max_brightness": 255, "direction": 90}],
    "warp": {"foreshorten": [0.01, 0.03], "rotation_deg": [-3, 3], "margin": [0.05, 0.10]},
    "camera": {"blur": [0.2, 0.5], "noise_sigma": [1, 3], "jpeg": [85, 95]},
}
SECOND_TIER = dict(VALID_TIER, name="heavy", suffix="heavy")


def _write(tmp_path: Path, block: object) -> Path:
    path = tmp_path / "generation_config.yml"
    path.write_text(yaml.safe_dump({"document_degradation": block}))
    return path


def _one_type(tiers: list) -> dict:
    """Wrap a tier list as the single-type mapping the loader expects."""
    return {"tiers": {"receipts": tiers}}


def test_loads_the_real_project_config():
    """Assert the ladder is well-formed, not which rungs it has.

    The rungs are an operator decision -- already changed once, from three
    tiers to two -- so pinning names here made this fail for expressing a
    preference rather than a contract.
    """
    by_type = load_tiers(Path("config/generation_config.yml"))
    assert by_type, "the config must declare tiers for at least one document type"
    for doc_type, tiers in by_type.items():
        assert tiers, f"{doc_type} declares no severity tier"
        assert all(isinstance(t, Tier) for t in tiers)
        names = [t.name for t in tiers]
        suffixes = [t.suffix for t in tiers]
        assert len(set(names)) == len(names), f"{doc_type}: duplicate tier names {names}"
        assert len(set(suffixes)) == len(suffixes), f"{doc_type}: duplicate suffixes {suffixes}"


def test_every_type_declares_the_same_rungs():
    """`heavy` must mean the same rung whatever the document type, since the
    condition label is compared across types."""
    by_type = load_tiers(Path("config/generation_config.yml"))
    rungs = {t: [(x.name, x.suffix) for x in tiers] for t, tiers in by_type.items()}
    assert len(set(map(tuple, rungs.values()))) == 1, f"rungs differ between types: {rungs}"


def test_types_carry_their_own_measured_values():
    """The whole reason for per-type ladders. If two types ever share a value
    set, one of them is uncalibrated -- the page sizes differ by 5x."""
    by_type = load_tiers(Path("config/generation_config.yml"))
    if len(by_type) < 2:
        pytest.skip("only one document type is degraded, so there is nothing to compare")
    blurs = {t: tuple(tiers[-1].camera["blur"]) for t, tiers in by_type.items()}
    assert len(set(blurs.values())) == len(blurs), (
        f"two document types share a heavy blur range {blurs}; pixel-valued parameters cannot "
        f"be equal across page sizes that differ by 5x"
    )


def test_missing_block_is_a_diagnostic(tmp_path):
    path = tmp_path / "generation_config.yml"
    path.write_text(yaml.safe_dump({"output_dir": "output"}))
    with pytest.raises(TierConfigError) as exc:
        load_tiers(path)
    assert_diagnostic_error(str(exc.value))
    assert "document_degradation" in str(exc.value)


def test_a_flat_tier_list_is_a_diagnostic_naming_the_old_shape(tmp_path):
    """The pre-per-type config. The message must say what changed, or an
    operator upgrading an old config has to read the loader to find out."""
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, {"tiers": [VALID_TIER]}))
    message = str(exc.value)
    assert_diagnostic_error(message)
    assert "per document type" in message


def test_empty_tier_mapping_is_a_diagnostic(tmp_path):
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, {"tiers": {}}))
    assert_diagnostic_error(str(exc.value))


def test_empty_tier_list_for_a_type_is_a_diagnostic(tmp_path):
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, {"tiers": {"receipts": []}}))
    message = str(exc.value)
    assert_diagnostic_error(message)
    assert "receipts" in message


@pytest.mark.parametrize("missing", ["name", "suffix", "ink", "paper", "warp", "camera"])
def test_missing_tier_key_is_a_diagnostic(tmp_path, missing):
    tier = {k: v for k, v in VALID_TIER.items() if k != missing}
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, _one_type([tier])))
    assert_diagnostic_error(str(exc.value))
    assert missing in str(exc.value)


def test_duplicate_suffix_within_a_type_is_a_diagnostic(tmp_path):
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, _one_type([VALID_TIER, dict(VALID_TIER, name="other")])))
    message = str(exc.value)
    assert_diagnostic_error(message)
    assert "moderate" in message


def test_the_same_suffix_across_types_is_fine(tmp_path):
    """Types write into the same directory but their filenames carry the type,
    so `CASE001_receipt_heavy.png` and `CASE001_invoice_heavy.png` do not
    collide. Sharing a suffix is required, not merely allowed."""
    block = {"tiers": {"receipts": [VALID_TIER], "invoices": [VALID_TIER]}}
    by_type = load_tiers(_write(tmp_path, block))
    assert by_type["receipts"][0].suffix == by_type["invoices"][0].suffix


def test_types_declaring_different_rungs_is_a_diagnostic(tmp_path):
    block = {"tiers": {"receipts": [VALID_TIER, SECOND_TIER], "invoices": [VALID_TIER]}}
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, block))
    message = str(exc.value)
    assert_diagnostic_error(message)
    assert "invoices" in message


def test_types_declaring_rungs_in_a_different_order_is_a_diagnostic(tmp_path):
    """Order fixes each tier's seed offset, so a reordered list is a different
    corpus even when the names match."""
    block = {
        "tiers": {
            "receipts": [VALID_TIER, SECOND_TIER],
            "invoices": [SECOND_TIER, VALID_TIER],
        }
    }
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, block))
    assert_diagnostic_error(str(exc.value))


def test_tier_that_is_not_a_mapping_is_a_diagnostic(tmp_path):
    with pytest.raises(TierConfigError) as exc:
        load_tiers(_write(tmp_path, _one_type(["moderate"])))
    assert_diagnostic_error(str(exc.value))
