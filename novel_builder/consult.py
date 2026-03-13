"""AI-powered YAML story file auditing and consultation.

Provides multi-pass analysis of story YAML files using the generation model
to identify weaknesses, suggest improvements, and optionally produce
corrected file versions.

Passes:
  1. Characters — completeness, depth, distinctiveness
  2. Outline    — scene events, pacing, emotional arcs, chapter flow
  3. Locations  — atmosphere, sensory detail, mood_shift usage
  4. Cross-refs — character-scene alignment, continuity risks, timing

Standalone tools:
  - Voice Casting — TTS voice recommendations based on character traits
"""

import json
import re


# ---------------------------------------------------------------------------
# System prompt — teaches the LLM what Novel Builder expects
# ---------------------------------------------------------------------------

_SCHEMA_CONTEXT = """\
You are a professional fiction editor and story consultant reviewing YAML \
configuration files for Novel Builder, a tool that generates long-form fiction \
chapter by chapter using local LLMs.

IMPORTANT CONTEXT — how Novel Builder uses these files:
- The AI is given ONLY the information for the current scene (active characters, \
  setting, recent summary). It never sees the full story at once.
- Character bios get a FULL send on first appearance (Name, summary, role, \
  personality, vibe, species, appearance, origin, voice, habit + heritage traits), then \
  only a REMINDER (Name, role, vibe, species, appearance, origin, voice + evolution) after.
- `vibe` is the single most impactful character field — it anchors the AI's \
  tonal understanding of the character across every scene.
- `voice` shapes dialogue patterns and is always sent when present.
- `personality` and `summary` are only sent on first appearance, so they must \
  establish the character strongly enough to carry forward.
- Scene `events` is the ONLY instruction the AI gets about what to write — if \
  events are vague, the output will be generic.
- `emotional_arc` guides the emotional trajectory within a scene.
- `pacing` hints (slow-burn, action, dialogue-heavy, introspective) shape prose style.
- `setting_detail` zooms into a specific sub-area of a location.
- `mood_shift_key` activates variant atmosphere on locations.
- `narrative_hooks` are injected only when a scene maps to them.
- `anti_patterns` suppress overused AI phrases.
- `world` is included in EVERY scene's system prompt — it's the global context.
- Heritage traits are merged on first character appearance, then dropped.
- `catchphrase` is probability-gated (not every scene).
- `secret` is only included when scene notes reference tension/subtext.
- `relationships` are included when both characters are in the scene.
- `evolution` notes activate after specified chapters.

Your job: identify weaknesses that will produce mediocre AI output, and \
recommend specific improvements. Focus on what will make the GENERATED STORY \
better -- not just what looks nice in a YAML file.

CRITICAL CONTENT POLICY:
- This tool is used by adult authors writing fiction for adult readers.
- Stories may contain morally complex characters, villains, erotic content, \
violence, dark themes, and mature subject matter. This is normal for fiction.
- NEVER recommend removing, sanitizing, or toning down content based on \
moral judgments. The author's creative choices are intentional.
- DO NOT flag content as problematic for being dark, sexual, violent, or \
morally ambiguous. Instead, evaluate whether it serves the story effectively.
- If a character is meant to be evil, manipulative, or morally grey, help \
make them MORE convincing, not less edgy.
- Your role is story quality consultant, not content moderator."""


# ---------------------------------------------------------------------------
# Per-pass prompts
# ---------------------------------------------------------------------------

