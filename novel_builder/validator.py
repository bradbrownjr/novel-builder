"""YAML validation for Novel Builder story files.

Produces structured error/warning/info results with file, dotted field path,
1-based line number, human-readable message, and a fix suggestion.

Usage:
    results = validate_all(outline_raw, outline_data,
                           char_raw, char_data,
                           loc_raw, loc_data)
    # results is a list of ValidationResult objects
"""

import yaml


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

class ValidationResult:
    """A single validation finding."""

    __slots__ = ("level", "source", "field", "line", "message", "suggestion")

    def __init__(self, level, source, field, message, suggestion=None, line=None):
        self.level = level          # "error" | "warning" | "info"
        self.source = source        # "outline" | "characters" | "locations" | "cross"
        self.field = field          # dotted path, e.g. "chapters[0].scenes[1].events"
        self.line = line            # 1-based line number, or None
        self.message = message
        self.suggestion = suggestion

    def to_dict(self):
        return {
            "level": self.level,
            "source": self.source,
            "field": self.field,
            "line": self.line,
            "message": self.message,
            "suggestion": self.suggestion,
        }

    def __repr__(self):
        loc = f" (line {self.line})" if self.line else ""
        return f"[{self.level.upper()}] {self.source}/{self.field}{loc}: {self.message}"


# ---------------------------------------------------------------------------
# Line index builder
# ---------------------------------------------------------------------------

def _build_line_index(raw_yaml_str):
    """Walk the YAML node tree and return a path → 1-based line number dict.

    Keys are dotted paths like 'chapters.0.scenes.1.events'.
    Returns an empty dict on any parse failure.
    """
    index = {}
    if not raw_yaml_str:
        return index

    def walk(node, path):
        if node is None:
            return
        index[path] = node.start_mark.line + 1  # 0-based → 1-based

        if isinstance(node, yaml.MappingNode):
            for key_node, val_node in node.value:
                key = key_node.value
                child_path = f"{path}.{key}" if path else key
                # Record the line of the key itself
                index[child_path] = key_node.start_mark.line + 1
                walk(val_node, child_path)

        elif isinstance(node, yaml.SequenceNode):
            for i, item_node in enumerate(node.value):
                child_path = f"{path}.{i}" if path else str(i)
                walk(item_node, child_path)

    try:
        root = yaml.compose(raw_yaml_str)
        if root:
            walk(root, "")
    except Exception:
        pass

    return index


def _line(index, *path_parts):
    """Look up line number for a dotted path, returning None if not found."""
    key = ".".join(str(p) for p in path_parts if p != "")
    return index.get(key)


def _iget(d, *keys):
    """Case-insensitive dict get. Returns the value for the first matching key.

    Checks each key as-is first, then lowercased against lowercased dict keys.
    Returns None if nothing matches or d is not a dict.
    """
    if not isinstance(d, dict):
        return None
    for key in keys:
        # Exact match first (fast path)
        if key in d:
            return d[key]
        # Case-insensitive fallback
        key_lower = key.lower()
        for k, v in d.items():
            if isinstance(k, str) and k.lower() == key_lower:
                return v
    return None


# ---------------------------------------------------------------------------
# Outline validation
# ---------------------------------------------------------------------------

_KNOWN_OUTLINE_KEYS = {
    "story_title", "overall_arc", "chapters", "style_directives",
    "anti_patterns", "narrative_hooks", "world", "characters",
    "heritage", "setting", "locations",
}


