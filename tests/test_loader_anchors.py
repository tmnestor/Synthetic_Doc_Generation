"""Tests for load_layout_registry's handling of top-level anchor siblings.

The de-duplication scheme puts anchor definitions (`_bank_base`, `_cba`, …) at
top level as siblings of `layouts:`, so the loader must unwrap `layouts:`
even when it is not the sole top-level key — as long as every other key is
underscore-prefixed. A non-underscore sibling is a genuine authoring error
(a mis-indented layout) and must fail fast.
"""

from pathlib import Path

import pytest

from generators.loader import load_layout_registry


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "layouts.yml"
    path.write_text(text)
    return path


def test_anchor_siblings_are_not_mistaken_for_layouts(tmp_path: Path):
    path = _write(
        tmp_path,
        """
_base: &base
  page_dimensions: {width: 1800, height: 3508}
  content_width: 1600
layouts:
  cba_standard:
    <<: *base
    row_height: 72
""",
    )
    registry = load_layout_registry(path)
    assert list(registry) == ["cba_standard"]
    assert registry["cba_standard"]["content_width"] == 1600
    assert registry["cba_standard"]["row_height"] == 72


def test_a_non_anchor_top_level_key_fails_fast(tmp_path: Path):
    path = _write(
        tmp_path,
        """
cba_standard:
  row_height: 72
layouts:
  westpac_standard:
    row_height: 62
""",
    )
    with pytest.raises(ValueError) as exc_info:
        load_layout_registry(path)
    message = str(exc_info.value)
    assert "cba_standard" in message
    assert "Recover:" in message


def test_a_file_with_only_layouts_still_unwraps(tmp_path: Path):
    path = _write(tmp_path, "layouts:\n  a:\n    row_height: 10\n")
    assert list(load_layout_registry(path)) == ["a"]