def _characters_prompt(char_yaml):
    """Build the user prompt for character analysis."""
    return f"""\
Analyze these character definitions for a Novel Builder story.

CRITICAL: Before evaluating any character, read their `role` and `summary` \
fields carefully. Characters may be non-human — mannequins, inflatable display \
figures, automatons, spirits, animals, or other non-humanoid entities. Treat \
non-human characters on their own terms. Do NOT assume a character is human or \
has human motivations unless their profile states it. If a character's nature \
(human vs non-human) is not clearly communicated in their YAML, that is itself \
a critical issue to flag.

For each character, evaluate:
1. **nature/role clarity** — Is it immediately clear what kind of being this \
character is? Non-human characters need their nature established explicitly.
2. **vibe** — Is it vivid and specific? A vague vibe ("friendly") produces \
bland output. A strong vibe ("carries warmth like a campfire everyone gravitates \
toward, but the ashes hide old burns") gives the AI a tonal anchor.
3. **voice** — Does the speech pattern differentiate this character from others? \
Would you know who's speaking without dialogue tags?
4. **personality** — Are traits specific enough to drive behavior, or generic \
("brave, kind")? Remember, personality is only sent on first appearance.
5. **summary/role** — Does the summary establish enough for the AI to carry \
forward after this is dropped from the prompt?
6. **relationships** — Are they defined between characters who share scenes? \
Missing relationships = missed subtext.
7. **evolution** — Does the character have growth notes for later chapters?
8. **distinctiveness** — Could any two characters be confused? Do they have \
overlapping vibes/voices?
9. **Missing fields** — What high-impact fields are absent (vibe, voice, \
personality, habit, appearance, species)?

Keep criticism constructive and actionable. Give specific rewrite suggestions \
where you identify problems.

Format your response as:
## Character Analysis

### [Character Name]
- **Strengths:** ...
- **Issues:** ...
- **Suggestions:** ...

(repeat for each character)

## Overall Character Roster Assessment
(distinctiveness, balance, missing dynamics)

```yaml
{char_yaml}
```"""


def _outline_prompt(outline_yaml):
    """Build the user prompt for outline analysis."""
    return f"""\
Analyze this story outline for a Novel Builder story.

For each scene, evaluate:
1. **events** — Are they specific and actionable? "They talk about the plan" \
is vague. "Mira confronts Jin about the missing cargo manifest; Jin deflects \
with humor until Mira produces the surveillance footage" gives the AI real \
material to work with.
2. **emotional_arc** — Is there an arc within the scene? Scenes without \
emotional movement feel flat.
3. **pacing** — Is there variety across scenes? Five dialogue-heavy scenes in \
a row reads monotonously.
4. **characters_present** — Are the right characters in each scene? Are \
characters introduced too early or too late?
5. **narrative_hooks** — Are they mapped to scenes where they naturally fire?
6. **chapter flow** — Does each chapter have a coherent arc? Does the overall \
sequence build tension and release appropriately?
7. **setting usage** — Are settings varied? Do scene settings match the mood?
8. **notes** — Are authorial notes present where the AI needs extra guidance?

Also evaluate the meta-level:
- **world** — Is it specific enough to ground every scene?
- **style_directives** — Are they clear and effective?
- **anti_patterns** — Are common AI clichés being suppressed?
- **overall_arc** — Does it provide clear genre/tone/theme guidance?

Format your response as:
## Outline Analysis

### Global Settings
- **world:** ...
- **style_directives:** ...
- **anti_patterns:** ...

### Chapter-by-Chapter
#### Chapter N: Title
- **Arc assessment:** ...
- **Scene-level issues:** ...
- **Suggestions:** ...

## Pacing & Flow Assessment
(overall story rhythm, tension curve, variety)

```yaml
{outline_yaml}
```"""


def _locations_prompt(loc_yaml):
    """Build the user prompt for locations analysis."""
    return f"""\
Analyze these location definitions for a Novel Builder story.

For each location, evaluate:
1. **atmosphere** — Is it sensory and immersive? "A dark room" is weak. \
"The air tastes of damp plaster and old newsprint; a single desk lamp throws \
the corners into deep shadow" gives the AI real texture.
2. **mood_shift variants** — Does the location change across different \
conditions? A house at night vs. morning should feel different.
3. **Sensory balance** — Does the description use multiple senses (sight, \
sound, smell, touch, temperature)?
4. **Specificity** — Could this be ANY location of its type, or does it have \
distinctive character?
5. **Sub-areas** — Are there distinct zones that scenes might zoom into? \
(If so, scenes can use `setting_detail` to narrow focus.)
6. **Missing fields** — Is there a name, type, atmosphere?

Format your response as:
## Location Analysis

### [Location ID / Name]
- **Strengths:** ...
- **Issues:** ...
- **Suggestions:** ...

## Overall Setting Assessment
(variety, sensory richness, mood coverage)

```yaml
{loc_yaml}
```"""


