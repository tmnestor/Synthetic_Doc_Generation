# Tiered Receipt Degradation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the corpus-wide degradation model with a receipt-only one that produces phone-photo-realistic images at three declared severity tiers.

**Architecture:** Augraphy applies ink and paper damage to the flat page; the existing camera-scan homography then warps it onto a desk background and applies camera photometrics. Severity is declared entirely in YAML as an ordered list of tiers; the tier list is the variant count. The eval-set degraded directory becomes 55 receipts × 3 tiers with its own ground truth, no longer a copy of the clean one.

**Tech Stack:** Python 3.12, Pillow, OpenCV (headless), NumPy, Augraphy, PyYAML, pytest.

**Design:** [`receipt_degradation_design.md`](receipt_degradation_design.md) · **Rationale:** [`tiered_receipt_degradation_pbi.md`](tiered_receipt_degradation_pbi.md)

## Global Constraints

- **Conda env:** `synthetic`. Run everything through `conda run -n synthetic ...`.
- **Never install packages directly.** Update `environment.yml` first, then `conda env update -f environment.yml --prune`.
- **YAML is the single source of truth.** No Python-side defaults for any config value. Every key is required; a missing key fails fast. Never `dict.get(key, fallback)` on config.
- **Every fail-fast diagnostic carries four elements:** what is wrong, where to fix it (absolute path + dotted key path), what a valid value looks like, how to recover. Tests assert all four via `assert_diagnostic_error` from `tests/conftest.py`.
- **Exception chaining (B904):** inside `except` blocks always `raise X() from None` or `from err`.
- **Line length:** 108 characters max.
- **Type hints:** Python 3.12 style (`X | Y`, not `Union`). No `from __future__ import annotations`. No `TYPE_CHECKING` guards for runtime-signature types.
- **Paths:** always `pathlib.Path`.
- **Docstrings:** Google style.
- **`tests/` is gitignored** — never `git add tests/`.
- **Never bypass pre-commit hooks** with `--no-verify`. No Claude attribution in commit messages.
- **Pre-commit gates:** `pytest tests/`, `ruff check --fix --ignore ARG001,ARG002,F841 .`, `ruff format .`, `mypy . --ignore-missing-imports`.
- **Never write the term "ATO"** anywhere. Use "PROD".

---

## File Structure

| File | Responsibility |
|---|---|
| `generators/degradation/__init__.py` | Public entry point: `degrade_receipt()`. Orchestrates augment → warp. |
| `generators/degradation/tiers.py` | Load and validate the `receipt_degradation:` block into `Tier` objects. No image handling. |
| `generators/degradation/augment.py` | Registry of allowed Augraphy augmentations; builds and runs a phase pipeline. No config parsing. |
| `generators/degradation/camera.py` | Perspective warp onto a desk background, drop shadow, camera photometrics. No Augraphy. |
| `config/generation_config.yml` | Tier declarations replace the deleted `degradation:` block. |
| `generators/common.py` | `degrade_image` and `DEFAULT_DEGRADATION_PARAMS` deleted. |
| `generators/pipeline.py` | Degraded-output wiring and `--clean-only` deleted. |
| `generators/eval_set.py` | Renders 3 variants per receipt; writes a separate degraded ground truth. |
| `degrade_camera_scan.py` | Deleted; logic moves to `generators/degradation/camera.py`. |

---

### Task 1: Environment — add Augraphy, pin NumPy, prove render-neutral

Augraphy's `numba` caps NumPy at ≤2.4 while the env resolves 2.5.1. This task lands the dependency change first and *proves* the downgrade does not alter rendered pixels, because discovering otherwise later would invalidate every downstream task.

**Files:**
- Modify: `environment.yml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: an environment where `import augraphy` succeeds and `cv2` still resolves to the headless build.

- [ ] **Step 1: Capture the current pixel-snapshot hashes as a reference**

```bash
cd /Users/tod/Desktop/Synthetic_Doc_Generation
cp tests/fixtures/bank_dsl_pixel_hashes.json /tmp/bank_hashes_before.json
cp tests/fixtures/receipt_legacy_snapshot.json /tmp/receipt_before.json
cp tests/fixtures/invoice_legacy_snapshot.json /tmp/invoice_before.json
```

- [ ] **Step 2: Add the dependencies to `environment.yml`**

Under the `pip:` list, replace the bare `- numpy` line with the pinned version and add the Augraphy block. Place the new block immediately after the `opencv-python-headless` entry:

```yaml
      # Capped at <=2.4 by numba, which augraphy imports unconditionally.
      # Pinned exactly so the cap is visible rather than resolved silently.
      - numpy==2.3.5
```

```yaml
      # Document-image degradation for receipts (generators/degradation/).
      # MUST be installed with --no-deps: augraphy declares `opencv-python`
      # (the full GUI build), which would displace the headless build pinned
      # above and pull GUI system libraries into locked-down PROD. Its real
      # transitive requirements are therefore listed explicitly below.
      - augraphy==8.2.6
      - numba
      - llvmlite
      - scikit-image
      - scikit-learn
      - lazy_loader
      - imageio
      - tifffile
      - networkx
      - joblib
      - threadpoolctl
      - narwhals
      - requests
      - urllib3
      - idna
      - certifi
```

- [ ] **Step 3: Add the Augraphy cache directory to `.gitignore`**

Augraphy writes intermediate PNGs into an `augraphy_cache/` directory in the working directory during some augmentations, even with `save_outputs=False`. Task 4 suppresses it; this is the backstop so a stray directory can never be committed.

```gitignore
# Augraphy scratch output — written during augmentation runs, never source.
augraphy_cache/
```

- [ ] **Step 4: Update the environment**

```bash
conda env update -f environment.yml --prune
```

Note: `conda env update` will resolve `augraphy`'s declared `opencv-python`. If it does, remove the full build and reinstall augraphy without deps:

```bash
conda run -n synthetic pip uninstall -y opencv-python
conda run -n synthetic pip install --no-deps augraphy==8.2.6
```

- [ ] **Step 5: Verify Augraphy imports and cv2 is still headless**

```bash
conda run -n synthetic python -c "
import cv2, numpy, augraphy
from augraphy import AugraphyPipeline, InkBleed, LightingGradient, ShadowCast, Folding
print('numpy', numpy.__version__)
print('augraphy', augraphy.__version__)
print('cv2', cv2.__version__)
"
conda run -n synthetic pip list | grep -i opencv
```

Expected: numpy 2.3.5, augraphy 8.2.6, and `pip list` shows **only** `opencv-python-headless`. If plain `opencv-python` appears, repeat Step 4's uninstall.

- [ ] **Step 6: Prove the NumPy downgrade is render-neutral**

```bash
conda run -n synthetic python -m pytest tests/ -q
```

Expected: PASS, 1067 tests. The pixel-snapshot tests hash renderer output; if they still match, rendering is provably unaffected by the NumPy change. **If any pixel snapshot fails, stop and report** — that means NumPy does influence rendering and the design's assumption is wrong.

- [ ] **Step 7: Commit**

```bash
git add environment.yml .gitignore
git commit -m ":heavy_plus_sign: add augraphy and pin numpy to numba's ceiling"
```

---

### Task 2: Delete the old degradation path

Removing Path A before building Path B keeps the two from coexisting in a confusing half-state, and retires the `DEFAULT_DEGRADATION_PARAMS` merge that violated the no-Python-defaults rule.

**Files:**
- Modify: `generators/common.py` (delete `DEFAULT_DEGRADATION_PARAMS`, `degrade_image`)
- Modify: `generators/pipeline.py:197-283` (delete `clean_only`, degraded wiring)
- Modify: `config/generation_config.yml` (delete `degradation:` block and `generate_degraded:` flags)
- Modify: `generators/eval_set.py` (delete the `degradation_params` load and its use)
- Delete: `degrade_camera_scan.py`
- Test: `tests/test_degradation_removal.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `generators.common` no longer exports `degrade_image` or `DEFAULT_DEGRADATION_PARAMS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_degradation_removal.py`:

