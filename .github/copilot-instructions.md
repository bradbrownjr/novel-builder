# Agent Guide for Novel Builder

## Product Purpose

Novel Builder is a **Python CLI tool** for **authors and storytellers** who want to use local LLMs (via Ollama) to generate **long-form fiction** — chapter by chapter, scene by scene — without overwhelming the model's context window. It feeds the AI only the information relevant to each scene (active characters, setting, recent context) to produce high-quality, flowing narrative that reads like a real novel, not a summarized outline.

## User Experience Requirements

- Authors define their story via structured YAML files (outline, characters, scenes/locations).
- The tool processes the story sequentially, writing each scene with appropriate context.
- Output is written to both file and terminal (configurable via CLI flags).
- Generation can be **paused and resumed** at any point — the tool tracks progress via checkpoint state.
- If Ollama times out or errors, the tool retries automatically and can resume from the last completed scene.
- The final output is a clean Markdown file suitable for further editing or export.
- Authors can customize style, tone, and generation parameters without modifying code.

## Technical Stack

- **Language:** Python 3.10+
- **LLM Backend:** Ollama REST API (`/api/generate`)
- **Data Format:** YAML for all configuration and story data
- **Output Format:** Markdown (`.md`)
- **CLI Framework:** `argparse` (stdlib)
- **HTTP Client:** `requests`
- **Dependencies:** `pyyaml`, `requests` (kept minimal by design)

## Engineering Principles

- **DRY:** Centralize prompt construction, YAML I/O, and Ollama interaction in reusable functions/classes.
- **SOLID:** Separate concerns — file I/O, prompt engineering, API communication, state management, and CLI live in distinct modules within the `novel_builder/` package.
- **KISS:** Favor straightforward, readable Python. Avoid unnecessary abstractions. Each module should have a clear, single responsibility.
- **Extensibility:** Design data structures and prompt templates so new features (e.g., new YAML fields, new generation modes) can be added without rewriting existing logic.
- **Graceful Degradation:** The tool should never crash silently. All errors must be reported clearly. Network failures trigger retries, not exits.

## Root-Cause Policy

- Never patch symptoms when resolving issues.
- Always research and identify the root cause before implementing a fix.
- Resolve root causes thoroughly, even when the correct fix is invasive.
- Maintain a strong foundation-first mindset for long-term maintainability.
- When AI output quality degrades, investigate prompt design and context management — not just post-processing hacks.

## Planning and Collaboration Rules

- Treat every user question as requiring a direct answer. Do not treat questions as rhetorical.
- Answer user questions before making code changes.
- Before implementing a feature or large change, present a clear plan of action.
- Before implementing a feature or large change, present open questions, risks, and tradeoffs.
- For large changes, get alignment on the plan before implementation.

## User Always/Never Memory Protocol

- If the user says to "always" or "never" do something, treat it as an instruction to update `AGENTS.md` with that directive.
- `AGENTS.md` is the persistent memory for this project.
- If an instruction is not in `AGENTS.md`, assume it may be forgotten in future sessions.
- When adding a rule, capture it as a clear, testable directive.

## Prompt Engineering Guidelines

- **Context Budget:** Every token in the prompt costs quality. Only include information the AI needs for the current scene.
- **Character Info:** Send only characters present in the scene. First appearance gets the full bio (summary, role, personality, vibe, habit) plus merged heritage traits. Subsequent appearances get only name, role, vibe, and accumulated evolution notes. The `vibe` field is the persistent tonal anchor. `voice` (speech patterns) is always included when present. `secret` is only included when scene notes reference tension or subtext. `relationships` are included when both characters are present in the scene.
- **Heritage:** Group identity traits (species, profession, faction) defined in `heritage:` and referenced by character. Merged into character context on first appearance; dropped after. Character-level fields always override heritage fields.
- **Story Memory:** After each scene, the summary model extracts persistent details (new minor characters, world facts, commitments). Stored in `checkpoint.yaml` under `story_memory`. The prompt builder includes relevant entries when a scene references those characters/locations.
- **Scene Continuity:** After generating a scene, use the AI to produce a brief, token-efficient summary of that scene. Feed that summary (not the raw text) into the next scene's context window.
- **Catch Phrases:** Catch phrases default to `occasional` frequency. The prompt builder rolls a probability check per scene and only includes the catch phrase when it hits. Support both simple string format (`catchphrase: "That figures."`) and list format with per-phrase frequency.
- **Scene Length:** Do not impose word count targets. Let the AI take the space it needs for effective storytelling.
- **Pacing Hints:** Scenes can be tagged with `pacing: slow-burn | action | dialogue-heavy | introspective`. Include the hint in the prompt when present.
- **World Context:** The `world` field from the outline is global context (era, tech level, genre rules) included in every system prompt.
- **Anti-Pattern Suppression:** Maintain a configurable list of overused AI phrases and patterns to suppress via system prompt instructions.
- **Style Directives:** Style instructions belong in the YAML outline, not hardcoded. They should be composable (base style + per-chapter overrides).