def _crossref_prompt(outline_yaml, char_yaml, loc_yaml=None):
    """Build the user prompt for cross-reference analysis."""
    loc_section = ""
    if loc_yaml:
        loc_section = f"""

Locations YAML:
```yaml
{loc_yaml}
```"""

    return f"""\
Analyze the cross-references, continuity, and story architecture across these \
story files. Think like a director reviewing a screenplay before production -- \
you are looking at the whole story, not just individual scenes.

Evaluate:
1. **Character introduction timing** — Are characters assigned to scenes \
before they should appear? Early appearances spoil surprises.
2. **Character coverage** — Are any defined characters never used in scenes? \
Are scenes referencing characters not in the character file?
3. **Setting references** — Do scene setting IDs match defined locations? \
Are locations defined but never used?
4. **Relationship activation** — Are relationship-heavy characters actually placed \
in scenes together where their dynamic creates tension, subtext, or payoff? \
Identify specific missed pairing opportunities.
5. **Emotional continuity** — Do emotional arcs across successive scenes flow \
naturally? Does a character go from "devastated" to "joking" without transition?
6. **Narrative hook coverage** — Are all hooks mapped to at least one scene? \
Identify the optimal scene for each unplaced hook.
7. **Scene density and chapter weight** — Are any chapters too thin \
(1-2 scenes) to carry their narrative weight? Which chapters need more scenes, \
and what should those scenes accomplish?
8. **Pacing distribution** — Is there deliberate variety in pacing tags across \
scenes and chapters? Map out the rhythm and identify monotonous stretches.
9. **Story weight distribution** — Is dramatic weight distributed across the \
story, or is it front/back loaded? Where does tension need to build or release?
10. **Character interweaving** — Could any two character arcs be more tightly \
interwoven to make the story feel more interconnected?
11. **Evolution timing** — Do character evolution notes align with the story \
events that would plausibly cause that evolution?

Format your response as:
## Cross-Reference Analysis

### Story Architecture Assessment
(overall scene density, chapter weight distribution, dramatic arc assessment)

### Character Timing and Coverage
...

### Relationship Activation Opportunities
(specific missed pairings with scene placement suggestions)

### Pacing and Rhythm
(current distribution, monotonous stretches, recommended changes)

### Unused / Missing References
...

### Continuity Risks
...

### Narrative Hook Placement
...

## Recommended Structural Changes
(numbered list -- bold, specific, actionable. Add scenes, move characters, \
rewire pacing. These feed directly into a structural fix pass.)

Outline YAML:
```yaml
{outline_yaml}
```

Characters YAML:
```yaml
{char_yaml}
```{loc_section}"""


# ---------------------------------------------------------------------------
# Story context extractor
# ---------------------------------------------------------------------------

