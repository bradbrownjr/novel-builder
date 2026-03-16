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
- **Never** rewrite a file that involves 200+ line deletions without first listing every named feature, API route, and JS function present in that file and confirming each will be preserved. Consult the Feature Registry below.
- **Always** run `git diff --stat` and review line-deletion counts before committing. A single commit removing more than 200 lines from an existing file is a regression risk and requires a feature audit.

## Feature Registry

Compact checklist of all implemented user-facing features keyed to their implementation locations.
Before any large file rewrite, verify every row in the affected file column is preserved.

| Feature | Key file(s) | Key identifiers |
|---|---|---|
| Story generation (CLI + web) | story_processor.py, web.py | `generate_story()`, `process_scene()`, `/api/generate` |
| Checkpoint / resume | state.py, web.py | `save_checkpoint()`, `load_checkpoint()`, `/api/status` |
| Web UI (all tabs) | web.py, templates/index.html | `run_server()`, all `/api/*` routes |
| TTS Read Aloud | web.py, tts.py, templates/index.html | `/api/tts/*`, `parse_span_segments()`, `parseSpanSegments()`, `const tts`, `btn-tts-play`, `btn-tts-stop` |
| TTS Download MP3 with chapters | web.py, templates/index.html | `/api/tts/add-chapters`, `downloadAudiobook()` |
| AI Consult (YAML audit) | consult.py, web.py | `/api/consult`, `/api/consult-apply` |
| Scene / chapter regeneration | story_processor.py, web.py | `regenerate_scene()`, `/api/regenerate` |
| Story memory (facts, actions) | state.py, web.py | `story_memory`, `/api/memory` |
| Used imagery suppression | state.py, prompt_builder.py | `get_used_imagery()`, `story_memory.used_imagery` |
| Prompt presets | web.py, templates/index.html | `/api/style-presets`, `style_presets.yaml` |
| Ollama model pull | web.py, templates/index.html | `/api/ollama-pull` |
| Ollama model unload | web.py, templates/index.html | `/api/ollama-unload`, `ollamaUnloadModel()` |
| YAML validator | validator.py, web.py | `validate_all()`, `/api/validate` |
| Scene markers in output | story_processor.py, web.py | `<!-- scene:X.Y -->`, `/api/download` (strips markers) |
| Character appearance tracking | characters.py, state.py | `character_appearances`, tiered context logic |
| Explicit character exclusion | prompt_builder.py, characters.py | `auto_detect_characters()`, absent character naming in exclusion directive |
| Voice catalog & descriptions | voice_catalog.py, web.py, templates/index.html | `KOKORO_VOICES`, `enrich_voice_list()`, `/api/tts/voices` (enriched), `/api/voice-catalog` |
| Voice casting (AI) | consult.py, web.py, templates/index.html | `build_voice_casting_prompt()`, `/api/voice-cast`, `/api/voice-cast/result`, `startVoiceCast()`, `applyVoiceCast()` |
| Story Concept Builder | concept.py, web.py, templates/index.html | `build_concept_prompt()`, `/api/concept`, `/api/concept/result`, `/api/concept/save`, `startConcept()`, `saveConceptFile()` |
| Text analysis | web.py, templates/index.html | `_analyze_text()`, `/api/text-analysis`, `showTextAnalysis()`, `taShowTab()` |

## Project Conventions

