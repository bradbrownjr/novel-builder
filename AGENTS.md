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
- **Never** use emoji in UI labels, status indicators, button text, log messages, or code comments. Keep text clean and professional.
- **Never** use em-dashes (--) in Python source code, comments, strings, or log messages. Use ` -- ` (space-hyphen-hyphen-space) instead. Em-dashes (U+2014) cause SyntaxErrors in some Python environments.
- **Never** include markdown formatting (`---`, scene headers, etc.) in generated scene text.
- **Always** preserve chapter headers before each chapter's first scene.
- **Never** censor, sanitize, or recommend removing story content based on moral judgments. This is a tool for adult authors writing fiction for adult readers. Dark themes, morally complex characters, erotic material, and violence are valid creative choices.

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
├── state.py              # load_checkpoint(), save_checkpoint(), should_resume(), should_compress(), compress_story_so_far(), get_used_imagery()
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

## Used Imagery Tracking

Prevents repetitive location/character descriptions across scenes by tracking distinctive descriptive phrases and suppressing their reuse.

**Extraction:** The summary model extracts `USED_IMAGERY` entries after each scene — vivid sensory details, specific metaphors, and recurring images (e.g., "dust motes danced in shafts of light", "weathered hands like old leather"). Each entry is prefixed with its subject (character name or "setting").

**Storage:** `checkpoint.yaml` → `story_memory.used_imagery` — list of dicts:
```yaml
- scene: "1.2"
  scope_type: setting      # setting | character | _global
  scope_id: toy_store      # location ID, character ID, or empty
  detail: "dust motes danced in shafts of light"
```

**Injection:** `build_scene_prompt()` retrieves imagery matching the current scene's `setting` and characters via `get_used_imagery()`, then appends a suppression block instructing the model to avoid those exact phrases and find fresh alternatives.

**Caps:**

| Scope | Max entries | Notes |
|---|---|---|
| Per location | 20 | Oldest evicted when exceeded |
| Per character | 10 | Oldest evicted when exceeded |
| Global (unkeyed) | 15 | Rolling window |
| Per prompt injection | 8 per category | Keeps token budget manageable |

**Editable:** Authors can view, add, edit, and delete used imagery entries in the Memory tab. Each entry shows its scope type, scope ID, phrase, and source scene.

## Resolved Issues

_(Track fixes here for reference.)_

- Retry logic on Ollama timeout — 5 retries with 3m/5m/15m/30m/60m backoff (Phase 1.1).
- Checkpoint/resume — generation can be paused and resumed from last completed scene (Phase 1.2).
- `story_so_far` rolling compression — every 5 scenes, the summary model compresses the accumulated text to stay within token budget (Phase 2.1).
- Story memory now extracts ACTIONS (who did what) alongside facts/commitments for continuity tracking.
- Story memory now extracts USED_IMAGERY (distinctive descriptive phrases) to prevent repetitive location/character descriptions.
- Recent memory items (actions, commitments, facts from last 5 scenes) are always injected into prompts regardless of keyword matching.
- Editable Memory tab — users can edit, add, and delete story memory items (facts, actions, commitments, characters, used imagery) and save back to checkpoint.
- Scene/chapter regeneration — users can regenerate individual scenes or entire chapters from the Output tab. Old text is logged before replacement.
- Scene markers (`<!-- scene:X.Y -->` / `<!-- /scene:X.Y -->`, `<!-- chapter:N -->`) embedded in .md output for regeneration targeting. Stripped from downloads.
- Character roster in system prompt scoped to appeared + current-scene characters only (prevents future character leakage).
- Summary model upgraded to `gemma3:4b` (from `gemma3:1b`) for better extraction quality.
- Extraction/summary prompt sharpened: focuses on plot-relevant facts, decisions, and commitments rather than trivial physical descriptions.
- Web UI model selectors with recommended models, RAM estimates, install status, and auto-pull from Ollama.
- AI Consult tab — multi-pass YAML audit with streaming analysis, per-file fix generation, and side-by-side diff review.
- Used Imagery tracking -- summary model extracts distinctive descriptive phrases; stored per-location and per-character in checkpoint; injected as suppression context to prevent repetitive descriptions across scenes.\n- Consult Generate Fix errors and crossref fix support -- fixed fix generation errors, added crossref multi-file fix support, diff view, download, fix persistence across page refresh, and \"Generate All Fixes\" button.\n- Content policy -- anti-censorship directives in all prompts (consult analysis, fix generation, story generation).

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
- `consult_num_ctx` (default 32768) controls the context window for AI Consult passes. Configurable in Settings tab. Increase if outline or cross-ref passes time out on large YAML files.

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
- `web.py` -- `/api/consult` (streaming SSE), `/api/consult-apply` (fix generation), `/api/consult-save`, `/api/consult-save-fix` (persist edits), `/api/consult-download-fix/<role>`, `/api/consult-original/<role>` (diff source)
- UI: Consult tab between Story and Settings in wizard flow

