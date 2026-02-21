"""YAML loading and saving utilities."""

import os
import sys

import yaml


def load_yaml(filepath):
    """Load a YAML file and return its contents as a dict.

    Args:
        filepath: Path to the YAML file.

    Returns:
        Parsed YAML data as a dict, or empty dict if file is empty.

    Raises:
        SystemExit: If the file does not exist or cannot be parsed.
    """
    if not os.path.exists(filepath):
        print(f"Error: Required file '{filepath}' not found.")
        sys.exit(1)
    try:
        with open(filepath, "r") as f:
            data = yaml.safe_load(f)
        return data if data is not None else {}
    except yaml.YAMLError as e:
        print(f"Error: Failed to parse '{filepath}': {e}")
        sys.exit(1)


def save_yaml(filepath, data):
    """Save a dict to a YAML file.

    Args:
        filepath: Path to write.
        data: Dict to serialize.
    """
    with open(filepath, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True,
                  sort_keys=False)


def load_yaml_optional(filepath):
    """Load a YAML file if it exists, otherwise return empty dict.

    Args:
        filepath: Path to the YAML file.

    Returns:
        Parsed YAML data as a dict, or empty dict if file doesn't exist.
    """
    if not os.path.exists(filepath):
        return {}
    return load_yaml(filepath)
