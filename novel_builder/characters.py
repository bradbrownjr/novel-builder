"""Character loading, filtering, heritage merging, evolution, and catch phrases."""

import random
import re


# Catch phrase frequency probabilities
_FREQUENCY_ODDS = {
    "rare": 1 / 8,
    "occasional": 1 / 4,
    "frequent": 1 / 2,
}
_DEFAULT_FREQUENCY = "occasional"


def load_characters(config):
    """Return the characters dict from loaded config.

    Args:
        config: Dict from config.load_config().

    Returns:
        Dict of character_id -> character_data.
    """
    return config.get("characters", {})


def auto_detect_characters(text, characters):
    """Scan text for mentions of character IDs or Names.

    Args:
        text: Text to scan (scene events, notes, etc.).
        characters: Dict of character_id -> character_data.

    Returns:
        List of detected character IDs.
    """
    detected = set()
    for char_id, info in characters.items():
        search_terms = [char_id]
        if isinstance(info, dict):
            name = info.get("Name") or info.get("name", "")
            if name:
                search_terms.append(name)

        for term in search_terms:
            pattern = rf"\b{re.escape(term)}\b"
            if re.search(pattern, text, re.IGNORECASE):
                detected.add(char_id)
                break

    return list(detected)


def filter_for_scene(characters, present_ids):
    """Return only characters whose IDs are in the present list.

    Args:
        characters: Full characters dict.
        present_ids: List of character IDs present in the scene.

    Returns:
        Dict of character_id -> character_data for present characters.
    """
    return {k: v for k, v in characters.items() if k in present_ids}


def merge_heritage(character, heritage_defs):
    """Merge heritage traits into a character's data for first appearance.

    Heritage fields are merged in list order. Character-level fields
    always override heritage fields.

    Args:
        character: Dict of character fields.
        heritage_defs: Dict of heritage_id -> heritage_data from config.

    Returns:
        Dict with heritage traits merged in. Original dict is not mutated.
    """
    heritage_refs = character.get("heritage", [])
    if not heritage_refs or not heritage_defs:
        return character

    # Normalize to list
    if isinstance(heritage_refs, str):
        heritage_refs = [heritage_refs]

    # Merge heritage entries in order
    merged_traits = {}
    for ref_id in heritage_refs:
        heritage = heritage_defs.get(ref_id, {})
        if not heritage:
            continue
        for key in ("traits", "speech_patterns", "cultural_notes"):
            if key in heritage:
                merged_traits[key] = heritage[key]
        # Also grab the label for context
        if "label" in heritage:
            merged_traits.setdefault("heritage_labels", [])
            merged_traits["heritage_labels"].append(heritage["label"])

    # Character fields override heritage
    result = dict(merged_traits)
    result.update(character)

    return result