def validate_outline(data, raw_yaml_str=""):
    """Validate story_outline.yaml data.

    Args:
        data: Parsed YAML dict (may be None or wrong type).
        raw_yaml_str: Raw YAML text for line-number extraction.

    Returns:
        List of ValidationResult objects.
    """
    results = []
    idx = _build_line_index(raw_yaml_str)
    src = "outline"

    def err(field, msg, suggestion=None, line=None):
        results.append(ValidationResult("error", src, field, msg, suggestion, line))

    def warn(field, msg, suggestion=None, line=None):
        results.append(ValidationResult("warning", src, field, msg, suggestion, line))

    def info(field, msg, suggestion=None, line=None):
        results.append(ValidationResult("info", src, field, msg, suggestion, line))

    # Top-level type check
    if not isinstance(data, dict):
        err("(document)",
            f"Expected a YAML mapping at the top level, got {type(data).__name__}.",
            "The file must start with key: value pairs, not a list ('- item') or scalar.")
        return results

    # Required: story_title
    if not data.get("story_title"):
        err("story_title",
            "story_title is required.",
            "Add: story_title: \"Your Story Title\"",
            line=_line(idx, "story_title"))

    # Info: world
    if not data.get("world"):
        info("world",
             "world is not set — it is included in every scene's system prompt.",
             "Add: world: \"Time period, tech level, genre rules that apply everywhere.\"",
             line=_line(idx, "world"))

    # Unknown top-level keys
    for key in data:
        if key not in _KNOWN_OUTLINE_KEYS:
            warn(key,
                 f"Unrecognized top-level key '{key}' — it will be ignored.",
                 f"Did you mean one of: {', '.join(sorted(_KNOWN_OUTLINE_KEYS))}?",
                 line=_line(idx, key))

    # Required: chapters
    chapters = data.get("chapters")
    if chapters is None:
        err("chapters",
            "chapters is required but not present.",
            "Add a chapters: list with at least one chapter.",
            line=_line(idx, "chapters"))
        return results

    if not isinstance(chapters, list):
        err("chapters",
            f"chapters must be a list, got {type(chapters).__name__}.",
            "Use YAML list syntax:\nchapters:\n  - chapter_number: 1\n    ...",
            line=_line(idx, "chapters"))
        return results

    if len(chapters) == 0:
        err("chapters",
            "chapters list is empty — nothing to generate.",
            "Add at least one chapter with scenes.",
            line=_line(idx, "chapters"))
        return results

    # Per-chapter validation
    for ci, ch in enumerate(chapters):
        ch_base = f"chapters.{ci}"

        if not isinstance(ch, dict):
            err(f"chapters[{ci}]",
                f"Chapter {ci} is not a mapping — got {type(ch).__name__}.",
                "Each chapter must be a YAML mapping starting with chapter_number:.",
                line=_line(idx, ch_base))
            continue

        ch_num = ch.get("chapter_number", ci + 1)
        label = f"Ch {ch_num}"

        if ch.get("chapter_number") is None:
            warn(f"chapters[{ci}].chapter_number",
                 f"{label}: chapter_number is missing — position {ci + 1} will be used.",
                 "Add: chapter_number: " + str(ci + 1),
                 line=_line(idx, ch_base, "chapter_number"))

        if not ch.get("title"):
            warn(f"chapters[{ci}].title",
                 f"{label}: title is missing.",
                 "Add: title: \"Chapter Title\"",
                 line=_line(idx, ch_base, "title"))

        if not ch.get("summary"):
            warn(f"chapters[{ci}].summary",
                 f"{label}: summary is missing — this guides the AI's chapter-level intent.",
                 "Add a brief summary of what happens in this chapter.",
                 line=_line(idx, ch_base, "summary"))

        scenes = ch.get("scenes")
        if scenes is None:
            err(f"chapters[{ci}].scenes",
                f"{label}: scenes is missing.",
                "Add a scenes: list with at least one scene.",
                line=_line(idx, ch_base, "scenes"))
            continue

        if not isinstance(scenes, list):
            err(f"chapters[{ci}].scenes",
                f"{label}: scenes must be a list, got {type(scenes).__name__}.",
                line=_line(idx, ch_base, "scenes"))
            continue

        if len(scenes) == 0:
            err(f"chapters[{ci}].scenes",
                f"{label}: scenes list is empty — at least one scene is required.",
                line=_line(idx, ch_base, "scenes"))
            continue

        # Per-scene validation
        for si, sc in enumerate(scenes):
            sc_base = f"chapters.{ci}.scenes.{si}"

            if not isinstance(sc, dict):
                err(f"chapters[{ci}].scenes[{si}]",
                    f"{label}, scene {si}: not a mapping.",
                    "Each scene must be a YAML mapping starting with scene_number:.",
                    line=_line(idx, sc_base))
                continue

            sc_num = sc.get("scene_number", f"{ch_num}.{si + 1}")
            sc_label = f"Ch {ch_num} Sc {sc_num}"

            if sc.get("scene_number") is None:
                warn(f"chapters[{ci}].scenes[{si}].scene_number",
                     f"{sc_label}: scene_number is missing.",
                     f"Add: scene_number: {ch_num}.{si + 1}",
                     line=_line(idx, sc_base, "scene_number"))

            if not sc.get("events"):
                err(f"chapters[{ci}].scenes[{si}].events",
                    f"{sc_label}: events is required — it tells the AI what happens.",
                    "Add: events: \"What happens in this scene.\"",
                    line=_line(idx, sc_base, "events"))

            if not sc.get("setting"):
                warn(f"chapters[{ci}].scenes[{si}].setting",
                     f"{sc_label}: setting is missing — the AI will have no location context.",
                     "Add: setting: \"Location description or location ID from locations.yaml\"",
                     line=_line(idx, sc_base, "setting"))

    return results