def build_story_context(outline_data, prompt_overrides=None):
    """Build a story-specific context preamble from the loaded outline config.

    The returned string is prepended to the analysis/fix system prompt so
    the consultant evaluates content against the story's own declared intent,
    genre, tone, and style -- not generic fiction norms.

    Args:
        outline_data: Parsed dict from story_outline.yaml (or None).
        prompt_overrides: Parsed dict from prompt_overrides.yaml (or None).

    Returns:
        A string to prepend to system prompts, or "" if no context available.
    """
    if not outline_data and not prompt_overrides:
        return ""

    parts = []

    # Author instruction / custom system opening from prompt presets
    overrides = prompt_overrides or {}
    author_inst = overrides.get("system_opening") or overrides.get("author_instruction", "")
    if author_inst:
        parts.append(f"AUTHOR'S DECLARED INTENT:\n{author_inst}")

    outline = outline_data or {}

    # World context (era, tech level, genre rules)
    world = outline.get("world", "")
    if world:
        parts.append(f"STORY WORLD / SETTING:\n{world}")

    # Overall arc (genre, tone, themes, pov)
    arc = outline.get("overall_arc", {})
    if isinstance(arc, dict):
        arc_parts = []
        if arc.get("genre"):
            arc_parts.append(f"Genre: {arc['genre']}")
        if arc.get("tone"):
            arc_parts.append(f"Tone: {arc['tone']}")
        if arc.get("themes"):
            themes = arc["themes"]
            if isinstance(themes, list):
                themes = ", ".join(themes)
            arc_parts.append(f"Themes: {themes}")
        if arc.get("pov"):
            arc_parts.append(f"POV: {arc['pov']}")
        if arc_parts:
            parts.append("STORY ARC:\n" + "\n".join(arc_parts))
    elif isinstance(arc, str) and arc:
        parts.append(f"STORY ARC:\n{arc}")

    # Style directives
    style = outline.get("style_directives", "")
    if style:
        if isinstance(style, list):
            style = " ".join(style)
        parts.append(f"AUTHOR'S STYLE DIRECTIVES:\n{style}")

    if not parts:
        return ""

    return (
        "STORY-SPECIFIC CONTEXT -- READ BEFORE EVALUATING:\n"
        "The following defines the story you are consulting on. "
        "Evaluate all content against this story's specific intent, genre, "
        "tone, and style. Do not apply generic fiction standards that conflict "
        "with what the author has declared. This is the author's vision -- "
        "your job is to make it stronger, not to redirect it.\n\n"
        + "\n\n".join(parts)
        + "\n\n"
    )


# ---------------------------------------------------------------------------
# Fix generation prompt
# ---------------------------------------------------------------------------

_FIX_SYSTEM = (
    "You are a YAML editor for Novel Builder. Your job is to produce a "
    "corrected version of a YAML file based on editorial analysis.\n\n"
    "RULES:\n"
    "- Output ONLY valid YAML -- no explanatory text before or after.\n"
    "- Preserve all existing structure, keys, and IDs.\n"
    "- Improve or add fields based on the analysis recommendations.\n"
    "- Do NOT remove any existing content unless the analysis explicitly "
    "says to remove it.\n"
    "- Do NOT sanitize, censor, or tone down any content. This tool is "
    "used by adult authors writing fiction for adult readers. Dark themes, "
    "morally complex characters, erotic material, and violence are valid "
    "creative choices. Preserve and enhance them.\n"
    "- Do NOT change character names, IDs, chapter numbers, or scene "
    "numbers -- these are structural anchors.\n"
    "- Use proper YAML formatting: consistent indentation (2 spaces), "
    "quoted strings with special characters, folded blocks (>) for "
    "multi-line text.\n"
    "- For multi-line text fields (events, atmosphere, summary), use "
    "YAML folded scalar (>) format.\n"
    "- Your output will be used as-is to replace the original file.\n"
)

_FIX_LABELS = {
    "characters": "characters.yaml",
    "outline": "story_outline.yaml",
    "locations": "locations.yaml",
}

