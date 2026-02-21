# Architecture

## Package Structure

Novel Builder is organized as a Python package:

```
novel_builder/
├── __init__.py            # Package init, version
├── __main__.py            # Entry point (routes to CLI or web)
├── cli.py                 # Argparse CLI definition
├── config.py              # Configuration loading, YAML discovery
├── ollama_client.py       # Ollama API calls, retry logic, model routing
├── prompt_builder.py      # System/user prompt construction per scene
├── state.py               # Checkpoint read/write, resume logic
├── story_processor.py     # Main generation loop, orchestration
├── characters.py          # Character loading, filtering, evolution, catch phrases
├── locations.py           # Location loading and resolution
├── yaml_io.py             # YAML loading/saving utilities
├── postprocess.py         # Regex cleanup, anti-pattern removal
├── web.py                 # Flask web UI backend, SSE streaming
└── templates/
    └── index.html         # Single-page web frontend
```

The `novel-builder.py` script in the project root is a thin wrapper that calls the package.

## How Generation Works

```
story_processor.generate_story()
│
├── Load characters, locations, heritage from config
├── Load or initialize checkpoint
├── Build system prompt (consistent across all scenes)
│
└── For each chapter → for each scene:
    ├── Detect characters (explicit list or auto-detection from scene text)
    ├── Build scene prompt:
    │   ├── Character context (full bio or reminder, based on appearance history)
    │   ├── Location/setting details
    │   ├── Running story summary (AI-generated, token-efficient)
    │   ├── Story memory (extracted facts, minor characters, commitments)
    │   ├── Narrative hook (if scene maps to one)
    │   └── Pacing hint (if tagged)
    ├── Call generation model (with retry + backoff)
    ├── Post-process (anti-pattern check, header cleanup)
    ├── Write to output file (immediately, not buffered)
    ├── Call summary model (extract summary + story memory)
    ├── Update checkpoint (appearance history, story memory, progress)
    └── Save checkpoint to disk
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Scene-level context** | Only characters, settings, and memory relevant to the current scene go into the prompt. Keeps token usage low, output quality high. |
| **Tiered character bios** | Full bio on first appearance, slim reminder after. Prevents the model from re-establishing characters every scene. |
| **AI-generated summaries** | A fast model summarizes each scene into a token-efficient recap. Raw text is never carried forward. |
| **Story memory extraction** | After each scene, the summary model extracts new minor characters, world facts, and commitments for future scenes. |
| **Probability-gated catch phrases** | Prevents mechanical repetition. Each phrase gets a dice roll per scene. |
| **Checkpoint after every scene** | Maximum one scene of work lost on failure. |
| **Event callback system** | `story_processor` accepts an optional `event_callback` for real-time reporting. When `None` (CLI default), no behavioral change. When set (web UI), emits progress/log/scene events through SSE. |

## Web Architecture

```
Browser ─── SSE (text/event-stream) ──→ Flask (threaded)
   │                                        │
   ├── GET  /api/status     ←── snapshot ───┤
   ├── POST /api/start      ───→ spawn ─────┤──→ background thread
   ├── POST /api/stop       ───→ flag ──────┤       │
   ├── GET  /api/events     ←── stream ─────┤←── emit()
   ├── POST /api/upload     ───→ disk ──────┤
   ├── GET  /api/parse-yaml ←── parsed ─────┤
   └── GET  /api/download   ←── file ───────┤
```

- Generation runs in a daemon thread. Browser can close and reconnect.
- All state lives server-side in `GenerationState` (thread-safe, lock-protected).
- SSE subscribers get events via `queue.Queue` per client.
- 15-second heartbeats keep connections alive.

## Dependencies

| Package | Purpose |
|---|---|
| `pyyaml` | YAML parsing for all story data |
| `requests` | HTTP client for Ollama API |
| `flask` | Web UI backend |

All are lightweight. No build tools, no npm, no C extensions.

---

← [Back to README](../README.md)
