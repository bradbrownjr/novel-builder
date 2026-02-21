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

## Setup Tab

| Feature | Details |
|---|---|
| **Ollama Host** | Enter the IP/URL of your Ollama server (e.g., `http://10.6.26.3:11434`). Saved to `workspace/web_config.json` — you set it once and it persists across restarts. |
| **Model selection** | Choose your generation model and summary model. |
| **Retries & timeout** | Configure retry attempts and timeout per request. |
| **File upload** | Upload, drag-drop, paste, or type YAML files for outline, characters, locations, and custom style prompt. Each file shows status, size, and timestamp. |
| **Edit / Export / Delete** | Edit any file in-browser, export it as a download, or remove it. |
| **Parsed data preview** | After uploading, see a summary of what's loaded: story title, chapter/scene tree, character names with trait icons, locations, heritage groups. Confirms everything parsed correctly before generating. |
| **New Story** | Clears all uploaded files, output, and checkpoint (with confirmation). Does not touch config. |

## Output Tab

- **Live viewer** — Scenes appear in real time as they're generated, with auto-scroll.
- **Refresh** — Pull the full output from disk at any time.
- **Download** — Grab the `.md` file directly from the browser.

## Logs Tab

- Timestamped log feed of every generation event — chapter/scene progress, character detection, errors, warnings.
- Persists server-side, so reconnecting shows the full history.

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
├── story_outline.yaml    # Uploaded outline
├── characters.yaml       # Uploaded characters
├── locations.yaml        # Uploaded locations (optional)
├── custom_style.txt      # Custom style prompt (optional)
├── full_story.md         # Generated output
├── checkpoint.yaml       # Generation progress
└── web_config.json       # Persisted config (host, model, retries, timeout)
```

---

← [Back to README](../README.md)
