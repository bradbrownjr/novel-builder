"""Configuration loading, defaults, and YAML file discovery."""

import os

from .yaml_io import load_yaml, load_yaml_optional


# Top-level keys recognized in combined YAML files
_OUTLINE_KEYS = {"story_title", "overall_arc", "chapters", "style_directives",
                 "anti_patterns", "narrative_hooks", "world"}
_CHARACTER_KEYS = {"characters"}
_LOCATION_KEYS = {"setting", "locations"}
_HERITAGE_KEYS = {"heritage"}

# Default filenames to search for
_OUTLINE_CANDIDATES = ["story_outline.yaml", "story_outline.yml"]
_CHARACTER_CANDIDATES = ["characters.yaml", "characters.yml"]
_LOCATION_CANDIDATES = ["locations.yaml", "locations.yml",
                        "settings.yaml", "settings.yml"]
_COMBINED_CANDIDATES = ["story_data.yaml", "story_data.yml"]


def _find_file(candidates):
    """Return the first existing file from a list of candidates, or None."""
    for name in candidates:
        if os.path.exists(name):
            return name
    return None


def discover_yaml_files(args):
    """Discover YAML files based on CLI args or auto-discovery.

    Supports both separate files and a single combined file.

    Args:
        args: Parsed argparse.Namespace with outline, characters, locations.

    Returns:
        Tuple of (outline_path, characters_path, locations_path).
        Any may be None if not found (locations are optional).
    """
    outline = args.outline
    characters = args.characters
    locations = args.locations

    # Check for combined file first
    combined = _find_file(_COMBINED_CANDIDATES)

    if not outline:
        outline = _find_file(_OUTLINE_CANDIDATES) or combined
    if not characters:
        characters = _find_file(_CHARACTER_CANDIDATES) or combined
    if not locations:
        locations = _find_file(_LOCATION_CANDIDATES) or combined

    return outline, characters, locations


def load_config(args):
    """Load all story configuration from discovered YAML files.

    Args:
        args: Parsed argparse.Namespace.

    Returns:
        dict with keys:
            story_title, overall_arc, style_directives, world,
            anti_patterns, narrative_hooks, chapters,
            characters, heritage, settings, raw_outline
    """
    outline_path, char_path, loc_path = discover_yaml_files(args)

    # Load outline (required)
    if not outline_path:
        print("Error: No story outline found. Provide --outline or create "
              "story_outline.yaml / story_data.yaml.")
        raise SystemExit(1)
    outline_data = load_yaml(outline_path)

    # Load characters
    if char_path and char_path != outline_path:
        char_data = load_yaml(char_path)
    else:
        char_data = outline_data

    # Load locations (optional)
    if loc_path and loc_path != outline_path and loc_path != char_path:
        loc_data = load_yaml_optional(loc_path)
    elif loc_path:
        loc_data = load_yaml(loc_path) if loc_path == outline_path else char_data
    else:
        loc_data = {}

    # Extract config from potentially combined sources
    config = {
        # Outline fields
        "story_title": outline_data.get("story_title", "Untitled"),
        "overall_arc": outline_data.get("overall_arc", {}),
        "pov_character": outline_data.get("pov_character", ""),
        "style_directives": outline_data.get("style_directives", ""),
        "world": outline_data.get("world", ""),
        "anti_patterns": outline_data.get("anti_patterns", []),
        "narrative_hooks": outline_data.get("narrative_hooks", []),
        "chapters": outline_data.get("chapters", []),

        # Characters — check both sources
        "characters": (char_data.get("characters", {})
                       if "characters" in char_data
                       else outline_data.get("characters", {})),

        # Heritage — can live in characters file, outline, or standalone
        "heritage": (char_data.get("heritage", {})
                     or outline_data.get("heritage", {})),

        # Settings — check 'setting' and 'locations' keys
        "settings": _extract_settings(loc_data, outline_data, char_data),

        # Keep raw outline for reference
        "raw_outline": outline_data,
    }

    return config


def _extract_settings(*sources):
    """Extract settings/locations from multiple potential sources.

    Checks for both 'setting' and 'locations' top-level keys.
    """
    for source in sources:
        if not source:
            continue
        for key in ("setting", "locations"):
            if key in source:
                return source[key]
    return {}