```python
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
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
conda run -n synthetic python -m pytest tests/test_degradation_removal.py -v
```

Expected: 5 FAILED — `degrade_image` still exists, the config block is present, the script is present.

- [ ] **Step 3: Delete from `generators/common.py`**

Delete the entire block from the `# --- Default degradation parameters ---` comment through the end of `degrade_image` (the last line of the file). Then remove now-unused imports — check whether `io`, `random`, `ImageEnhance`, `ImageFilter` and `np` are still referenced elsewhere in the file before removing any:

```bash
conda run -n synthetic python -c "
import re, pathlib
src = pathlib.Path('generators/common.py').read_text()
for name in ('io.', 'random.', 'ImageEnhance', 'ImageFilter', 'np.'):
    print(name, len(re.findall(re.escape(name), src)))
"
```

Remove only the imports whose count drops to zero.

- [ ] **Step 4: Delete the wiring from `generators/pipeline.py`**

In `generate()`:
- Delete the `clean_only` typer option from the signature.
- Delete `degradation_params = cfg.get("degradation", None)`.
- Delete `degraded_dir = output_dir / "degraded" / subdir` and the `if not clean_only: degraded_dir.mkdir(...)` block.
- Delete `generate_degraded = doc_cfg.get("generate_degraded", True) and not clean_only`.
- Delete the whole `if generate_degraded:` block (seed, `degrade_image` call, `degraded_filename`, save).
- Remove `degrade_image` from the `generators.common` import.

Keep `generate_clean` — it is a separate, still-meaningful per-type flag.

- [ ] **Step 5: Delete the config**

In `config/generation_config.yml`, delete the entire `degradation:` block (the seven parameter lines and its header) and every `generate_degraded: true` line under `document_types`.

- [ ] **Step 6: Delete the eval-set use**

In `generators/eval_set.py::_render_documents`, delete `degradation_params = data.get("degradation")` and the `if not isinstance(degradation_params, dict) ...` diagnostic block that follows it.

**Keep `data = yaml.safe_load(config_path.read_text())`.** It looks like it exists only for the degradation params, but the loop below reads `doc_cfg = data["document_types"][dtype]` from it. Deleting it breaks every document type.

Change the `degrade_image(...)` save line to write the clean image for now — Task 6 replaces this properly:

```python
            img.save(clean_dir / filename)
            img.save(degraded_dir / filename)  # replaced in Task 6
```

Remove the `degrade_image` import.

- [ ] **Step 7: Delete the root script**

```bash
git rm degrade_camera_scan.py
```

- [ ] **Step 8: Run the removal tests**

```bash
conda run -n synthetic python -m pytest tests/test_degradation_removal.py -v
```

Expected: 5 PASSED.

- [ ] **Step 9: Run the full suite and fix fallout**

```bash
conda run -n synthetic python -m pytest tests/ -q
```

Expected: failures in any test importing `degrade_image` or asserting on `output/degraded/`. Delete those tests — they cover deleted behaviour. Do **not** delete tests that merely reference `degradation_seed`; that key survives and Task 5 uses it.

- [ ] **Step 10: Commit**

```bash
git add -A generators/ config/generation_config.yml
git commit -m ":fire: delete the corpus-wide degradation path"
```

---

### Task 3: Tier configuration and validation

**Files:**
- Create: `generators/degradation/__init__.py`
- Create: `generators/degradation/tiers.py`
- Modify: `config/generation_config.yml`
- Test: `tests/degradation/test_tiers.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Tier` — frozen dataclass with fields `name: str`, `suffix: str`, `ink: list[dict]`, `paper: list[dict]`, `warp: dict`, `camera: dict`.
  - `load_tiers(config_path: Path) -> list[Tier]`
  - `class TierConfigError(RuntimeError)`

- [ ] **Step 1: Write the failing tests**

Create `tests/degradation/__init__.py` (empty) and `tests/degradation/test_tiers.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
conda run -n synthetic python -m pytest tests/degradation/test_tiers.py -v
```

Expected: collection error — `No module named 'generators.degradation'`.

- [ ] **Step 3: Create the package and implement `tiers.py`**

`generators/degradation/__init__.py` — leave empty for now; Task 5 adds `degrade_receipt`.

`generators/degradation/tiers.py`:

```python
"""Load and validate the `receipt_degradation:` tier declarations.

The tier list *is* the variant count -- three tiers produce three degraded
variants per receipt. There is deliberately no separate count key, so the
configuration cannot contradict itself.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

_BLOCK = "receipt_degradation"
_TIER_KEYS = ("name", "suffix", "ink", "paper", "warp", "camera")

_EXAMPLE = """              receipt_degradation:
                tiers:
                  - name: light
                    suffix: v1
                    ink:    [{augmentation: InkBleed, intensity: [0.05, 0.15], kernel: 3}]
                    paper:  [{augmentation: LightingGradient, max_brightness: 255, direction: 90}]
                    warp:   {foreshorten: [0.01, 0.03], rotation_deg: [-3, 3], margin: [0.05, 0.10]}
                    camera: {blur: [0.2, 0.5], noise_sigma: [1, 3], jpeg: [85, 95]}"""


class TierConfigError(RuntimeError):
    """Raised when the receipt_degradation block is missing or malformed."""


@dataclass(frozen=True)
class Tier:
    """One declared severity level.

    Attributes:
        name: Human-readable severity label, e.g. "light".
        suffix: Filename suffix distinguishing this tier's variant, e.g. "v1".
        ink: Augraphy ink-phase augmentation specs, each with an
            `augmentation:` key naming a registered class.
        paper: Augraphy paper-phase augmentation specs, same shape as `ink`.
        warp: Perspective-warp parameters consumed by camera.warp_to_photo.
        camera: Photometric parameters consumed by camera.apply_photometrics.
    """

    name: str
    suffix: str
    ink: list[dict]
    paper: list[dict]
    warp: dict
    camera: dict


def _err(what: str, *, config_path: Path, key_path: str, expected: str, recover: str) -> TierConfigError:
    """Build a four-element fail-fast diagnostic."""
    return TierConfigError(
        f"Invalid receipt degradation config.\n"
        f"  What:     {what}\n"
        f"  Where:    {config_path.resolve()} -> {key_path}\n"
        f"  Expected: {expected}\n"
        f"  Recover:  {recover}"
    )


def load_tiers(config_path: Path) -> list[Tier]:
    """Load every declared severity tier, in YAML order.

    Args:
        config_path: Path to generation_config.yml.

    Returns:
        The declared tiers, in the order they appear in the YAML. That order
        fixes each tier's seed offset, so reordering the list changes output.

    Raises:
        TierConfigError: The block is absent, empty, malformed, or declares a
            tier missing any required key or reusing a suffix.
    """
    data = yaml.safe_load(config_path.read_text()) or {}

    block = data.get(_BLOCK)
    if not isinstance(block, dict):
        raise _err(
            f"the top-level '{_BLOCK}:' block is missing, so no degraded receipt "
            f"can be produced.",
            config_path=config_path,
            key_path=_BLOCK,
            expected=f"a mapping with a 'tiers:' list, e.g.\n{_EXAMPLE}",
            recover=f"add a '{_BLOCK}:' block to {config_path.name}.",
        )

    raw_tiers = block.get("tiers")
    if not isinstance(raw_tiers, list) or not raw_tiers:
        raise _err(
            f"'{_BLOCK}.tiers' is missing or empty, so there is no severity level to render.",
            config_path=config_path,
            key_path=f"{_BLOCK}.tiers",
            expected=f"a non-empty list of tier mappings, e.g.\n{_EXAMPLE}",
            recover=f"declare at least one tier under {_BLOCK}.tiers.",
        )

    tiers: list[Tier] = []
    seen_suffixes: dict[str, str] = {}
    for index, raw in enumerate(raw_tiers):
        if not isinstance(raw, dict):
            raise _err(
                f"tier at index {index} is a {type(raw).__name__}, not a mapping.",
                config_path=config_path,
                key_path=f"{_BLOCK}.tiers[{index}]",
                expected=f"a mapping carrying {list(_TIER_KEYS)}, e.g.\n{_EXAMPLE}",
                recover=f"replace {_BLOCK}.tiers[{index}] with a mapping.",
            )

        missing = [key for key in _TIER_KEYS if key not in raw]
        if missing:
            raise _err(
                f"tier at index {index} is missing required key(s): {missing}.",
                config_path=config_path,
                key_path=f"{_BLOCK}.tiers[{index}]",
                expected=f"every one of {list(_TIER_KEYS)}, e.g.\n{_EXAMPLE}",
                recover=f"add {missing} to {_BLOCK}.tiers[{index}].",
            )

        suffix = str(raw["suffix"])
        if suffix in seen_suffixes:
            raise _err(
                f"tiers '{seen_suffixes[suffix]}' and '{raw['name']}' both declare "
                f"suffix '{suffix}', so their images would overwrite each other.",
                config_path=config_path,
                key_path=f"{_BLOCK}.tiers[{index}].suffix",
                expected="a suffix unique across every tier, e.g. v1 / v2 / v3.",
                recover=f"give {_BLOCK}.tiers[{index}] a suffix no other tier uses.",
            )
        seen_suffixes[suffix] = str(raw["name"])

        tiers.append(
            Tier(
                name=str(raw["name"]),
                suffix=suffix,
                ink=list(raw["ink"]),
                paper=list(raw["paper"]),
                warp=dict(raw["warp"]),
                camera=dict(raw["camera"]),
            )
        )

    return tiers
```

