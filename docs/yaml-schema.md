# Novel Builder — YAML Schema Reference

This document defines the structure, fields, and usage of all YAML files used by Novel Builder. All fields are optional unless marked **required**.

---

## File Discovery

Novel Builder looks for YAML data in one of two ways:

1. **Separate files** (default): `story_outline.yaml`, `characters.yaml`, `locations.yaml` (or `settings.yaml`)
2. **Combined file**: A single `story_data.yaml` containing all top-level keys

CLI flags (`--outline`, `--characters`, `--locations`) override auto-discovery.

---

## Story Outline

**File:** `story_outline.yaml` (or top-level keys in a combined file)

```yaml
# ─── Story Metadata ───────────────────────────────────────────────
story_title: "The Last Lighthouse"

style_directives: >
  Write grounded literary fiction with sensory detail.
  Favor dry humor over melodrama. Avoid purple prose.

# ─── World / Global Setting ──────────────────────────────────────
# Included in every scene's system prompt. Use for time period,
# genre rules, tech level, or anything universally true.
world: >
  A coastal New England town in the late 1980s. No cell phones,
  no internet. News travels by word of mouth and the local paper.

# ─── Overall Arc ──────────────────────────────────────────────────
overall_arc:
  theme: "Isolation, duty, and the cost of keeping secrets."
  tone: "Atmospheric and melancholic with moments of warmth."
  pov: "Third-person limited, following the keeper."

# ─── Anti-Pattern Suppression ────────────────────────────────────
# Phrases/constructions the AI should avoid. Built-in defaults cover
# purple prose, emoji, em-dashes, and common AI clichés ("delve",
# "tapestry", "a single tear", etc.). These are always active.
# Add your own here — duplicates of built-in defaults are
# automatically skipped to save tokens.
anti_patterns:
  - "shiver down * spine"
  - "a wave of *"
  - "the weight of the world"

# ─── Narrative Hooks ─────────────────────────────────────────────
# Story-level plot beats not tied to a specific chapter. The prompt
# builder includes the relevant hook when a scene maps to it.
# Optional: add 'chapters' range to control when a hook is active.
narrative_hooks:
  - hook: "The Storm: A nor'easter isolates the peninsula, cutting off escape."
    chapters: [3, 7]       # active during chapters 3 through 7
  - hook: "The Letter: A decades-old letter surfaces, rewriting the family history."
    chapters: [5, 12]
  - hook: "The Rescue: The keeper must choose between duty and a life at sea."
    # no chapter range = available whenever scene context matches

# ─── Chapters ────────────────────────────────────────────────────
chapters:
  - chapter_number: 1                    # REQUIRED
    title: "The Light on the Water"      # REQUIRED
    summary: >                           # REQUIRED
      Introduction to the keeper and the lighthouse.
      Establish the isolation and daily routine.
    style_override: null                 # Optional per-chapter style tweaks
    scenes:                              # REQUIRED (at least one scene)
      - scene_number: 1.1               # REQUIRED
        setting: "the_lighthouse"        # Reference to locations/settings ID, or inline string
        characters_present:              # Optional explicit list (auto-detected if omitted)
          - silas_marsh
        events: >                        # REQUIRED
          Silas performs his morning inspection. Describe the lighthouse
          interior, the view, and his meticulous routine.
        emotional_arc: "Calm → restless" # Optional
        pacing: slow-burn                # Optional: slow-burn | action | dialogue-heavy | introspective
        notes: >                         # Optional
          Establish Silas's isolation. Use sensory details: salt air,
          metal railing, the foghorn rhythm.

      - scene_number: 1.2
        setting: "The general store in town. Fluorescent lights, linoleum floor."
        characters_present:
          - silas_marsh
          - ruth_perry
        events: >
          Silas makes his weekly supply run. Ruth probes for gossip
          he won't give. Their dynamic: warmth vs. deflection.
        pacing: dialogue-heavy
        notes: "First appearance of Ruth. Show the town's curiosity about Silas."

  - chapter_number: 2
    title: "What the Tide Brought"
    summary: "A stranger washes ashore. Silas is forced to break his routine."
    scenes:
      - scene_number: 2.1
        setting: "the_lighthouse"
        events: "Silas finds an unconscious woman on the rocks below the lighthouse."
        emotional_arc: "Alarm → reluctant obligation"
        pacing: action
```

