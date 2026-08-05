# Receipt Degradation Design: camera-scan + Augraphy, tiered

## Purpose

Replace the corpus-wide degradation model with a receipt-only one that produces
credible phone photographs at three declared severity tiers.

The benchmark's degraded half exists to predict how a VLM performs on what users
actually submit. Users photograph receipts; they do not photograph bank
statements or invoices, which arrive as clean PDFs or printouts. Degrading all
three types uniformly therefore models a workflow nobody has, while the receipts
— the one type that genuinely arrives creased, shadowed and photographed at an
angle — get the same mild treatment as everything else.

Scoring is **value-F1**: a field is scored on whether the extracted string is
right, not on where it sits. Ground truth is therefore invariant to any
geometric or photometric distortion, so degradation adds no labelling work and
no label risk. This is what makes the change cheap.

## Motivating evidence

A comparison sheet was rendered over `CASE003_receipt_retail_tax` through every
available option (clean, both current paths, Augraphy at three intensities). It
established one thing that redirected the design:

**Every Augraphy effect is a flat-page effect.** Ink bleed, lighting gradients,
cast shadows, folds and dirty rollers all treat the document as a rectangle
facing the camera square-on. None produce perspective, a background, or framing.
But the dominant visual gap between the current degraded corpus and a real phone
photo is exactly that geometry — and `degrade_camera_scan.py` already solves it
convincingly, while being wired to nothing.

So Augraphy alone was never going to close the gap, and the camera-scan path
alone lacks paper character. The design uses both, each for what the other
cannot do.

## Current state

Two independent degradation paths exist. Only the weaker one is wired in.

| | `degrade_image()` (Path A) | `degrade_camera_scan.py` (Path B) |
|---|---|---|
| Location | `generators/common.py` | repo root, standalone |
| Used by | `pipeline generate`, `eval_set.py` | nothing (`__main__` only) |
| Model | tint → contrast → brightness → blur → ±2° rotate → salt-pepper → JPEG | homography warp onto a desk, drop shadow, camera photometrics |
| Coverage | all 3 types, 165 docs | receipts only |

Path A also merges `DEFAULT_DEGRADATION_PARAMS` from Python over the YAML
(`common.py:755`), so deleting a key from `generation_config.yml` silently falls
back to a Python constant instead of failing. That contradicts CLAUDE.md's
"YAML is the single source of truth" and "every config key is required" rules.
Removing Path A retires that violation as a side effect.

## Scope

**Deleted:**

- `degrade_image()` and `DEFAULT_DEGRADATION_PARAMS` (`generators/common.py`)
- the `degradation:` block in `config/generation_config.yml`
- the `generate_degraded` per-type flags and their pipeline wiring
- `degrade_camera_scan.py` at the repo root (its logic moves into `generators/`)

**Consequence:** `pipeline generate` becomes clean-only. `output/degraded/`
ceases to exist and the `--clean-only` flag becomes meaningless, so it is
removed rather than left as a no-op.

**Kept:** `rectify_camera_scan.py`. It is a separate offline concern and still
consumes the warp this design produces. It references `degrade_camera_scan.py`
only in prose, never by import, so moving that module breaks nothing — but its
docstrings need repointing at the new location.

**Documentation to update** (each currently describes deleted behaviour):

- `README.md` — the "7-stage pipeline" section documents Path A, which no longer
  exists; the `degrade_camera_scan.py --batch output` usage examples name a
  deleted script; the repo-tree listing names it too.
- `environment.yml` — the `opencv-python-headless` comment cites
  `degrade_camera_scan.py` and claims cv2 is "not used by the core generators
  pipeline", which this design makes false.
- `CLAUDE.md` — the commands section lists `generate --clean-only`, which is
  being removed.
- `rectify_camera_scan.py` docstrings — repoint at `generators/degradation/`.

These are part of the work, not follow-ups. A README that documents a deleted
function is worse than no README.

## Architecture

The camera-scan logic moves from a hand-run root script into a package, since it
becomes pipeline-wired code with configuration and tests.

| Unit | Responsibility | Depends on |
|---|---|---|
| `generators/degradation/tiers.py` | Load and validate tier config; fail fast on missing or unknown keys | YAML only |
| `generators/degradation/augment.py` | Registry mapping YAML names to Augraphy classes; build a phase pipeline from a tier spec | augraphy |
| `generators/degradation/camera.py` | The warp: desk background, perspective, drop shadow, camera photometrics | cv2, numpy |

Each unit is independently testable: `tiers.py` needs no image, `augment.py`
needs no config file, `camera.py` needs neither.

The augmentation registry mirrors the existing `field_providers` and row-provider
pattern, so a YAML typo fails at startup against a named list rather than at
render time against a stack trace.

## Physical ordering

Augraphy runs on the flat page **before** the warp; camera effects run **after**,
on the whole frame:

```
clean receipt (flat)
  ↓  Augraphy ink phase     — ink bleed, faded toner        } damage to the
  ↓  Augraphy paper phase   — creases, stains, texture      } paper itself
  ↓  camera warp            — desk, perspective, shadow
  ↓  camera photometrics    — lighting, blur, noise, JPEG   } the act of
degraded variant                                            } photographing
```