- [ ] **Step 4: Add the tier block to `config/generation_config.yml`**

Add where the deleted `degradation:` block was:

```yaml
# Receipt degradation. Receipts are the only type users photograph -- bank
# statements and invoices arrive as clean PDFs or printouts -- so they are the
# only type degraded. Each tier below produces one variant per receipt, so the
# length of this list IS the variant count.
#
# Ordering is significant: a tier's index fixes its seed offset, so reordering
# the list changes every rendered image.
#
# Excluded deliberately: Augraphy's DirtyRollers and BadPhotoCopy model
# photocopier damage, a different story from a phone photograph. Also excluded:
# Augraphy's geometric augmentations -- the warp owns geometry, and stacking a
# second perspective transform would defeat the rectifier's quad detection.
receipt_degradation:
  tiers:
    - name: light
      suffix: v1
      ink:    [{augmentation: InkBleed, intensity: [0.05, 0.15], kernel: 3}]
      paper:  [{augmentation: LightingGradient, max_brightness: 255, direction: 90}]
      warp:   {foreshorten: [0.01, 0.03], rotation_deg: [-3, 3], margin: [0.05, 0.10]}
      camera: {blur: [0.2, 0.5], noise_sigma: [1, 3], jpeg: [85, 95]}

    - name: moderate
      suffix: v2
      ink:    [{augmentation: InkBleed, intensity: [0.15, 0.30], kernel: 5}]
      paper:
        - {augmentation: LightingGradient, max_brightness: 245, direction: 45}
        - {augmentation: ShadowCast, side: bottom, opacity: [0.25, 0.45]}
      warp:   {foreshorten: [0.03, 0.06], rotation_deg: [-8, 8], margin: [0.07, 0.14]}
      camera: {blur: [0.4, 0.8], noise_sigma: [2, 5], jpeg: [65, 80]}

    - name: heavy
      suffix: v3
      ink:    [{augmentation: InkBleed, intensity: [0.30, 0.50], kernel: 5}]
      paper:
        - {augmentation: Folding, fold_count: 2, fold_noise: 0.1}
        - {augmentation: LightingGradient, max_brightness: 230, direction: 135}
        - {augmentation: ShadowCast, side: left, opacity: [0.40, 0.60]}
      warp:   {foreshorten: [0.06, 0.10], rotation_deg: [-14, 14], margin: [0.10, 0.18]}
      camera: {blur: [0.7, 1.3], noise_sigma: [4, 8], jpeg: [50, 65]}
```

- [ ] **Step 5: Run the tests**

```bash
conda run -n synthetic python -m pytest tests/degradation/test_tiers.py -v
```

Expected: all PASS (11 tests — 5 named plus 6 parametrised).

- [ ] **Step 6: Commit**

```bash
git add generators/degradation/ config/generation_config.yml
git commit -m ":sparkles: declare receipt degradation severity tiers in YAML"
```

---

### Task 4: Augraphy augmentation registry

**Files:**
- Create: `generators/degradation/augment.py`
- Test: `tests/degradation/test_augment.py`

**Interfaces:**
- Consumes: `Tier` from `generators.degradation.tiers`.
- Produces:
  - `AUGMENTATIONS: dict[str, Callable[..., object]]` — name → Augraphy class.
  - `class AugmentationError(RuntimeError)`
  - `apply_augraphy(image: Image.Image, tier: Tier, seed: int) -> Image.Image`

- [ ] **Step 1: Write the failing tests**

Create `tests/degradation/test_augment.py`:

```python
"""The augmentation registry rejects unknown names at build time, and the
augmented output is deterministic for a given seed."""

import numpy as np
import pytest
from conftest import assert_diagnostic_error
from PIL import Image

from generators.degradation.augment import AUGMENTATIONS, AugmentationError, apply_augraphy
from generators.degradation.tiers import Tier


def _tier(ink=None, paper=None) -> Tier:
    return Tier(
        name="probe",
        suffix="vX",
        ink=ink if ink is not None else [],
        paper=paper if paper is not None else [],
        warp={},
        camera={},
    )


def _page() -> Image.Image:
    """A small page with real ink on it -- a blank image augments to itself."""
    arr = np.full((240, 180, 3), 250, dtype=np.uint8)
    arr[60:70, 20:160] = 20
    arr[110:120, 20:160] = 20
    return Image.fromarray(arr)


def test_registry_exposes_the_tier_augmentations():
    for name in ("InkBleed", "LightingGradient", "ShadowCast", "Folding"):
        assert name in AUGMENTATIONS


def test_photocopier_augmentations_are_not_registered():
    """Excluded by design -- they model a different damage story."""
    assert "DirtyRollers" not in AUGMENTATIONS
    assert "BadPhotoCopy" not in AUGMENTATIONS


def test_unknown_augmentation_is_a_diagnostic():
    tier = _tier(ink=[{"augmentation": "Sepia", "intensity": 1}])
    with pytest.raises(AugmentationError) as exc:
        apply_augraphy(_page(), tier, seed=1)
    assert_diagnostic_error(str(exc.value))
    assert "Sepia" in str(exc.value)
    assert "InkBleed" in str(exc.value)  # lists what IS registered


def test_spec_without_an_augmentation_key_is_a_diagnostic():
    with pytest.raises(AugmentationError) as exc:
        apply_augraphy(_page(), _tier(ink=[{"intensity": 1}]), seed=1)
    assert_diagnostic_error(str(exc.value))


def test_same_seed_gives_identical_output():
    tier = _tier(ink=[{"augmentation": "InkBleed", "intensity": [0.2, 0.4], "kernel": 3}])
    first = apply_augraphy(_page(), tier, seed=7)
    second = apply_augraphy(_page(), tier, seed=7)
    assert first.tobytes() == second.tobytes()


def test_augmentation_changes_the_image():
    tier = _tier(ink=[{"augmentation": "InkBleed", "intensity": [0.3, 0.5], "kernel": 5}])
    page = _page()
    assert apply_augraphy(page, tier, seed=3).tobytes() != page.tobytes()


def test_empty_phases_pass_the_image_through_unchanged():
    page = _page()
    assert apply_augraphy(page, _tier(), seed=1).size == page.size


def test_dimensions_are_preserved():
    """Ground truth is value-F1, but a size change would break the warp's
    source quad, which assumes the augmented page is the original size."""
    tier = _tier(
        ink=[{"augmentation": "InkBleed", "intensity": [0.2, 0.3], "kernel": 3}],
        paper=[{"augmentation": "LightingGradient", "max_brightness": 245, "direction": 45}],
    )
    page = _page()
    assert apply_augraphy(page, tier, seed=5).size == page.size
```

- [ ] **Step 2: Run to verify it fails**

```bash
conda run -n synthetic python -m pytest tests/degradation/test_augment.py -v
```

Expected: collection error — `No module named 'generators.degradation.augment'`.

- [ ] **Step 3: Implement `augment.py`**

```python
"""Registry and runner for the Augraphy phase pipeline.

Only the augmentations this project actually declares are registered. An
allow-list rather than a passthrough to Augraphy's whole catalogue is
deliberate: it turns a YAML typo into a startup diagnostic naming the valid
options, and it documents which of Augraphy's ~30 effects were chosen and why
the rest were not (see the exclusions in config/generation_config.yml).
"""

from collections.abc import Callable

import numpy as np
from PIL import Image

from generators.degradation.tiers import Tier

try:
    from augraphy import AugraphyPipeline, Folding, InkBleed, LightingGradient, ShadowCast
except ImportError as err:  # pragma: no cover - environment failure, not logic
    raise ImportError(
        "Augraphy is not installed.\n"
        f"  What:     receipt degradation needs augraphy, which failed to import: {err}.\n"
        "  Where:    environment.yml -> dependencies.pip\n"
        "  Expected: augraphy==8.2.6 installed WITHOUT its declared dependencies, "
        "since it requires `opencv-python` (the full GUI build) which would displace "
        "the pinned opencv-python-headless. numpy must also be <=2.4, the ceiling "
        "numba imposes.\n"
        "  Recover:  conda env update -f environment.yml --prune, then "
        "`pip install --no-deps augraphy==8.2.6` if the full opencv was pulled in."
    ) from err

# YAML name -> Augraphy class. Deliberately excludes DirtyRollers and
# BadPhotoCopy (photocopier damage, not phone photography) and every geometric
# augmentation (camera.py owns geometry).
AUGMENTATIONS: dict[str, Callable[..., object]] = {
    "InkBleed": InkBleed,
    "LightingGradient": LightingGradient,
    "ShadowCast": ShadowCast,
    "Folding": Folding,
}

# YAML key -> the constructor keyword each Augraphy class expects. The YAML
# uses short, readable names; Augraphy's own parameter names are longer and
# inconsistent between classes. Verified against augraphy 8.2.6 -- if the pin
# ever moves, re-check with:
#   inspect.signature(InkBleed.__init__).parameters
_PARAM_NAMES: dict[str, dict[str, str]] = {
    "InkBleed": {"intensity": "intensity_range", "kernel": "kernel_size"},
    "LightingGradient": {"max_brightness": "max_brightness", "direction": "direction"},
    "ShadowCast": {"side": "shadow_side", "opacity": "shadow_opacity_range"},
    "Folding": {"fold_count": "fold_count", "fold_noise": "fold_noise"},
}


class AugmentationError(RuntimeError):
    """Raised when a tier names an augmentation that is not registered."""


def _build(spec: dict, *, tier_name: str, phase: str) -> object:
    """Instantiate one augmentation from its YAML spec.

    Args:
        spec: The YAML mapping, carrying `augmentation:` plus its parameters.
        tier_name: Owning tier's name, for diagnostics.
        phase: "ink" or "paper", for diagnostics.

    Returns:
        The constructed Augraphy augmentation.

    Raises:
        AugmentationError: No `augmentation:` key, or an unregistered name.
    """
    name = spec.get("augmentation")
    if name is None:
        raise AugmentationError(
            "Invalid augmentation spec.\n"
            f"  What:     a {phase}-phase entry of tier '{tier_name}' has no "
            f"'augmentation:' key, so there is nothing to construct.\n"
            f"  Where:    config/generation_config.yml -> "
            f"receipt_degradation.tiers[{tier_name}].{phase}\n"
            f"  Expected: every entry to name one of {sorted(AUGMENTATIONS)}, e.g.\n"
            "              {augmentation: InkBleed, intensity: [0.05, 0.15], kernel: 3}\n"
            f"  Recover:  add an 'augmentation:' key to the {phase} entry."
        )

    factory = AUGMENTATIONS.get(str(name))
    if factory is None:
        raise AugmentationError(
            "Unknown augmentation.\n"
            f"  What:     tier '{tier_name}' names '{name}' in its {phase} phase, "
            f"which is not registered.\n"
            f"  Where:    config/generation_config.yml -> "
            f"receipt_degradation.tiers[{tier_name}].{phase}\n"
            f"  Expected: one of {sorted(AUGMENTATIONS)}.\n"
            "  Recover:  use a registered augmentation, or add the class to "
            "AUGMENTATIONS in generators/degradation/augment.py."
        )

    mapping = _PARAM_NAMES[str(name)]
    kwargs = {mapping[key]: value for key, value in spec.items() if key != "augmentation"}
    # Augraphy wants tuples for its *_range parameters; YAML gives lists.
    kwargs = {k: tuple(v) if isinstance(v, list) else v for k, v in kwargs.items()}
    return factory(**kwargs)


def apply_augraphy(image: Image.Image, tier: Tier, seed: int) -> Image.Image:
    """Apply a tier's ink and paper phases to the flat page.

    Runs before any warp: these model damage to the paper itself, which must
    then be warped *with* the page rather than painted across a tilted photo.

    Args:
        image: The clean, flat rendered page.
        tier: The severity tier supplying the phase specs.
        seed: Seed making this tier's output reproducible.

    Returns:
        The augmented page, at the same dimensions as the input.

    Raises:
        AugmentationError: A phase entry is malformed or names an unknown
            augmentation.
    """
    ink = [_build(spec, tier_name=tier.name, phase="ink") for spec in tier.ink]
    paper = [_build(spec, tier_name=tier.name, phase="paper") for spec in tier.paper]

    if not ink and not paper:
        return image.copy()

    pipeline = AugraphyPipeline(
        ink_phase=ink,
        paper_phase=paper,
        post_phase=[],
        save_outputs=False,
        log=False,
        random_seed=seed,
    )
    result = pipeline(np.array(image.convert("RGB")))
    return Image.fromarray(np.asarray(result, dtype=np.uint8), "RGB")
```