### Field Reference — Story Outline

| Field | Type | Required | Description |
|---|---|---|---|
| `story_title` | string | Yes | Title of the story |
| `style_directives` | string | No | Global writing style instructions for the AI |
| `world` | string | No | Global setting context (era, genre rules, tech level) — included in every prompt |
| `overall_arc` | object | No | Theme, tone, and POV for the story |
| `overall_arc.theme` | string | No | Central theme(s) |
| `overall_arc.tone` | string | No | Narrative tone/mood |
| `overall_arc.pov` | string | No | Point of view |
| `anti_patterns` | list of strings | No | Additional AI phrases/clichés to suppress (built-in defaults always active) |
| `narrative_hooks` | list | No | Story-level plot beats (see below) |
| `chapters` | list | Yes | Chapter definitions |

**Narrative Hook Fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `hook` | string | Yes | Description of the plot beat |
| `chapters` | list of 2 ints | No | `[start, end]` — active chapter range. Omit for always-available hooks. |

**Scene Fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `scene_number` | string/number | Yes | Identifier (e.g., `1.1`, `1.2`) |
| `setting` | string | Yes | Location ID (from settings file) or inline description |
| `characters_present` | list of strings | No | Character IDs. Auto-detected from events/notes if omitted. |
| `events` | string | Yes | What happens in the scene |
| `emotional_arc` | string | No | Emotional trajectory (e.g., "Calm → dread") |
| `pacing` | string | No | `slow-burn`, `action`, `dialogue-heavy`, `introspective` |
| `notes` | string | No | Authorial guidance for the AI |

---

## Characters

**File:** `characters.yaml` (or `characters:` key in a combined file)

```yaml
characters:
  silas_marsh:                           # Character ID (used for references)
    Name: Silas Marsh                    # REQUIRED — display name
    heritage: [human, lightkeeper]       # Optional — list of heritage IDs
    summary: >                           # Recommended
      Reclusive lighthouse keeper in his late fifties. Weathered,
      taciturn, secretly grieving a loss he won't name.
    role: "Lighthouse Keeper"            # Recommended
    personality:                         # Optional — trait list
      - stoic
      - methodical
      - privately sentimental
      - stubborn
    vibe: >                              # Recommended — tonal anchor
      A man who has made peace with solitude but not with himself.
      Every action is measured, every word costs him something.
    voice: >                             # Optional — speech patterns
      Sparse, declarative sentences. Avoids questions. Uses
      nautical terms unconsciously. Never raises his voice.
    habit: >                             # Optional — behavioral quirk
      Taps the barometer glass three times every morning, even
      though he knows the reading won't change.
    catchphrase: "It'll pass."           # Optional — simple string format
    catchphrase_frequency: rare          # Optional — rare | occasional | frequent (default: occasional)
    secret: >                            # Optional — hidden knowledge
      His wife didn't die in the accident. She left.
      He tells everyone she's gone because it's easier.
    relationships:                       # Optional — map of character_id: description
      ruth_perry: "The only person who checks on him. He tolerates it."
      the_stranger: "An obligation he didn't ask for."
    evolution:                           # Optional — character growth notes
      - after_chapter: 4
        note: "Starts speaking in longer sentences. Opening up despite himself."
      - after_chapter: 8
        note: "Confronts his lie about his wife. Raw, defensive, then resigned."

  ruth_perry:
    Name: Ruth Perry
    summary: "Town postmistress and unofficial gossip wire. Sharp, warm, relentless."
    role: "Postmistress / Social Connector"
    personality: [perceptive, nosy, generous, blunt]
    vibe: "A woman who believes knowing everyone's business is a form of care."
    voice: "Rapid-fire questions, doesn't wait for answers. Uses first names aggressively."
    catchphrase: "Now you listen to me."
    catchphrase_frequency: occasional
    relationships:
      silas_marsh: "Her personal project. She's determined to crack him open."

  the_stranger:
    Name: "Unknown (revealed Chapter 6)"
    summary: "A young woman found unconscious on the rocks. No ID, no memory."
    role: "Catalyst"
    personality: [guarded, observant, quick-tempered]
    vibe: "A wound wrapped in silence. She watches everything and trusts nothing."
    secret: "She remembers more than she lets on."
```