## Module Structure

The codebase is organized as a Python package. See `AGENTS.md` for the full module tree with function listings.

```
novel_builder/
├── __init__.py           # Package init, version
├── __main__.py           # Entry point: `python -m novel_builder`
├── cli.py                # Argparse CLI definition
├── config.py             # Configuration loading, defaults, YAML discovery
├── ollama_client.py      # Ollama API calls, retry logic, model routing
├── prompt_builder.py     # System/user prompt construction per scene
├── state.py              # Checkpoint read/write, resume logic
├── story_processor.py    # Main generation loop, orchestration
├── characters.py         # Character loading, filtering, evolution, catch phrases
├── locations.py          # Location loading and resolution
├── yaml_io.py            # YAML loading/saving utilities
└── postprocess.py        # Regex cleanup, anti-pattern removal
```

## YAML Data Architecture

All story data lives in YAML files. The canonical structure:

- **`story_outline.yaml`** — Story metadata, overall arc, style directives, narrative hooks, anti-patterns, and chapter/scene definitions.
- **`characters.yaml`** — Character bios (Name, summary, role, catchphrase, personality, vibe, voice, habit, secret, relationships, evolution notes). Heritage references.
- **`heritage.yaml`** (optional) — Shared group traits (species, profession, faction) referenced by characters. Can also live in `characters.yaml` or combined file under `heritage:` key.
- **`locations.yaml`** or **`settings.yaml`** (optional) — Reusable scene/location descriptions that can be referenced by ID from the outline. Both `setting:` and `locations:` are recognized as top-level keys.
- **`checkpoint.yaml`** (auto-generated) — Tracks generation progress: last completed chapter/scene, running summary, character appearance history, and state needed to resume.

If combining files makes more sense for a given story, a single `story_data.yaml` with clearly separated top-level keys is acceptable.

**`narrative_hooks`** are story-level plot beats (e.g., "The First Contact", "The Arrival") that aren't tied to a specific chapter. The prompt builder includes the relevant hook when a scene maps to it, rather than injecting all hooks into every prompt.

## State Management and Resilience

- **Checkpointing:** After each scene is written, save progress to `checkpoint.yaml` including: last completed chapter/scene numbers, the running story summary, character appearance history, story memory (extracted details), and any accumulated character evolution notes.
- **Resume:** On startup, detect existing checkpoint and offer to resume from where generation left off.
- **Retry:** Ollama API calls must have configurable retry logic (default: 3 attempts with exponential backoff). Timeouts should be generous (default: 900s) but configurable.

## Output and Logging

- **File Output:** Story content writes to the Markdown output file after each scene (append mode). Never buffer entire chapters in memory before writing.
- **Terminal Output:** By default, print generated scenes to the terminal. Controllable via `--quiet` flag.
- **Progress:** Print clear progress indicators: chapter X/Y, scene X/Y, character detection results, retry attempts.

## Implementation Expectations

- Preserve architectural consistency as features are added.
- Keep prompt construction logic explicit, readable, and testable.
- Ensure story flow and context passing remain accurate and traceable.
- Prefer cohesive refactors over layered quick fixes.
- Update this document and `AGENTS.md` when behavior, architecture, or workflows change.

## Definition of Done

- The change solves the validated root cause.
- The implementation aligns with DRY, SOLID, and KISS principles.
- User-facing CLI behavior is clear and documented in `--help` output.
- Story output quality is not degraded by the change.
- Error handling covers failure modes gracefully.
- Related documentation (`AGENTS.md`, this file, `DESIGN_PLAN.md`) is updated.
