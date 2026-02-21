"""Location/setting loading and resolution."""


def load_locations(config):
    """Return the settings/locations dict from loaded config.

    Args:
        config: Dict from config.load_config().

    Returns:
        Dict of location_id -> location_data.
    """
    return config.get("settings", {})


def resolve_location(setting_ref, locations):
    """Resolve a scene's setting reference to full location data.

    If the reference matches a location ID, return that location's data.
    If it's an inline string description, return it wrapped in a dict.

    Args:
        setting_ref: Scene's setting field — either a location ID or a
                     freeform description string.
        locations: Dict of location_id -> location_data.

    Returns:
        Dict with location details. At minimum contains 'description'.
    """
    if not setting_ref:
        return {"description": "Unspecified location."}

    # Check if it's a reference to a defined location
    if isinstance(setting_ref, str) and setting_ref in locations:
        loc = locations[setting_ref]
        if isinstance(loc, dict):
            return loc
        # Unlikely but handle string-valued locations
        return {"description": str(loc)}

    # Inline description string
    return {"description": str(setting_ref)}


def format_location_for_prompt(location_data, mood_key=None):
    """Format location data into a readable string for the prompt.

    Args:
        location_data: Dict of location fields.
        mood_key: Optional mood_shift key (e.g., 'night', 'storm') to
                  include variant atmosphere.

    Returns:
        Formatted string describing the location.
    """
    if not location_data:
        return ""

    parts = []

    # Type / classification
    if location_data.get("type"):
        parts.append(f"Location type: {location_data['type']}")

    # Main description
    if location_data.get("description"):
        parts.append(location_data["description"])

    # Atmosphere
    if location_data.get("atmosphere"):
        parts.append(f"Atmosphere: {location_data['atmosphere']}")

    # Mood shift variant
    if mood_key and "mood_shift" in location_data:
        shift = location_data["mood_shift"].get(mood_key)
        if shift:
            parts.append(f"Current mood: {shift}")

    # Any other string/list fields (sub-areas, details, etc.)
    _skip = {"type", "description", "atmosphere", "mood_shift"}
    for key, value in location_data.items():
        if key in _skip:
            continue
        if isinstance(value, str):
            parts.append(f"{key.replace('_', ' ').title()}: {value}")
        elif isinstance(value, list):
            items = "; ".join(str(v) for v in value)
            parts.append(f"{key.replace('_', ' ').title()}: {items}")
        elif isinstance(value, dict):
            # Nested sub-area — include key-value pairs
            for sub_key, sub_val in value.items():
                parts.append(f"  {sub_key}: {sub_val}")

    return "\n".join(parts)