### Field Reference — Characters

| Field | Type | Required | Sent to AI | When |
|---|---|---|---|---|
| `Name` | string | Yes | Always | Every scene the character appears in |
| `heritage` | string or list | No | Merged (see Heritage) | First appearance: full heritage traits. Later: dropped. |
| `summary` | string | No | First appearance | Dropped after character is established |
| `role` | string | No | Always | Every scene |
| `personality` | list | No | First appearance | Dropped after established |
| `vibe` | string | No | Always | Tonal anchor — never dropped |
| `voice` | string | No | Always | Shapes dialogue quality |
| `habit` | string | No | Always | Included if present |
| `catchphrase` | string | No | Probability-gated | When the frequency roll hits |
| `catchphrase_frequency` | string | No | (internal) | Controls probability gate |
| `catchphrases` | list | No | Probability-gated | Alternative list format (see below) |
| `secret` | string | No | Conditional | Included when scene notes reference tension/subtext |
| `relationships` | map | No | Conditional | Included for scenes where both characters are present |
| `evolution` | list | No | Accumulated | All notes up to current chapter |

**Catch Phrase Formats:**

The simple string format covers most cases:
```yaml
catchphrase: "It'll pass."
catchphrase_frequency: occasional    # rare (1/8) | occasional (1/4) | frequent (1/2)
```

For multiple catch phrases with individual frequency control:
```yaml
catchphrases:
  - phrase: "It'll pass."
    frequency: rare
  - phrase: "That's the sea for you."
    frequency: occasional
```

If no frequency is specified, it defaults to `occasional`.

---

## Heritage

**File:** `characters.yaml`, `heritage.yaml`, or `heritage:` key in a combined file

Heritage defines shared traits for groups — species, professions, factions, social classes, or any identity that multiple characters share. Characters reference heritage by ID, and the prompt builder merges inherited traits into their context.

```yaml
heritage:
  dwarf:
    label: "Mountain Dwarf"
    traits: "Stocky, broad-shouldered, rarely over 4'8". Deep voices. Suspicious of surface customs."
    speech_patterns: "Clipped sentences. Heavy use of oaths and craft metaphors."
    cultural_notes: >-
      Greet peers with a closed-fist chest tap. Consider eye contact
      during meals rude. Value craftsmanship over titles.

  elf:
    label: "Sylvan Elf"
    traits: "Tall, angular, unnervingly still. Move silently without trying."
    speech_patterns: "Formal register, even in casual conversation. Rarely use contractions."
    cultural_notes: "Mark time in seasons, not years. Names have three parts: given, lineage, deed."

  blacksmith:
    label: "Guild Blacksmith"
    traits: "Burn-scarred forearms, calloused hands. Judges people by their tools."
    speech_patterns: "Measures words like metal — nothing wasted."
    cultural_notes: "Greet fellow smiths by showing palms. Never touch another smith's hammer."

  clergy:
    label: "Order of the Quiet Flame"
    traits: "Tonsured, soft-spoken, carries a censer or prayer beads."
    speech_patterns: "Formal, uses 'we' instead of 'I'. Quotes scripture reflexively."
    cultural_notes: "Forbidden from drawing blood directly. Takes meals in silence."

  miner:
    label: "Deep Miner"
    traits: "Permanently squinting, pale skin, pitch-stained fingernails."
    speech_patterns: "Low volume — used to echoing tunnels. Heavy on understatement."
```

Characters reference one or more heritage entries:

```yaml
characters:
  grimnar:
    Name: Grimnar Ironfold
    heritage: [dwarf, blacksmith]        # Layered: species + profession
    summary: "A disgraced smith seeking redemption through impossible craft."
    role: "Reluctant ally"
    vibe: "Shame and pride fighting for the same face."
    voice: "Even gruffer than most dwarves. Talks to his hammer."

  brother_aldric:
    Name: Brother Aldric
    heritage: [human, clergy]            # Species + social role
    summary: "A monk whose faith is quieter than his order demands."
    role: "Moral compass"
    vibe: "Doubt worn like a second robe."

  tessa_quarry:
    Name: Tessa Quarry
    heritage: halfling                   # Single heritage (string, not list) works too
    summary: "A halfling who talks too much and sees too much."
    role: "Scout"
```

