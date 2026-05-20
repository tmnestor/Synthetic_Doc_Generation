"""YAML loading utilities for ground truth, layout registries, and generation config.

All loaders fail fast with diagnostic errors per CLAUDE.md requirements.
"""

from pathlib import Path

import yaml


def load_ground_truth(path: Path) -> dict:
    """Load a ground truth YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        Dict mapping case IDs to entry dicts.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If YAML cannot be parsed.
    """
    if not path.exists():
        msg = (
            f"Ground truth file not found: {path.resolve()}. "
            f"Create the file or check the path in config/generation_config.yml."
        )
        raise FileNotFoundError(msg)

    text = path.read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = (
            f"Failed to parse YAML in {path.resolve()}: {exc}. "
            f"Check for syntax errors (indentation, colons, quotes)."
        )
        raise ValueError(msg) from exc

    if not isinstance(data, dict):
        msg = (
            f"Expected top-level mapping in {path.resolve()}, "
            f"got {type(data).__name__}. "
            f"Each top-level key should be a CASE ID."
        )
        raise ValueError(msg)

    return data


def load_layout_registry(path: Path) -> dict:
    """Load a layout registry YAML file.

    Args:
        path: Path to the layout YAML file.

    Returns:
        Dict mapping layout IDs to layout config dicts.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If YAML cannot be parsed.
    """
    if not path.exists():
        msg = f"Layout registry not found: {path.resolve()}. Create the file under config/layouts/."
        raise FileNotFoundError(msg)

    text = path.read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"Failed to parse layout YAML in {path.resolve()}: {exc}."
        raise ValueError(msg) from exc

    if not isinstance(data, dict):
        msg = f"Expected mapping in {path.resolve()}, got {type(data).__name__}."
        raise ValueError(msg)

    # If the YAML has a top-level "layouts:" wrapper, extract the inner dict.
    if "layouts" in data and isinstance(data["layouts"], dict) and len(data) == 1:
        return data["layouts"]

    return data


def load_generation_config(path: Path) -> dict:
    """Load the master generation config.

    Args:
        path: Path to generation_config.yml.

    Returns:
        Config dict with document_types, degradation params, etc.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If YAML cannot be parsed or required keys missing.
    """
    if not path.exists():
        msg = (
            f"Generation config not found: {path.resolve()}. "
            f"Create config/generation_config.yml with 'document_types' mapping."
        )
        raise FileNotFoundError(msg)

    text = path.read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"Failed to parse config YAML in {path.resolve()}: {exc}."
        raise ValueError(msg) from exc

    required_keys = ["output_dir", "derived_dir", "ground_truth_dir", "document_types"]
    for key in required_keys:
        if key not in data:
            msg = f"Missing required key '{key}' in {path.resolve()}. Add '{key}:' to the config file."
            raise ValueError(msg)

    return data