- [ ] **Step 4: Run the tests**

```bash
conda run -n synthetic python -m pytest tests/degradation/test_augment.py -v
```

Expected: 8 PASSED.

If `test_same_seed_gives_identical_output` fails, Augraphy's `random_seed` does not fully control its sampling. Fix by seeding NumPy's global RNG immediately before the pipeline call, keeping `random_seed` as well:

```python
    np.random.seed(seed)
    result = pipeline(np.array(image.convert("RGB")))
```

- [ ] **Step 5: Verify no cache directory was created**

```bash
ls augraphy_cache 2>/dev/null && echo "LEAKED" || echo "clean"
```

Expected: `clean`. If `LEAKED`, an augmentation writes regardless of `save_outputs`; the `.gitignore` entry from Task 1 keeps it out of the repo, and the directory should be removed in Step 6's commit prep.

- [ ] **Step 6: Commit**

```bash
git add generators/degradation/augment.py
git commit -m ":sparkles: add an allow-listed Augraphy augmentation registry"
```

---

### Task 5: Camera warp and the public entry point

**Files:**
- Create: `generators/degradation/camera.py`
- Modify: `generators/degradation/__init__.py`
- Test: `tests/degradation/test_camera.py`

**Interfaces:**
- Consumes: `Tier` from `tiers.py`, `apply_augraphy` from `augment.py`.
- Produces:
  - `warp_to_photo(image: Image.Image, warp: dict, rng: np.random.Generator) -> Image.Image`
  - `apply_photometrics(image: Image.Image, camera: dict, rng: np.random.Generator) -> Image.Image`
  - `degrade_receipt(image: Image.Image, tier: Tier, seed: int) -> Image.Image` (exported from `generators.degradation`)
  - `tier_seed(base_seed: int, tier_index: int) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/degradation/test_camera.py`:

```python
"""The warp produces a photo-shaped frame, and the whole pipeline is
deterministic per (case seed, tier index)."""

import numpy as np
from PIL import Image

from generators.degradation import degrade_receipt, tier_seed
from generators.degradation.camera import apply_photometrics, warp_to_photo
from generators.degradation.tiers import Tier

WARP = {"foreshorten": [0.03, 0.06], "rotation_deg": [-8, 8], "margin": [0.07, 0.14]}
CAMERA = {"blur": [0.4, 0.8], "noise_sigma": [2, 5], "jpeg": [65, 80]}


def _tier(name="moderate", suffix="v2") -> Tier:
    return Tier(
        name=name,
        suffix=suffix,
        ink=[{"augmentation": "InkBleed", "intensity": [0.15, 0.30], "kernel": 5}],
        paper=[{"augmentation": "LightingGradient", "max_brightness": 245, "direction": 45}],
        warp=WARP,
        camera=CAMERA,
    )


def _page() -> Image.Image:
    arr = np.full((300, 200, 3), 250, dtype=np.uint8)
    arr[80:95, 20:180] = 15
    return Image.fromarray(arr)


def test_warp_enlarges_the_frame_by_the_margin():
    """The receipt must occupy a sub-region, surrounded by background --
    that framing is the whole point of the camera model."""
    page = _page()
    out = warp_to_photo(page, WARP, np.random.default_rng(1))
    assert out.width > page.width
    assert out.height > page.height


def test_warp_leaves_background_in_the_corners():
    """A corner pixel should be desk, not paper: if the page still filled the
    frame, the perspective warp did not happen."""
    out = warp_to_photo(_page(), WARP, np.random.default_rng(2))
    corner = out.getpixel((2, 2))
    assert corner != (255, 255, 255), "corner is pure white -- no background composited"


def test_photometrics_preserve_dimensions():
    page = _page()
    assert apply_photometrics(page, CAMERA, np.random.default_rng(3)).size == page.size


def test_tier_seed_is_stable_and_distinct_per_tier():
    assert tier_seed(9821, 0) == tier_seed(9821, 0)
    assert tier_seed(9821, 0) != tier_seed(9821, 1)
    assert tier_seed(9821, 1) != tier_seed(9822, 1)


def test_degrade_receipt_is_deterministic():
    page = _page()
    first = degrade_receipt(page, _tier(), seed=tier_seed(4242, 1))
    second = degrade_receipt(page, _tier(), seed=tier_seed(4242, 1))
    assert first.tobytes() == second.tobytes()


def test_tiers_differ_from_each_other():
    page = _page()
    light = degrade_receipt(page, _tier("light", "v1"), seed=tier_seed(4242, 0))
    heavy = degrade_receipt(page, _tier("heavy", "v3"), seed=tier_seed(4242, 2))
    assert light.tobytes() != heavy.tobytes()


def test_degrade_receipt_returns_rgb():
    assert degrade_receipt(_page(), _tier(), seed=1).mode == "RGB"
```

- [ ] **Step 2: Run to verify it fails**

```bash
conda run -n synthetic python -m pytest tests/degradation/test_camera.py -v
```

Expected: collection error — `cannot import name 'degrade_receipt'`.

- [ ] **Step 3: Implement `camera.py`**

This is the deleted `degrade_camera_scan.py`'s logic, parameterised by tier rather than hardcoded. The `_rot`, quad-construction, warp, shadow and composite steps are carried over unchanged in behaviour.

