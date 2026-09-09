"""Ensure Pillow is pinned so FreeType font metrics are reproducible.

fit_text() measurement depends on Pillow's FreeType version; an unpinned Pillow
could shift getbbox() widths and change rendered pixels / fit decisions.
"""

from pathlib import Path

import yaml


def _pip_deps() -> list[str]:
    env = yaml.safe_load(Path("environment.yml").read_text())
    for dep in env["dependencies"]:
        if isinstance(dep, dict) and "pip" in dep:
            return dep["pip"]
    raise AssertionError("no pip section in environment.yml")


def test_pillow_is_pinned():
    pins = _pip_deps()
    assert any(d.startswith("pillow==") for d in pins), (
        f"pillow must be pinned for reproducible FreeType metrics; got {pins}"
    )