- Code is organized as a Python package: `novel_builder/` with `novel-builder.py` as a thin wrapper.
- YAML is the only data format for story input/configuration.
- Supports both separate YAML files (characters.yaml, locations.yaml, story_outline.yaml) and a single combined `story_data.yaml`.
- Markdown is the output format.
- Ollama is the only supported LLM backend (for now).
- Minimal dependencies: `pyyaml`, `requests`, `flask`, `mutagen` (TTS chapter tagging), stdlib only.
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
├── ollama_client.py      # call_ollama(), call_ollama_with_retry(), call_summary_model(), unload_model(), _OllamaWatchdog, _wait_for_ollama()
├── prompt_builder.py     # build_system_prompt(), build_scene_prompt(), build_summary_prompt()
├── state.py              # load_checkpoint(), save_checkpoint(), should_resume(), should_compress(), compress_story_so_far(), get_used_imagery()
├── story_processor.py    # generate_story(), process_chapter(), process_scene(), regenerate_scene(), regenerate_chapter()
├── characters.py         # load_characters(), filter_for_scene(), auto_detect_characters(), get_evolution_context()
├── locations.py          # load_locations(), resolve_location()
├── yaml_io.py            # load_yaml(), save_yaml()
├── postprocess.py        # clean_scene_text(), apply_anti_patterns()
├── tts.py                # parse_span_segments(), _has_spoken_dialogue()
├── voice_catalog.py      # KOKORO_VOICES, enrich_voice_list(), get_voice_info(), get_catalog_summary()
├── web.py                # Flask web UI, TTS proxy, /api/memory (GET+POST), /api/regenerate, /api/download (marker-stripped), /api/ollama-pull (model download), /api/consult (AI audit), /api/voice-cast (voice casting), /api/concept (story concept builder)
├── concept.py            # Story Concept Builder: build_concept_prompt()
├── consult.py            # AI-powered YAML audit: multi-pass analysis prompts, fix generation, voice casting prompts
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
| **Full bio** | First appearance in story | Name, summary, role, personality, vibe, species, appearance, origin, voice, habit, status + merged heritage traits |
| **Reminder** | Subsequent appearances | Name, role, vibe, species, appearance, origin, voice, status + evolution notes |

- `vibe` is the persistent tonal anchor — always included.
- `voice` (speech patterns) is always included when present — shapes dialogue.
- `origin` (cultural/geographic background) is always included when present — shapes dialect, slang, and TTS voice casting.
- `personality` and `summary` are dropped after first appearance (now established in narrative).
- `status` (behavioral/situational info) is always included when present -- captures constraints like "inanimate unless alone with trusted human."
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