```python
"""The camera model: a photograph of a receipt lying on a flat surface.

A clean, upright page is warped onto a desk background so it occupies a
sub-region of the frame, perspective-distorted and rotated -- the input a
document-rectification preprocessor must later undo. This is the geometry
Augraphy cannot produce: every Augraphy effect treats the page as a rectangle
square-on to the camera.

The warp uses the same homography library the rectifier uses
(cv2.getPerspectiveTransform / cv2.warpPerspective). Compositing and
photometrics stay in PIL/NumPy. Everything is RGB throughout -- PIL does I/O
and NumPy arrays feed straight to cv2 -- so there is no BGR channel swap.
"""

import io

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def _rot(point: list[float], cx: float, cy: float, degrees: float) -> list[float]:
    """Rotate a point about (cx, cy) by `degrees`."""
    theta = np.radians(degrees)
    x, y = point[0] - cx, point[1] - cy
    return [cx + x * np.cos(theta) - y * np.sin(theta), cy + x * np.sin(theta) + y * np.cos(theta)]


def warp_to_photo(image: Image.Image, warp: dict, rng: np.random.Generator) -> Image.Image:
    """Warp a flat page onto a desk background, as if photographed off-axis.

    Args:
        image: The (already ink/paper-augmented) flat page.
        warp: Tier warp parameters -- `foreshorten`, `rotation_deg` and
            `margin`, each a [min, max] pair.
        rng: Seeded generator; all randomness is drawn from it.

    Returns:
        An RGB frame larger than the input, with the page occupying a
        perspective-distorted sub-region over a desk background.
    """
    page = image.convert("RGB")
    w, h = page.size

    margin_lo, margin_hi = warp["margin"]
    pad_x = int(w * rng.uniform(margin_lo, margin_hi))
    pad_y = int(h * rng.uniform(margin_lo, margin_hi))
    cw, ch = w + 2 * pad_x, h + 2 * pad_y

    # Flat desk: muted tone, gentle lighting gradient, faint noise.
    base = np.array([rng.uniform(150, 200), rng.uniform(140, 190), rng.uniform(125, 175)])
    bg = np.ones((ch, cw, 3)) * base
    gx = np.linspace(rng.uniform(-25, 0), rng.uniform(0, 25), cw)[None, :, None]
    gy = np.linspace(rng.uniform(-20, 0), rng.uniform(0, 20), ch)[:, None, None]
    bg = np.clip(bg + gx + gy + rng.normal(0, 3, (ch, cw, 3)), 0, 255)

    # Destination quad: foreshorten one edge, then rotate the whole page.
    fore_lo, fore_hi = warp["foreshorten"]
    f = rng.uniform(fore_lo, fore_hi)
    edge = int(rng.integers(0, 4))
    q = [[0.0, 0.0], [float(w), 0.0], [float(w), float(h)], [0.0, float(h)]]  # TL TR BR BL
    if edge == 0:  # top edge away
        q[0][0] += w * f
        q[1][0] -= w * f
    elif edge == 1:  # right edge away
        q[1][1] += h * f
        q[2][1] -= h * f
    elif edge == 2:  # bottom edge away
        q[3][0] += w * f
        q[2][0] -= w * f
    else:  # left edge away
        q[0][1] += h * f
        q[3][1] -= h * f

    rot_lo, rot_hi = warp["rotation_deg"]
    degrees = rng.uniform(rot_lo, rot_hi)
    q = [_rot(p, w / 2, h / 2, degrees) for p in q]

    ox = pad_x + rng.uniform(-pad_x * 0.3, pad_x * 0.3)
    oy = pad_y + rng.uniform(-pad_y * 0.3, pad_y * 0.3)
    dst = np.array([[x + ox, y + oy] for x, y in q], dtype=np.float32)
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)

    m = cv2.getPerspectiveTransform(src, dst)
    rgba = np.dstack([np.array(page), np.full((h, w), 255, np.uint8)])
    warped = cv2.warpPerspective(
        rgba, m, (cw, ch),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    alpha = (warped[:, :, 3].astype(np.float32) / 255.0)[:, :, None]

    # Drop shadow under the page.
    shadow = cv2.GaussianBlur(warped[:, :, 3], (0, 0), max(w, h) * 0.02) * 0.45
    offset = int(max(w, h) * 0.015)
    shadow = np.roll(np.roll(shadow, offset, axis=0), offset, axis=1)[:, :, None] / 255.0
    bg = bg * (1 - shadow) + np.array([25, 22, 20]) * shadow

    composite = bg * (1 - alpha) + warped[:, :, :3].astype(np.float32) * alpha
    return Image.fromarray(np.clip(composite, 0, 255).astype(np.uint8), "RGB")


def apply_photometrics(image: Image.Image, camera: dict, rng: np.random.Generator) -> Image.Image:
    """Apply lens and sensor artefacts to a whole frame.

    Runs after the warp: blur, sensor noise and JPEG blocking are properties of
    the camera and the file, not of the paper.

    Args:
        image: The composited frame.
        camera: Tier camera parameters -- `blur`, `noise_sigma` and `jpeg`,
            each a [min, max] pair.
        rng: Seeded generator; all randomness is drawn from it.

    Returns:
        The photographed-looking frame, same dimensions as the input.
    """
    frame = image.convert("RGB")
    frame = ImageEnhance.Brightness(frame).enhance(rng.uniform(0.92, 1.05))
    frame = ImageEnhance.Contrast(frame).enhance(rng.uniform(0.90, 1.0))

    blur_lo, blur_hi = camera["blur"]
    frame = frame.filter(ImageFilter.GaussianBlur(rng.uniform(blur_lo, blur_hi)))

    noise_lo, noise_hi = camera["noise_sigma"]
    sigma = rng.uniform(noise_lo, noise_hi)
    arr = np.array(frame).astype(np.int16)
    arr = arr + rng.normal(0, sigma, arr.shape).astype(np.int16)
    frame = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")

    jpeg_lo, jpeg_hi = camera["jpeg"]
    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=int(rng.integers(jpeg_lo, jpeg_hi + 1)))
    buf.seek(0)
    return Image.open(buf).convert("RGB")
```

- [ ] **Step 4: Implement the entry point in `generators/degradation/__init__.py`**

```python
"""Receipt degradation: Augraphy paper damage, then a camera-scan warp.

Receipts are the only document type users photograph -- bank statements and
invoices arrive as clean PDFs or printouts -- so they are the only type this
package degrades.

Ordering is load-bearing. Augraphy's ink and paper phases run on the flat page,
before the warp, because a crease belongs to the paper and must be warped *with*
it; painting one flat across an already-tilted photo would read as a defect in
the image rather than in the document. Blur, sensor noise and JPEG blocking run
after, because they are artefacts of the camera and the file.
"""

import numpy as np
from PIL import Image

from generators.degradation.augment import apply_augraphy
from generators.degradation.camera import apply_photometrics, warp_to_photo
from generators.degradation.tiers import Tier, TierConfigError, load_tiers

__all__ = ["Tier", "TierConfigError", "degrade_receipt", "load_tiers", "tier_seed"]

# Multiplier spacing each tier's seed far apart in the generator's sequence, so
# tier 0 and tier 1 of the same case share no draws.
_TIER_STRIDE = 100_003  # prime, to avoid collisions with round case seeds


def tier_seed(base_seed: int, tier_index: int) -> int:
    """Derive a tier's seed from the case seed and the tier's position.

    Args:
        base_seed: The ground-truth entry's `degradation_seed`.
        tier_index: The tier's index in the declared list.

    Returns:
        A seed unique to this (case, tier) pair and stable across runs.
    """
    return base_seed * _TIER_STRIDE + tier_index


def degrade_receipt(image: Image.Image, tier: Tier, seed: int) -> Image.Image:
    """Degrade one clean receipt render to one tier's severity.

    Args:
        image: The clean rendered receipt.
        tier: The severity tier to apply.
        seed: Seed for this (case, tier) pair -- see `tier_seed`.

    Returns:
        An RGB frame of the receipt as photographed on a desk.

    Raises:
        AugmentationError: The tier names an unregistered augmentation.
    """
    augmented = apply_augraphy(image, tier, seed)
    rng = np.random.default_rng(seed)
    warped = warp_to_photo(augmented, tier.warp, rng)
    return apply_photometrics(warped, tier.camera, rng)
```

- [ ] **Step 5: Run the tests**

```bash
conda run -n synthetic python -m pytest tests/degradation/ -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add generators/degradation/
git commit -m ":sparkles: warp augmented receipts onto a desk as camera photos"
```

---

### Task 6: Wire tiered variants into the eval-set export

The degraded directory's ground truth stops being a copy of the clean one: it now has different rows entirely (165 receipt variants, versus 165 documents across three types).

**Files:**
- Modify: `generators/eval_set.py` (`_render_documents`, `export_eval_set`)
- Test: `tests/test_eval_set_variants.py`

**Interfaces:**
- Consumes: `degrade_receipt`, `load_tiers`, `tier_seed` from `generators.degradation`.
- Produces: `_render_documents(...) -> tuple[list[dict], list[dict]]` — `(clean_documents, degraded_documents)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_set_variants.py`:

