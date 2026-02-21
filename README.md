# Novel Builder

Generate long-form fiction using local LLMs — chapter by chapter, scene by scene — without overwhelming the model's context window.

You define your story in YAML: an outline with chapters and scenes, character bios, locations, style directives. Novel Builder feeds the AI only what's relevant to each scene — the right characters, the right setting, a summary of what came before — and writes a flowing Markdown narrative that reads like a novel, not a summarized outline.

Run it from the **command line** or through a **browser-based web UI** that streams progress in real time.

## Why This Exists

LLMs lose coherence over long outputs. They forget characters, repeat themselves, and flatten tone. Novel Builder solves this by breaking the story into scenes and carefully managing what goes into each prompt — so the model stays focused and the narrative stays consistent across tens of thousands of words.

## What It Does

- **Scene-by-scene generation** with only relevant context per prompt
- **AI-powered continuity** — each scene is summarized for the next, not the raw text
- **Smart character handling** — full bios on first appearance, slim reminders after; evolution notes, heritage traits, probability-gated catch phrases
- **Story memory** — auto-tracks minor characters, world facts, and commitments across scenes
- **Checkpoint & resume** — saves after every scene; crashes lose at most one scene
- **Anti-pattern suppression** — blocks AI clichés you define in YAML
- **Web UI** — upload files, configure models, watch scenes generate live from any device
- **CLI** — scriptable, with dry-run, selective generation, and interactive host prompt

## Quick Start

```bash
git clone https://github.com/bradbrownjr/novel-builder.git
cd novel-builder
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# CLI
python -m novel_builder

# Web UI
python -m novel_builder --web
```

> Need more detail? → [Quick Start Guide](docs/quick-start.md)

## Documentation

| Guide | What's in it |
|---|---|
| [Installation](docs/installation.md) | Debian/Ubuntu setup, other Linux, Ollama install, systemd service |
| [Quick Start](docs/quick-start.md) | Minimal YAML examples, first generation run |
| [Web UI](docs/web-ui.md) | Browser interface — tabs, status bar, file management, reverse proxy |
| [CLI Reference](docs/cli-reference.md) | All flags, environment variables, workflow (resume, dry-run, single scene) |
| [YAML Schema](docs/yaml-schema.md) | Complete field reference — outline, characters, heritage, locations, checkpoint |
| [Tips](docs/tips.md) | Practical advice for better output quality |
| [Architecture](docs/architecture.md) | Module structure, generation flow, design decisions |
| [Design Plan](DESIGN_PLAN.md) | Roadmap, phased implementation, resolved decisions |

## License

_TBD_
