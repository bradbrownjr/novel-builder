# AGENTS.md — Novel Builder Memory

This file is the persistent memory for the Novel Builder project. Copilot reads this file on every session to recall user directives and project conventions.

## Always/Never Directives

_(Add directives here when the user says "always" or "never" do something.)_

- **Always** commit and push changes to the repository after making code changes.

- **Always** write generated scenes to the output file immediately after generation (never buffer full chapters).
- **Always** default to outputting scenes to both file and terminal unless overridden by CLI flags.
- **Never** hardcode style directives in Python — they belong in the YAML outline.
- **Never** include all character bios in every scene prompt — only send characters present in the scene.
- **Always** keep `README.md` as a concise table of contents with a project description. Detailed documentation goes in `docs/`. Keep content scannable and bite-sized for readers.
- **Never** include scene dividers (dashes, lines, etc.) in output — aim for a book-like appearance.
- **Never** include markdown formatting (`---`, scene headers, etc.) in generated scene text.
- **Always** preserve chapter headers before each chapter's first scene.

## Project Conventions

- Code is organized as a Python package: `novel_builder/` with `novel-builder.py` as a thin wrapper.
- YAML is the only data format for story input/configuration.
- Supports both separate YAML files (characters.yaml, locations.yaml, story_outline.yaml) and a single combined `story_data.yaml`.
- Markdown is the output format.
- Ollama is the only supported LLM backend (for now).
- Minimal dependencies: `pyyaml`, `requests`, stdlib only.
- Default generation model: `gemma3:12b`. Default summary model: `gemma3:4b`.
- No word count targets — let the AI decide scene length.
- Interactive mode is deferred (P3). Post-completion rewrite is the near-term alternative.

## Module Tree

```
novel_builder/
├── __init__.py           # Package init, version
├── __main__.py           # Entry point: python -m novel_builder
├── cli.py                # parse_args()
├── config.py             # load_config(), discover_yaml_files()
├── ollama_client.py      # call_ollama(), call_ollama_with_retry()
├── prompt_builder.py     # build_system_prompt(), build_scene_prompt(), build_summary_prompt()
├── state.py              # load_checkpoint(), save_checkpoint(), should_resume(), should_compress(), compress_story_so_far()
├── story_processor.py    # generate_story(), process_chapter(), process_scene(), regenerate_scene(), regenerate_chapter()
├── characters.py         # load_characters(), filter_for_scene(), auto_detect_characters(), get_evolution_context()
├── locations.py          # load_locations(), resolve_location()
├── yaml_io.py            # load_yaml(), save_yaml()
├── postprocess.py        # clean_scene_text(), apply_anti_patterns()
├── tts.py                # segment_text_for_tts(), _find_speaker(), _name_matches_attribution()
├── web.py                # Flask web UI, TTS proxy, /api/memory (GET+POST), /api/regenerate, /api/download (marker-stripped), /api/ollama-pull (model download), /api/consult (AI audit)
├── consult.py            # AI-powered YAML audit: multi-pass analysis prompts, fix generation
└── validator.py          # validate_all()
```

_(Update this tree when functions are added, renamed, or moved.)_

## Known Issues (Active)

- Catch phrases are injected indiscriminately into every scene prompt, causing overuse in output. → Fix: Phase 2.3 (frequency gating)
- Full character bios are sent every scene, inhibiting character growth and adding unnecessary tokens. → Fix: Phase 2.2 (tiered context)
- Scene/location models are mixed into character YAML — need separation or clear structure. → Fix: Phase 4.1

## Character Context Strategy

| Context tier | When | Fields sent |
|---|---|---|
| **Full bio** | First appearance in story | Name, summary, role, personality, vibe, species, appearance, voice, habit + merged heritage traits |
| **Reminder** | Subsequent appearances | Name, role, vibe, species, appearance, voice + evolution notes |

- `vibe` is the persistent tonal anchor — always included.
- `voice` (speech patterns) is always included when present — shapes dialogue.
- `personality` and `summary` are dropped after first appearance (now established in narrative).
- `heritage` traits merged on first appearance, dropped after (established in narrative). Character fields override heritage.
- `catchphrase` is probability-gated, not included every scene.
- `secret` is only included when the scene's notes reference tension or subtext.
- `relationships` are included when both characters in the relationship are present in the scene.
- Character appearance history is tracked in `checkpoint.yaml`.
- Story memory (auto-extracted minor characters, facts, commitments) is tracked in `checkpoint.yaml` and injected when relevant.

## Resolved Issues

_(Track fixes here for reference.)_

- Retry logic on Ollama timeout — 5 retries with 3m/5m/15m/30m/60m backoff (Phase 1.1).
- Checkpoint/resume — generation can be paused and resumed from last completed scene (Phase 1.2).
- `story_so_far` rolling compression — every 5 scenes, the summary model compresses the accumulated text to stay within token budget (Phase 2.1).
- Story memory now extracts ACTIONS (who did what) alongside facts/commitments for continuity tracking.
- Recent memory items (actions, commitments, facts from last 5 scenes) are always injected into prompts regardless of keyword matching.
- Editable Memory tab — users can edit, add, and delete story memory items (facts, actions, commitments, characters) and save back to checkpoint.
- Scene/chapter regeneration — users can regenerate individual scenes or entire chapters from the Output tab. Old text is logged before replacement.
- Scene markers (`<!-- scene:X.Y -->` / `<!-- /scene:X.Y -->`, `<!-- chapter:N -->`) embedded in .md output for regeneration targeting. Stripped from downloads.
- Character roster in system prompt scoped to appeared + current-scene characters only (prevents future character leakage).
- Summary model upgraded to `gemma3:4b` (from `gemma3:1b`) for better extraction quality.
- Extraction/summary prompt sharpened: focuses on plot-relevant facts, decisions, and commitments rather than trivial physical descriptions.
- Web UI model selectors with recommended models, RAM estimates, install status, and auto-pull from Ollama.
- AI Consult tab — multi-pass YAML audit with streaming analysis, per-file fix generation, and side-by-side diff review.

