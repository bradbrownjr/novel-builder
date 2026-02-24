"""AI-powered YAML story file auditing and consultation.

Provides multi-pass analysis of story YAML files using the generation model
to identify weaknesses, suggest improvements, and optionally produce
corrected file versions.

Passes:
  1. Characters — completeness, depth, distinctiveness
  2. Outline    — scene events, pacing, emotional arcs, chapter flow
  3. Locations  — atmosphere, sensory detail, mood_shift usage
  4. Cross-refs — character-scene alignment, continuity risks, timing
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
  personality, vibe, species, appearance, voice, habit + heritage traits), then \
  only a REMINDER (Name, role, vibe, species, appearance, voice + evolution) after.
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
better — not just what looks nice in a YAML file."""


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
Analyze the cross-references and continuity across these story files.

Evaluate:
1. **Character introduction timing** — Are characters assigned to scenes \
before they should appear in the story? Early appearances spoil surprises.
2. **Character coverage** — Are any defined characters never used in scenes? \
Are scenes referencing characters not in the character file?
3. **Setting references** — Do scene setting IDs match defined locations? \
Are locations defined but never used?
4. **Relationship activation** — When two characters with defined relationships \
share a scene, their dynamic should be leverageable. Are relationship-heavy \
characters actually placed in scenes together?
5. **Emotional continuity** — Do emotional arcs across successive scenes flow \
naturally? Does a character go from "devastated" to "joking" without transition?
6. **Narrative hook coverage** — Are all hooks mapped to at least one scene?
7. **Pacing distribution** — Is there good variety in pacing tags across the story?
8. **Evolution timing** — Do character evolution notes align with story events?

Format your response as:
## Cross-Reference Analysis

### Character Timing
...

### Unused / Missing References
...

### Continuity Risks
...

### Relationship Opportunities
...

## Recommended Fixes
(numbered list of specific, actionable fixes)

Outline YAML:
```yaml
{outline_yaml}
```

Characters YAML:
```yaml
{char_yaml}
```{loc_section}"""


# ---------------------------------------------------------------------------
# Fix generation prompt
# ---------------------------------------------------------------------------

def build_fix_prompt(role, original_yaml, analysis_text):
    """Build a prompt to produce a corrected YAML file.

    Args:
        role: "characters", "outline", or "locations".
        original_yaml: The current YAML content.
        analysis_text: The audit analysis with recommendations.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    system = (
        "You are a YAML editor for Novel Builder. Your job is to produce a "
        "corrected version of a YAML file based on editorial analysis.\n\n"
        "RULES:\n"
        "- Output ONLY valid YAML — no explanatory text before or after.\n"
        "- Preserve all existing structure, keys, and IDs.\n"
        "- Improve or add fields based on the analysis recommendations.\n"
        "- Do NOT remove any existing content unless the analysis explicitly "
        "says to remove it.\n"
        "- Do NOT change character names, IDs, chapter numbers, or scene "
        "numbers — these are structural anchors.\n"
        "- Use proper YAML formatting: consistent indentation (2 spaces), "
        "quoted strings with special characters, folded blocks (>) for "
        "multi-line text.\n"
        "- For multi-line text fields (events, atmosphere, summary), use "
        "YAML folded scalar (>) format.\n"
        "- Your output will be used as-is to replace the original file.\n"
    )

    labels = {
        "characters": "characters.yaml",
        "outline": "story_outline.yaml",
        "locations": "locations.yaml",
    }

    user = (
        f"Based on the editorial analysis below, produce a corrected version "
        f"of this {labels.get(role, role)} file.\n\n"
        f"Apply all recommendations from the analysis that improve story "
        f"output quality. Be thorough but conservative — enhance, don't "
        f"restructure.\n\n"
        f"## Editorial Analysis\n\n{analysis_text}\n\n"
        f"## Original YAML\n\n```yaml\n{original_yaml}\n```\n\n"
        f"Now output the complete corrected YAML file (no markdown fences, "
        f"no explanatory text — YAML only):"
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


def build_pass_prompt(pass_name, files):
    """Build the prompt for a specific analysis pass.

    Args:
        pass_name: One of "characters", "outline", "locations", "crossref".
        files: Dict with YAML content strings.

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

    return _SCHEMA_CONTEXT, user_prompt
