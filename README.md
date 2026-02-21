# Novel Builder

A Python CLI tool that uses local LLMs (via [Ollama](https://ollama.com)) to generate long-form fiction — chapter by chapter, scene by scene — without overwhelming the model's context window.

You feed it a story outline, character descriptions, and location details in YAML. It writes a full narrative, one scene at a time, passing only the relevant context to each generation call. The result is a Markdown file that reads like a novel, not a summarized outline.

## Features

- **Scene-by-scene generation** — Each scene gets only the characters, setting, and recent context it needs. No bloated prompts.
- **AI-powered continuity** — After each scene, a fast summarization pass creates a token-efficient recap that feeds into the next scene's prompt.
- **Smart character context** — Full bios on first appearance, slim reminders after that. Characters evolve via `evolution` notes.
- **Heritage system** — Define shared traits for species, professions, factions, or social classes. Characters inherit and can override.
- **Story memory** — Automatically tracks minor characters, world facts, and commitments the AI establishes, so they're remembered across scenes.
- **Catch phrase control** — Probability-gated injection prevents overuse. Phrases appear naturally, not mechanically.
- **Checkpoint & resume** — Progress saves after every scene. Timeouts or crashes lose at most one scene of work.
- **Retry with backoff** — Ollama API failures retry automatically (configurable attempts and timeout).
- **Anti-pattern suppression** — Configurable list of AI clichés to block in both prompts and post-processing.
- **Flexible YAML input** — Separate files or a single combined file. Your choice.
- **Dry run mode** — Validate your YAML and see the generation plan without calling the LLM.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally or on a network host
- A model pulled in Ollama (e.g., `ollama pull gemma3:12b`)

## Installation

### Debian / Ubuntu

```bash
# Install Python and venv (if not already present)
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

# Clone the repo
git clone https://github.com/bradbrownjr/novel-builder.git
cd novel-builder

# Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Other Linux / macOS

```bash
git clone https://github.com/bradbrownjr/novel-builder.git
cd novel-builder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dependencies are minimal: `pyyaml`, `requests`, and `flask`.

### Install Ollama

If Ollama isn't installed on the generation host yet:

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Pull models
ollama pull gemma3:12b     # Generation model
ollama pull gemma3:1b      # Summary model (fast, lightweight)

# Verify it's running
curl http://localhost:11434/api/tags
```

If Ollama runs on a different machine on your LAN, just point Novel Builder at it with `--host http://<ip>:11434` or set `OLLAMA_HOST`.

## Quick Start

### 1. Set up Ollama

Make sure Ollama is running and a model is available:

```bash
# On the machine running Ollama:
ollama pull gemma3:12b     # Generation model
ollama pull gemma3:1b      # Summary model (fast, lightweight)
```

### 2. Create your story files

At minimum, you need a story outline with chapters and scenes. Create `story_outline.yaml`:

```yaml
story_title: "My Story"

overall_arc:
  tone: "Suspenseful and atmospheric"
  pov: "First person"
  theme: "Trust and betrayal"

chapters:
  - chapter_number: 1
    title: "The Beginning"
    summary: "Our protagonist arrives in town."
    scenes:
      - scene_number: 1.1
        setting: "A rain-soaked bus station at dusk."
        events: "The protagonist steps off the bus with one suitcase and no plan."
        notes: "Establish mood and isolation. Sensory details."
```

Create `characters.yaml`:

```yaml
characters:
  protagonist:
    Name: Jordan Blake
    summary: "Recently laid off, recently divorced, recently out of excuses."
    role: "Protagonist"
    vibe: "Someone pretending to have a plan while clearly improvising."
    personality: [wry, guarded, observant]
    catchphrase: "That tracks."
```

See [YAML_SCHEMA.md](YAML_SCHEMA.md) for the full schema reference and all available fields.

### 3. Run it

```bash
# Set the Ollama host (or pass --host)
export OLLAMA_HOST=http://localhost:11434

# Generate the story
python -m novel_builder --outline story_outline.yaml --characters characters.yaml

# Or if using the wrapper script:
python novel-builder.py --outline story_outline.yaml --characters characters.yaml
```

The tool writes each scene to `full_story.md` as it generates and prints progress to the terminal.

## Web UI

Novel Builder includes a browser-based interface for managing stories remotely — useful for headless servers or when you want to monitor generation from a phone or tablet.

```bash
source .venv/bin/activate
python -m novel_builder --web
```

This launches a Flask server on `http://0.0.0.0:8080`. Open it from any device on your LAN.

**Features:**

- Upload, drag-drop, paste, or type YAML files and custom style prompts
- Configure Ollama host, models, retries, and timeout from the browser
- Start/stop generation with real-time progress (SSE streaming)
- Live output viewer — scenes appear as they're written
- Ollama connection indicator with model status (generating / summarizing / idle)
- Parsed YAML preview — see loaded characters, chapters, scenes, locations before generating
- Download the output `.md` or export any YAML file
- "New Story" button clears the workspace for a fresh start
- Dark mode default with light toggle
- Survives browser close — generation runs server-side, reconnect to see current state

```bash
# Custom port:
python -m novel_builder --web --port 9090

# Behind a reverse proxy (Caddy, nginx, etc.):
# Just proxy to http://localhost:8080 — SSE works over HTTP/1.1 and HTTP/2
```

## Usage

```
python -m novel_builder [OPTIONS]

Options:
  --host HOST              Ollama host URL (default: $OLLAMA_HOST or prompted)
  --model MODEL            Generation model (default: gemma3:12b)
  --summary-model MODEL    Summarization model (default: gemma3:1b)
  --outline FILE           Story outline YAML (default: story_outline.yaml)
  --characters FILE        Character YAML (default: characters.yaml)
  --locations FILE         Locations/settings YAML (default: auto-discovered)
  --output FILE            Output Markdown file (default: full_story.md)
  --resume                 Resume from checkpoint without prompting
  --restart                Ignore checkpoint, start fresh
  --quiet                  Suppress terminal output of generated scenes
  --retries N              Ollama retry attempts on failure (default: 3)
  --timeout SECS           Ollama request timeout in seconds (default: 900)
  --dry-run                Parse YAML and show the generation plan, don't generate
  --chapter N              Generate only chapter N
  --scene N.M              Generate only chapter N, scene M
  --web                    Launch the web UI instead of CLI generation
  --port PORT              Web UI port (default: 8080)
```

### Environment Variables

| Variable | Description |
|---|---|
| `OLLAMA_HOST` | Ollama server URL (e.g., `http://192.168.1.50:11434`). If not set, the tool prompts for it. |

## Workflow

### Typical run

```bash
python -m novel_builder
```

1. Loads YAML files (outline, characters, settings)
2. For each chapter → for each scene:
   - Detects which characters are present (auto + explicit)
   - Builds a context-aware prompt (character bios, setting, recent summary)
   - Sends to Ollama for generation
   - Writes the scene to file and terminal
   - Summarizes the scene (fast model) for continuity
   - Saves checkpoint
3. On completion: prints total word count and elapsed time

### Resume after interruption

If Ollama times out or you hit Ctrl+C, progress is saved automatically:

```bash
# Resume from where you left off:
python -m novel_builder --resume

# Or start fresh:
python -m novel_builder --restart
```

### Validate your YAML without generating

```bash
python -m novel_builder --dry-run
```

This parses all YAML, detects characters per scene, resolves setting references, and prints the full generation plan. No LLM calls are made.

### Generate a single scene

```bash
# Regenerate just chapter 3, scene 2:
python -m novel_builder --scene 3.2
```

## File Structure

```
your-project/
├── story_outline.yaml    # Story metadata, chapters, scenes
├── characters.yaml       # Character definitions
├── locations.yaml        # Reusable settings/locations (optional)
├── full_story.md         # Generated output (created by tool)
└── checkpoint.yaml       # Progress state (created by tool)
```

Or use a single combined file:

```
your-project/
├── story_data.yaml       # Everything in one file
├── full_story.md
└── checkpoint.yaml
```

## YAML Schema

See [YAML_SCHEMA.md](YAML_SCHEMA.md) for the complete field reference, including:

- **Story Outline** — chapters, scenes, narrative hooks, anti-patterns, pacing hints
- **Characters** — bios, personality, vibe, voice, catch phrases, secrets, relationships, evolution
- **Settings** — locations with atmosphere, sub-areas, and mood shifts
- **Checkpoint** — auto-generated progress tracking (do not edit manually)

### Minimal viable story

The absolute minimum to generate output:

```yaml
# story_outline.yaml
story_title: "Untitled"
chapters:
  - chapter_number: 1
    title: "Chapter One"
    summary: "Something happens."
    scenes:
      - scene_number: 1.1
        setting: "A room."
        events: "A person enters the room and finds something unexpected."
```

```yaml
# characters.yaml
characters:
  protagonist:
    Name: The Protagonist
    vibe: "Curious and slightly anxious."
```

Everything else — style directives, anti-patterns, narrative hooks, voice descriptions, evolution notes, location files — is optional and additive.

## Tips for Best Results

1. **Invest in `vibe`.** This single field has the highest impact on output quality. It shapes *how the character feels to the reader* — more valuable than listing facts.

2. **Use `voice` for dialogue.** If dialogue feels generic, add a `voice` field: "Short fragments, avoids direct answers, speaks in metaphors."

3. **Write `notes` for the AI.** Scene notes are your direct channel. "Make this tense" or "Let the silence carry this scene" both work.

4. **Start small, add detail.** Write a bare outline first, generate, then add `personality`, `voice`, `evolution`, and `pacing` where the output needs sharpening.

5. **Use the dry run.** Before a long generation run, `--dry-run` catches YAML errors and shows you exactly what each scene will include.

6. **Tag `pacing` on pivotal scenes.** The AI defaults to mid-pace. Tagging `action` or `slow-burn` changes output noticeably.

7. **Don't fight the length.** Scenes take the space they need. A dialogue-heavy scene will be shorter than a world-building opener. That's correct.

## Architecture

Novel Builder is organized as a Python package:

```
novel_builder/
├── __init__.py            # Package init
├── __main__.py            # Entry point
├── cli.py                 # CLI argument parsing
├── config.py              # Configuration, YAML discovery
├── ollama_client.py       # Ollama API, retry logic
├── prompt_builder.py      # Prompt construction per scene
├── state.py               # Checkpoint read/write
├── story_processor.py     # Main generation loop
├── characters.py          # Character loading, filtering, evolution
├── locations.py           # Location loading, resolution
├── yaml_io.py             # YAML utilities
├── postprocess.py         # Regex cleanup
├── web.py                 # Flask web UI backend + SSE
└── templates/
    └── index.html         # Single-page web frontend
```

The `novel-builder.py` script in the project root is a thin wrapper that calls the package.

## License

_TBD_