- Retry logic on Ollama timeout -- 5 retries with 5m/15m/30m/60m/60m backoff (Phase 1.1).
- Ollama watchdog liveness monitor -- `_OllamaWatchdog` polls `/api/ps` every 30s during generation to confirm the model is still loaded. Read timeout set to unlimited (`None`) so slow model loading and prompt evaluation never cause false timeouts. The watchdog only aborts after 3 consecutive checks find the model missing AND no tokens for 60s+. Retry backoff now polls `/api/tags` and resumes immediately when Ollama comes back online.
- Automatic model unloading between model switches -- `unload_model()` sends `keep_alive=0` to free memory before switching between generation and summary models. Only fires when the two models differ. Prevents RAM/VRAM pressure from having both models loaded simultaneously.
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
- Used Imagery tracking -- summary model extracts distinctive descriptive phrases; stored per-location and per-character in checkpoint; injected as suppression context to prevent repetitive descriptions across scenes.
- Sensory word frequency tracking -- after each scene, generated text is scanned for a curated watch list of ~90 sensory/atmospheric words (sound, sight, smell, touch, atmosphere categories). Counts accumulate in `checkpoint.yaml` under `word_frequency`. When a word hits 3+ uses, it appears in future scene prompts as a variety nudge (e.g. "groan (8x)"). Capped at 12 words per injection. Authors can view raw counts in checkpoint.yaml. \n- Consult Generate Fix errors and crossref fix support -- fixed fix generation errors, added crossref multi-file fix support, diff view, download, fix persistence across page refresh, and \"Generate All Fixes\" button.\n- Content policy -- anti-censorship directives in all prompts (consult analysis, fix generation, story generation).
- TTS Read Aloud and MP3 download restored -- lost in the fcafc95 UI rewrite, fully restored. Four API routes (/api/tts/health, /api/tts/voices, /api/tts/speak, /api/tts/segments), TTS config card in Setup tab, Read Aloud/Pause/Stop controls and Download MP3 button in Output tab, header status indicators.
- TTS Download MP3 with chapters -- MP3 audiobook download now embeds ID3v2 CHAP/CTOC chapter markers. Each `<!-- chapter:N -->` boundary in the output file maps to a chapter in the tagged MP3, with time offsets interpolated from byte offsets. Requires `mutagen>=1.47`. Route: `/api/tts/add-chapters` (multipart: mp3 file + chapters JSON). Falls back to untagged MP3 gracefully if tagging fails or only one chapter is present.
- Inline TTS voice tagging -- voice attribution now happens during scene generation, not as a post-processing pass. The generation model wraps spoken dialogue in `<span data-tts="CharacterName">` tags inline. Removed: heuristic attribution engine (`segment_text_for_tts`), model-based tagger (`tag_dialogue_with_model`, `tag_scene_text_with_spans`), tagging routes (`/api/tts/tag-story`, `/api/tts/tag-status`, `/api/tts/tag-stop`), tagging UI (buttons, header chip, config inputs). `tts.py` reduced from 847 lines to ~90 lines. `parse_span_segments()` parses inline spans for TTS playback. `prompt_builder.py` injects tagging instructions when `_tts_voice_map` is present in config.
- TTS voice name scoping -- the TTS tagging instruction block in the system prompt now lists only characters that have appeared in the story or are present in the current scene. Previously it listed ALL characters with `tts_voice` defined, which leaked future character names (e.g. Chrissy, Francine) into early scenes and caused the model to hallucinate their premature introduction.
- TTS duplication postprocessing -- `clean_scene_text()` in `postprocess.py` now detects and collapses duplicated dialogue where the model writes a quote both untagged and span-tagged (e.g. `"Hello!" <span data-tts="X">"Hello!"</span>` becomes just the tagged version).
- Voice catalog and descriptions -- `voice_catalog.py` provides metadata (description, accent, gender, tone, best-for) for 58 Kokoro TTS voices. `/api/tts/voices` now returns enriched voice data with descriptions. Voice selection dropdowns show descriptions alongside voice IDs.
- Voice casting (AI) -- new card in Consult tab. Uses the generation model to analyze character traits (vibe, voice, personality, origin, role) against the voice catalog and recommend TTS voices. Streams recommendations via SSE. "Apply Recommendations" parses the YAML output block and writes voice assignments to character inputs. Route: `/api/voice-cast` (streaming SSE), `/api/voice-cast/result` (snapshot), `/api/voice-catalog` (catalog JSON).
- Story Concept Builder -- Plan tab card that takes a free-form story idea and generates complete YAML files (outline, characters, locations) via the generation model. Streams output via SSE. Parsed output populates three editable YAML textareas. "Save to Plan" buttons write validated YAML to workspace files. Route: `/api/concept` (POST, streaming SSE), `/api/concept/result` (GET, snapshot), `/api/concept/save` (POST, validates + saves). Architecture mirrors voice cast pattern (_concept_state, _concept_lock, _concept_subs). Temperature 0.7 for creative output.
- Gender field + AI voice casting correction -- optional `gender` field in characters.yaml enables validation of voice assignments. `/api/voice-cast/correct` detects violations (invalid IDs, CJK voice conflicts, gender mismatches) and calls AI to correct them. Auto-audit rewrites YAML in-place with corrections; manual Apply button for user review. Narrator voice enforced to match POV character when first-person. Commit: b34cf92 (voice cast: full feature through gender + correction + narrator enforcement).
- TTS markdown header filtering -- `parse_span_segments()` in `tts.py` now skips markdown header lines (e.g., "# Chapter Title") when extracting narration segments. Regex `^\s*#+\s` identifies headers; `_filter_markdown_headers()` removes them. Fixes Read Aloud reading titles as part of first dialogue line. Commit: b34cf92.
- Chapter transition directive -- `build_scene_prompt()` in `prompt_builder.py` injects a CHAPTER TRANSITION directive for the first scene of each chapter (scene X.1), instructing the model to treat it as a fresh narrative beat without recapping the prior chapter. Fixes chapter content bleed (e.g. Ch1 morning routine repeated in Ch2).
- Scene continuation directive -- `build_scene_prompt()` injects a SCENE CONTINUATION directive for non-first scenes within a chapter, instructing the model to continue from where the prior scene ended without replaying events. Fixes intra-chapter scene repetition.
- Gender in character context -- `build_character_context()` in `characters.py` and `_build_character_block()` in `prompt_builder.py` now include the `gender` field in both first-appearance and reminder tiers. Fixes gender confusion where the LLM misidentifies character gender (e.g. male character called "daughter").
- String relationships handling -- `get_relevant_relationships()` in `characters.py` now handles string-format relationships (returns as `{"_general": value}`) instead of silently dropping them. `_build_character_block()` in `prompt_builder.py` renders `_general` key without a partner label. Fixes relationship data being lost when defined as a string instead of a dict.
- Location spatial accuracy directive -- `build_scene_prompt()` appends a directive after the Setting block instructing the model to use spatial details exactly as described, preventing invented access routes or layouts (e.g. "staircase behind the counter" when YAML says "behind the stockroom").
- TTS playback speed -- Full pipeline: UI speed dropdown (0.75x-1.25x) in Setup tab, `tts.speed` on JS object, speed passed in `fetchTTSAudio()` body, `/api/tts/speak` in `web.py` extracts `speed` and forwards to Speaches API `"speed"` parameter, speed saved/loaded in TTS config.
- MP3 title and chapter header speaking -- `downloadAudiobook()` in `index.html` now injects the story title as a spoken segment at the start of the audiobook, and each chapter title as a spoken segment before its first scene. Both use narrator voice.
- MP3 title/chapter pause -- title and chapter header segments in `downloadAudiobook()` now append ` . . .` to text so TTS generates a natural trailing pause before scene audio begins. Fixes abrupt transition from title speech to scene speech in downloaded audiobooks.
- TTS speed single application -- removed `audio.playbackRate` from `playAudioBlob()` in `index.html`. Speed is now applied server-side only (via `/api/tts/speak` speed parameter). Previously speed was applied twice (server + client), effectively squaring the speed factor.
- Explicit character exclusion -- `build_scene_prompt()` in `prompt_builder.py` now detects characters mentioned in scene events/notes who are NOT in the explicit character list, and names them in an exclusion directive ("must NOT appear on-stage, speak dialogue, or take any visible action"). Also excludes ALL characters who have appeared in the story so far but are not in the current scene's character list, preventing the model from pulling in known characters from the system prompt roster (e.g. Morty appearing in scenes where only Elias and Chrissy are listed, even when Morty isn't mentioned in events).
- TTS stutter preprocessing -- `_preprocess_tts_text()` in `web.py` converts stutter patterns (e.g. "H-hello", "S-stop") to phonetic forms ("heh hello", "suh stop") before sending text to the TTS engine. Only triggers when the letter and word share the same starting letter, avoiding false positives on normal hyphenated words. Same-letter repetition ("I-I") converts to ellipsis pause ("I... I"). Applied in `/api/tts/speak` route.
- Habit probability gating -- `should_include_habit()` in `characters.py` rolls ~33% odds per scene. Habit field no longer injected every prompt, reducing repetitive behavioral tics. Called from `_build_character_block()` in `prompt_builder.py`.
- Catchphrase streak prevention -- `should_include_catchphrase()` in `characters.py` now accepts `char_id` and `state`, enforcing a 2-scene cooldown via `catchphrase_last_scene` tracker. `record_catchphrase_used()` updates the tracker after inclusion. Prevents back-to-back catchphrase injection.
- Expanded word frequency watch list -- `_SENSORY_WATCH_WORDS` in `state.py` expanded with "action" (36 verbs: nodded, shrugged, sighed, etc.) and "dialogue" (21 verbs: murmured, whispered, stammered, etc.) categories. Total ~150+ tracked words.
- Story memory action suppression -- Actions in prompt injection changed from "Action taken:" to "Already narrated (do NOT re-narrate):" in `prompt_builder.py`, making the directive explicitly suppressive rather than informational.
- Word frequency windowed decay -- `update_word_frequency()` in `state.py` rewritten to use rolling `word_frequency_log` (15-scene window via `_WORD_FREQ_WINDOW`). Aggregate `word_frequency` rebuilt from window each update, so old usage naturally drops off. Prevents permanent word flagging.
- Text analysis -- `/api/text-analysis` in `web.py` analyzes `full_story.md` for most common words and phrases (bigrams/trigrams), filtered by comprehensive stop word list. UI modal in Output tab shows tabbed results (Words/Phrases) with counts, total/unique word stats.

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

