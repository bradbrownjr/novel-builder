# CLI Reference

## Usage

```
python -m novel_builder [OPTIONS]
```

Or via the wrapper script:

```
python novel-builder.py [OPTIONS]
```

## Generation Options

| Flag | Default | Description |
|---|---|---|
| `--host HOST` | `$OLLAMA_HOST` | Ollama host URL. If not set, prompts interactively. |
| `--model MODEL` | `gemma3:12b` | Model for scene generation. |
| `--summary-model MODEL` | `gemma3:4b` | Model for scene summarization. |
| `--outline FILE` | auto-discovered | Story outline YAML file. |
| `--characters FILE` | auto-discovered | Characters YAML file. |
| `--locations FILE` | auto-discovered | Locations/settings YAML file. |
| `--output FILE` | `full_story.md` | Output Markdown file. |
| `--resume` | — | Resume from last checkpoint without prompting. |
| `--restart` | — | Ignore checkpoint, start fresh. |
| `--quiet` | — | Suppress terminal output of generated scenes. |
| `--retries N` | `5` | Retry attempts on Ollama failure. |
| `--timeout SECS` | `900` | Ollama request timeout in seconds. |
| `--dry-run` | — | Parse YAML and show generation plan. No LLM calls. |
| `--chapter N` | — | Generate only chapter N. |
| `--scene N.M` | — | Generate only chapter N, scene M. |

## Web UI Options

| Flag | Default | Description |
|---|---|---|
| `--web` | — | Launch the web UI instead of CLI generation. |
| `--port PORT` | `8080` | Web UI server port. |

## Environment Variables

| Variable | Description |
|---|---|
| `OLLAMA_HOST` | Ollama server URL (e.g., `http://192.168.1.50:11434`). If not set, the CLI prompts interactively. You can enter a bare IP and it auto-formats to `http://<ip>:11434`. |

## Workflow

### Standard generation

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

Progress saves after every scene. If Ollama times out or you hit Ctrl+C:

```bash
# Resume from where you left off
python -m novel_builder --resume

# Or start fresh
python -m novel_builder --restart
```

### Validate YAML without generating

```bash
python -m novel_builder --dry-run
```

Parses all YAML, detects characters per scene, resolves setting references, and prints the full generation plan. No LLM calls are made.

### Generate a single scene

```bash
# Regenerate chapter 3, scene 2
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

Or a single combined file:

```
your-project/
├── story_data.yaml       # Everything in one file
├── full_story.md
└── checkpoint.yaml
```

---

← [Back to README](../README.md)
