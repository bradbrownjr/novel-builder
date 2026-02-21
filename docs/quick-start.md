# Quick Start

Get a story generating in under 5 minutes.

## 1. Install

```bash
git clone https://github.com/bradbrownjr/novel-builder.git
cd novel-builder
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

> Full install guide: [docs/installation.md](installation.md)

## 2. Pull models

On the machine running Ollama:

```bash
ollama pull gemma3:12b     # Generation
ollama pull gemma3:1b      # Summarization
```

## 3. Create your story files

**story_outline.yaml**

```yaml
story_title: "My Story"

world: "Contemporary small-town USA. Smartphones exist but everyone knows everyone."

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

**characters.yaml**

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

That's it. Everything else — locations, heritage, anti-patterns, voice, evolution — is optional. Add it when you need it.

> Full YAML reference: [docs/yaml-schema.md](yaml-schema.md)

## 4. Run it

### Option A: Command line

```bash
export OLLAMA_HOST=http://localhost:11434
python -m novel_builder
```

It will auto-discover your YAML files, generate scene by scene, and write output to `full_story.md`.

### Option B: Web UI

```bash
python -m novel_builder --web
```

Open `http://localhost:8080` in your browser. Upload your YAML files, set the Ollama host in the config panel, and click **Start Generation**.

> Full web UI guide: [docs/web-ui.md](web-ui.md) · CLI reference: [docs/cli-reference.md](cli-reference.md)

## Minimal viable story

The absolute minimum to generate output — two files, ~10 lines total:

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

## What happens next

1. The tool loads your YAML files
2. For each scene, it builds a focused prompt with only the relevant characters, setting, and recent context
3. Sends it to Ollama for generation
4. Writes the scene to `full_story.md` immediately
5. Summarizes the scene (fast model) for continuity into the next
6. Saves a checkpoint — if anything breaks, you resume from the last completed scene

---

← [Back to README](../README.md)