**Multi-pass analysis:**

| Pass | Input | Focus |
|---|---|---|
| Characters | characters.yaml | Completeness, depth, distinctiveness, vibe/voice quality |
| Outline | story_outline.yaml | Events quality, pacing variety, emotional arcs, chapter flow |
| Locations | locations.yaml | Atmosphere quality, sensory detail, mood_shift usage |
| Cross-refs | All files | Character-scene alignment, continuity risks, timing |

- Each pass streams incrementally via SSE (`consult_chunk` events)
- Uses configurable `consult_num_ctx` (default 32768) for analytical depth
- Temperature `0.4` for analysis, `0.3` for fix generation
- "Generate Fixed" buttons appear for ALL passes including Cross-References after completion
- Cross-ref fix uses multi-file output with `--- FILE: filename.yaml ---` markers
- "Generate All Fixes" button triggers fix generation for all completed passes at once
- Fix generation runs in a background thread on the server (sequential, one role at a time)
- Fix generation persists across browser refreshes and device switches
- Fix progress tracked via polling `/api/consult-results` (1.5s interval)
- Model indicator shows active fix generation in the header status bar
- Log entries emitted for fix start, completion, and errors
- Fix statuses: `queued` | `generating` | `done` | `error`
- `POST /api/consult-apply` accepts `{"roles": [...]}` for batch fix generation
- Corrected YAML shown in side-by-side diff view (original vs proposed) via "Show Diff" toggle
- Proposed pane is editable before applying -- user can review and modify
- Fix content is persisted in `consult_cache.json` and survives page refresh
- Stale `generating`/`queued` fix statuses from crashes are reset to `error` on server restart
- "Download Fix" button lets user save proposed YAML locally as backup
- Apply validates YAML before saving

**Content policy:**
- All analysis and fix prompts include explicit anti-censorship directives
- Consult will never recommend removing content for being dark, sexual, or violent
- Generation system prompt instructs the model to write authentically without content filtering
- The tool treats adult themes, morally complex characters, and mature content as valid creative choices

**Persistence & retry:**
- Consult results are persisted to `consult_cache.json` in the workspace directory after each pass completes or errors.
- Results survive server restarts and are restored automatically on startup.
- Failed passes show a "Retry" button to re-run only that pass without losing completed results.
- A "Retry Failed" button in the header retries all error'd passes at once.
- `POST /api/consult` accepts optional `{"passes": ["outline", "crossref"]}` body to retry specific passes.
- `POST /api/consult-clear` clears both in-memory state and the cache file.

**Live feedback during audit:**
- Each pass shows a live elapsed-time + token counter in the status badge ("analyzing… 12s · 45 tokens")
- On completion, stats bar shows: words generated, tokens, prompt tokens, tok/s, elapsed time
- Ollama's done-chunk metadata (`eval_count`, `eval_duration`, `prompt_eval_count`) captured for accurate stats
- Pass progress indicator in header status bar ("Pass 2/4 — analyzing outline…")
- All audit events (start, per-pass start/complete/error, finish) emitted to Logs tab via `state.emit("log")` and `addLogEntry()`

**Tab order (wizard flow):** Setup → Plan → Consult → Logs → Memory → Output

## Regeneration Workflow

1. User clicks 🔄 Regen on a scene or chapter in the Output tab.
2. `POST /api/regenerate` starts a background thread.
3. For each scene: build prompt (with current memory/edits) → LLM call → postprocess → replace in file → log old text → re-summarize → merge extraction → save checkpoint.
4. SSE event `scene_regenerated` updates the UI live (replaces scene text, flashes green).
5. Old scene text is sent as a warn-level log entry visible in the Logs tab.