### Merge Rules

When a character references multiple heritage entries, fields are merged in list order. Later entries override earlier ones for overlapping fields. The character's own fields always override heritage.

**Priority stack (highest wins):**
```
character.voice  >  last heritage speech_patterns  >  first heritage speech_patterns
character.vibe   >  (heritage has no vibe — vibe is character-only)
```

### When Heritage Data Is Sent

| Tier | Heritage data included |
|---|---|
| **First appearance** | Merged `traits`, `speech_patterns`, and `cultural_notes` alongside character bio |
| **Subsequent appearances** | Heritage traits dropped (now established in narrative) |

If a scene involves cross-heritage interaction and the contrast matters, the prompt builder may re-include relevant `cultural_notes` as scene context.

### Field Reference — Heritage

| Field | Type | Required | Description |
|---|---|---|---|
| *(key)* | string | Yes | Heritage ID used for character references |
| `label` | string | No | Display name for the heritage group |
| `traits` | string | No | Physical/behavioral traits common to the group |
| `speech_patterns` | string | No | How members of this group typically speak |
| `cultural_notes` | string | No | Customs, rituals, social norms |

---

## Settings / Locations

**File:** `locations.yaml`, `settings.yaml`, or `setting:`/`locations:` key in a combined file

Both `setting:` and `locations:` are recognized as top-level keys.

```yaml
setting:
  the_lighthouse:
    type: "19th-century stone lighthouse on a rocky peninsula"
    atmosphere: >
      Salt-crusted windows, the constant low vibration of the sea.
      Everything smells of brine and machine oil.
    exterior: >
      Whitewashed stone, streaked with rust from the iron railing.
      A narrow path of crushed shells leads to the keeper's cottage.
    interior: >
      Spiral iron staircase, 127 steps. Brass instruments on the
      watch room desk. The lens room hums when the light is on.
    mood_shift:
      night: "The lighthouse transforms. Shadows pool on the stairs. The foghorn is a heartbeat."
      storm: "The walls groan. Spray hits the windows at the top. The light feels like the only real thing."

  perry_general_store:
    type: "Small-town general store, also serves as post office"
    atmosphere: "Fluorescent hum, coffee always on, linoleum that squeaks."
    details:
      - "A community bulletin board covered in layers of flyers"
      - "Ruth's handwritten signs with aggressive underlining"
      - "A cat named Senator who sleeps on the mail counter"

  the_rocks:
    type: "Rocky shoreline below the lighthouse"
    atmosphere: "Exposed, raw, loud. The waves are a constant percussion."
    mood_shift:
      low_tide: "Tide pools, slippery kelp, the smell of marine life."
      high_tide: "Violent spray, no footing, the rocks disappear under whitewater."
```

### Field Reference — Settings

| Field | Type | Required | Description |
|---|---|---|---|
| *(key)* | string | Yes | Location ID used for scene references |
| `type` | string | No | Brief classification of the place |
| `atmosphere` | string | No | Default sensory/mood description |
| `mood_shift` | map | No | Keyed variants (time of day, weather, story phase) |
| *(any other keys)* | string/list | No | Sub-areas, details, or descriptive fields — all included in prompt |

The schema is intentionally flexible for nested sub-areas. Any key that isn't a recognized field name is treated as a sub-location or descriptive attribute and included when the scene references this setting.

---

## Checkpoint (Auto-Generated)

**File:** `checkpoint.yaml` — written automatically after each scene. **Do not edit manually** unless recovering from corruption.

