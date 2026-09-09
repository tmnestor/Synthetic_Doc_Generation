"""Derive quality-screen defect labels from what the generator actually drew.

Each declared defect answers one question: does THIS image carry that defect?
The answer comes from provenance -- the values drawn for this image -- not from
the tier's declared range. A tier declaring rotation [-8, 8] can draw 0.4
degrees, and calling that image "tilted" because its tier could have tilted it
puts noise into exactly the borderline cases the screen exists to judge.

The labels are polarity-free facts: "this image is blurred", never "the answer
to question 1 is NO". Whether a defect means YES or NO belongs to the prompt's
wording, which lives with the prompt.
"""

from pathlib import Path

import yaml

_BLOCK = "document_degradation.defect_labels"

# Values a rule may compare against. Every one is either recorded directly in
# provenance or derived from it here; a rule naming anything else is a config
# error, not a silent False.
_DERIVED = {
    # Sign says which way the page leans, which no question asks about.
    "rotation_deg_abs": lambda p: abs(p["rotation_deg"]),
}

_EXAMPLE = """              defect_labels:
                rules:
                  blur:    {drawn: blur_sigma, at_least: 0.60}
                  shadow:  {augmentation: ShadowCast}
                  speckle:
                    any_of:
                      - {drawn: noise_sigma, at_least: 3.0}
                      - {drawn: jpeg_quality, at_most: 70}
                filename: quality_ground_truth.jsonl"""


class DefectLabelError(RuntimeError):
    """Raised when the defect_labels block is missing or malformed."""


def _err(what: str, *, config_path: Path, key_path: str, expected: str, recover: str) -> DefectLabelError:
    """Build a four-element fail-fast diagnostic."""
    return DefectLabelError(
        f"Invalid defect label config.\n"
        f"  What:     {what}\n"
        f"  Where:    {config_path.resolve()} -> {key_path}\n"
        f"  Expected: {expected}\n"
        f"  Recover:  {recover}"
    )


def load_defect_labels(config_path: Path) -> tuple[dict, str]:
    """Load the defect rules and the ground-truth filename.

    Args:
        config_path: Path to generation_config.yml.

    Returns:
        A (rules, filename) pair.

    Raises:
        DefectLabelError: The block is absent, empty, or malformed.
    """
    data = yaml.safe_load(config_path.read_text()) or {}
    block = (data.get("document_degradation") or {}).get("defect_labels")

    if not isinstance(block, dict):
        raise _err(
            f"the '{_BLOCK}:' block is missing, so no quality ground truth can be written.",
            config_path=config_path,
            key_path=_BLOCK,
            expected=f"a mapping with 'rules:' and 'filename:', e.g.\n{_EXAMPLE}",
            recover=f"add a '{_BLOCK}:' block to {config_path.name}.",
        )

    rules = block.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise _err(
            f"'{_BLOCK}.rules' is missing or empty, so no defect would be labelled.",
            config_path=config_path,
            key_path=f"{_BLOCK}.rules",
            expected=f"a non-empty mapping of defect name to rule, e.g.\n{_EXAMPLE}",
            recover=f"declare at least one rule under {_BLOCK}.rules.",
        )

    filename = block.get("filename")
    if not isinstance(filename, str) or not filename:
        raise _err(
            f"'{_BLOCK}.filename' is missing, so there is no name to write the record under.",
            config_path=config_path,
            key_path=f"{_BLOCK}.filename",
            expected="a filename, e.g. 'quality_ground_truth.jsonl'.",
            recover=f"add a 'filename:' to {_BLOCK}.",
        )

    for defect, rule in rules.items():
        _validate_rule(rule, defect=defect, config_path=config_path)

    return rules, filename


def _validate_rule(rule: object, *, defect: str, config_path: Path) -> None:
    """Reject a rule shape now rather than mislabelling every image later."""
    key_path = f"{_BLOCK}.rules.{defect}"

    if not isinstance(rule, dict):
        raise _err(
            f"the rule for '{defect}' is a {type(rule).__name__}, not a mapping.",
            config_path=config_path,
            key_path=key_path,
            expected=f"a mapping, e.g.\n{_EXAMPLE}",
            recover=f"replace {key_path} with a mapping.",
        )

    if "any_of" in rule:
        clauses = rule["any_of"]
        if not isinstance(clauses, list) or not clauses:
            raise _err(
                f"'{defect}' declares 'any_of' but it is not a non-empty list.",
                config_path=config_path,
                key_path=f"{key_path}.any_of",
                expected=f"a non-empty list of rules, e.g.\n{_EXAMPLE}",
                recover=f"give {key_path}.any_of at least one rule.",
            )
        for clause in clauses:
            _validate_rule(clause, defect=defect, config_path=config_path)
        return

    if "augmentation" in rule:
        return

    if "drawn" in rule:
        param = rule["drawn"]
        if "at_least" not in rule and "at_most" not in rule:
            raise _err(
                f"'{defect}' compares the drawn value '{param}' against nothing.",
                config_path=config_path,
                key_path=key_path,
                expected="an 'at_least:' or 'at_most:' threshold alongside 'drawn:'.",
                recover=f"add 'at_least: <value>' or 'at_most: <value>' to {key_path}.",
            )
        return

    raise _err(
        f"the rule for '{defect}' names none of 'augmentation', 'drawn' or 'any_of', "
        f"so there is no way to decide it.",
        config_path=config_path,
        key_path=key_path,
        expected=(
            "exactly one of:\n"
            "                'augmentation: <Name>'  present iff the tier declares it\n"
            "                'drawn: <param>' with 'at_least:'/'at_most:'\n"
            "                'any_of: [<rule>, ...]'"
        ),
        recover=f"give {key_path} one of those three forms.",
    )


def _decide(rule: dict, provenance: dict) -> bool:
    """Evaluate one validated rule against one image's provenance."""
    if "any_of" in rule:
        return any(_decide(clause, provenance) for clause in rule["any_of"])

    if "augmentation" in rule:
        return rule["augmentation"] in provenance["augmentations"]

    param = rule["drawn"]
    value = _DERIVED[param](provenance) if param in _DERIVED else provenance[param]
    if "at_least" in rule:
        return value >= rule["at_least"]
    return value <= rule["at_most"]


def defects_for(provenance: dict, rules: dict) -> dict[str, bool]:
    """Label one image from its provenance.

    Args:
        provenance: The record returned alongside the image by
            `degrade_document` or `compose_clean`.
        rules: The validated rules from `load_defect_labels`.

    Returns:
        Defect name -> whether this image carries it, in declaration order.

    Raises:
        DefectLabelError: A rule names a value the provenance does not carry --
            a config/generator mismatch that would otherwise mislabel silently.
    """
    labels: dict[str, bool] = {}
    for defect, rule in rules.items():
        try:
            labels[defect] = _decide(rule, provenance)
        except KeyError as err:
            missing = err.args[0]
            raise DefectLabelError(
                f"Defect rule refers to a value the generator does not record.\n"
                f"  What:     the rule for '{defect}' reads '{missing}', which is not in the "
                f"provenance for this image. Recorded values are: "
                f"{sorted(k for k in provenance if k != 'augmentations')}, "
                f"plus derived {sorted(_DERIVED)}.\n"
                f"  Where:    config/generation_config.yml -> {_BLOCK}.rules.{defect}\n"
                f"  Expected: a 'drawn:' naming one of those values.\n"
                f"  Recover:  point the rule at a recorded value, or record '{missing}' in "
                f"generators/degradation/camera.py and return it in its provenance."
            ) from None
    return labels