## Scene Marker Format

Output `.md` files contain HTML comment markers for scene identification:

```
<!-- chapter:1 -->
## Chapter 1 — Title

<!-- scene:1.1 -->
Scene text here...
<!-- /scene:1.1 -->

<!-- scene:1.2 -->
Scene text here...
<!-- /scene:1.2 -->
```

- Markers are invisible in rendered Markdown.
- `/api/download` strips all markers and collapses excess blank lines for a clean book file.
- `renderScenes()` in the UI parses these markers to create per-scene blocks with Regen buttons.

## Character Roster Scoping

The system prompt's character roster is **scoped per scene** to prevent the generation model from introducing characters before their intended appearance:

- Only characters that have **already appeared** (tracked in `character_appearances` in checkpoint) are listed.
- Characters **explicitly assigned to the current scene** (via character list or auto-detection) are also included.
- Characters not yet introduced are invisible to the generation model.
- `build_system_prompt()` accepts `state` and `scene_char_ids` parameters for this scoping.

## Model Selection & Pull

- Web UI provides combo-box selectors with recommended models (including RAM estimates and quality notes).
- Users can also type any model name directly.
- If a selected model is not installed, a "Pull from Ollama" button appears.
- `/api/ollama-pull` streams download progress from Ollama's `/api/pull` endpoint as SSE events.
- Recommended generation models: gemma3:4b, gemma3:12b, gemma3:27b, qwen2.5:7b, qwen2.5:14b, llama3.1:8b, mistral:7b, deepseek-r1:8b.
- Recommended summary models: gemma3:1b, gemma3:4b, qwen2.5:3b, qwen2.5:7b, phi4-mini, gemma3:12b.

## Setting Detail

Scenes support an optional `setting_detail` key that narrows the focus to a specific sub-area within a location:

```yaml
- scene_number: 3.1
  setting: toy_store
  setting_detail: "The narrow aisles between towering shelves"
```

- `setting_detail` is appended after the base location text in the prompt as `Specific area: ...`.
- Works with or without a `setting` reference — can be used standalone for ad-hoc area descriptions.
- Keeps the base location data (name, atmosphere, mood_shift) intact while zooming in.
- Implemented in `build_scene_prompt()` in `prompt_builder.py`.

## AI Consult (YAML Audit)

The Consult tab provides an AI-powered audit of uploaded YAML story files using the generation model.

**Architecture:**
- `consult.py` — prompt construction for multi-pass analysis and fix generation
- `web.py` — `/api/consult` (streaming SSE), `/api/consult-apply` (fix generation), `/api/consult-save`
- UI: Consult tab between Story and Settings in wizard flow

**Multi-pass analysis:**

| Pass | Input | Focus |
|---|---|---|
| Characters | characters.yaml | Completeness, depth, distinctiveness, vibe/voice quality |
| Outline | story_outline.yaml | Events quality, pacing variety, emotional arcs, chapter flow |
| Locations | locations.yaml | Atmosphere quality, sensory detail, mood_shift usage |
| Cross-refs | All files | Character-scene alignment, continuity risks, timing |

- Each pass streams incrementally via SSE (`consult_chunk` events)
- Uses `num_ctx=16384` for analytical depth
- Temperature `0.4` for analysis, `0.3` for fix generation
- "Generate Fixed" buttons appear per file-specific pass after completion
- Corrected YAML shown in side-by-side diff view (original vs proposed)
- Proposed pane is editable before applying — user can review and modify
- Apply validates YAML before saving

**Live feedback during audit:**
- Each pass shows a live elapsed-time + token counter in the status badge ("analyzing… 12s · 45 tokens")
- On completion, stats bar shows: words generated, tokens, prompt tokens, tok/s, elapsed time
- Ollama's done-chunk metadata (`eval_count`, `eval_duration`, `prompt_eval_count`) captured for accurate stats
- Pass progress indicator in header status bar ("Pass 2/4 — analyzing outline…")
- All audit events (start, per-pass start/complete/error, finish) emitted to Logs tab via `state.emit("log")` and `addLogEntry()`

**Tab order (wizard flow):** Story → Consult → Settings → Logs → Memory → Output

## Regeneration Workflow

1. User clicks 🔄 Regen on a scene or chapter in the Output tab.
2. `POST /api/regenerate` starts a background thread.
3. For each scene: build prompt (with current memory/edits) → LLM call → postprocess → replace in file → log old text → re-summarize → merge extraction → save checkpoint.
4. SSE event `scene_regenerated` updates the UI live (replaces scene text, flashes green).
5. Old scene text is sent as a warn-level log entry visible in the Logs tab.