```yaml
story_title: "The Last Lighthouse"
output_file: "full_story.md"
last_completed_chapter: 1
last_completed_scene: "1.2"
timestamp: "2026-02-21T14:30:00"

# Rolling story summary (AI-generated, token-efficient)
story_so_far: >
  Silas Marsh tends the lighthouse alone, locked into a routine that
  keeps grief at arm's length. His weekly trip to town reveals Ruth
  Perry as the only person who tries to reach him.

# Recent scene summaries (rolling window, last 3)
recent_scenes:
  - scene: "1.1"
    summary: "Silas performs his morning inspection. The lighthouse is described in detail — the isolation is physical and emotional."
  - scene: "1.2"
    summary: "Silas and Ruth spar at the general store. Ruth pushes; Silas deflects. Warmth underneath."

# Tracks which characters have appeared (for bio tier logic)
character_appearances:
  silas_marsh: ["1.1", "1.2"]
  ruth_perry: ["1.2"]

# Story memory — persistent details extracted from generated scenes
story_memory:
  characters:
    barista_jake:
      name: Jake
      introduced_scene: "2.1"
      description: "Bearded barista at the harbor café. Knows Silas by order."
      last_seen: "4.2"
      notes: "Seemed distracted in 4.2 — dark circles, short-tempered."
  facts:
    - scene: "1.1"
      detail: "The lighthouse foghorn sounds every 30 seconds in fog."
    - scene: "1.2"
      detail: "Ruth saves the Tuesday paper for Silas every week."
  commitments:
    - scene: "2.2"
      detail: "Silas told Ruth he'd attend the town meeting. He won't."
```

**Story Memory** is extracted automatically after each scene by the summary model. It captures throw-away characters, world facts, and promises/commitments that may matter later. The prompt builder includes relevant memory entries when a scene references those characters or locations. Authors can review and edit this section between runs.

---

## Combined File Format

All data can live in a single `story_data.yaml`:

```yaml
story_title: "The Last Lighthouse"
style_directives: "Grounded literary fiction with sensory detail."
world: "Coastal New England, late 1980s."

overall_arc:
  theme: "Isolation, duty, secrets"
  tone: "Atmospheric, melancholic"
  pov: "Third-person limited"

anti_patterns:
  - "unbeknownst"
  - "shiver down * spine"

narrative_hooks:
  - hook: "The Storm"
    chapters: [3, 7]

characters:
  silas_marsh:
    Name: Silas Marsh
    heritage: human
    summary: "Reclusive lighthouse keeper."
    role: "Keeper"
    vibe: "A man who made peace with solitude but not himself."
    catchphrase: "It'll pass."

setting:
  the_lighthouse:
    type: "Stone lighthouse"
    atmosphere: "Salt, brine, machine oil."

chapters:
  - chapter_number: 1
    title: "The Light on the Water"
    summary: "Introduction to Silas and the lighthouse."
    scenes:
      - scene_number: 1.1
        setting: the_lighthouse
        events: "Silas performs his morning inspection."
```

The script detects top-level keys (`characters`, `setting`/`locations`, `chapters`, etc.) and loads them regardless of which file they're in.

---

## Tips for Authors

1. **Start minimal.** Only `story_title`, `chapters` (with `events`), and `characters` (with `Name`) are truly required. Add detail as you refine.

2. **Write `vibe`, not biography.** The `vibe` field has the highest impact on output quality. It tells the AI *how the character should feel to the reader* — more valuable than a list of facts.

3. **Use `voice` for dialogue quality.** If a character's dialogue feels generic, adding a `voice` field ("Short sentences, avoids eye contact in conversation, uses hedging language") will sharpen it immediately.

4. **Don't over-describe settings.** A few vivid details beat a paragraph of description. The AI will fill in the gaps — and often better when given room.

5. **Use `notes` liberally in scenes.** This is your direct channel to the AI. "Make this scene tense" or "Let the silence do the work here" are valid notes.

6. **Tag `pacing` on key scenes.** The AI defaults to a middle-of-the-road pace. Tagging a scene as `action` or `slow-burn` noticeably changes its output.

7. **Add `evolution` notes as you plan.** Even rough notes ("Gets angrier after chapter 5") help the AI build character arcs instead of writing flat repetitions.

8. **Use `mood_shift` for locations that change.** A house at night vs. morning, a street in rain vs. sun — these small variants add atmospheric depth without duplicating location entries.

9. **Use `heritage` for shared group traits.** If multiple characters share species, profession, or faction traits, define them once in `heritage:` and reference by ID. Saves repetition and ensures consistency.

10. **Don't worry about story memory.** The tool automatically tracks throw-away characters, world facts, and commitments. If the AI invents a bartender in chapter 2, it'll remember them in chapter 7.
