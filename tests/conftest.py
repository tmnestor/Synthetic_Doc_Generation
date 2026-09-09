"""Shared test configuration and helpers (local-only; tests/ is gitignored).

Puts the repo root on sys.path so `import generators...` works without per-file
boilerplate, and provides the four-element fail-fast diagnostic assertion.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def assert_diagnostic_error(
    error: BaseException | str,
    path: Path | None = None,
    token: str | None = None,
) -> None:
    """Assert a fail-fast diagnostic carries all four required elements.

    Per CLAUDE.md, every fail-fast diagnostic must name (1) WHAT is wrong,
    (2) WHERE to fix it, (3) WHAT IT SHOULD LOOK LIKE, and (4) HOW TO RECOVER.
    This helper supports the two labeling conventions already in use across
    this project's fail-fast paths, selected by which arguments are given:

    Legacy / labeled-block convention (e.g. generators/content_engine.py,
    generators/layout_budgets.py, generators/common.py), where the message
    contains literal "What:", "Where:", "Expected:", "Recover:" lines. Call
    with just the message or exception::

        assert_diagnostic_error(str(exc_info.value))
        assert_diagnostic_error(exc_info.value)

    Config-style convention (e.g. generators/exporters/config.py), where the
    message is prose naming a resolved file path plus inline "Example:" and
    "Remediation:" sections rather than labeled blocks. Call with the raised
    exception, the `Path` that was passed to the function under test, and the
    key or value the message is expected to name::

        assert_diagnostic_error(exc_info.value, path, "cord_extension_scoring")

    Args:
        error: The raised exception, or its message as a string (legacy form).
        path: The config path passed to the function under test. When given
            together with `token`, asserts that `str(path.resolve())` appears
            in the message (the WHERE element).
        token: The key or value name the message is expected to name — e.g.
            the missing/invalid key, or the offending value. Required
            together with `path`; omit both for the legacy labeled-block form.

    Raises:
        AssertionError: If any of the four required elements is absent.
        ValueError: If only one of `path`/`token` is given.
    """
    message = error if isinstance(error, str) else str(error)

    if path is None and token is None:
        low = message.lower()
        assert "what:" in low, f"missing WHAT in: {message}"
        assert "where:" in low, f"missing WHERE in: {message}"
        assert "expected:" in low, f"missing EXPECTED in: {message}"
        assert "recover:" in low, f"missing RECOVER in: {message}"
        return

    if path is None or token is None:
        raise ValueError("assert_diagnostic_error: pass both `path` and `token`, or neither")

    resolved = str(path.resolve())
    assert token in message, f"missing WHAT ({token!r}) in: {message}"
    assert resolved in message, f"missing WHERE ({resolved!r}) in: {message}"
    assert "Example:" in message, f"missing EXAMPLE in: {message}"
    assert "Remediation:" in message, f"missing REMEDIATION in: {message}"
