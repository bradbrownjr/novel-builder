# Web UI

Novel Builder includes a browser-based interface for managing stories remotely — useful for headless servers, or when you want to monitor generation from a phone, tablet, or another machine on your network.

## Launching

```bash
source .venv/bin/activate
python -m novel_builder --web
```

Opens on `http://0.0.0.0:8080`. Accessible from any device on your LAN.

```bash
# Custom port
python -m novel_builder --web --port 9090
```

## Tabs

The interface is organized as a wizard-style flow: **Setup → Plan → Consult → Logs → Memory → Output**

### Setup Tab

| Feature | Details |
|---|---|
| **Ollama Host** | Enter the IP/URL of your Ollama server (e.g., `http://192.168.1.x:11434`). Saved to `workspace/web_config.json` — you set it once and it persists across restarts. |
| **Model selection** | Choose your generation and summary models from a dropdown of recommended options (with RAM estimates), or type any model name. If a model isn't installed, a Pull button fetches it from Ollama. |
| **Retries & timeout** | Configure retry attempts and timeout per request. |
| **File upload** | Upload, drag-drop, paste, or type YAML files for outline, characters, locations, and custom style prompt. Each file shows status, size, and timestamp. |
| **Edit / Export / Delete** | Edit any file in-browser, export it as a download, or remove it. |
| **Prompt Presets** | Create and activate named prompt configurations (author instruction, style, scene closing, extra anti-patterns). Activating a preset writes `custom_style.txt` and `prompt_overrides.yaml` in the workspace. |
| **New Story** | Clears all uploaded files, output, and checkpoint (with confirmation). Does not touch config. |

### Plan Tab

- **Parsed data preview** — After uploading YAML, see a summary of everything loaded: story title, chapter/scene tree, character names with trait icons, locations, heritage groups.
- **Generation plan** — Full scene-by-scene breakdown of what will be generated: characters detected per scene, setting resolved, hooks matched.
- Confirms everything parsed and resolved correctly before you start generating.
- Shows any validation warnings without blocking generation.

### Consult Tab

AI-powered audit of your YAML story files using the generation model.

- **Multi-pass analysis** — Separate passes for Characters, Outline, Locations, and Cross-references. Each streams incrementally.
- **Generate Fix** — For any completed pass, generate a corrected YAML file. A side-by-side diff lets you review and edit before applying.
- **Generate All Fixes** — Trigger fix generation for all completed passes at once.
- **Retry** — Re-run a failed pass without losing completed results.
- Results persist in `workspace/consult_cache.json` and survive page refresh and server restarts.

### Logs Tab

- Timestamped log feed of every generation event — chapter/scene progress, character detection, retry attempts, errors, warnings.
- Persists server-side, so reconnecting shows the full history.

### Memory Tab

- View and edit all story memory extracted from generated scenes: facts, actions, commitments, minor characters, and used imagery.
- Add, edit, or delete any entry — changes are saved back to `checkpoint.yaml`.
- Used imagery entries show scope type, scope ID, phrase, and source scene.

### Output Tab

- **Live viewer** — Scenes appear in real time as they are generated, with auto-scroll. Each scene block has a **Regen** button to regenerate that scene individually, or regenerate the entire chapter.
- **Read Aloud** — TTS playback of the story using Kokoro voices, with play/pause/stop controls. Requires a running Kokoro TTS server.
- **Download MP3** — Export the story as a voiced MP3 audiobook with embedded chapter markers.
- **Refresh** — Pull the full output from disk at any time.
- **Download** — Grab a clean `.md` file (scene markers stripped) directly from the browser.

## Status Bar

| Indicator | What it shows |
|---|---|
| **Generation status** | Idle / Running (animated) / Completed / Paused / Error |
| **Ollama connection** | Live health check — connected model count or error. Pings every 30s, re-checks on host change. |
| **Model activity** | Which model is currently active: generation model, summary model, or idle. |
| **Progress** | Percentage and scene count (e.g., "42% — Scene 5/12"). |

## Resilience

- **Reconnect-safe** — Generation runs in a server-side background thread. Close your browser, switch devices, lose wifi — reconnect and the page restores full state from the server.
- **Stop button** — Graceful stop that finishes the current scene, saves checkpoint, and allows resume.
- **SSE streaming** — Real-time updates via Server-Sent Events with auto-reconnect. No WebSocket dependency. Works over HTTP/1.1 and HTTP/2.

## Reverse Proxy

SSE works without special configuration on most proxies.

**Caddy:**

```
novelbuilder.example.com {
    reverse_proxy localhost:8080
}
```

**nginx** — if you see buffering or delayed events, add:

```nginx
location / {
    proxy_pass http://localhost:8080;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
}
```

## File Storage

Uploaded files and output live in the `workspace/` directory next to the project root. This directory is created automatically and is gitignored.

```
workspace/
├── story_outline.yaml      # Uploaded outline
├── characters.yaml         # Uploaded characters
├── locations.yaml          # Uploaded locations (optional)
├── custom_style.txt        # Written when a style preset is activated
├── prompt_overrides.yaml   # Written when a preset is activated (author instruction, scene closing)
├── style_presets.yaml      # Named prompt presets
├── full_story.md           # Generated output
├── checkpoint.yaml         # Generation progress and story memory
├── consult_cache.json      # Persisted AI Consult results (survives restarts)
└── web_config.json         # Persisted config (host, model, retries, timeout)
```

---

← [Back to README](../README.md)