# ---------------------------------------------------------------------------
# Characters validation
# ---------------------------------------------------------------------------

def validate_characters(data, raw_yaml_str=""):
    """Validate characters.yaml data.

    Args:
        data: Parsed YAML dict.
        raw_yaml_str: Raw YAML text for line-number extraction.

    Returns:
        List of ValidationResult objects.
    """
    results = []
    idx = _build_line_index(raw_yaml_str)
    src = "characters"

    def err(field, msg, suggestion=None, line=None):
        results.append(ValidationResult("error", src, field, msg, suggestion, line))

    def warn(field, msg, suggestion=None, line=None):
        results.append(ValidationResult("warning", src, field, msg, suggestion, line))

    if not isinstance(data, dict):
        err("(document)",
            f"Expected a YAML mapping at the top level, got {type(data).__name__}.",
            "The file must start with 'characters:' or character id keys.")
        return results

    # Support both top-level 'characters:' key and bare character IDs
    chars = data.get("characters", data)
    if not isinstance(chars, dict):
        err("characters",
            f"characters must be a mapping of id → character data, got {type(chars).__name__}.",
            "Format:\ncharacters:\n  hero:\n    Name: Jane\n    vibe: \"...\"")
        return results

    if len(chars) == 0:
        warn("characters",
             "No characters defined.",
             "Add at least one character with Name and vibe.")
        return results

    for cid, cdata in chars.items():
        base = f"characters.{cid}"
        if not isinstance(cdata, dict):
            err(f"characters.{cid}",
                f"Character '{cid}' is not a mapping.",
                "Each character must be a YAML mapping with Name, vibe, etc.",
                line=_line(idx, base))
            continue

        if not _iget(cdata, "Name", "name"):
            err(f"characters.{cid}.Name",
                f"Character '{cid}' is missing Name.",
                "Add: Name: \"Full Name\"",
                line=_line(idx, base, "Name") or _line(idx, base))

        if not _iget(cdata, "vibe"):
            warn(f"characters.{cid}.vibe",
                 f"Character '{cid}' is missing vibe — this has the highest impact on output quality.",
                 "Add: vibe: \"How this character feels to the reader in one sentence.\"",
                 line=_line(idx, base, "vibe") or _line(idx, base))

        if not _iget(cdata, "role"):
            warn(f"characters.{cid}.role",
                 f"Character '{cid}' is missing role — used in scene reminders.",
                 "Add: role: \"Protagonist\" (or Antagonist, Supporting, etc.)",
                 line=_line(idx, base, "role") or _line(idx, base))

    return results


# ---------------------------------------------------------------------------
# Locations validation
# ---------------------------------------------------------------------------

def validate_locations(data, raw_yaml_str=""):
    """Validate locations/settings YAML data.

    Args:
        data: Parsed YAML dict.
        raw_yaml_str: Raw YAML text.

    Returns:
        List of ValidationResult objects.
    """
    results = []
    idx = _build_line_index(raw_yaml_str)
    src = "locations"

    def warn(field, msg, suggestion=None, line=None):
        results.append(ValidationResult("warning", src, field, msg, suggestion, line))

    if not isinstance(data, dict):
        results.append(ValidationResult(
            "error", src, "(document)",
            f"Expected a YAML mapping, got {type(data).__name__}.",
            "Use 'setting:' or 'locations:' as the top-level key."))
        return results

    locs = data.get("setting", data.get("locations", data))
    if not isinstance(locs, dict) or len(locs) == 0:
        warn("(document)",
             "No locations defined.",
             "Locations are optional — inline setting descriptions in scenes also work.")
        return results

    for lid, ldata in locs.items():
        if lid in ("setting", "locations"):
            continue
        if not isinstance(ldata, dict):
            continue
        base = f"setting.{lid}"
        if not _iget(ldata, "atmosphere") and not _iget(ldata, "description"):
            warn(f"setting.{lid}",
                 f"Location '{lid}' has no atmosphere or description — the AI will have minimal context.",
                 "Add: atmosphere: \"Sensory impression of the space.\"",
                 line=_line(idx, base))

    return results


