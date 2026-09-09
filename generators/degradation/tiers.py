"""Load and validate the `document_degradation:` tier declarations.

The tier list *is* the variant count -- two tiers produce two degraded variants
per document. There is deliberately no separate count key, so the configuration
cannot contradict itself.

Which document types are put through these tiers is declared separately, under
`eval_set.degrade_types:`. A tier describes a severity, not a document type.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

_BLOCK = "document_degradation"
_TIER_KEYS = ("name", "suffix", "ink", "paper", "warp", "camera")

_EXAMPLE = """              document_degradation:
                tiers:
                  receipts:
                    - name: moderate
                      suffix: moderate
                      ink:    [{augmentation: InkBleed, intensity: [0.15, 0.30], kernel: 5}]
                      paper:  [{augmentation: LightingGradient, max_brightness: 245, direction: 45}]
                      warp:   {foreshorten: [0.03, 0.06], rotation_deg: [-8, 8], margin: [0.07, 0.14]}
                      camera: {blur: [0.4, 0.8], noise_sigma: [2, 5], jpeg: [65, 80]}
                  invoices:
                    - name: moderate
                      suffix: moderate
                      ...   # same rungs, values measured for this page size"""


class TierConfigError(RuntimeError):
    """Raised when the document_degradation block is missing or malformed."""


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


def load_tiers(config_path: Path) -> dict[str, list[Tier]]:
    """Load every declared severity tier, per document type, in YAML order.

    Args:
        config_path: Path to generation_config.yml.

    Returns:
        Document-type key -> that type's tiers, in the order they appear in the
        YAML. That order fixes each tier's seed offset, so reordering a list
        changes output.

    Raises:
        TierConfigError: The block is absent, empty, malformed, declares a tier
            missing any required key or reusing a suffix within its type, or
            declares different rungs for different types.
    """
    data = yaml.safe_load(config_path.read_text()) or {}

    block = data.get(_BLOCK)
    if not isinstance(block, dict):
        raise _err(
            f"the top-level '{_BLOCK}:' block is missing, so no degraded image can be produced.",
            config_path=config_path,
            key_path=_BLOCK,
            expected=f"a mapping with a 'tiers:' mapping, e.g.\n{_EXAMPLE}",
            recover=f"add a '{_BLOCK}:' block to {config_path.name}.",
        )

    raw_tiers = block.get("tiers")
    if not isinstance(raw_tiers, dict) or not raw_tiers:
        # A list here is the pre-per-type shape, so name that specifically:
        # it is the likely cause and the message should not make the operator
        # guess what changed.
        was_list = isinstance(raw_tiers, list)
        raise _err(
            f"'{_BLOCK}.tiers' is {'a list' if was_list else 'missing or empty'}, but tiers are "
            f"declared per document type."
            + (
                " A single shared list is the older shape: parameters are in pixels, and the "
                "document types differ in size by 5x, so one list made a tier name mean "
                "different severities for different types."
                if was_list
                else ""
            ),
            config_path=config_path,
            key_path=f"{_BLOCK}.tiers",
            expected=f"a mapping of document type to a non-empty tier list, e.g.\n{_EXAMPLE}",
            recover=f"nest the existing list under its document type inside {_BLOCK}.tiers.",
        )

    by_type: dict[str, list[Tier]] = {}
    for doc_type, raw_list in raw_tiers.items():
        if not isinstance(raw_list, list) or not raw_list:
            raise _err(
                f"'{_BLOCK}.tiers.{doc_type}' is missing or empty, so there is no severity "
                f"level to render for that type.",
                config_path=config_path,
                key_path=f"{_BLOCK}.tiers.{doc_type}",
                expected=f"a non-empty list of tier mappings, e.g.\n{_EXAMPLE}",
                recover=f"declare at least one tier under {_BLOCK}.tiers.{doc_type}.",
            )
        by_type[str(doc_type)] = _load_one_type(raw_list, doc_type=str(doc_type), config_path=config_path)

    _assert_rungs_agree(by_type, config_path=config_path)
    return by_type


def _load_one_type(raw_list: list, *, doc_type: str, config_path: Path) -> list[Tier]:
    """Validate and build one document type's tier list."""
    tiers: list[Tier] = []
    seen_suffixes: dict[str, str] = {}
    for index, raw in enumerate(raw_list):
        key_path = f"{_BLOCK}.tiers.{doc_type}[{index}]"
        if not isinstance(raw, dict):
            raise _err(
                f"tier at {doc_type}[{index}] is a {type(raw).__name__}, not a mapping.",
                config_path=config_path,
                key_path=key_path,
                expected=f"a mapping carrying {list(_TIER_KEYS)}, e.g.\n{_EXAMPLE}",
                recover=f"replace {key_path} with a mapping.",
            )

        missing = [key for key in _TIER_KEYS if key not in raw]
        if missing:
            raise _err(
                f"tier at {doc_type}[{index}] is missing required key(s): {missing}.",
                config_path=config_path,
                key_path=key_path,
                expected=f"every one of {list(_TIER_KEYS)}, e.g.\n{_EXAMPLE}",
                recover=f"add {missing} to {key_path}.",
            )

        suffix = str(raw["suffix"])
        if suffix in seen_suffixes:
            raise _err(
                f"tiers '{seen_suffixes[suffix]}' and '{raw['name']}' of type '{doc_type}' both "
                f"declare suffix '{suffix}', so their images would overwrite each other.",
                config_path=config_path,
                key_path=f"{key_path}.suffix",
                expected="a suffix unique within the type, e.g. moderate / heavy.",
                recover=f"give {key_path} a suffix no other tier of that type uses.",
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


def _assert_rungs_agree(by_type: dict[str, list[Tier]], *, config_path: Path) -> None:
    """Every type must declare the same rungs, in the same order.

    A tier name is a rung on a shared severity ladder: the corpus labels an
    image `heavy`, and a scorer compares those labels across document types. If
    one type declared `moderate/heavy` and another `light/severe`, or the same
    names in a different order, the condition column would not mean one thing
    and the seed offsets would not line up either.
    """
    reference_type, reference = next(iter(by_type.items()))
    expected = [(t.name, t.suffix) for t in reference]
    for doc_type, tiers in by_type.items():
        found = [(t.name, t.suffix) for t in tiers]
        if found != expected:
            raise _err(
                f"document type '{doc_type}' declares rungs {found}, but '{reference_type}' "
                f"declares {expected}. A tier name is a rung on one shared severity ladder, so "
                f"every type must declare the same names and suffixes in the same order.",
                config_path=config_path,
                key_path=f"{_BLOCK}.tiers.{doc_type}",
                expected=f"the same (name, suffix) pairs in the same order as '{reference_type}': "
                f"{expected}. Only the parameter VALUES differ between types.",
                recover=f"rename or reorder the tiers under {_BLOCK}.tiers.{doc_type} to match.",
            )
