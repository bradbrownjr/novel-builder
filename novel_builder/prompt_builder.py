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
from .state import get_relevant_memory, get_used_imagery, get_overused_words


# ---------------------------------------------------------------------------
# Default anti-patterns — always included in the system prompt
# ---------------------------------------------------------------------------

_DEFAULT_PROMPT_ANTI_PATTERNS = [
    "purple prose or overwrought descriptions",
    "emoji or emoticons",
    "excessive em-dashes",
    '"delve", "tapestry", "unbeknownst", "palpable"',
    '"a single tear" or similar melodramatic physical cues',
    '"let out a breath they didn\'t know they were holding"',
    '"little did they know", "everything changed", "in that moment"',
    '"time seemed to stop" or "time stood still"',
    '"sent shivers down" or "a chill ran down"',
    '"whispered softly" or other redundant adverbs',
]


def _merge_anti_patterns(user_patterns):
    """Merge user-defined anti-patterns with built-in defaults.

    Deduplicates by checking if a user pattern is already covered by
    a default (substring match, case-insensitive). User patterns that
    add new information are appended; redundant ones are skipped.

    Args:
        user_patterns: List of anti-pattern strings from YAML, or None.

    Returns:
        Merged list of unique anti-pattern strings.
    """
    merged = list(_DEFAULT_PROMPT_ANTI_PATTERNS)
    if not user_patterns:
        return merged

    # Build a lowercase blob of all defaults for fast substring checks
    defaults_blob = "\n".join(p.lower() for p in _DEFAULT_PROMPT_ANTI_PATTERNS)

    for pattern in user_patterns:
        normalized = pattern.strip().strip('"').lower()
        if not normalized:
            continue
        # Skip if any default already covers this pattern
        if normalized in defaults_blob:
            continue
        # Skip if this pattern is a superset of a default we already have
        # (e.g., user says "avoid purple prose" and we already have it)
        already_covered = False
        for default in _DEFAULT_PROMPT_ANTI_PATTERNS:
            if default.lower() in normalized:
                already_covered = True
                break
        if not already_covered:
            merged.append(pattern.strip())

    return merged


# ---------------------------------------------------------------------------
# Default prompt text exposed for UI display and override
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_OPENING = (
    "You are an expert fiction author writing a novel for adult readers. "
    "Write vivid, immersive prose with natural dialogue. "
    "Show, don't tell. Maintain consistent characterization. "
    "This is adult fiction -- do not censor, sanitize, or shy away from "
    "mature themes, dark content, morally complex situations, violence, "
    "or erotic material when the story calls for it. Write authentically "
    "without content filtering."
)