# ---------------------------------------------------------------------------
# Cross-reference validation
# ---------------------------------------------------------------------------

_INLINE_SETTING_RE = r"[ ,.]"   # Has spaces/punctuation → definitely inline prose


def validate_cross_references(outline_data, char_data, loc_data):
    """Check references across files.

    - characters_present IDs that don't exist in characters
    - Named setting IDs that don't exist in locations

    Args:
        outline_data: Parsed outline dict.
        char_data: Parsed characters dict.
        loc_data: Parsed locations dict.

    Returns:
        List of ValidationResult objects.
    """
    results = []
    import re

    if not isinstance(outline_data, dict):
        return results

    # Build known character IDs
    chars = {}
    if isinstance(char_data, dict):
        chars = char_data.get("characters", char_data)
    known_chars = set(chars.keys()) if isinstance(chars, dict) else set()

    # Build known location IDs
    locs = {}
    if isinstance(loc_data, dict):
        locs = loc_data.get("setting", loc_data.get("locations", loc_data))
    known_locs = set(locs.keys()) if isinstance(locs, dict) else set()

    chapters = outline_data.get("chapters") or []
    if not isinstance(chapters, list):
        return results

    for ci, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        ch_num = ch.get("chapter_number", ci + 1)
        scenes = ch.get("scenes") or []
        if not isinstance(scenes, list):
            continue

        for si, sc in enumerate(scenes):
            if not isinstance(sc, dict):
                continue
            sc_num = sc.get("scene_number", f"{ch_num}.{si + 1}")
            label = f"Ch {ch_num} Sc {sc_num}"

            # Check characters_present references
            chars_present = sc.get("characters_present") or []
            if isinstance(chars_present, list) and known_chars:
                for cref in chars_present:
                    if isinstance(cref, str) and cref not in known_chars:
                        results.append(ValidationResult(
                            "warning", "cross",
                            f"chapters[{ci}].scenes[{si}].characters_present",
                            f"{label}: character ID '{cref}' not found in characters file.",
                            f"Add '{cref}' to characters.yaml or correct the spelling."))

            # Check named setting references
            setting = sc.get("setting", "")
            if (isinstance(setting, str)
                    and setting
                    and known_locs
                    and not re.search(_INLINE_SETTING_RE, setting)
                    and setting not in known_locs):
                results.append(ValidationResult(
                    "warning", "cross",
                    f"chapters[{ci}].scenes[{si}].setting",
                    f"{label}: setting ID '{setting}' not found in locations file.",
                    f"Add '{setting}' to locations.yaml, or use a full description string instead."))

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def validate_all(outline_raw, outline_data,
                 char_raw=None, char_data=None,
                 loc_raw=None, loc_data=None):
    """Run all validators and return a combined list of ValidationResult objects.

    Args:
        outline_raw: Raw outline YAML string (for line numbers).
        outline_data: Parsed outline dict.
        char_raw: Raw characters YAML string.
        char_data: Parsed characters dict.
        loc_raw: Raw locations YAML string.
        loc_data: Parsed locations dict.

    Returns:
        List of ValidationResult objects sorted by (source, line).
    """
    results = []

    if outline_data is not None:
        results.extend(validate_outline(outline_data, outline_raw or ""))

    if char_data is not None:
        results.extend(validate_characters(char_data, char_raw or ""))

    if loc_data is not None:
        results.extend(validate_locations(loc_data, loc_raw or ""))

    if outline_data is not None and (char_data is not None or loc_data is not None):
        results.extend(validate_cross_references(
            outline_data,
            char_data or {},
            loc_data or {}))

    # Sort: errors first, then by source, then by line number
    level_order = {"error": 0, "warning": 1, "info": 2}
    results.sort(key=lambda r: (level_order.get(r.level, 9), r.source, r.line or 9999))

    return results
