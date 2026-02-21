# Novel Builder — Design Plan

## Overview

This document is the roadmap for expanding Novel Builder from a working prototype into a robust, resilient, quality-focused story generation tool. Changes are organized into phases. Each phase is self-contained and delivers usable improvements.

## Resolved Decisions

| Decision | Resolution |
|----------|------------|
| Summary model | `gemma3:1b` (fast, adequate for factual compression; bump to 4b if quality falls short) |
| Generation model | `gemma3:12b` (user's current default) |
| Character bios | Brief bios confirmed. First appearance: full bio. Subsequent: name + role + vibe + evolution notes. |
| Catch phrase gating | Simple string format in YAML; default frequency `occasional`; probability rolls in prompt builder |
| Checkpoint per-scene | Approved — write state after every scene |
| Per-scene file writes | Approved — append mode, never buffer full chapters |
| Scene length control | Let the AI decide — no word count targets |
| Interactive mode | Future (P3) — not near-term |
| Post-completion rewrite | P3 feature — reference original prompt + prior summary to regenerate with user guidance |
| Proofread pass | Optional `--proofread` flag (P3) — regex cleanup is automatic; LLM proofread is opt-in |
| Code structure | Modularized Python package (`novel_builder/`) |
| YAML structure | Support both separate files and single combined file |

---

## Phase 1: Resilience & Resume (Critical Path)

These fixes address the "lost 15 of 21 chapters" problem — the highest priority.

### 1.1 Retry Logic for Ollama API Calls

**Problem:** A single timeout kills the entire run.

**Solution:**
- Wrap `call_ollama()` with configurable retry logic: default 3 attempts, exponential backoff (5s, 15s, 45s).
- On final failure, save state and exit gracefully instead of `sys.exit(1)`.
- Make retry count and timeout configurable via CLI flags (`--retries`, `--timeout`).

### 1.2 Checkpoint / Resume System

**Problem:** No way to continue from where generation left off.

**Solution:**
- After each scene completes, write a `checkpoint.yaml` file containing:
  - `last_completed_chapter` and `last_completed_scene`
  - `story_so_far` summary text
  - `output_file` path (to resume appending)
  - Timestamp
- On startup, detect `checkpoint.yaml` and prompt: "Resume from Chapter X, Scene Y? [Y/n]"
- Add `--resume` CLI flag to auto-resume without prompting.
- Add `--restart` CLI flag to ignore checkpoint and start fresh.

### 1.3 Graceful Shutdown

- Catch `KeyboardInterrupt` (Ctrl+C) and save checkpoint before exiting.
- Print clear message: "Progress saved. Run again to resume from Chapter X, Scene Y."

---

## Phase 2: Context Quality (Story Flow)

These changes address the core quality issues: catch phrase overuse, character description bloat, and weak scene-to-scene continuity.

### 2.1 AI-Powered Scene Summarization

**Problem:** `story_so_far` is a raw concatenation of outline summaries — not a flowing, token-efficient narrative context.

**Solution:**
- After writing each scene, make a second (smaller, faster) Ollama call to summarize that scene into 2-3 sentences.
- Use a dedicated summarization prompt: "Summarize this scene in 2-3 concise sentences, focusing on key plot developments, emotional shifts, and character actions."
- Store the summary in `checkpoint.yaml` and feed it into the next scene's prompt.
- Maintain a **rolling window** of the last N scene summaries (configurable, default: 3) plus a compressed "story so far" that itself gets re-summarized every chapter.

### 2.2 Smart Character Context

**Problem:** Sending full character bios every scene wastes tokens and causes the AI to mechanically describe characters instead of letting them evolve.

**Solution — tiered context based on appearance count:**

| Context tier | When | Fields sent |
|---|---|---|
| **Full bio** | First appearance in story | Name, summary, role, personality, vibe, habit (if any), heritage traits |
| **Reminder** | Subsequent appearances | Name, role, vibe + evolution notes up to current chapter |

The `vibe` field is the persistent tonal anchor — it tells the AI *how this character should feel in the story*, not just factual traits. `personality` and `summary` are dropped after first appearance since those traits are now established in the narrative.

Add an optional `evolution` list to character YAML entries:
```yaml
characters:
  elias_thorne:
    Name: Elias Thorne
    summary: "Introverted, physically strong clerk; alone and struggling with grief."
    role: "Inventory Clerk / Heavy Lifter"
    catchphrase: "That figures."
    personality: [timid, observant, empathetic, resigned, diligent]
    vibe: "A listless young man trying to find purpose or direction."
    evolution:
      - after_chapter: 3
        note: "Beginning to form genuine connection; less withdrawn"
```
The prompt builder reads evolution notes up to the current chapter and includes them.

The `characters.py` module tracks which characters have appeared (via checkpoint state) to determine full-bio vs. reminder tier.

### 2.3 Catch Phrase Frequency Control

**Problem:** Catch phrases appear in every scene, feeling forced and repetitive.

**Solution:**
- YAML keeps the simple string format: `catchphrase: "That figures."`
- An optional `catchphrase_frequency` field controls injection rate. If omitted, defaults to `occasional`.
- Frequency probabilities: `rare` (1 in 8 scenes), `occasional` (1 in 4), `frequent` (1 in 2).
- The prompt builder rolls a probability check per scene per character and only includes the catch phrase instruction when it hits.
- When included, frame it as a suggestion: "If it feels natural, {character} might say something like '{phrase}'."
- When excluded, omit entirely — don't say "don't use catch phrases" (that paradoxically reminds the AI of them).
- For authors who want per-phrase control, a list format is also supported:
  ```yaml
  catchphrases:
    - phrase: "That figures."
      frequency: rare
    - phrase: "Well, here we go."
      frequency: occasional
  ```
  The prompt builder detects either format.

### 2.4 Anti-Pattern Suppression List

**Problem:** AI models repeat certain clichéd constructions ("a shiver ran down their spine", "little did they know", em-dashes everywhere).

**Solution:**
- Add a configurable `anti_patterns` list in the outline YAML:
  ```yaml
  anti_patterns:
    - "shiver down * spine"
    - "unbeknownst"
    - "little did * know"
    - "the weight of *"
    - "em-dashes"
  ```
- Include these in the system prompt as suppression instructions.
- Also apply lightweight regex post-processing to catch patterns that slip through (like the existing em-dash replacement).

### 2.5 Story Memory

**Problem:** The AI invents minor characters, establishes world facts, and makes promises that it immediately forgets. Recurring throw-away characters are re-introduced as strangers. Established details contradict.

**Solution:**
- After each scene, combine the summarization call with a structured extraction step (same call, single prompt to the summary model).
- Extraction prompt: "Summarize this scene in 2-3 sentences. Then list any NEW persistent details: new named characters (name, description, role), relationships formed/changed, promises or commitments, objects introduced, facts about the world. Only new information."
- Store extracted data in `story_memory` section of `checkpoint.yaml`:
  ```yaml
  story_memory:
    characters:
      barista_jake:
        name: Jake
        introduced_scene: "2.1"
        description: "Bearded barista at the harbor café. Knows Silas by order."
        last_seen: "4.2"
        notes: "Seemed distracted — dark circles, short-tempered."
    facts:
      - scene: "1.2"
        detail: "Ruth saves the Tuesday paper for Silas every week."
    commitments:
      - scene: "2.2"
        detail: "Silas told Ruth he'd attend the town meeting."
  ```
- The prompt builder includes relevant memory entries when a scene references those characters or locations.
- **Scope control:** Cap tracked characters at ~20. Auto-archive facts/commitments unreferenced for N chapters. Extraction uses low temperature (0.3) to minimize hallucination.
- **Author editable:** `checkpoint.yaml` is human-readable YAML. Authors can review and correct between runs.

### 2.6 Heritage System

**Problem:** When multiple characters share species, profession, or faction traits, those traits must be repeated in every character bio — risking inconsistency and wasting tokens.

**Solution:**
- Add a `heritage:` top-level YAML section defining shared group traits.
- Characters reference heritage by ID: `heritage: [dwarf, blacksmith]` (list) or `heritage: clergy` (string).
- The prompt builder merges heritage traits into character context on first appearance. Later appearances drop heritage (established in narrative).
- Character-level fields always override heritage fields (individual > group).
- For scenes with cross-heritage interaction, relevant `cultural_notes` may be re-included.
- Heritage data lives alongside characters — same file or separate `heritage.yaml`.
- Zero extra LLM calls — purely a prompt-building feature.

---

## Phase 3: CLI & UX Polish

### 3.1 Argparse CLI

Replace bare `input()` calls with a proper CLI:

```
novel-builder.py [OPTIONS]

Options:
  --host HOST          Ollama host URL (overrides OLLAMA_HOST env)
  --model MODEL        Ollama model name (default: gemma3:12b)
  --outline FILE       Story outline YAML (default: story_outline.yaml)
  --characters FILE    Character YAML (default: characters.yaml)
  --locations FILE     Location YAML (default: locations.yaml)
  --output FILE        Output markdown file (default: full_story.md)
  --resume             Resume from checkpoint without prompting
  --restart            Ignore checkpoint and start fresh
  --quiet              Suppress terminal output of generated text
  --retries N          Ollama retry attempts (default: 3)
  --timeout SECS       Ollama request timeout (default: 900)
  --summary-model MODEL  Use a different (faster) model for summarization
  --dry-run            Parse YAML and show plan without generating
  --chapter N          Generate only chapter N
  --scene N.M          Generate only chapter N, scene M
```

Interactive `input()` prompts remain as fallback when CLI args are not provided.

### 3.2 Dry Run Mode

`--dry-run` parses all YAML, detects characters per scene, and prints the generation plan without calling Ollama. Useful for validating outline structure and character detection.

### 3.3 Progress Display

- Print: `[Chapter 3/12, Scene 2/4] Writing "The Betrayal"...`
- On completion: print total word count, chapter count, elapsed time.

---

## Phase 4: YAML Data Architecture

### 4.1 Settings / Locations File

Settings (or locations) describe reusable places. Both `setting:` and `locations:` are recognized as keys. Rich nesting is supported for sub-areas and sensory detail.

```yaml
setting:
  empire_toys_and_hobbies:
    type: "Ancient, three-story toy store"
    atmosphere: "Cedar wood, old paper, and vintage plastic; groaning floorboards."
    security:
      camera: "Non-functional 1990s CCTV; fake red light."
      alarm: "Ancient, hair-trigger system; piercing bell if front door is rattled."
    the_aisles: "Narrow, claustrophobic paths lined with dead stock and fading displays."

  elias_apartment:
    type: "Cramped studio apartment"
    atmosphere: "Dim, cluttered, smells of old coffee."
```

Scenes reference settings by ID:
```yaml
scenes:
  - scene_number: 2.1
    setting: empire_toys_and_hobbies
    events: "Elias arrives for work, meets Morty."
```

The prompt builder resolves the setting ID and includes relevant details. For inline settings (a string instead of an ID), the text is used as-is.

### 4.2 Enhanced Story Outline Structure

```yaml
story_title: "To Be Determined"

style_directives: "You are an author specializing in adult novels and short stories."

overall_arc:
  theme: "Loneliness, connection, acceptance, and transformation."
  tone: "Atmospheric, sensual, and emotionally resonant."
  pov: "First-person, Elias' perspective."

anti_patterns:
  - "shiver down * spine"
  - "unbeknownst"
  - "a wave of *"

narrative_hooks:
  - "The First Contact: Elias, locked in the dark, talks to the display to ease his loneliness."
  - "The Arrival: A heavy crate arrives; Elias must unbox Francine."
  - "The Guardian: When Morty's forgetfulness creates danger, the group must work together."

chapters:
  - chapter_number: 1
    title: "The Empty Apartment"
    summary: "Introduction to Elias and his life. Establishing his loneliness and grief."
    style_override: null  # or per-chapter style tweaks
    scenes:
      - scene_number: 1.1
        setting: "Elias's apartment - cramped, messy, reflecting his emotional state."
        events: "Elias wakes up, goes through his morning routine. Internal monologue."
        emotional_arc: "Resignation → flickers of hope"
        notes: "Focus on sensory details - old coffee, dim light, city sounds."
```

**`narrative_hooks`** are story-level plot beats not tied to a specific chapter. The prompt builder includes the *relevant* hook when a scene maps to it (matched by keyword/character), rather than dumping all hooks into every prompt.

### 4.3 Character YAML Schema

Based on real author data, the canonical character schema:

```yaml
characters:
  elias_thorne:
    Name: Elias Thorne
    summary: "Introverted, physically strong clerk; alone and struggling with grief."
    role: "Inventory Clerk / Heavy Lifter"
    catchphrase: "That figures."
    catchphrase_frequency: occasional  # rare | occasional | frequent (default: occasional)
    personality: [timid, observant, empathetic, resigned, diligent]
    vibe: "A listless young man with his whole life ahead of him trying to find purpose."
    evolution:
      - after_chapter: 3
        note: "Beginning to form genuine connection; less withdrawn"

  morty_wick:
    Name: Morty Wick
    summary: "Senile store owner; kind but deeply disoriented; relies on muscle memory."
    role: "Proprietor"
    catchphrase: "Now, what was I saying?"
    personality: [forgetful, warm, repetitive, shaky]
    habit: "Locks the store while Elias is still inside; sets the alarm by rote."
    vibe: "A fading craftsman who treats his stock like old friends he can't quite name."
```

**Supported fields** (all optional except `Name`):
| Field | Purpose | Used in prompt |
|---|---|---|
| `Name` | Display name | Always |
| `summary` | One-line character description | First appearance only |
| `role` | Story/occupation role | Always |
| `catchphrase` | Signature line (string) | Probability-gated |
| `catchphrase_frequency` | `rare`/`occasional`/`frequent` | Controls gate |
| `catchphrases` | List format alternative (see 2.3) | Probability-gated |
| `personality` | Trait list | First appearance only |
| `vibe` | Tonal/atmospheric anchor | Always (core context) |
| `habit` | Behavioral quirk | Always if present |
| `heritage` | Group identity references (list) | First appearance: merged traits. Later: dropped. |
| `evolution` | Growth notes per chapter | Accumulated to current chapter |

---

## Phase 5: Advanced Features (Future)

### 5.1 Multi-Pass Revision

After full draft generation, offer an optional revision pass:
- Feed each chapter back to the AI with instructions to improve prose quality, smooth transitions, and ensure consistency.
- Use a different system prompt focused on editing rather than generation.

### 5.2 Continuity Checker

After generation, run a validation pass:
- Feed the AI the full character list + story outline + generated text.
- Ask it to flag continuity errors (character in wrong location, timeline inconsistencies, etc.).

### 5.3 Export Formats

- Markdown (current) 
- EPUB generation via pandoc or a lightweight library
- Plain text

### 5.4 Interactive Mode

- After generating a scene, optionally prompt the author: "Accept / Regenerate / Edit instructions?"
- In edit mode, let the author type feedback that gets fed back to the AI: "Make the dialogue sharper" → regenerate that scene with the note.

### 5.5 Post-Completion Scene Rewrite

**Problem:** After a full generation run, some scenes may need rework but the author doesn't want to regenerate the whole story.

**Solution:**
- Add `--rewrite N.M` flag (chapter N, scene M) to regenerate a specific scene.
- The rewrite references the original generation prompt and the prior scene's stored summary from `checkpoint.yaml`.
- Prompt the user: "What should change about this scene?" and incorporate their guidance into the regeneration prompt.
- Replace the scene in the output file in-place (or write to a separate `_rewrite.md` for comparison).
- This is the "walk away and come back" workflow — review at leisure, then selectively fix.

### 5.6 Proofread Pass

**Problem:** Minor grammar issues, leftover AI-isms, and awkward phrasing slip through generation.

**Solution — two layers:**
1. **Regex post-processing** (automatic, every scene): Deterministic cleanup of known patterns (em-dashes, clichéd phrases). Zero risk.
2. **LLM proofread pass** (optional, `--proofread` flag): Runs after full generation completes. Uses the summary model (`gemma3:1b`) for speed. Tightly scoped prompt: "Fix grammar and remove clichés. Preserve the author's voice. Do not add, remove, or rearrange content." Writes proofread output to `{output}_proofread.md`.

### 5.7 Parallel Scene Generation

- For scenes that are independent (different POV characters, no causal dependency), allow parallel Ollama calls to speed up generation.
- Requires dependency analysis from the outline YAML.

### 5.8 Model Routing

- Use `gemma3:1b` (default) for summarization and proofread tasks.
- Use `gemma3:12b` (default) for scene generation.
- Both configurable via `--model` and `--summary-model` flags.

---

## Implementation Priority

| Priority | Item | Phase | Effort |
|----------|------|-------|--------|
| **P0** | Retry logic | 1.1 | Small |
| **P0** | Checkpoint/resume | 1.2 | Medium |
| **P0** | Graceful shutdown | 1.3 | Small |
| **P1** | AI scene summarization | 2.1 | Medium |
| **P1** | Smart character context | 2.2 | Medium |
| **P1** | Catch phrase frequency | 2.3 | Small |
| **P1** | Anti-pattern suppression | 2.4 | Small |
| **P1** | Story memory | 2.5 | Medium |
| **P1** | Heritage system | 2.6 | Small |
| **P2** | Argparse CLI | 3.1 | Medium |
| **P2** | Dry run mode | 3.2 | Small |
| **P2** | Progress display | 3.3 | Small |
| **P2** | Locations YAML | 4.1 | Small |
| **P2** | Enhanced YAML schemas | 4.2-4.3 | Medium |
| **P3** | Multi-pass revision | 5.1 | Large |
| **P3** | Continuity checker | 5.2 | Medium |
| **P3** | Export formats | 5.3 | Medium |
| **P3** | Interactive mode | 5.4 | Large |
| **P3** | Post-completion rewrite | 5.5 | Medium |
| **P3** | Proofread pass | 5.6 | Medium |
| **P3** | Parallel generation | 5.7 | Large |
| **P3** | Model routing | 5.8 | Small |

---

## Resolved Questions

1. **Single file vs. multi-module?** → **Modularized.** Split into a `novel_builder/` package. Maintain a module tree in `AGENTS.md` for quick reference.

2. **YAML consolidation?** → **Support both.** Detect `story_data.yaml` (combined) or separate files. Auto-discovery with CLI overrides.

3. **Summary model?** → **`gemma3:1b`** for summaries. Fast, adequate for factual compression. Override with `--summary-model`.

4. **Scene length control?** → **No targets.** Let the AI take the space it needs for effective storytelling.

5. **Interactive mode priority?** → **Future (P3).** Post-completion scene rewrite is the near-term alternative.

## Open Questions

_(None at this time. All design questions resolved.)_

---

## Module Structure

```
novel-builder/
├── novel_builder/
│   ├── __init__.py           # Package init, version
│   ├── __main__.py           # Entry point: `python -m novel_builder`
│   ├── cli.py                # Argparse CLI definition
│   ├── config.py             # Configuration loading, defaults, YAML discovery
│   ├── ollama_client.py      # Ollama API calls, retry logic, model routing
│   ├── prompt_builder.py     # System/user prompt construction per scene
│   ├── state.py              # Checkpoint read/write, resume logic
│   ├── story_processor.py    # Main generation loop, orchestration
│   ├── characters.py         # Character loading, filtering, evolution, catch phrases
│   ├── locations.py          # Location loading and resolution
│   ├── yaml_io.py            # YAML loading/saving utilities
│   └── postprocess.py        # Regex cleanup, anti-pattern removal
├── novel-builder.py          # Thin wrapper (calls novel_builder.__main__)
├── story_outline.yaml        # User-provided story data
├── characters.yaml           # User-provided character data
├── locations.yaml            # User-provided location data (optional)
├── checkpoint.yaml           # Auto-generated, tracks progress
├── DESIGN_PLAN.md
├── AGENTS.md
├── requirements.txt
└── .github/
    └── copilot-instructions.md
```

## Status

- [x] Design plan written
- [x] Decisions resolved with user
- [ ] Phase 1: Resilience & Resume
- [ ] Phase 2: Context Quality  
- [ ] Phase 3: CLI & UX Polish
- [ ] Phase 4: YAML Architecture
- [ ] Phase 5: Advanced Features