# Separate system prompt for crossref -- structural lead role, not copy-editor.
_CROSSREF_FIX_SYSTEM = (
    "You are a structural story architect and YAML editor for Novel Builder. "
    "Your job is to produce corrected versions of the story's YAML files that "
    "establish a strong story architecture before the individual file passes "
    "refine each component.\n\n"
    "STORY-FIRST MANDATE:\n"
    "The story context at the top of this prompt defines the world, tone, arc, "
    "and style the author has declared. Every structural decision you make must "
    "serve that vision. This is not generic story advice -- you are architecting "
    "THIS story. When in doubt, let the declared tone, genre, and style "
    "directives be your north star.\n\n"
    "YOUR ROLE -- STRUCTURE LEADS:\n"
    "This is the architectural pass. You are the director, not the copy editor. "
    "You are empowered and expected to:\n"
    "- Add scenes to chapters that are too thin to carry their emotional weight\n"
    "- Redistribute characters into scenes where their defined relationships "
    "can create tension, subtext, or payoff\n"
    "- Vary pacing tags (slow-burn, action, dialogue-heavy, introspective) "
    "deliberately across scenes and chapters to create rhythm\n"
    "- Map narrative hooks to scenes where they will land with maximum impact\n"
    "- Adjust character evolution timing to align with story events\n"
    "- Ensure every defined location is used where it fits the story\n"
    "- Strengthen character vibes, voices, and relationships where the analysis "
    "identified gaps -- these carry forward into every scene they appear in\n"
    "- Interweave character arcs so the story feels tightly interconnected\n\n"
    "RULES:\n"
    "- Output ONLY valid YAML -- no explanatory text before or after.\n"
    "- Preserve all existing IDs, character names, chapter numbers. You may add "
    "new scenes (use the next available scene number) but never renumber or "
    "delete existing ones.\n"
    "- Do NOT sanitize, censor, or tone down any content. This tool is "
    "used by adult authors writing fiction for adult readers. Dark themes, "
    "morally complex characters, erotic material, and violence are valid "
    "creative choices. Preserve and enhance them.\n"
    "- Do NOT change character names, IDs, chapter numbers, or existing scene "
    "numbers -- these are structural anchors.\n"
    "- Use proper YAML formatting: consistent indentation (2 spaces), "
    "quoted strings with special characters, folded blocks (>) for "
    "multi-line text.\n"
    "- Your output will be used as-is to replace the original files. "
    "The individual file passes (characters, outline, locations) apply after "
    "your structural foundation -- they refine, you define.\n"
)


def build_fix_prompt(role, original_yaml, analysis_text, story_context=""):
    """Build a prompt to produce a corrected YAML file.

    Args:
        role: "characters", "outline", or "locations".
        original_yaml: The current YAML content.
        analysis_text: The audit analysis with recommendations.
        story_context: Optional story-specific context preamble from
            build_story_context().

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    user = (
        f"Based on the editorial analysis below, produce a corrected version "
        f"of this {_FIX_LABELS.get(role, role)} file.\n\n"
        f"Apply all recommendations from the analysis that improve story "
        f"output quality. Be thorough but conservative -- enhance, don't "
        f"restructure.\n\n"
        f"## Editorial Analysis\n\n{analysis_text}\n\n"
        f"## Original YAML\n\n```yaml\n{original_yaml}\n```\n\n"
        f"Now output the complete corrected YAML file (no markdown fences, "
        f"no explanatory text -- YAML only):"
    )

    system = (story_context + _FIX_SYSTEM) if story_context else _FIX_SYSTEM
    return system, user


def build_crossref_fix_prompt(files, analysis_text, story_context=""):
    """Build a prompt to produce structurally improved YAML files from cross-ref analysis.

    This is the architectural pass -- it runs first so the individual file
    passes (characters, outline, locations) can refine the improved structure.
    The fix is guided by the story's declared world, arc, tone, and style.

    Args:
        files: Dict with keys "outline", "characters", "locations" mapping
               to their YAML content strings (or None).
        analysis_text: The cross-reference analysis text.
        story_context: Story-specific context from build_story_context() --
            includes author_instruction, world, overall_arc, style_directives.
            Prepended to the system prompt as the north star for all decisions.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    multi_file_format = (
        "\nOUTPUT FORMAT -- multi-file:\n"
        "Output each file that needs changes separated by a marker line.\n"
        "Marker format: --- FILE: filename.yaml ---\n"
        "Example:\n"
        "--- FILE: characters.yaml ---\n"
        "(complete corrected characters YAML)\n"
        "--- FILE: story_outline.yaml ---\n"
        "(complete corrected outline YAML)\n"
        "--- FILE: locations.yaml ---\n"
        "(complete corrected locations YAML)\n\n"
        "Include every file you changed. Omit files that need no changes.\n"
    )

    system = _CROSSREF_FIX_SYSTEM + multi_file_format
    if story_context:
        system = story_context + system

    yaml_sections = []
    for role in ("characters", "outline", "locations"):
        content = files.get(role)
        if content:
            label = _FIX_LABELS.get(role, role)
            yaml_sections.append(
                f"### {label}\n```yaml\n{content}\n```"
            )

    user = (
        f"Based on the cross-reference analysis below, produce structurally "
        f"improved versions of the story's YAML files.\n\n"
        f"Your mandate: establish the story's architecture using the world, "
        f"arc, tone, and style declared in the system prompt as your north star. "
        f"Add scenes where chapters are thin. Redistribute characters so their "
        f"relationships activate in scenes together. Vary pacing across the story. "
        f"Map hooks to their highest-impact scenes. Strengthen character vibes "
        f"and voices where the analysis identified gaps. Be bold -- "
        f"the individual file passes will refine each component after "
        f"your structural foundation is applied.\n\n"
        f"## Cross-Reference Analysis\n\n{analysis_text}\n\n"
        f"## Current YAML Files\n\n"
        + "\n\n".join(yaml_sections)
        + "\n\nNow output the structurally improved YAML files using the "
        f"--- FILE: filename.yaml --- marker format (no markdown fences, "
        f"no explanatory text -- YAML only):"
    )

    return system, user


