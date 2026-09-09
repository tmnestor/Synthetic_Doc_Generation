"""Runs the shipped seed-reproducibility check as part of the suite.

The check itself lives in `scripts/check_seed_reproducibility.py` rather than
here, because `tests/` is gitignored and this property is one a consumer of the
repo needs: it is the only thing that notices when an edit to a seed script
stops the committed corpus being reproducible. This module is a thin wrapper so
the local suite still exercises it — the logic has one home.
"""

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHECK = _REPO_ROOT / "scripts" / "check_seed_reproducibility.py"


def test_seed_scripts_reproduce_the_committed_ground_truth_byte_identically():
    result = subprocess.run(
        [sys.executable, str(_CHECK)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"scripts/check_seed_reproducibility.py failed.\n{result.stdout}\n{result.stderr}"
    )
