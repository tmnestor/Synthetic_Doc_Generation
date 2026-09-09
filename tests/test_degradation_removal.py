"""The old corpus-wide degradation path is deleted, not deprecated.

A leftover `degrade_image` would be a second, silently-diverging way to
degrade a document, and its Python-side DEFAULT_DEGRADATION_PARAMS merge is
exactly the "silent fallback" CLAUDE.md forbids.
"""

from pathlib import Path

import yaml

import generators.common as common


def test_degrade_image_is_gone():
    assert not hasattr(common, "degrade_image")


def test_default_degradation_params_is_gone():
    assert not hasattr(common, "DEFAULT_DEGRADATION_PARAMS")


def test_generation_config_has_no_degradation_block():
    cfg = yaml.safe_load(Path("config/generation_config.yml").read_text())
    assert "degradation" not in cfg


def test_no_generate_degraded_flags_remain():
    cfg = yaml.safe_load(Path("config/generation_config.yml").read_text())
    for dtype, doc_cfg in cfg["document_types"].items():
        assert "generate_degraded" not in doc_cfg, f"{dtype} still declares generate_degraded"


def test_root_camera_scan_script_is_gone():
    assert not Path("degrade_camera_scan.py").exists()