```python
"""The degraded eval set is receipts only, one image per tier, with ground
truth duplicated per variant."""

import csv
import json
from pathlib import Path

import pytest

from generators.eval_set import export_eval_set

CONFIG = Path("config/generation_config.yml")


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("evalset")
    summary = export_eval_set(CONFIG, out, force=True)
    return summary, Path(summary["clean_dir"]), Path(summary["degraded_dir"])


def test_clean_dir_still_holds_every_type(exported):
    _, clean_dir, _ = exported
    names = [p.name for p in clean_dir.glob("*.png")]
    assert len(names) == 165
    assert sum("bank_statement" in n for n in names) == 55
    assert sum("invoice" in n for n in names) == 55
    assert sum("receipt" in n for n in names) == 55


def test_degraded_dir_holds_only_receipt_variants(exported):
    _, _, degraded_dir = exported
    names = [p.name for p in degraded_dir.glob("*.png")]
    assert len(names) == 165, "55 receipts x 3 tiers"
    assert all("receipt" in n for n in names)
    assert not any("bank_statement" in n or "invoice" in n for n in names)


def test_every_receipt_has_one_image_per_tier(exported):
    _, _, degraded_dir = exported
    names = {p.name for p in degraded_dir.glob("*.png")}
    for case in (1, 27, 55):
        for suffix in ("v1", "v2", "v3"):
            assert f"CASE{case:03d}_receipt_{suffix}.png" in names


def test_degraded_ground_truth_has_one_row_per_variant(exported):
    _, _, degraded_dir = exported
    rows = list(csv.DictReader((degraded_dir / "ground_truth.csv").open()))
    assert len(rows) == 165
    images = {p.name for p in degraded_dir.glob("*.png")}
    assert {r["image_file"] for r in rows} == images


def test_variants_of_a_case_share_identical_field_values(exported):
    """The value-F1 contract: distortion never changes the answer."""
    _, _, degraded_dir = exported
    rows = {r["image_file"]: r for r in csv.DictReader((degraded_dir / "ground_truth.csv").open())}
    for case in (1, 27, 55):
        variants = [rows[f"CASE{case:03d}_receipt_v{i}.png"] for i in (1, 2, 3)]
        for other in variants[1:]:
            for column, value in variants[0].items():
                if column == "image_file":
                    continue
                assert other[column] == value, f"CASE{case:03d} {column} differs across tiers"


def test_degraded_jsonl_matches_the_csv(exported):
    _, _, degraded_dir = exported
    lines = (degraded_dir / "ground_truth.jsonl").read_text().splitlines()
    assert len(lines) == 165
    assert {json.loads(line)["image_file"] for line in lines} == {
        p.name for p in degraded_dir.glob("*.png")
    }


def test_case_ids_still_resolve_for_linking(exported):
    """Case ids are unsuffixed, so transaction_links.yml keeps resolving."""
    _, _, degraded_dir = exported
    rows = list(csv.DictReader((degraded_dir / "ground_truth.csv").open()))
    for row in rows:
        assert row["image_file"].split("_")[0].startswith("CASE")
```

- [ ] **Step 2: Run to verify it fails**

```bash
conda run -n synthetic python -m pytest tests/test_eval_set_variants.py -v
```

Expected: FAIL — the degraded directory currently mirrors the clean one.

- [ ] **Step 3: Rewrite `_render_documents` in `generators/eval_set.py`**

Replace the function's signature, docstring and body. The clean loop is unchanged; the degraded write becomes a per-tier loop that only fires for receipts.

```python
def _render_documents(
    config_path: Path,
    eval_cfg: dict,
    schema: ExtractionSchema,
    clean_dir: Path,
    degraded_dir: Path,
    renderers: dict,
) -> tuple[list[dict], list[dict]]:
    """Render the clean set once, and a tiered degraded set for receipts only.

    Receipts are the only type users photograph, so they are the only type
    degraded -- and each is degraded once per declared severity tier. Every
    variant's ground-truth record carries field values identical to its source
    receipt, differing only in `image_file`, which is the value-F1 contract:
    distortion never changes the answer.

    Args:
        config_path: Path to generation_config.yml.
        eval_cfg: The validated `eval_set` block.
        schema: The loaded extraction schema.
        clean_dir: Directory to save clean images into.
        degraded_dir: Directory to save degraded receipt variants into.
        renderers: Document type -> renderer callable.

    Returns:
        `(clean_documents, degraded_documents)`, each a list of
        `{"filename": str, "fields": dict}` sorted by filename. The two lists
        differ in both length and content -- the degraded one holds only
        receipt variants.

    Raises:
        ValueError: any missing renderer, layout, seed, document type, or
            duplicate output filename.
        TierConfigError: the receipt_degradation block is missing or malformed.
    """
    tiers = load_tiers(config_path)
    data = yaml.safe_load(config_path.read_text())

    documents: list[dict] = []
    degraded_documents: list[dict] = []
    seen: dict[str, str] = {}

    for dtype in eval_cfg["document_types"]:
        doc_cfg = data["document_types"][dtype]
        renderer = renderers.get(dtype)
        if not renderer:
            raise _err(
                f"no renderer is registered for document type '{dtype}'.",
                path=config_path,
                key_path=f"{_ROOT_KEY}.document_types",
                expected=f"a type with a renderer: {sorted(renderers)}.",
                recover=f"remove '{dtype}' from {_ROOT_KEY}.document_types",
            )

        gt_path = Path(doc_cfg["ground_truth"])
        gt_data = load_ground_truth(gt_path)
        layouts = load_layout_registry(Path(doc_cfg["layouts"]))

        for case_id, entry in gt_data.items():
            layout_ref = entry.get("layout", "")
            layout = layouts.get(layout_ref, {})
            if not layout:
                raise _err(
                    f"{case_id} references layout '{layout_ref}', which is not in the registry.",
                    path=Path(doc_cfg["layouts"]),
                    key_path=f"layouts.{layout_ref}",
                    expected="every ground-truth entry's layout to exist in its layout registry.",
                    recover=f"add '{layout_ref}' to the registry or fix {case_id}'s layout",
                )

            fields = entry.get("fields", {}) or {}
            doc_type = fields.get("DOCUMENT_TYPE", "")
            resolved_type = schema.resolve_doc_type(str(doc_type))
            projected = project_fields(str(case_id), fields, str(doc_type), schema, gt_path)
            filename = f"{case_id}_{resolved_type}.png"

            if filename in seen:
                raise _err(
                    f"two documents would both be exported as '{filename}' "
                    f"({seen[filename]} and {case_id} / {layout_ref}).",
                    path=gt_path,
                    key_path=f"{case_id}.fields.DOCUMENT_TYPE",
                    expected="exactly one document per case per extraction document type.",
                    recover=f"remove or re-type the duplicate entry for {case_id}",
                )
            seen[filename] = f"{case_id} / {layout_ref}"

            seed = entry.get("degradation_seed")
            if not isinstance(seed, int):
                raise _err(
                    f"{case_id} has no integer 'degradation_seed', so its degraded image "
                    f"would not be reproducible.",
                    path=gt_path,
                    key_path=f"{case_id}.degradation_seed",
                    expected="an integer, e.g. 'degradation_seed: 9821'.",
                    recover=f"add a 'degradation_seed:' to {case_id}",
                )

            entry["case_id"] = str(case_id)
            try:
                img = renderer(entry, layout)
            except FitError as exc:
                raise build_overflow_error(
                    [f"{case_id} / {layout_ref}: {str(exc).splitlines()[0]}"]
                ) from None

            img.save(clean_dir / filename)
            documents.append({"filename": filename, "fields": projected})

            if resolved_type != _DEGRADED_TYPE:
                continue

            for index, tier in enumerate(tiers):
                variant_name = f"{case_id}_{resolved_type}_{tier.suffix}.png"
                degrade_receipt(img, tier, tier_seed(seed, index)).save(degraded_dir / variant_name)
                degraded_documents.append({"filename": variant_name, "fields": projected})

    documents.sort(key=lambda doc: doc["filename"])
    degraded_documents.sort(key=lambda doc: doc["filename"])
    return documents, degraded_documents
```