## Tab Persistence Design

All data-heavy tabs refresh their content automatically so the UI stays current when the user backgrounds the browser or switches browser tabs.

**Design decision:** Use the `visibilitychange` browser event and the `switchTab()` function as the two refresh trigger points. No polling is needed -- a single fetch on return is sufficient.

| Trigger | Tabs refreshed |
|---|---|
| `visibilitychange` (page becomes visible) | Consult (if not running), Output, Memory |
| `switchTab(name)` | Consult (if not running), Output, Memory |

- Consult uses `restoreConsult()` to replay SSE-derived state from server cache.
- Output uses `refreshOutput()` to re-fetch the current Markdown from `/api/output`.
- Memory uses `refreshMemory()` to re-fetch checkpoint state.
- Logs tab is driven by the persistent SSE connection and does not need manual refresh.
- **Always** extend this pattern to new data-heavy tabs -- add the tab name to both `switchTab` and the `visibilitychange` handler.

## Mobile Header Layout

The header uses a two-row column layout so status chips do not compete for space with the logo and action buttons on small screens.

- **Row 1** (`.header-top`): logo + header action buttons (right-aligned, `justify-content: space-between`)
- **Row 2** (`.status-bar`): status indicator chips, full-width, wrapping
- The `header` element is `flex-direction: column` -- do not revert to a single-row flex.

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
- `generation_num_ctx` (default 8192) controls the context window for scene generation. Configurable in Setup tab. Reduce for faster CPU inference; increase for very long scene prompts or large character rosters.

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