This ordering is not cosmetic. A crease is a property of the paper and must be
warped *with* the page; painting it flat across an already-tilted photo would
read as a defect in the image rather than in the document. The same argument
puts blur, sensor noise and JPEG after the warp — they are camera and file
artefacts, not paper artefacts.

Augraphy's own geometric augmentations stay unused. The warp owns geometry, so
nothing stacks a second perspective transform that would defeat the rectifier's
quad detection.

## Configuration

A new `receipt_degradation:` block in `config/generation_config.yml` replaces the
deleted `degradation:` block. Every key is required — a missing key fails at
startup with a four-element diagnostic, never a silent default.

```yaml
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

The tier list *is* the variant count — three tiers produce three variants per
receipt. There is deliberately no separate count key, so the configuration
cannot contradict itself.

`DirtyRollers` and `BadPhotoCopy` are excluded from every tier. They model
photocopier damage, which is a different story from a phone photograph. Adding a
photocopy tier later is a YAML edit.

## Data flow

The clean directory is unchanged: 165 images across all three types.

The degraded directory becomes receipts only:

```
degraded_<date>/
  CASE001_receipt_v1.png  …  CASE055_receipt_v3.png   (55 × 3 = 165 images)
  ground_truth.csv                                    (165 rows)
  ground_truth.jsonl
```

Each variant's ground-truth row carries **field values identical** to its source
receipt, differing only in `image_file`. `CASE_ID` is untouched, so
`transaction_links.yml` and receipt→bank linking continue to resolve.

`eval_set.py`'s `seen[filename]` duplicate guard needs its invariant widened
from "one document per case per extraction type" to "one document per case per
extraction type **per tier**". The guard itself stays — two documents colliding
on a filename is still an error.

## Determinism

Each variant's seed derives from the entry's existing integer
`degradation_seed` combined with the tier index, so a tier's output is stable and
independent of how the tiers are ordered in YAML.

Augraphy samples from NumPy's **global** RNG rather than an injected generator,
so the pipeline calls `np.random.seed()` immediately before each Augraphy
invocation. This is the one place global random state is unavoidable; it is
isolated inside `augment.py` and covered by a byte-identity test.

## Environment

Augraphy's `numba` dependency caps NumPy at ≤2.4, while the environment
currently pins nothing and resolves 2.5.1. `environment.yml` therefore gains an
explicit `numpy==2.3.5`.

The downgrade is expected to be render-neutral because the renderers draw
through PIL, not NumPy; NumPy appears only in degradation and cv2 array
handling. This is an expectation, not an assumption: it is proven by re-running
the pixel snapshots and confirming the hashes still match.

A `--no-deps` Augraphy install needs more than the four packages previously
identified. The full set for the Artifactory request:

```
augraphy==8.2.6, numba, llvmlite, scikit-image, scikit-learn,
lazy_loader, imageio, tifffile, networkx, joblib, threadpoolctl,
narwhals, requests, urllib3, idna, certifi
```

`--no-deps` is required so Augraphy's declared `opencv-python` (the full GUI
build) does not displace the pinned `opencv-python-headless==4.13.0.92`. This
was verified locally: `cv2` continued resolving to the headless package
throughout.

## Error handling

Every failure below raises at startup with all four diagnostic elements (what,
where, expected, recover):

| Failure | Diagnostic names |
|---|---|
| `receipt_degradation:` block absent | the config path and the block to add |
| tier missing any key | the tier name, the missing key, an example tier |
| empty tier list | that at least one tier is required |
| unknown augmentation name | the registry's registered names |
| non-integer `degradation_seed` | the case id and the key path |
| Augraphy import fails | the `--no-deps` install line and the NumPy cap |

## Testing

- **Tier config:** each fail-fast path asserts all four diagnostic elements, via
  the existing `assert_diagnostic_error` helper.
- **Determinism:** the same case and tier rendered twice produces byte-identical
  PNGs.
- **Ground-truth invariance:** for each case, all three variants' field values
  equal each other and equal the clean row — the value-F1 contract, asserted
  rather than assumed.
- **Counts:** exactly `55 × len(tiers)` images and the same number of CSV rows.
- **Removal:** `degrade_image` no longer exists in `generators.common`, and
  `generation_config.yml` has no `degradation:` key.
- **Regression:** bank, receipt and invoice pixel snapshots still match after the
  NumPy pin, proving the downgrade is render-neutral.
- **Linking:** `CASE_ID` values in the degraded ground truth still resolve
  against `transaction_links.yml`.

## Open item

Tier calibration is currently informed judgement, not measurement. There are no
real phone photographs of Australian receipts to calibrate against, so the
`heavy` tier in particular is a guess at what "hard but fair" means.

Mitigation: regenerate the comparison sheet after implementation, showing all
three tiers side by side, and tune the ranges by eye. Because every parameter
lives in YAML, that is a configuration edit rather than a code change.