Add near the module's other constants:

```python
# The one extraction document type users photograph, and so the only one the
# degraded half of the evaluation set contains.
_DEGRADED_TYPE = "receipt"
```

Add the imports:

```python
from generators.degradation import degrade_receipt, load_tiers, tier_seed
```

- [ ] **Step 4: Update `export_eval_set` to write two ground truths**

Replace the tail of `export_eval_set` from the `_render_documents` call onward:

```python
    documents, degraded_documents = _render_documents(
        config_path, eval_cfg, schema, clean_dir, degraded_dir, renderers
    )

    jsonl_path = write_jsonl(documents, clean_dir / eval_cfg["jsonl_name"])
    csv_path = csv_from_jsonl(jsonl_path, clean_dir / eval_cfg["csv_name"])

    # Written, not copied: the degraded set holds different rows entirely
    # (receipt variants, one per tier), so it needs its own ground truth
    # rather than a copy of the clean one.
    degraded_jsonl = write_jsonl(degraded_documents, degraded_dir / eval_cfg["jsonl_name"])
    csv_from_jsonl(degraded_jsonl, degraded_dir / eval_cfg["csv_name"])

    return {
        "images": len(documents),
        "degraded_images": len(degraded_documents),
        "clean_dir": str(clean_dir),
        "degraded_dir": str(degraded_dir),
        "csv": str(csv_path),
        "jsonl": str(jsonl_path),
    }
```

Update the docstring's `Returns:` to describe `degraded_images` and to drop the claim that the degraded copies are byte-identical. Remove the now-unused `shutil.copy2` loop; check whether `shutil` is still used elsewhere in the file (`_prepare_dir` uses `shutil.rmtree`, so keep the import).

- [ ] **Step 5: Run the variant tests**

```bash
conda run -n synthetic python -m pytest tests/test_eval_set_variants.py -v
```

Expected: 7 PASSED.

- [ ] **Step 6: Fix the existing eval-set tests**

```bash
conda run -n synthetic python -m pytest tests/test_eval_set.py tests/test_eval_format.py -v
```

Existing tests asserting the two directories hold identical filename sets, or that the ground-truth files are byte-identical copies, now encode deleted behaviour. Update each to the new contract: clean holds 165 across three types; degraded holds 165 receipt variants with its own ground truth.

- [ ] **Step 7: Commit**

```bash
git add generators/eval_set.py
git commit -m ":sparkles: export three degraded receipt variants per case"
```

---

### Task 7: Calibrate the tiers and update the documentation

**Files:**
- Modify: `config/generation_config.yml` (tuned tier values)
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `environment.yml` (comment only)
- Modify: `rectify_camera_scan.py` (docstrings only)

- [ ] **Step 1: Render a calibration sheet**

```bash
conda run -n synthetic python -m generators.pipeline eval-set --out /tmp/calibration --force
```

Then build a side-by-side of one receipt at all three tiers:

```bash
conda run -n synthetic python -c "
from pathlib import Path
from PIL import Image
src = Path('/tmp/calibration')
deg = next(src.glob('degraded_*'))
clean = next(src.glob('synthetic_*'))
tiles = [Image.open(clean / 'CASE003_receipt.png')] + [
    Image.open(deg / f'CASE003_receipt_v{i}.png') for i in (1, 2, 3)
]
w = 700
tiles = [t.resize((w, int(t.height * w / t.width)), Image.Resampling.LANCZOS) for t in tiles]
h = max(t.height for t in tiles)
sheet = Image.new('RGB', (len(tiles) * (w + 20) + 20, h + 40), 'white')
for i, t in enumerate(tiles):
    sheet.paste(t, (20 + i * (w + 20), 20))
sheet.save('/tmp/calibration/tiers.png')
print('wrote /tmp/calibration/tiers.png')
"
```

- [ ] **Step 2: Review and tune**

Open `/tmp/calibration/tiers.png`. Judge each tier against: *light* should look like a good phone photo of a fresh receipt; *moderate* like a used receipt in poor light; *heavy* like a creased receipt photographed badly but still legible to a careful human. If any tier is wrong, edit only `config/generation_config.yml` and re-run Step 1 — no code changes.

**Every field value must remain humanly legible at `heavy`.** A tier so severe that a human cannot read the total is not measuring robustness, it is measuring noise.

- [ ] **Step 3: Update `README.md`**

Three edits:
- Replace the "7-stage pipeline" degradation section with the tier model: receipts only, three tiers, Augraphy-then-warp ordering, and the fact that all parameters live in `config/generation_config.yml`.
- Replace the `python degrade_camera_scan.py --batch output` usage examples — that script no longer exists. Degradation now runs only as part of `eval-set`.
- In the repo-tree listing, replace the `degrade_camera_scan.py` line with `generators/degradation/`.

- [ ] **Step 4: Update `CLAUDE.md`**

Remove the `generate --clean-only` line from the commands block (the flag is deleted). Add a line to the "Key Data Conventions" section:

```markdown
- **Degradation**: receipts only, three severity tiers declared in `config/generation_config.yml`; the degraded eval set is 55 receipts × 3 tiers with per-variant ground truth
```

- [ ] **Step 5: Update the `environment.yml` comment**

The `opencv-python-headless` comment claims cv2 is "not used by the core generators pipeline". That is now false — `generators/degradation/camera.py` uses it. Replace with:

```yaml
      # Perspective warp for receipt degradation (generators/degradation/camera.py)
      # and the offline rectifier (rectify_camera_scan.py). Pinned so camera-scan
      # output stays byte-stable across rebuilds.
```

- [ ] **Step 6: Update `rectify_camera_scan.py` docstrings**

Replace both references to `degrade_camera_scan.py` with `generators/degradation/camera.py`.

- [ ] **Step 7: Run every gate**

```bash
conda run -n synthetic python -m pytest tests/ -q
conda run -n synthetic ruff check --fix --ignore ARG001,ARG002,F841 .
conda run -n synthetic ruff format .
conda run -n synthetic mypy . --ignore-missing-imports
```

Expected: all tests pass; ruff clean; mypy reports only the 8 pre-existing `degrade_camera_scan.py`-unrelated errors — note that file is deleted, so those 8 should now be **gone**. If mypy is fully clean, say so in the commit.

- [ ] **Step 8: Commit**

```bash
git add config/generation_config.yml README.md CLAUDE.md environment.yml rectify_camera_scan.py
git commit -m ":memo: calibrate degradation tiers and update the docs"
```

---

## Verification

After Task 7, confirm the design's Definition of Done:

```bash
# 55 receipts x 3 tiers, no other type
ls /tmp/calibration/degraded_*/*.png | wc -l          # 165
ls /tmp/calibration/degraded_*/*.png | grep -c receipt # 165

# Ground truth rows match images
wc -l < /tmp/calibration/degraded_*/ground_truth.jsonl # 165

# The old path is gone
grep -rn "degrade_image" generators/ && echo FAIL || echo "removed"
test -f degrade_camera_scan.py && echo FAIL || echo "removed"
```