def build_character_context(char_id, character, heritage_defs,
                            appearance_history, current_chapter):
    """Build the prompt context for a character based on appearance tier.

    First appearance: full bio + heritage traits.
    Subsequent: slim reminder + evolution notes.

    Args:
        char_id: Character ID string.
        character: Character data dict.
        heritage_defs: Heritage definitions dict.
        appearance_history: Dict of char_id -> list of scene IDs from checkpoint.
        current_chapter: Current chapter number.

    Returns:
        Dict of fields to include in the prompt for this character.
    """
    first_appearance = char_id not in appearance_history

    if first_appearance:
        # Full bio with heritage merged
        merged = merge_heritage(character, heritage_defs)
        context = {}

        # Always included
        context["Name"] = merged.get("Name") or merged.get("name", char_id)
        context["role"] = merged.get("role", "")
        context["vibe"] = merged.get("vibe", "")

        # First appearance extras
        context["summary"] = merged.get("summary", "")
        context["personality"] = merged.get("personality", [])

        # Always if present — physical/nature facts that must never drift
        if merged.get("species"):
            context["species"] = merged["species"]
        if merged.get("appearance"):
            context["appearance"] = merged["appearance"]
        if merged.get("voice"):
            context["voice"] = merged["voice"]
        if merged.get("habit"):
            context["habit"] = merged["habit"]

        # Heritage traits (first appearance only)
        if merged.get("traits"):
            context["heritage_traits"] = merged["traits"]
        if merged.get("speech_patterns"):
            context["heritage_speech"] = merged["speech_patterns"]
        if merged.get("cultural_notes"):
            context["cultural_notes"] = merged["cultural_notes"]
        if merged.get("heritage_labels"):
            context["heritage"] = ", ".join(merged["heritage_labels"])

    else:
        # Reminder tier
        context = {}
        context["Name"] = character.get("Name") or character.get("name", char_id)
        context["role"] = character.get("role", "")
        context["vibe"] = character.get("vibe", "")

        # Always — physical/nature facts that must never drift
        if character.get("species"):
            context["species"] = character["species"]
        if character.get("appearance"):
            context["appearance"] = character["appearance"]
        if character.get("voice"):
            context["voice"] = character["voice"]
        if character.get("habit"):
            context["habit"] = character["habit"]

    # Evolution notes — accumulated up to current chapter
    evolution = get_evolution_context(character, current_chapter)
    if evolution:
        context["character_development"] = evolution

    return context


def get_evolution_context(character, current_chapter):
    """Get accumulated evolution notes up to the current chapter.

    Args:
        character: Character data dict.
        current_chapter: Current chapter number.

    Returns:
        String of accumulated evolution notes, or empty string.
    """
    evolution = character.get("evolution", [])
    if not evolution:
        return ""

    notes = []
    for entry in evolution:
        after_ch = entry.get("after_chapter", 0)
        if after_ch < current_chapter:
            notes.append(entry.get("note", ""))

    return " ".join(notes) if notes else ""


def should_include_catchphrase(character):
    """Roll probability check for catch phrase inclusion.

    Args:
        character: Character data dict.

    Returns:
        Tuple of (include: bool, phrase: str or None).
    """
    # Check for list format first
    catchphrases = character.get("catchphrases", [])
    if catchphrases:
        results = []
        for entry in catchphrases:
            freq = entry.get("frequency", _DEFAULT_FREQUENCY)
            odds = _FREQUENCY_ODDS.get(freq, _FREQUENCY_ODDS[_DEFAULT_FREQUENCY])
            if random.random() < odds:
                results.append(entry.get("phrase", ""))
        if results:
            return True, random.choice(results)
        return False, None

    # Simple string format
    phrase = character.get("catchphrase", "")
    if not phrase:
        return False, None

    freq = character.get("catchphrase_frequency", _DEFAULT_FREQUENCY)
    odds = _FREQUENCY_ODDS.get(freq, _FREQUENCY_ODDS[_DEFAULT_FREQUENCY])

    if random.random() < odds:
        return True, phrase
    return False, None


def should_include_secret(character, scene_notes):
    """Determine if a character's secret should be included.

    Included when scene notes reference tension, subtext, or secrets.

    Args:
        character: Character data dict.
        scene_notes: Scene notes string.

    Returns:
        The secret string if it should be included, else None.
    """
    secret = character.get("secret", "")
    if not secret or not scene_notes:
        return None

    tension_keywords = ["tension", "subtext", "secret", "hidden", "reveal",
                        "confront", "truth", "lie", "suspicion", "distrust"]
    notes_lower = scene_notes.lower()
    for keyword in tension_keywords:
        if keyword in notes_lower:
            return secret
    return None


def get_relevant_relationships(character, present_ids):
    """Get relationships between this character and others present in scene.

    Args:
        character: Character data dict.
        present_ids: List of character IDs present in the scene.

    Returns:
        Dict of character_id -> relationship description, or empty dict.
    """
    relationships = character.get("relationships", {})
    if not relationships or not isinstance(relationships, dict):
        return {}

    return {k: v for k, v in relationships.items() if k in present_ids}