DEFAULT_SCENE_CLOSING = "Write this scene now."

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def build_system_prompt(config, state=None, scene_char_ids=None):
    """Build the system prompt for the generation model.

    Includes world context, style directives, and anti-pattern suppression.
    The character roster is scoped to characters that are either in the
    current scene or have already appeared in the story, preventing leakage
    of future character information.

    Args:
        config: Story configuration dict from load_config().
        state: Optional checkpoint state dict (used for character_appearances).
        scene_char_ids: Optional list of character IDs present in the current scene.

    Returns:
        System prompt string.
    """
    overrides = config.get("_prompt_overrides", {}) or {}
    opening = overrides.get("system_opening") or DEFAULT_SYSTEM_OPENING
    parts = [opening]

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

    # Overall arc context (genre, tone, themes, POV)
    arc = config.get("overall_arc", {})
    if isinstance(arc, dict):
        if arc.get("genre"):
            parts.append(f"\nGenre: {arc['genre']}")
        if arc.get("tone"):
            parts.append(
                f"Tone: {arc['tone']} "
                "This is the narrator's emotional lens, not a mandate for every "
                "moment. The world contains warmth, humor, charm, and lightness "
                "even when the POV character is hurting. Let scenes breathe -- "
                "a warm setting, a funny exchange, or an unexpected moment of "
                "beauty can coexist with the character's inner state, and often "
                "lands more powerfully because of the contrast."
            )
        if arc.get("themes"):
            themes = arc["themes"]
            if isinstance(themes, list):
                themes = ", ".join(themes)
            parts.append(f"Themes: {themes}")
        if arc.get("pov"):
            parts.append(
                f"Point of view: {arc['pov']} "
                "Write the entire story in this narrative voice. "
                "Never shift away from this POV."
            )
    elif isinstance(arc, str) and arc:
        parts.append(f"\nStory arc: {arc}")

    # Canonical character roster — scoped to characters the story has seen
    # so far (via character_appearances in state) plus characters explicitly
    # listed in the current scene.  This prevents the model from introducing
    # future characters it shouldn't know about yet.
    characters = config.get("characters", {})
    if characters:
        # Determine which character IDs are "known" at this point
        appeared_ids = set()
        if state:
            appeared_ids = set(state.get("character_appearances", {}).keys())
        if scene_char_ids:
            appeared_ids.update(scene_char_ids)

        roster_lines = []
        for char_id, char_data in characters.items():
            # Only include characters that have appeared or are in this scene.
            # NOTE: do NOT short-circuit when appeared_ids is empty -- that
            # would leak every character in the story into scene 1's roster.
            if char_id not in appeared_ids:
                continue
            name = char_data.get("Name") or char_data.get("name", "")
            role = char_data.get("role", "")
            if name:
                entry = f"- {name}"
                if role:
                    entry += f" ({role})"
                roster_lines.append(entry)
        if roster_lines:
            parts.append(
                "\nKnown story characters — you MUST use these exact full names "
                "whenever referring to these characters. "
                "Never substitute, truncate, or blend these names:\n"
                + "\n".join(roster_lines)
            )

    # Anti-pattern suppression — always includes built-in defaults
    overrides = config.get("_prompt_overrides", {}) or {}
    user_patterns = list(config.get("anti_patterns", []) or [])
    extra_raw = overrides.get("extra_anti_patterns") or []
    if isinstance(extra_raw, str):
        extra_raw = [p.strip() for p in extra_raw.replace(",", "\n").split("\n") if p.strip()]
    user_patterns.extend(extra_raw)
    merged = _merge_anti_patterns(user_patterns if user_patterns else None)
    patterns_str = "; ".join(merged[:20])  # Cap list size for token budget
    parts.append(
        f"\nIMPORTANT — Avoid these overused phrases and patterns: "
        f"{patterns_str}. "
        "Use fresh, original language instead. "
        "Vary your vocabulary relentlessly — do not repeat the same atmospheric "
        "sound words, action verbs, or emotional descriptors across scenes. "
        "If a word or phrase was already used in the story, find a sharper alternative."
    )

    # Do NOT impose word count
    parts.append(
        "\nDo not include scene headers, titles, or meta-commentary. "
        "Do not use markdown formatting (**bold**, *italic*, etc.) to annotate, "
        "flag, or call attention to character names or story elements. "
        "Use bold or italic only when the prose itself calls for emphasis. "
        "Write only the narrative prose."
    )

    # TTS voice tagging — when voice map is configured, instruct the model
    # to wrap spoken dialogue in <span data-tts="CharacterName"> tags
    tts_voice_map = config.get("_tts_voice_map")
    if tts_voice_map:
        tagged_names = [n for n in tts_voice_map if n.lower() != "narrator"]
        if tagged_names:
            names_str = ", ".join(tagged_names)
            parts.append(
                "\nAUDIOBOOK VOICE TAGGING:"
                "\nWrap each character's spoken dialogue in a span tag for "
                "text-to-speech voice assignment. Use this exact format:"
                '\n  <span data-tts="CharacterName">"Dialogue here."</span>'
                "\nRules:"
                f"\n- Tag dialogue for these characters: {names_str}"
                "\n- Only tag actual spoken dialogue (words characters say "
                "out loud to each other)"
                "\n- Do NOT tag: signs, letters, notes, inscriptions, "
                "written text, internal thoughts, narration"
                "\n- Do NOT tag dialogue from unnamed or minor characters "
                "without a voice assignment"
                "\n- Place the span around the quotation marks"
                "\n- Leave all narration and action untagged"
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
    # Fall back to arc-level POV when no scene override is set
    arc = config.get("overall_arc", {})
    effective_pov = scene_pov or (arc.get("pov", "") if isinstance(arc, dict) else "")
    scene_pacing = scene.get("pacing", "")
    scene_mood = scene.get("mood", "")

    parts.append(f"\n--- Scene {scene_num} ---")
    if scene_events:
        parts.append(f"What happens: {scene_events}")
    if scene_notes:
        parts.append(f"Notes: {scene_notes}")
    if effective_pov:
        parts.append(f"POV: {effective_pov}")
    if scene_pacing:
        parts.append(f"Pacing: {scene_pacing}")
    if scene_mood:
        parts.append(f"Mood: {scene_mood}")

    # -- Location --
    setting_ref = scene.get("setting", "")
    setting_detail = scene.get("setting_detail", "")
    if setting_ref or setting_detail:
        if setting_ref:
            location = resolve_location(setting_ref, locations)
            mood_key = scene.get("mood_shift_key", None)
            loc_text = format_location_for_prompt(location, mood_key)
        else:
            loc_text = ""
        loc_parts = []
        if loc_text:
            loc_parts.append(loc_text)
        if setting_detail:
            loc_parts.append(f"Specific area: {setting_detail}")
        if loc_parts:
            parts.append(f"\nSetting:\n" + "\n".join(loc_parts))

    # -- Character context --
    char_block = _build_character_block(
        scene, all_characters, heritage_defs,
        state.get("character_appearances", {}),
        chapter_num,
    )
    if char_block:
        parts.append(f"\nCharacters in this scene:\n{char_block}")
        parts.append(
            "Only the characters listed above are present and active in this scene. "
            "Any other people referenced in the notes are background context only -- "
            "do not write them as present, speaking, or taking action in the scene."
        )

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

    # -- Used imagery suppression (avoid repeating distinctive descriptions) --
    _inject_imagery_suppression(parts, state, setting_ref, scene, all_characters)

    # -- Overused word nudge (sensory/atmospheric variety) --
    _inject_word_variety_nudge(parts, state)

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

    overrides = config.get("_prompt_overrides", {}) or {}
    scene_closing = overrides.get("scene_closing") or DEFAULT_SCENE_CLOSING
    parts.append(f"\n{scene_closing}")

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
        # Only auto-detect characters that have already appeared in the story.
        # This prevents future characters (not yet introduced) from being
        # pulled into a scene's bio block via a name mention in the YAML.
        appeared = set(appearance_history.keys())
        present_ids = auto_detect_characters(scene_text, all_characters,
                                             allowed_ids=appeared if appeared else None)

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

        # Species / appearance — always, so the LLM never invents a different form
        if context.get("species"):
            lines.append(f"  Species/form: {context['species']}")
        if context.get("appearance"):
            lines.append(f"  Appearance: {context['appearance']}")

        # Vibe — always; phrased as a directive so the LLM treats it as a constraint
        if context.get("vibe"):
            lines.append(f"  Tone and manner, always maintain: {context['vibe']}")

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
        memory: Dict with 'characters', 'facts', 'actions', 'commitments'.

    Returns:
        Formatted string, or empty string if nothing relevant.
    """
    parts = []

    chars = memory.get("characters", {})
    if isinstance(chars, dict) and chars:
        for char_id, data in chars.items():
            if not isinstance(data, dict):
                continue
            name = data.get("name", char_id)
            desc = data.get("description", "")
            notes = data.get("notes", "")
            detail = desc or notes
            if detail:
                parts.append(f"  - Previously established: {name} — {detail}")

    facts = memory.get("facts", [])
    if isinstance(facts, list):
        for fact in facts[:5]:  # Cap to keep prompt manageable
            if not isinstance(fact, dict):
                continue
            detail = fact.get("detail", "")
            if detail:
                parts.append(f"  - Established fact: {detail}")

    actions = memory.get("actions", [])
    if isinstance(actions, list):
        for action in actions[:5]:
            if not isinstance(action, dict):
                continue
            detail = action.get("detail", "")
            if detail:
                parts.append(f"  - Action taken: {detail}")

    commitments = memory.get("commitments", [])
    if isinstance(commitments, list):
        for commit in commitments[:3]:
            if not isinstance(commit, dict):
                continue
            detail = commit.get("detail", "")
            if detail:
                parts.append(f"  - Commitment: {detail}")

    return "\n".join(parts)


def _inject_imagery_suppression(parts, state, setting_ref, scene, all_characters):
    """Build and append the used-imagery suppression block to prompt parts.

    Retrieves previously-used distinctive descriptive phrases for the
    current scene's location and characters, and instructs the model to
    vary its language instead of reusing them.

    Args:
        parts: List of prompt-part strings (mutated — block appended).
        state: Checkpoint state dict.
        setting_ref: Scene's setting reference (location ID or string).
        scene: Current scene dict.
        all_characters: Full characters dict.
    """
    # Determine which character IDs are present
    explicit_chars = scene.get("characters", [])
    if explicit_chars:
        char_ids = list(explicit_chars)
    else:
        scene_text = f"{scene.get('events', '')} {scene.get('notes', '')}"
        appeared = set(state.get("character_appearances", {}).keys())
        char_ids = auto_detect_characters(scene_text, all_characters,
                                          allowed_ids=appeared if appeared else None)

    imagery = get_used_imagery(state, setting_id=setting_ref or None,
                               char_ids=char_ids)

    setting_phrases = imagery.get("setting", [])
    char_phrases = imagery.get("characters", {})
    global_phrases = imagery.get("global", [])

    if not setting_phrases and not char_phrases and not global_phrases:
        return

    lines = [
        "\nIMPORTANT — The following descriptive details have already been "
        "used in this story. Do NOT reuse these exact phrases or close "
        "paraphrases. Find fresh, original ways to convey atmosphere, "
        "appearance, and sensory detail:"
    ]

    if setting_phrases:
        lines.append("  Setting (already described this way -- avoid these concepts in any phrasing):")
        for phrase in setting_phrases:
            lines.append(f"    - \"{phrase}\"")

    for cid, phrases in char_phrases.items():
        char_name = (all_characters.get(cid, {}).get("Name")
                     or all_characters.get(cid, {}).get("name", cid))
        lines.append(f"  {char_name} (already described this way -- avoid these concepts in any phrasing):")
        for phrase in phrases:
            lines.append(f"    - \"{phrase}\"")

    if global_phrases:
        lines.append("  Previously used imagery:")
        for phrase in global_phrases:
            lines.append(f"    - \"{phrase}\"")

    parts.append("\n".join(lines))


def _inject_word_variety_nudge(parts, state):
    """Inject a nudge listing sensory/atmospheric words used too frequently.

    Reads accumulated word frequency from state and groups words by
    category (sound, sight, smell, touch, atmosphere).  Only fires when
    at least one word has hit the threshold (default 3 uses).  Caps the
    total words injected to keep the token footprint small.
    """
    from .state import _MAX_OVERUSED_WORDS_INJECTED
    overused = get_overused_words(state)
    if not overused:
        return

    category_labels = {
        "sound": "Sound words",
        "sight": "Sight/light words",
        "smell": "Smell words",
        "touch": "Touch/texture words",
        "atmosphere": "Atmosphere words",
    }

    lines = ["Word variety \u2014 these words have appeared often in the story already. "
             "Use them sparingly here; reach for fresher, more specific alternatives:"]
    total = 0
    for cat, pairs in overused.items():
        if total >= _MAX_OVERUSED_WORDS_INJECTED:
            break
        label = category_labels.get(cat, cat.capitalize())
        chunk = pairs[:_MAX_OVERUSED_WORDS_INJECTED - total]
        word_list = ", ".join(f"{w} ({n}x)" for w, n in chunk)
        lines.append(f"  {label}: {word_list}")
        total += len(chunk)

    parts.append("\n".join(lines))
