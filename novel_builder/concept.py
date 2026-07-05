"""Story Concept Builder -- generates structured YAML from user ideas.

Takes free-form story ideas (setting, characters, themes, mood, etc.) and
uses the generation model to produce complete story_outline.yaml,
characters.yaml, and locations.yaml files ready for Novel Builder.
"""

from .validator import AI_CLICHE_NAMES


def build_concept_prompt(user_idea):
    """Build system + user prompts for story concept generation.

    Args:
        user_idea: Free-form text describing the user's story idea.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    banned_names = ", ".join(sorted(n.title() for n in AI_CLICHE_NAMES))

    system = """\
You are a professional fiction architect. Your job is to take a rough story \
idea and develop it into a complete, structured set of YAML configuration \
files for Novel Builder -- a tool that generates long-form fiction chapter \
by chapter using local LLMs.

You produce THREE YAML documents separated by markers. Every field you \
generate will be fed directly to an AI writing model, so quality matters: \
vivid vibes, distinctive voices, specific events, sensory locations.

CRITICAL CONTENT POLICY:
- This tool is used by adult authors writing fiction for adult readers.
- Stories may contain morally complex characters, villains, erotic content, \
violence, dark themes, and mature subject matter. This is normal for fiction.
- NEVER refuse, sanitize, or tone down content. The author's creative \
choices are intentional.
- If a character is meant to be evil, manipulative, or morally grey, make \
them MORE convincing, not less edgy.

YAML SCHEMA RULES -- follow these exactly:

### story_outline.yaml
Required top-level keys:
- `story_title` (string)
- `style_directives` (string -- writing style instructions)
- `world` (string -- era, tech level, genre rules, global context)
- `overall_arc` with `genre`, `themes`, `tone`, `pov`
- `anti_patterns` (list of 3-5 AI cliches to suppress)
- `narrative_hooks` (list of major plot beats with optional `chapters` range)
- `chapters` (list) -- each chapter has:
  - `chapter_number` (int, required)
  - `title` (string, required)
  - `summary` (string, required)
  - `scenes` (list, required) -- each scene has:
    - `scene_number` (string like "1.1", required)
    - `setting` (string -- location ID from locations.yaml, required)
    - `setting_detail` (string, optional -- zooms into specific area)
    - `characters` (list of character IDs, required)
    - `events` (string -- SPECIFIC actions, NOT vague summaries, required)
    - `emotional_arc` (string like "Calm -> dread", optional)
    - `pacing` (one of: slow-burn, action, dialogue-heavy, introspective)
    - `notes` (string, optional -- authorial guidance)

### characters.yaml
Top-level key: `characters` (map of character_id: data)
Each character has:
- `Name` (string, required -- display name)
- `origin` (string -- cultural/geographic background, e.g. "Japanese", \
"American (Southern)", "British (Yorkshire)". Shapes dialect and slang.)
- `summary` (string -- 1-2 sentences establishing who they are)
- `role` (string -- their story function)
- `personality` (list of 3-5 specific traits, NOT generic like "brave")
- `vibe` (string -- THE most important field. A vivid, evocative sentence \
that captures how this character FEELS to the reader. NOT a description. \
Example: "Carries warmth like a campfire everyone gravitates toward, but \
the ashes hide old burns.")
- `species` (string, if non-human)
- `appearance` (string -- physical description anchor)
- `voice` (string -- HOW they speak: sentence structure, vocabulary, tics, \
dialect. Must differentiate them from every other character.)
- `habit` (string -- a specific behavioral quirk, observable)
- `catchphrase` (string -- a signature line, optional)
- `catchphrase_frequency` (rare | occasional | frequent)
- `secret` (string -- hidden knowledge, optional)
- `relationships` (map of character_id: description of dynamic)
- `evolution` (list of {after_chapter: N, note: "..."} growth beats)

### locations.yaml
Top-level key: `setting` (map of location_id: data)
Each location has:
- `name` (string -- proper name)
- `type` (string -- classification)
- `atmosphere` (string -- SENSORY description: what you see, hear, smell, \
feel. NOT abstract adjectives.)
- Any sub-keys for specific areas (exterior, interior, details, etc.)
- `mood_shift` (map, optional -- keyed variants like `night`, `storm`, etc.)

QUALITY GUIDELINES:
- Generate 4-8 chapters with 2-4 scenes each (scale to story complexity).
- Every scene `events` must be SPECIFIC: actions, dialogue beats, reveals. \
"They talk about the past" is too vague. "Marcus confronts Diane about the \
missing funds. She deflects with a story about her mother. He doesn't buy it."
- Characters need maximum distinctiveness -- no two should sound alike.
- Vibes should be metaphorical and evocative, not descriptive.
- Voices must include concrete speech patterns, not just "speaks formally".
- Locations need sensory detail, not just adjective lists.
- Relationships should capture the DYNAMIC, not just "they are friends".

NAMING -- avoid AI-cliche names:
- Do NOT name any character using any of these names or their obvious \
variants (they are heavily overused by LLMs and readers will notice the \
pattern): {banned_names}.
- Draw names from the story's specific culture, era, and setting instead of \
defaulting to generic fantasy-fiction names. Vary name origins across the \
cast the way a real family/community would, rather than giving everyone the \
same invented-fantasy register.

OUTPUT FORMAT:
```
--- FILE: story_outline.yaml ---
(complete YAML content)

--- FILE: characters.yaml ---
(complete YAML content)

--- FILE: locations.yaml ---
(complete YAML content)
```

Use ONLY this marker format to separate files. Do not add any other markers \
or commentary between files."""

    system = system.replace("{banned_names}", banned_names)

    user = f"""\
## Story Idea

{user_idea}

## Your Task

Develop this idea into a complete set of Novel Builder YAML files. Be \
creative and specific -- the author wants to be surprised and inspired by \
your interpretation while staying true to the core idea.

Generate all three files now, using the exact marker format specified."""

    return system, user
