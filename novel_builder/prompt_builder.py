"""System and user prompt construction per scene.

This module builds the prompts sent to the generation model. It follows
the Context Budget principle: every token costs quality, so only include
information the AI needs for the current scene.
"""

from .characters import (
    auto_detect_characters,
    build_character_context,
    filter_for_scene,
    get_relevant_relationships,
    should_include_catchphrase,
    should_include_secret,
)
from .locations import resolve_location, format_location_for_prompt
from .state import get_relevant_memory


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def build_system_prompt(config):
    """Build the system prompt for the generation model.

    Includes world context, style directives, and anti-pattern suppression.
    This prompt is consistent across all scenes.

    Args:
        config: Story configuration dict from load_config().

    Returns:
        System prompt string.
    """
    parts = [
        "You are an expert fiction author writing a novel. "
        "Write vivid, immersive prose with natural dialogue. "
        "Show, don't tell. Maintain consistent characterization."
    ]

    # World context (era, tech level, genre rules)
    world = config.get("world", "")
    if world:
        parts.append(f"\nWorld context: {world}")

    # Style directives from YAML
    style = config.get("style_directives", "")
    if style:
        if isinstance(style, list):
            style = " ".join(style)
        parts.append(f"\nStyle: {style}")

    # Overall arc context (genre, tone, themes)
    arc = config.get("overall_arc", {})
    if isinstance(arc, dict):
        if arc.get("genre"):
            parts.append(f"\nGenre: {arc['genre']}")
        if arc.get("tone"):
            parts.append(f"Tone: {arc['tone']}")
        if arc.get("themes"):
            themes = arc["themes"]
            if isinstance(themes, list):
                themes = ", ".join(themes)
            parts.append(f"Themes: {themes}")
    elif isinstance(arc, str) and arc:
        parts.append(f"\nStory arc: {arc}")

    # Anti-pattern suppression
    anti_patterns = config.get("anti_patterns", [])
    if anti_patterns:
        patterns_str = "; ".join(anti_patterns[:15])  # Cap list size
        parts.append(
            f"\nIMPORTANT — Avoid these overused phrases and patterns: "
            f"{patterns_str}. "
            "Use fresh, original language instead."
        )

    # Do NOT impose word count
    parts.append(
        "\nDo not include scene headers, titles, or meta-commentary. "
        "Write only the narrative prose."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Scene prompt
# ---------------------------------------------------------------------------

def build_scene_prompt(config, chapter, scene, state, heritage_defs,
                       all_characters, locations, chapter_num):
    """Build the user prompt for a specific scene.

    Includes: scene description, character context (tiered), location,
    narrative hooks, story memory, recent summaries, pacing hints.

    Args:
        config: Story configuration dict.
        chapter: Current chapter dict from the outline.
        scene: Current scene dict from the chapter.
        state: Checkpoint state dict.
        heritage_defs: Heritage definitions dict.
        all_characters: Full characters dict.
        locations: Locations dict.
        chapter_num: Current chapter number (1-based).

    Returns:
        User prompt string.
    """
    parts = []

    # -- Chapter context --
    ch_title = chapter.get("title", f"Chapter {chapter_num}")
    ch_summary = chapter.get("summary", "")
    parts.append(f"=== Chapter {chapter_num}: {ch_title} ===")
    if ch_summary:
        parts.append(f"Chapter arc: {ch_summary}")

    # Per-chapter style override
    ch_style = chapter.get("style_override", "")
    if ch_style:
        parts.append(f"Style for this chapter: {ch_style}")

    # -- Scene description --
    scene_num = scene.get("scene_number", "")
    scene_events = scene.get("events", "")
    scene_notes = scene.get("notes", "")
    scene_pov = scene.get("pov", "")
    scene_pacing = scene.get("pacing", "")
    scene_mood = scene.get("mood", "")

    parts.append(f"\n--- Scene {scene_num} ---")
    if scene_events:
        parts.append(f"What happens: {scene_events}")
    if scene_notes:
        parts.append(f"Notes: {scene_notes}")
    if scene_pov:
        parts.append(f"POV: {scene_pov}")
    if scene_pacing:
        parts.append(f"Pacing: {scene_pacing}")
    if scene_mood:
        parts.append(f"Mood: {scene_mood}")

    # -- Location --
    setting_ref = scene.get("setting", "")
    if setting_ref:
        location = resolve_location(setting_ref, locations)
        mood_key = scene.get("mood_shift_key", None)
        loc_text = format_location_for_prompt(location, mood_key)
        if loc_text:
            parts.append(f"\nSetting:\n{loc_text}")

    # -- Character context --
    char_block = _build_character_block(
        scene, all_characters, heritage_defs,
        state.get("character_appearances", {}),
        chapter_num,
    )
    if char_block:
        parts.append(f"\nCharacters in this scene:\n{char_block}")

    # -- Narrative hooks --
    hook_text = _get_relevant_hook(config, scene)
    if hook_text:
        parts.append(f"\nNarrative hook: {hook_text}")

    # -- Story memory (relevant remembered details) --
    scan_text = f"{scene_events} {scene_notes}"
    memory = get_relevant_memory(state, scan_text)
    memory_text = _format_story_memory(memory)
    if memory_text:
        parts.append(f"\nEstablished details:\n{memory_text}")

    # -- Recent scene summaries (continuity) --
    recent = state.get("recent_scenes", [])
    if recent:
        parts.append("\nRecent events:")
        for entry in recent:
            parts.append(f"  - {entry.get('summary', '')}")

    # -- Story so far (condensed) --
    story_so_far = state.get("story_so_far", "")
    if story_so_far:
        # Truncate if very long — keep the essentials
        max_len = 1500
        if len(story_so_far) > max_len:
            story_so_far = story_so_far[-max_len:]
            # Trim to sentence boundary
            first_period = story_so_far.find(". ")
            if first_period > 0:
                story_so_far = story_so_far[first_period + 2:]
        parts.append(f"\nStory so far: {story_so_far}")

    parts.append("\nWrite this scene now.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Summary prompt
# ---------------------------------------------------------------------------

def build_summary_prompt(scene_text):
    """Build the prompt for the summary model.

    This is a thin wrapper — the actual system prompt lives in
    ollama_client.call_summary_model(). This builds just the user side.

    Args:
        scene_text: The generated scene text.

    Returns:
        User prompt string for the summary model.
    """
    return f"Analyze this scene:\n\n{scene_text}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_character_block(scene, all_characters, heritage_defs,
                           appearance_history, chapter_num):
    """Build the character context section for a scene prompt.

    Args:
        scene: Scene dict.
        all_characters: Full characters dict.
        heritage_defs: Heritage definitions dict.
        appearance_history: Dict of char_id -> list of scene IDs.
        chapter_num: Current chapter number.

    Returns:
        Formatted character context string.
    """
    # Determine which characters are in this scene
    explicit_chars = scene.get("characters", [])
    scene_text = f"{scene.get('events', '')} {scene.get('notes', '')}"

    if explicit_chars:
        present_ids = list(explicit_chars)
    else:
        present_ids = auto_detect_characters(scene_text, all_characters)

    if not present_ids:
        return ""

    present = filter_for_scene(all_characters, present_ids)
    scene_notes = scene.get("notes", "")

    blocks = []
    for char_id, char_data in present.items():
        context = build_character_context(
            char_id, char_data, heritage_defs,
            appearance_history, chapter_num,
        )

        lines = []
        name = context.get("Name", char_id)
        role = context.get("role", "")
        lines.append(f"**{name}** ({role})" if role else f"**{name}**")

        # Vibe — always
        if context.get("vibe"):
            lines.append(f"  Vibe: {context['vibe']}")

        # Summary (first appearance only)
        if context.get("summary"):
            lines.append(f"  Background: {context['summary']}")

        # Personality (first appearance only)
        if context.get("personality"):
            traits = context["personality"]
            if isinstance(traits, list):
                traits = ", ".join(traits)
            lines.append(f"  Personality: {traits}")

        # Heritage info (first appearance only)
        if context.get("heritage"):
            lines.append(f"  Heritage: {context['heritage']}")
        if context.get("heritage_traits"):
            traits = context["heritage_traits"]
            if isinstance(traits, list):
                traits = ", ".join(traits)
            lines.append(f"  Heritage traits: {traits}")
        if context.get("heritage_speech"):
            lines.append(f"  Speech patterns: {context['heritage_speech']}")

        # Voice — always when present
        if context.get("voice"):
            lines.append(f"  Voice: {context['voice']}")

        # Habit
        if context.get("habit"):
            lines.append(f"  Habit: {context['habit']}")

        # Catch phrase — probability gated
        include_phrase, phrase = should_include_catchphrase(char_data)
        if include_phrase and phrase:
            lines.append(
                f"  Catch phrase (use naturally, max once): \"{phrase}\""
            )

        # Secret — only when scene has tension/subtext
        secret = should_include_secret(char_data, scene_notes)
        if secret:
            lines.append(
                f"  Hidden knowledge: {secret} (show through subtext, "
                f"don't explicitly reveal)"
            )

        # Relationships with present characters
        relationships = get_relevant_relationships(char_data, present_ids)
        if relationships:
            for other_id, rel_desc in relationships.items():
                other_name = present.get(other_id, {}).get("Name", other_id)
                lines.append(f"  Relationship with {other_name}: {rel_desc}")

        # Evolution / character development
        if context.get("character_development"):
            lines.append(
                f"  Recent development: {context['character_development']}"
            )

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _get_relevant_hook(config, scene):
    """Find the narrative hook relevant to this scene, if any.

    Args:
        config: Story configuration dict.
        scene: Current scene dict.

    Returns:
        Hook description string, or empty string.
    """
    hooks = config.get("narrative_hooks", [])
    if not hooks:
        return ""

    # Scene can reference a hook by name
    hook_ref = scene.get("hook", "")
    if not hook_ref:
        return ""

    for hook in hooks:
        if isinstance(hook, dict):
            hook_name = hook.get("name", "")
            if hook_name.lower() == hook_ref.lower():
                return hook.get("description", hook_name)
        elif isinstance(hook, str) and hook.lower() == hook_ref.lower():
            return hook

    return ""


def _format_story_memory(memory):
    """Format relevant story memory entries for the prompt.

    Args:
        memory: Dict with 'characters', 'facts', 'commitments'.

    Returns:
        Formatted string, or empty string if nothing relevant.
    """
    parts = []

    chars = memory.get("characters", {})
    if chars:
        for char_id, data in chars.items():
            name = data.get("name", char_id)
            desc = data.get("description", "")
            notes = data.get("notes", "")
            detail = desc or notes
            if detail:
                parts.append(f"  - Previously established: {name} — {detail}")

    facts = memory.get("facts", [])
    for fact in facts[:5]:  # Cap to keep prompt manageable
        detail = fact.get("detail", "")
        if detail:
            parts.append(f"  - Established fact: {detail}")

    commitments = memory.get("commitments", [])
    for commit in commitments[:3]:
        detail = commit.get("detail", "")
        if detail:
            parts.append(f"  - Commitment: {detail}")

    return "\n".join(parts)