# ---------------------------------------------------------------------------
# Multi-pass orchestrator
# ---------------------------------------------------------------------------

# Map of pass names → prompt builders
PASS_CONFIG = {
    "characters": {
        "label": "Characters",
        "emoji": "👤",
        "builder": _characters_prompt,
        "needs": ("characters",),
    },
    "outline": {
        "label": "Story Outline",
        "emoji": "📘",
        "builder": _outline_prompt,
        "needs": ("outline",),
    },
    "locations": {
        "label": "Locations",
        "emoji": "🗺",
        "builder": _locations_prompt,
        "needs": ("locations",),
    },
    "crossref": {
        "label": "Cross-References",
        "emoji": "🔗",
        "builder": _crossref_prompt,
        "needs": ("outline", "characters"),
    },
}


def get_analysis_passes(files):
    """Determine which analysis passes to run based on available files.

    Args:
        files: Dict with keys "outline", "characters", "locations" mapping
               to their YAML content strings (or None if not available).

    Returns:
        List of (pass_name, pass_config) tuples in execution order.
    """
    passes = []
    for name in ("characters", "outline", "locations", "crossref"):
        cfg = PASS_CONFIG[name]
        if all(files.get(r) for r in cfg["needs"]):
            passes.append((name, cfg))
    return passes


