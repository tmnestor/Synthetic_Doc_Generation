"""`generate` validates every DSL layout before it renders anything.

Before the layout DSL, an incomplete layout degraded gracefully: a missing key
took a Python default and the run finished. It does not any more — every
primitive parameter resolves through `resolve_param`, so an omission is a
render-time exception. `validate` catching that is no use to an operator who
ran `generate` directly, which is why `generate` now runs the same check
itself, before the first image is written.
"""

import pytest
from typer.testing import CliRunner

from generators.pipeline import app


@pytest.fixture
def broken_registry(monkeypatch):
    """Make `load_layout_registry` drop a required default from one layout.

    Patching the loader rather than the YAML keeps the shipped layout files
    untouched while still driving the real `generate` command end to end.
    """
    import generators.pipeline as pipeline
    from generators.loader import load_layout_registry as real_load

    def _load(path):
        registry = real_load(path)
        for layout in registry.values():
            if "body" in layout:
                layout["defaults"].pop("pair_separator", None)
                break
        return registry

    monkeypatch.setattr(pipeline, "load_layout_registry", _load)


def test_generate_rejects_an_incomplete_layout_before_rendering(broken_registry):
    result = CliRunner().invoke(app, ["generate", "--type", "receipts"])

    assert result.exit_code == 1, result.output
    # The four-element diagnostic reaches the operator, naming the omission and
    # the layout — not a bare traceback from whichever block asked first.
    assert "pair_separator" in result.output
    assert "defaults" in result.output
    # ...and it happened before any rendering: no per-type success line.
    assert "generated" not in result.output


def test_generate_still_produces_documents_when_layouts_are_valid():
    """The guard must not cost a valid run anything. One document type, so the
    test stays fast; the eight-type run is covered by the CLI itself."""
    result = CliRunner().invoke(app, ["generate", "--type", "invoices"])
    assert result.exit_code == 0, result.output
    assert "invoices: generated 55 documents." in result.output