## Prompt Presets

Named, reusable prompt configurations stored in `style_presets.yaml` in the workspace. Each preset carries four fields that together define the AI's writing behavior:

- **`author_instruction`** -- replaces the system prompt opening (model identity/role). Pre-populated with `DEFAULT_SYSTEM_OPENING` for new presets.
- **`style`** -- prose style directives appended to outline's `style_directives`. Deployed to `custom_style.txt`.
- **`scene_closing`** -- replaces "Write this scene now." at the end of each scene prompt. Pre-populated with `DEFAULT_SCENE_CLOSING` for new presets.
- **`extra_anti_patterns`** -- list of phrases appended to built-in anti-pattern suppression list.

**API:**
- `GET /api/style-presets` -- returns presets, active preset name, and built-in defaults
- `POST /api/style-presets` -- create/update a preset (fields: name, author_instruction, style, scene_closing, extra_anti_patterns, activate)
- `DELETE /api/style-presets/<name>` -- delete a preset
- `POST /api/style-presets/<name>/activate` -- deploy a preset
- `POST /api/style-presets/deactivate` -- clear active preset, revert to built-in defaults

**Deploy behavior:** Activating a preset writes `style` to `custom_style.txt` and `author_instruction`/`scene_closing`/`extra_anti_patterns` to `prompt_overrides.yaml`. Deactivating clears both files.

**Backward compat:** Old string-only preset values (pre-merge format) are auto-migrated to `{style: "..."}`.

**Generation pipeline:** `prompt_builder.py` reads overrides from `config["_prompt_overrides"]` (injected by `web.py` from `prompt_overrides.yaml`). `DEFAULT_SYSTEM_OPENING` and `DEFAULT_SCENE_CLOSING` are exported constants.

- UI: Prompt Presets card on Setup tab (merged Style Presets + Prompt Overrides)

## Regeneration Workflow

1. User clicks 🔄 Regen on a scene or chapter in the Output tab.
2. `POST /api/regenerate` starts a background thread.
3. For each scene: build prompt (with current memory/edits) → LLM call → postprocess → replace in file → log old text → re-summarize → merge extraction → save checkpoint.
4. SSE event `scene_regenerated` updates the UI live (replaces scene text, flashes green).
5. Old scene text is sent as a warn-level log entry visible in the Logs tab.