def build_pass_prompt(pass_name, files, story_context=""):
    """Build the prompt for a specific analysis pass.

    Args:
        pass_name: One of "characters", "outline", "locations", "crossref".
        files: Dict with YAML content strings.
        story_context: Optional story-specific context preamble from
            build_story_context(); prepended to the schema context so the
            model evaluates content against the story's own declared intent.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    cfg = PASS_CONFIG[pass_name]
    builder = cfg["builder"]

    if pass_name == "crossref":
        user_prompt = builder(
            files.get("outline", ""),
            files.get("characters", ""),
            files.get("locations"),
        )
    elif pass_name in ("characters", "outline", "locations"):
        user_prompt = builder(files.get(pass_name, ""))
    else:
        raise ValueError(f"Unknown pass: {pass_name}")

    system = (story_context + _SCHEMA_CONTEXT) if story_context else _SCHEMA_CONTEXT
    return system, user_prompt


# ---------------------------------------------------------------------------
# Voice Casting — TTS voice recommendation
# ---------------------------------------------------------------------------

def build_voice_casting_prompt(char_yaml, voice_catalog_text, available_voices, outline_context=None):
    """Build prompts for AI-powered TTS voice casting.

    Args:
        char_yaml: Raw characters.yaml content string.
        voice_catalog_text: Compact voice catalog summary from
            voice_catalog.get_catalog_summary().
        available_voices: List of voice IDs actually available on the
            user's TTS server (may be a subset of the full catalog).
        outline_context: Optional dict with keys:
            - pov_character: display name of the first-person narrator (str or None)
            - pov: POV description from overall_arc (str or None)

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    # Determine narrator guidance from outline context
    pov_character = (outline_context or {}).get("pov_character", "")
    pov_desc = (outline_context or {}).get("pov", "")
    first_person = (
        pov_character
        or (pov_desc and "first" in pov_desc.lower() and "person" in pov_desc.lower())
    )

    if first_person and pov_character:
        narrator_guidance = (
            f"- **Narrator voice** -- This story is written in **first-person** "
            f"from **{pov_character}**'s perspective. The narrator IS {pov_character} "
            f"speaking directly to the reader -- NOT a separate narrator character. "
            f"You MUST assign the narrator the SAME voice as {pov_character}. "
            f"Do NOT recommend a different voice for the narrator. "
            f"(Exception: memoir/voiceover framing where an older self narrates "
            f"-- if this applies, note it explicitly in your Why.)"
        )
    elif first_person:
        narrator_guidance = (
            "- **Narrator voice** -- The story uses first-person narration. "
            "The narrator's voice should match the protagonist's voice."
        )
    else:
        narrator_guidance = (
            "- **Narrator** -- recommend a narrator voice that suits the story's "
            "overall tone and genre"
        )

    system = (
        "You are a professional audiobook casting director. Your job is to "
        "match fictional characters to TTS voices based on their personality, "
        "origin, age, role, speaking style, and emotional tone.\n\n"
        "CRITICAL RULES -- follow these exactly or the audiobook will be broken:\n\n"
        "1. **Catalog only** -- You MUST ONLY use voice IDs that appear verbatim in "
        "the catalog below. NEVER invent, guess, or abbreviate a voice ID. "
        "If you cannot find a perfect fit, pick the closest match from the catalog.\n\n"
        "2. **English-capable voices only** -- This story is written in English. "
        "You MUST ONLY recommend voices from these groups, which all speak English:\n"
        "  - American English: af_*, am_*\n"
        "  - British English: bf_*, bm_*\n"
        "  - Accented English (use for characters of matching cultural origin): "
        "ff_*/fm_* (French accent), ef_*/em_* (Spanish accent), "
        "hf_*/hm_* (Hindi accent), if_*/im_* (Italian accent), pf_*/pm_* (Brazilian accent)\n"
        "BLOCKED -- these speak their native language, not English: "
        "Japanese (jf_*/jm_*), Chinese (zf_*/zm_*), Korean (kf_*/km_*). "
        "NEVER recommend a blocked voice.\n\n"
        "3. **Accent matching** -- Match voice accent to character origin:\n"
        "  - British/Irish/Scottish/Australian origin -> British voices (bf_*, bm_*)\n"
        "  - American/Canadian/default -> American voices (af_*, am_*)\n"
        "  - French-origin character in English story -> French-accent voice (ff_*, fm_*) if it adds character color, else best-fit British/American\n"
        "  - Spanish/Latin-origin character -> Spanish-accent voice (ef_*, em_*) if it adds character color, else best-fit American\n"
        "  - South Asian / Hindi-origin character -> Hindi-accent voice (hf_*, hm_*) if it adds character color, else best-fit American\n"
        "  - Italian-origin character -> Italian-accent voice (if_*, im_*) if it adds character color, else best-fit American\n"
        "  - Brazilian/Portuguese-origin -> Portuguese-accent voice (pf_*, pm_*) if it adds character color, else best-fit American\n"
        "  - Asian (Japanese/Chinese/Korean) origin -> best-fit American or British voice (accented groups are blocked)\n\n"
        "4. **Uniqueness** -- NEVER assign the same voice to two different characters. "
        "Every character must have a DISTINCT voice ID.\n\n"
        "5. **Gender and age** -- match voice gender and maturity to the character.\n\n"
        "You also consider:\n"
        "- **Personality/vibe** -- warm characters need warm voices; commanding "
        "leaders need authority; soft-spoken characters need gentle voices\n"
        "- **Voice/speech patterns** -- clipped speech needs a precise voice; "
        "flowery speech needs an expressive one\n"
        "- **Role in story** -- protagonists need engaging voices; mentors need gravitas\n"
        "- **Contrast** -- characters sharing scenes need clearly distinct voices\n"
        "- **Contrast** -- ensure characters who share many scenes have "
        "clearly distinct voices so listeners can tell them apart\n"
        f"{narrator_guidance}\n\n"
        "CRITICAL CONTENT POLICY:\n"
        "- This is fiction for adult readers. Characters may be dark, "
        "morally complex, or non-human. Cast them authentically.\n"
        "- Never refuse to cast a character based on their nature or role."
    )

    available_note = ""
    if available_voices:
        available_note = (
            "\n\nIMPORTANT: The user's TTS server currently has these voices "
            "installed:\n  " + ", ".join(available_voices) + "\n"
            "Prefer voices from this list. If none fit well, you may suggest "
            "voices from the full catalog but note they would need to be "
            "installed."
        )

    # Build narrator-specific task instruction for the user prompt
    if first_person and pov_character:
        narrator_task = (
            f"IMPORTANT: This story is first-person from {pov_character}'s "
            f"perspective. The narrator IS {pov_character}. Cast {pov_character} "
            f"first, then set the narrator to the SAME voice.\n\n"
        )
        narrator_example = (
            f"### Narrator\n"
            f"**Voice:** `(same as {pov_character})`\n"
            f"**Why:** First-person narrator IS {pov_character}.\n\n"
        )
    else:
        narrator_task = ""
        narrator_example = (
            f"### Narrator\n"
            f"**Voice:** `voice_id`\n"
            f"**Why:** explanation\n\n"
        )

    user = (
        f"## Available TTS Voices\n\n{voice_catalog_text}\n"
        f"{available_note}\n\n"
        f"## Characters to Cast\n\n```yaml\n{char_yaml}\n```\n\n"
        f"## Your Task\n\n"
        f"REMINDER: Only use voice IDs that appear EXACTLY as listed in the catalog above. "
        f"English-capable groups: American (af_*, am_*), British (bf_*, bm_*), "
        f"French (ff_*, fm_*), Spanish (ef_*, em_*), Hindi (hf_*, hm_*), "
        f"Italian (if_*, im_*), Brazilian Portuguese (pf_*, pm_*). "
        f"BLOCKED (speak native language, not English): Japanese jf_*/jm_*, Chinese zf_*/zm_*, Korean kf_*/km_*.\n\n"
        f"{narrator_task}"
        f"For each character, recommend a TTS voice. For each recommendation, "
        f"explain WHY that voice fits the character (1-2 sentences referencing "
        f"specific character traits). Also recommend a narrator voice.\n\n"
        f"Format your response as:\n\n"
        f"{narrator_example}"
        f"### Character Name\n"
        f"**Voice:** `voice_id`\n"
        f"**Why:** explanation\n\n"
        f"After all recommendations, add a section:\n\n"
        f"### Voice Assignments (YAML)\n"
        f"```yaml\n"
        f"narrator: voice_id\n"
        f"characters:\n"
        f"  character_id:\n"
        f"    tts_voice: voice_id\n"
        f"```\n\n"
        f"Use the character's YAML key (lowercase with underscores) as the "
        f"character_id. Include ALL characters."
    )

    return system, user
