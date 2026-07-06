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
    record_catchphrase_used,
    should_include_catchphrase,
    should_include_habit,
    should_include_secret,
)
from .locations import resolve_location, format_location_for_prompt
from .state import (
    get_overused_words,
    get_recent_scene_boundaries,
    get_relevant_memory,
    get_used_imagery,
)


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
    '"cleared throat" as a dialogue beat -- use varied transitions',
    '"couldn\'t quite" or "couldn\'t quite name" -- find direct expressions',
    '"dust motes dancing" or "dust motes" as atmospheric filler',
    '"grime coated windows" or "grime-coated" -- vary window/light descriptions',
    '"something else entirely" or "something else" as vague descriptions',
    '"couldn\'t help but" -- remove; just state the action directly',
    '"the weight of" as emotional metaphor -- find concrete alternatives',
    '"seemed to" or "appeared to" -- commit to the observation or cut it',
    '"a mixture of" or "a mix of" for emotions -- show conflicting emotions through action',
    '"let out a breath/sigh/laugh" -- show the reaction, don\'t narrate the exhale',
    '"found himself/herself/themselves" -- rewrite as direct action',
    '"hung in the air" or "hung between them" -- show tension through behavior',
    '"filled the room" or "filled the space" -- use specific sensory detail instead',
    '"a sense of" -- vague; replace with concrete sensation',
    '"the sound of" -- name the sound directly without this frame',
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
                f"Tone: {arc['tone']}. "
                "This is the prevailing emotional register for the story. "
                "Scenes may naturally vary in intensity -- let each scene "
                "breathe at its own pace rather than forcing every moment "
                "to the same pitch."
            )
        if arc.get("themes"):
            themes = arc["themes"]
            if isinstance(themes, list):
                themes = ", ".join(themes)
            parts.append(f"Themes: {themes}")
        pov_text = arc.get("pov", "")
        pov_char = config.get("pov_character", "")
        if pov_text:
            parts.append(
                f"Point of view: {pov_text} "
                "Write the entire story in this narrative voice. "
                "Never shift away from this POV."
            )
        elif pov_char:
            parts.append(
                f"Point of view: First-person, from {pov_char}'s perspective. "
                f"Write the entire story in {pov_char}'s voice using 'I', "
                "not 'he', 'she', or 'they'. "
                "Never shift away from this POV."
            )
        # Relational naming directive for first-person POV
        if pov_text or pov_char:
            parts.append(
                "\nRELATIONAL NAMING: In first-person narration, the narrator "
                "refers to family members by relationship term (Mom, Dad, "
                "my sister, my brother, etc.), NOT by their first name, unless "
                "there is a specific in-story reason to use the formal name "
                "(e.g. emotional distance, estrangement, or introducing the name "
                "to the reader for the first time in a natural way like "
                "'my mother, Samantha'). After the first natural introduction, "
                "revert to the relational term."
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
            if not isinstance(char_data, dict):
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
    # Cap generously -- large enough that the 25 built-in defaults plus a
    # realistic set of author-added patterns always fit. Previously capped
    # at 20, which silently dropped the last 5 built-in defaults AND every
    # user-defined anti_pattern / preset extra_anti_pattern (they're
    # appended after the defaults in _merge_anti_patterns).
    patterns_str = "; ".join(merged[:60])
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
        "\nDo not include scene headers, titles, chapter headings, or "
        "meta-commentary in your output. Do not write lines like "
        "'Chapter 3: The Lock-In' or 'Scene 2' -- neither as markdown "
        "headers nor as plain text. "
        "Do not use markdown formatting (**bold**, *italic*, etc.) to annotate, "
        "flag, or call attention to character names or story elements. "
        "Use bold or italic only when the prose itself calls for emphasis. "
        "Write only the narrative prose."
    )

    # TTS voice tagging — when voice map is configured, instruct the model
    # to wrap spoken dialogue in <span data-tts="CharacterName"> tags.
    # IMPORTANT: Scope to appeared + current-scene characters only, matching
    # the character roster scoping above.  Listing future character names
    # here would leak them to the model and cause premature introductions.
    tts_voice_map = config.get("_tts_voice_map")
    if tts_voice_map:
        # Build the same appeared_ids set used for the roster
        tts_known = set()
        if state:
            tts_known = set(state.get("character_appearances", {}).keys())
        if scene_char_ids:
            tts_known.update(scene_char_ids)

        # Map character IDs to display names for scoping
        characters = config.get("characters", {})
        known_names = set()
        for cid in tts_known:
            cdata = characters.get(cid, {})
            if isinstance(cdata, dict):
                known_names.add(cdata.get("Name") or cdata.get("name", cid))

        # Exclude the POV narrator from tagging -- their own dialogue IS the
        # narration voice; wrapping it in a span causes it to be treated as
        # a separate character rather than the narrator's own voice.
        pov_name = (config.get("pov_character") or "").strip()
        tagged_names = [
            n for n in tts_voice_map
            if n.lower() != "narrator" and n in known_names
            and n != pov_name
        ]
        if tagged_names:
            names_str = ", ".join(tagged_names)
            parts.append(
                "\nAUDIOBOOK VOICE TAGGING:"
                "\nEvery line of spoken dialogue from a listed character "
                "MUST be wrapped in a span tag. Do NOT write the dialogue "
                "outside the span and then repeat it inside -- the span IS "
                "the dialogue. Use this exact format:"
                '\n  <span data-tts="CharacterName">"Dialogue here."</span>'
                "\nRules:"
                f"\n- Tag ALL spoken dialogue for: {names_str}"
                "\n- Every quoted line these characters speak gets a span"
                "\n- Only tag actual spoken dialogue (words characters say "
                "out loud)"
                "\n- Do NOT tag: signs, letters, notes, inscriptions, "
                "written text, internal thoughts, narration"
                "\n- Do NOT tag dialogue from unnamed or minor characters "
                "without a voice assignment"
                "\n- Place the span around the quotation marks"
                "\n- Leave all narration and action untagged"
                "\n- Tag EVERY quoted line, no matter how short (even "
                '"\"Yes.\", \"Oh dear.\", \"Night.\")'
                "\n- When a character speaks, then narration interrupts, "
                "then the SAME character speaks again, tag EACH quoted "
                "segment separately. Example:"
                '\n  <span data-tts="Morty">"First line."</span> He paused. '
                '<span data-tts="Morty">"Second line."</span>'
                "\n- NEVER tag the narrator's own dialogue. If the story "
                "is first-person, lines followed by 'I said', 'I replied', "
                "'I whispered', 'I muttered', etc. belong to the narrator "
                "and must NOT be wrapped in any character's span."
                "\n- CRITICAL: Always close every span tag you open. Every"
                " <span data-tts=\"Name\"> MUST have a corresponding </span>"
                " on the same line. Never leave a span unclosed."
            )

    # Optional: non-lexical vocalizations for audiobook flavor.  Only enabled
    # when the TTS engine can voice them (gated in the UI on capability).
    if config.get("_tts_vocalizations"):
        parts.append(
            "\nSPOKEN VOCALIZATIONS:"
            "\nThis story will be read aloud, so portray characters' emotions "
            "with brief non-lexical sounds in their dialogue when the moment "
            "calls for it. The emotion is carried by WHICH sound you choose "
            "and by its punctuation, so pick the spelling that matches the "
            "feeling:"
            "\n- Thought / curiosity: \"Hmm.\"   Excited surprise or delight: "
            "\"Oh!\" or \"Ooh!\"   Dismay, weariness, or exasperation: "
            "\"Ohh...\" or \"Ugh.\""
            "\n- Pleasure or contentment: \"Mmm.\"   Eager excitement: "
            "\"Mmm!\"   Frustration or contempt: \"Hmph.\" or \"Mmph.\""
            "\n- Effort or exertion: \"Unh.\" or \"Nngh.\"   Hesitation: "
            "\"Uh...\" or \"Um...\"   Relief: \"Phew.\"   Disgust: \"Ew.\""
            "\nRules:"
            "\n- Use them sparingly and only when they earn their place; "
            "overuse reads as filler and weakens the prose."
            "\n- Let punctuation carry the intensity: \"!\" for an excited or "
            "sharp sound, \"...\" for a trailing, weary, or drawn-out one. A "
            "short form reads as curt; a slightly longer run (\"mmm\" vs "
            "\"mm\") reads as sustained. Keep runs short (\"mmm\", never "
            "\"mmmmmmm\")."
            "\n- Write them lowercase, capitalized only when they begin a "
            "line of dialogue."
            "\n- Keep them inside the speaking character's dialogue and, when "
            "that character has a voice tag, inside their span."
            "\n- Never add them to narration or to the narrator's own voice."
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

    # -- Chapter transition directive --
    # When this is the first scene of a chapter after chapter 1, signal
    # that a new narrative beat has started so the LLM doesn't repeat
    # actions from the previous chapter.
    scene_num = scene.get("scene_number", "")
    scene_num_str = str(scene_num)
    is_first_scene = scene_num_str.endswith(".1") or scene_num_str == str(chapter_num)
    has_prior_content = bool(state.get("story_so_far", ""))
    if is_first_scene and has_prior_content and chapter_num > 1:
        parts.append(
            "\nCHAPTER TRANSITION: This is the start of a new chapter. "
            "The previous chapter's events have concluded. Do NOT re-narrate "
            "actions, routines, or descriptions that already appeared in "
            "earlier scenes (waking up, getting dressed, making coffee, "
            "describing the apartment, etc.). Pick up the story at the "
            "new chapter's starting point. Move forward, not backward."
        )

    # Per-chapter style override
    ch_style = chapter.get("style_override", "")
    if ch_style:
        parts.append(f"Style for this chapter: {ch_style}")

    # -- Scene continuation directive --
    # When multiple scenes share a chapter, signal that this is a
    # continuation so the LLM doesn't re-establish what just happened.
    if not is_first_scene and has_prior_content:
        recent = state.get("recent_scenes", [])
        if recent:
            prev = recent[-1]
            prev_scene = prev.get("scene", "")
            # Check if previous scene is in the same chapter
            prev_ch = prev_scene.split(".")[0] if "." in prev_scene else ""
            if prev_ch == str(chapter_num):
                parts.append(
                    "\nSCENE CONTINUATION: This scene continues directly from "
                    f"the previous scene ({prev_scene}). Do NOT re-narrate the "
                    "setup, departure, or events from the previous scene. "
                    "Continue the narrative flow seamlessly from where it left off."
                )

    # -- Scene description --
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
        parts.append(
            f"SCENE EVENTS (follow these faithfully -- this is what must "
            f"happen in this scene, in this order): {scene_events}"
        )
    if scene_notes:
        parts.append(f"Author notes: {scene_notes}")
    if effective_pov:
        parts.append(f"POV: {effective_pov}")
    elif config.get("pov_character"):
        # Reinforce first-person POV at scene level to prevent drift
        parts.append(
            f"POV: First-person narration by {config['pov_character']}. "
            "Use 'I', not third-person pronouns."
        )
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
            parts.append(
                "Use the setting details above exactly as described. "
                "Do not invent, relocate, or alter spatial details such as "
                "access routes, room layouts, or building features."
            )

    # -- Character context --
    char_block = _build_character_block(
        scene, all_characters, heritage_defs,
        state.get("character_appearances", {}),
        chapter_num, state=state,
    )
    if char_block:
        parts.append(f"\nCharacters in this scene:\n{char_block}")

        # Character familiarity directive -- when multiple characters are
        # present and have relationship data, explicitly state they know
        # each other so the LLM doesn't write introductions or treat
        # established characters as strangers.
        explicit_chars = scene.get("characters", [])
        if isinstance(explicit_chars, str):
            explicit_chars = [explicit_chars] if explicit_chars else []
        present_set = set(explicit_chars)
        if len(present_set) > 1:
            familiar_pairs = []
            for cid in present_set:
                cdata = all_characters.get(cid, {})
                if not isinstance(cdata, dict):
                    continue
                rels = cdata.get("relationships", "")
                if not rels:
                    continue
                cname = cdata.get("Name") or cdata.get("name", cid)
                if isinstance(rels, str):
                    rels_lower = rels.lower()
                    for other_id in present_set:
                        if other_id == cid:
                            continue
                        other_data = all_characters.get(other_id, {})
                        if not isinstance(other_data, dict):
                            continue
                        other_name = (other_data.get("Name")
                                      or other_data.get("name", other_id))
                        # Check full name, first name, and ID
                        first_name = other_name.split()[0] if other_name else ""
                        if (other_name.lower() in rels_lower
                                or other_id.lower() in rels_lower
                                or (first_name
                                    and first_name.lower() in rels_lower)):
                            familiar_pairs.append((cname, other_name))
                elif isinstance(rels, dict):
                    for other_id_rel, rel_desc in rels.items():
                        if other_id_rel in present_set:
                            other_data = all_characters.get(other_id_rel, {})
                            if isinstance(other_data, dict):
                                other_name = (other_data.get("Name")
                                              or other_data.get("name",
                                                                other_id_rel))
                            else:
                                other_name = other_id_rel
                            familiar_pairs.append((cname, other_name))
            if familiar_pairs:
                parts.append(
                    "CHARACTER FAMILIARITY: The characters listed above "
                    "already know each other as described in their "
                    "relationship data. Do NOT write them meeting for the "
                    "first time or introducing themselves to each other "
                    "unless the scene events explicitly say so."
                )

        # Build exclusion list: ALL characters the model knows about
        # who are NOT in this scene's character list.  This covers:
        #  - Characters that appeared earlier (in the system-prompt roster)
        #  - Characters mentioned in events/notes for context only
        absent_ids = set()
        # 1) Every character that has appeared in the story so far
        appeared = state.get("character_appearances", {})
        absent_ids.update(appeared.keys())
        # 2) Characters mentioned by name in events/notes text
        scan_text = f"{scene_events} {scene_notes}"
        absent_ids.update(auto_detect_characters(scan_text, all_characters))
        # Remove characters that ARE present in this scene
        absent_ids -= present_set

        if absent_ids:
            absent_names = []
            for cid in sorted(absent_ids):
                cdata = all_characters.get(cid, {})
                if isinstance(cdata, dict):
                    name = cdata.get("Name") or cdata.get("name", cid)
                else:
                    name = cid
                absent_names.append(name)
            parts.append(
                "Only the characters listed above are present and active in "
                "this scene. The following characters must NOT appear "
                "on-stage, speak dialogue, or take any visible action in "
                "this scene: " + ", ".join(absent_names) + ". "
                "They exist in the story world but are OFF-STAGE for this "
                "scene. Do not write them as present."
            )
        else:
            parts.append(
                "Only the characters listed above are present and active in "
                "this scene. Any other people referenced in the notes are "
                "background context only -- do not write them as present, "
                "speaking, or taking action in the scene."
            )

    # -- Off-stage character context --
    # Characters mentioned in events/notes who are NOT present in the scene.
    # Provides the LLM with relationship context, vital status, and naming
    # guidance so it doesn't mishandle references to absent characters.
    offstage_block = _build_offstage_context(
        scene, all_characters, config,
    )
    if offstage_block:
        parts.append(f"\nReferenced off-stage characters (mentioned but NOT physically present):\n{offstage_block}")

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

    # -- Scene opening/closing variety (structural repetition) --
    _inject_scene_boundary_nudge(parts, state)

    # -- Story so far (condensed) --
    story_so_far = state.get("story_so_far", "")
    if story_so_far:
        # Keep enough for meaningful continuity (~500 words / ~3000 chars).
        # The compression step keeps this manageable between scenes; the
        # truncation here is a safety net for very long runs.
        max_len = 3000
        if len(story_so_far) > max_len:
            story_so_far = story_so_far[-max_len:]
            # Trim to sentence boundary so we don't start mid-thought
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
                           appearance_history, chapter_num, state=None):
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
    if isinstance(explicit_chars, str):
        explicit_chars = [explicit_chars] if explicit_chars else []
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

        # Gender — always, so the LLM never misidentifies pronouns or sex
        if context.get("gender"):
            lines.append(f"  Gender: {context['gender']}")

        # Species / appearance — always, so the LLM never invents a different form
        if context.get("species"):
            lines.append(f"  Species/form: {context['species']}")
        if context.get("appearance"):
            lines.append(f"  Appearance: {context['appearance']}")
        if context.get("origin"):
            lines.append(f"  Origin: {context['origin']}")

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

        # Habit -- probability gated (~33% per scene)
        include_habit, habit_text = should_include_habit(char_data)
        if include_habit and habit_text:
            lines.append(f"  Habit: {habit_text}")

        # Status — behavioral/situational info (always when present)
        if context.get("status"):
            lines.append(f"  Status/behavior: {context['status']}")

        # Catch phrase -- probability gated with streak prevention
        include_phrase, phrase = should_include_catchphrase(
            char_data, char_id=char_id, state=state,
        )
        if include_phrase and phrase:
            lines.append(
                f"  Catch phrase (use naturally, max once): \"{phrase}\""
            )
            if state is not None:
                record_catchphrase_used(char_id, state)

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
                if other_id == "_general":
                    # Freeform string relationships -- include as general context
                    lines.append(f"  Relationships: {rel_desc}")
                else:
                    other_char = present.get(other_id, {})
                    other_name = (other_char.get("Name", other_id)
                                  if isinstance(other_char, dict) else other_id)
                    lines.append(f"  Relationship with {other_name}: {rel_desc}")

        # Evolution / character development
        if context.get("character_development"):
            lines.append(
                f"  Recent development: {context['character_development']}"
            )

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _build_offstage_context(scene, all_characters, config):
    """Build context for characters mentioned in events/notes but not present.

    When scene events reference characters who are off-stage (deceased,
    absent, remembered), the LLM needs:
    - Their name and relationship to present characters
    - Vital status (alive, deceased, absent)
    - How the narrator/present characters would refer to them

    Args:
        scene: Current scene dict.
        all_characters: Full characters dict from config.
        config: Story configuration dict (for POV character).

    Returns:
        Formatted off-stage context string, or empty string.
    """
    explicit_chars = scene.get("characters", [])
    if isinstance(explicit_chars, str):
        explicit_chars = [explicit_chars] if explicit_chars else []
    present_set = set(explicit_chars)

    # Scan events + notes for character name mentions
    scan_text = f"{scene.get('events', '')} {scene.get('notes', '')}"
    if not scan_text.strip():
        return ""

    mentioned_ids = auto_detect_characters(scan_text, all_characters)
    offstage_ids = [cid for cid in mentioned_ids if cid not in present_set]

    if not offstage_ids:
        # Also scan for non-character names referenced in summaries of
        # present characters (family members etc.)  These aren't in the
        # characters dict but appear in present chars' summary/relationships.
        return ""

    pov_char = config.get("pov_character", "")
    blocks = []

    for cid in offstage_ids:
        cdata = all_characters.get(cid, {})
        if not isinstance(cdata, dict):
            continue
        name = cdata.get("Name") or cdata.get("name", cid)
        role = cdata.get("role", "")
        summary = cdata.get("summary", "")

        lines = [f"**{name}** (OFF-STAGE)"]
        if role:
            lines.append(f"  Role: {role}")
        if summary:
            lines.append(f"  Key facts: {summary}")

        # Include relationships so the LLM knows how present characters
        # relate to this person
        relationships = cdata.get("relationships", "")
        if relationships:
            if isinstance(relationships, str):
                lines.append(f"  Relationships: {relationships}")
            elif isinstance(relationships, dict):
                for rel_target, rel_desc in relationships.items():
                    if rel_target in present_set:
                        target_data = all_characters.get(rel_target, {})
                        target_name = (target_data.get("Name", rel_target)
                                       if isinstance(target_data, dict)
                                       else rel_target)
                        lines.append(
                            f"  Relationship with {target_name}: {rel_desc}"
                        )

        lines.append(
            f"  This character is NOT physically present. They may be "
            f"referenced in memory, dialogue, or thoughts only."
        )
        blocks.append("\n".join(lines))

    if not blocks:
        return ""

    # Add global directive for how to reference off-stage characters
    directive = (
        "These characters are mentioned in the scene context but are NOT "
        "present. They may be thought about, discussed, or remembered, but "
        "must NOT appear, speak, or take physical action. "
        "Present characters should refer to them naturally -- by "
        "relationship term (Mom, my wife, the old man) in internal thoughts, "
        "and by name or relationship in dialogue as appropriate to the speaker."
    )

    return "\n\n".join(blocks) + "\n\n" + directive


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
        for fact in facts[:8]:  # Cap to keep prompt manageable
            if not isinstance(fact, dict):
                continue
            detail = fact.get("detail", "")
            if detail:
                parts.append(f"  - Established fact: {detail}")

    actions = memory.get("actions", [])
    if isinstance(actions, list):
        for action in actions[:8]:
            if not isinstance(action, dict):
                continue
            detail = action.get("detail", "")
            if detail:
                parts.append(
                    f"  - Already narrated (do NOT re-narrate): {detail}"
                )

    commitments = memory.get("commitments", [])
    if isinstance(commitments, list):
        for commit in commitments[:5]:
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
    if isinstance(explicit_chars, str):
        explicit_chars = [explicit_chars] if explicit_chars else []
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
        "action": "Action/gesture words",
        "dialogue": "Dialogue tags",
        "hedge": "Hedge/filler words",
        "modifier": "Overused modifiers",
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


def _inject_scene_boundary_nudge(parts, state):
    """Inject a reminder of how recent scenes opened and closed.

    Word-frequency and imagery suppression catch repeated vocabulary and
    descriptive phrases, but not structural repetition -- e.g. every scene
    opening on waking up or a weather description, or every scene closing
    on a portentous one-liner. This surfaces the last few scenes' opening
    and closing sentences so the model picks a different move.
    """
    recent = get_recent_scene_boundaries(state, limit=5)
    if not recent:
        return

    lines = [
        "\nSCENE VARIETY — recent scenes opened and closed with the lines "
        "below. Start and end THIS scene differently -- do not repeat these "
        "moves (e.g. waking up, weather, a portentous closing line):"
    ]
    for entry in recent:
        if entry.get("opening"):
            lines.append(f"  Opened: \"{entry['opening']}\"")
        if entry.get("closing"):
            lines.append(f"  Closed: \"{entry['closing']}\"")

    parts.append("\n".join(lines))
