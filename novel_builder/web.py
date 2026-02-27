"""Web UI for Novel Builder.

Provides a Flask-based single-page web interface for uploading YAML files,
configuring generation parameters, starting/stopping generation, and
monitoring progress in real time via Server-Sent Events.

Usage:
    python -m novel_builder --web [--port 8080]
"""

import json
import os
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
)

import yaml as _yaml
from .validator import validate_all as _validate_all
import requests as _requests

# Lazy imports to avoid circular imports at module level
_config_loader = None
_story_generator = None
_story_stopper = None


def _lazy_imports():
    global _config_loader, _story_generator, _story_stopper
    if _config_loader is None:
        from .config import load_config
        from .story_processor import generate_story, request_stop
        _config_loader = load_config
        _story_generator = generate_story
        _story_stopper = request_stop


# ---------------------------------------------------------------------------
# Flask app setup
# ---------------------------------------------------------------------------

_template_dir = os.path.join(os.path.dirname(__file__), "templates")
app = Flask(__name__, template_folder=_template_dir)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB upload limit

# Workspace directory for uploaded files and output
WORKSPACE_DIR = os.path.join(os.getcwd(), "workspace")
ALLOWED_EXTENSIONS = {".yaml", ".yml", ".txt", ".md"}
CONFIG_FILE = "web_config.json"

# Known YAML file roles and their standard names
FILE_ROLES = {
    "outline": "story_outline.yaml",
    "characters": "characters.yaml",
    "locations": "locations.yaml",
    "style": "custom_style.txt",
}


def _normalize_host(host):
    """Normalize an Ollama host string to a full URL.

    Accepts bare IPs (192.168.1.x), IP:port (192.168.1.x:11434),
    or full URLs (http://192.168.1.x:11434).  Mirrors the same
    normalization the CLI applies interactively.
    """
    if not host:
        return host
    host = host.strip().rstrip("/")
    if not host.startswith("http://") and not host.startswith("https://"):
        # Bare IP or IP:port — add scheme
        if ":" not in host:
            # No port either — add default Ollama port
            host = f"http://{host}:11434"
        else:
            host = f"http://{host}"
    return host


# ---------------------------------------------------------------------------
# Server-side generation state
# ---------------------------------------------------------------------------

class GenerationState:
    """Thread-safe state that survives browser disconnection."""

    def __init__(self):
        self.status = "idle"  # idle | running | completed | error | stopped
        self.progress = {
            "chapter": 0,
            "total_chapters": 0,
            "scene": 0,
            "total_scenes": 0,
            "percent": 0,
        }
        self.active_model = {"model": "idle", "name": ""}
        self.logs = []
        self.output_scenes = []
        self.error = None
        self.start_time = None
        self._thread = None
        self._event_queues = []
        self._lock = threading.Lock()

    # -- Event broadcasting --

    def emit(self, event_type, data):
        """Push a structured event to all SSE subscribers."""
        event = {
            "type": event_type,
            "data": data,
            "time": time.time(),
        }
        with self._lock:
            # Update internal state from event
            if event_type == "progress":
                self.progress.update(data)
            elif event_type == "model_active":
                self.active_model = {
                    "model": data.get("model", "idle"),
                    "name": data.get("name", ""),
                }
            elif event_type == "scene_complete":
                self.output_scenes.append({
                    "scene_num": data.get("scene_num", ""),
                    "title": data.get("title", ""),
                    "text": data.get("text", ""),
                    "summary": data.get("summary", ""),
                    "chars": data.get("chars", 0),
                })
            elif event_type == "status_change":
                self.status = data.get("status", self.status)
                if data.get("message"):
                    self.error = data["message"]
            elif event_type == "log":
                ts = datetime.now().strftime("%H:%M:%S")
                entry = {
                    "time": ts,
                    "message": data.get("message", ""),
                    "level": data.get("level", "info"),
                }
                self.logs.append(entry)
                if len(self.logs) > 500:
                    self.logs = self.logs[-500:]

            # Push to all SSE subscriber queues
            dead = []
            for q in self._event_queues:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._event_queues.remove(q)

    def subscribe(self):
        """Create a new SSE event queue for a client."""
        q = queue.Queue(maxsize=200)
        with self._lock:
            self._event_queues.append(q)
        return q

    def unsubscribe(self, q):
        """Remove an SSE subscriber queue."""
        with self._lock:
            if q in self._event_queues:
                self._event_queues.remove(q)

    def snapshot(self):
        """Return full state as a JSON-safe dict for reconnection."""
        with self._lock:
            return {
                "status": self.status,
                "progress": dict(self.progress),
                "active_model": dict(self.active_model),
                "logs": list(self.logs[-100:]),
                "output_scenes": [
                    {
                        "scene_num": s["scene_num"],
                        "title": s["title"],
                        "chars": s["chars"],
                    }
                    for s in self.output_scenes
                ],
                "error": self.error,
                "start_time": self.start_time,
                "is_alive": (
                    self._thread is not None and self._thread.is_alive()
                ),
            }

    def reset(self):
        """Reset state for a new generation run."""
        with self._lock:
            self.status = "idle"
            self.progress = {
                "chapter": 0, "total_chapters": 0,
                "scene": 0, "total_scenes": 0, "percent": 0,
            }
            self.active_model = {"model": "idle", "name": ""}
            self.logs = []
            self.output_scenes = []
            self.error = None
            self.start_time = None


state = GenerationState()


# ---------------------------------------------------------------------------
# Consult state (AI analysis results — survives browser refresh)
# ---------------------------------------------------------------------------

class ConsultState:
    """Stores consultation analysis results server-side.

    Uses a subscriber queue pattern matching GenerationState so results
    persist across page refreshes and are accessible from any device.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.status = "idle"   # idle | running | completed | error
        self.passes = {}       # pass_name → {label, emoji, text, status, stats, error}
        self.error = None
        self._thread = None
        self._event_queues = []

    def emit(self, event_type, data):
        """Update cached state and push event to all SSE subscribers."""
        with self._lock:
            if event_type == "pass_start":
                name = data["pass"]
                self.passes[name] = {
                    "label": data.get("label", name),
                    "emoji": data.get("emoji", ""),
                    "text": "",
                    "status": "running",
                    "stats": None,
                    "error": None,
                }
            elif event_type == "pass_chunk":
                name = data["pass"]
                if name in self.passes:
                    self.passes[name]["text"] += data.get("chunk", "")
            elif event_type == "pass_done":
                name = data["pass"]
                if name in self.passes:
                    self.passes[name]["status"] = "done"
                    self.passes[name]["stats"] = data.get("stats")
            elif event_type == "pass_error":
                name = data["pass"]
                if name in self.passes:
                    self.passes[name]["status"] = "error"
                    self.passes[name]["error"] = data.get("message", "")
            elif event_type == "consult_start":
                self.status = "running"
            elif event_type == "consult_done":
                self.status = "completed"
            elif event_type == "consult_error":
                self.status = "error"
                self.error = data.get("message", "")

            event = {"type": event_type, "data": data, "time": time.time()}
            dead = []
            for q in self._event_queues:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._event_queues.remove(q)

    def subscribe_with_snapshot(self):
        """Subscribe atomically with a snapshot — prevents duplicate chunks.

        By subscribing inside the lock, any chunk emitted after we return
        will be in the queue, and the snapshot will contain all chunks
        emitted before. No overlap.

        Returns:
            (queue, snapshot_dict) tuple.
        """
        with self._lock:
            q = queue.Queue(maxsize=500)
            self._event_queues.append(q)
            snapshot = {
                "status": self.status,
                "passes": {k: dict(v) for k, v in self.passes.items()},
                "error": self.error,
                "is_alive": self._thread is not None and self._thread.is_alive(),
            }
        return q, snapshot

    def unsubscribe(self, q):
        with self._lock:
            if q in self._event_queues:
                self._event_queues.remove(q)

    def snapshot(self):
        with self._lock:
            return {
                "status": self.status,
                "passes": {k: dict(v) for k, v in self.passes.items()},
                "error": self.error,
                "is_alive": self._thread is not None and self._thread.is_alive(),
            }

    def reset(self):
        with self._lock:
            self.status = "idle"
            self.passes = {}
            self.error = None


consult_state = ConsultState()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_workspace():
    """Create workspace directory if it doesn't exist."""
    os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _safe_filename(filename):
    """Sanitize a filename — no path traversal, no shell special chars."""
    # Strip path components
    name = os.path.basename(filename)
    # Allow only safe characters
    name = re.sub(r"[^\w\-. ]", "_", name)
    return name


def _workspace_path(filename):
    """Get absolute path inside workspace."""
    return os.path.join(WORKSPACE_DIR, _safe_filename(filename))


def _load_web_config():
    """Load saved web configuration from workspace."""
    path = os.path.join(WORKSPACE_DIR, CONFIG_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "host": os.environ.get("OLLAMA_HOST", ""),
        "model": "gemma3:12b",
        "summary_model": "gemma3:1b",
        "retries": 3,
        "timeout": 900,
    }


def _save_web_config(cfg):
    """Persist web configuration to workspace."""
    _ensure_workspace()
    path = os.path.join(WORKSPACE_DIR, CONFIG_FILE)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)


def _list_workspace_files():
    """List uploaded files in workspace with metadata."""
    _ensure_workspace()
    files = {}
    for role, standard_name in FILE_ROLES.items():
        path = os.path.join(WORKSPACE_DIR, standard_name)
        if os.path.exists(path):
            stat = os.stat(path)
            files[role] = {
                "filename": standard_name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(
                    stat.st_mtime
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "preview": _file_preview(path),
            }
    return files


def _file_preview(path, max_chars=200):
    """Read first N characters of a file for preview."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(max_chars)
            if len(content) == max_chars:
                content += "..."
            return content
    except (OSError, UnicodeDecodeError):
        return "(binary or unreadable)"


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _event_callback(event_type, data):
    """Bridge between story_processor events and GenerationState."""
    state.emit(event_type, data)


def _start_generation(web_config):
    """Start story generation in a background thread."""
    _lazy_imports()

    if state._thread is not None and state._thread.is_alive():
        return False, "Generation already running"

    _ensure_workspace()

    # Build args namespace matching what CLI produces
    args = SimpleNamespace(
        host=_normalize_host(web_config.get("host", "")),
        model=web_config.get("model", "gemma3:12b"),
        summary_model=web_config.get("summary_model", "gemma3:1b"),
        retries=int(web_config.get("retries", 3)),
        timeout=int(web_config.get("timeout", 900)),
        output=os.path.join(WORKSPACE_DIR, "full_story.md"),
        quiet=True,  # Web UI handles display
        resume=web_config.get("resume", False),
        restart=not web_config.get("resume", False),
        dry_run=False,
        chapter=None,
        scene=None,
        # File paths — point to workspace
        outline=os.path.join(WORKSPACE_DIR, FILE_ROLES["outline"]),
        characters=os.path.join(WORKSPACE_DIR, FILE_ROLES["characters"]),
        locations=os.path.join(WORKSPACE_DIR, FILE_ROLES["locations"]),
    )

    # Validate required files exist
    if not os.path.exists(args.outline):
        return False, "Story outline file not uploaded"
    if not os.path.exists(args.characters):
        return False, "Characters file not uploaded"

    # Locations are optional — set to None if missing
    if not os.path.exists(args.locations):
        args.locations = None

    # Load custom style if present
    style_path = os.path.join(WORKSPACE_DIR, FILE_ROLES["style"])
    custom_style = ""
    if os.path.exists(style_path):
        try:
            with open(style_path, "r", encoding="utf-8") as f:
                custom_style = f.read().strip()
        except OSError:
            pass

    # Load config from YAML files
    try:
        config = _config_loader(args)
    except Exception as e:
        return False, f"Failed to load story config: {e}"

    # Inject custom style if provided
    if custom_style:
        existing = config.get("style_directives", "")
        if existing:
            config["style_directives"] = f"{existing}\n{custom_style}"
        else:
            config["style_directives"] = custom_style

    # Reset state and start
    state.reset()
    state.start_time = time.time()
    state.status = "running"

    def worker():
        try:
            _story_generator(config, args, event_callback=_event_callback)
        except Exception as e:
            state.emit("log", {
                "message": f"Unexpected error: {e}",
                "level": "error",
            })
            state.emit("status_change", {"status": "error", "message": str(e)})

    thread = threading.Thread(target=worker, daemon=True, name="novel-gen")
    thread.start()
    state._thread = thread

    return True, "Generation started"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the single-page web UI."""
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """Full state snapshot for page load / reconnection."""
    snap = state.snapshot()
    snap["config"] = _load_web_config()
    snap["files"] = _list_workspace_files()
    return jsonify(snap)


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Get or save generation configuration."""
    if request.method == "GET":
        return jsonify(_load_web_config())

    data = request.get_json(force=True)
    # Sanitize — only accept known keys
    allowed = {"host", "model", "summary_model", "retries", "timeout"}
    cfg = _load_web_config()
    for key in allowed:
        if key in data:
            cfg[key] = data[key]
    if "host" in data:
        cfg["host"] = _normalize_host(cfg["host"])
    _save_web_config(cfg)
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload a YAML file for a specific role (outline, characters, etc.)."""
    _ensure_workspace()

    role = request.form.get("role", "").strip()
    if role not in FILE_ROLES:
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    # Validate extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({
            "ok": False,
            "error": f"Invalid file type: {ext}",
        }), 400

    # Save with the standard name for the role
    dest = os.path.join(WORKSPACE_DIR, FILE_ROLES[role])
    file.save(dest)

    return jsonify({
        "ok": True,
        "filename": FILE_ROLES[role],
        "size": os.path.getsize(dest),
    })


@app.route("/api/save-text", methods=["POST"])
def api_save_text():
    """Save pasted/typed text as a file for a specific role."""
    _ensure_workspace()

    data = request.get_json(force=True)
    role = data.get("role", "").strip()
    content = data.get("content", "")

    if role not in FILE_ROLES:
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400

    if not content.strip():
        return jsonify({"ok": False, "error": "Content is empty"}), 400

    # Basic size check
    if len(content) > 5 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Content too large (>5MB)"}), 400

    dest = os.path.join(WORKSPACE_DIR, FILE_ROLES[role])
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)

    return jsonify({
        "ok": True,
        "filename": FILE_ROLES[role],
        "size": len(content.encode("utf-8")),
    })


@app.route("/api/files")
def api_files():
    """List uploaded files in workspace."""
    return jsonify(_list_workspace_files())


@app.route("/api/file-content/<role>")
def api_file_content(role):
    """Get the full content of an uploaded file by role."""
    if role not in FILE_ROLES:
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400

    path = os.path.join(WORKSPACE_DIR, FILE_ROLES[role])
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "File not found"}), 404

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"ok": True, "content": content, "filename": FILE_ROLES[role]})
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/download-file/<role>")
def api_download_file(role):
    """Download a workspace file by role (outline, characters, locations, style)."""
    if role not in FILE_ROLES:
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400

    path = os.path.join(WORKSPACE_DIR, FILE_ROLES[role])
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "File not found"}), 404

    mime = "text/yaml" if path.endswith((".yaml", ".yml")) else "text/plain"
    return send_file(
        path,
        mimetype=mime,
        as_attachment=True,
        download_name=FILE_ROLES[role],
    )


@app.route("/api/new-story", methods=["POST"])
def api_new_story():
    """Clear workspace files to start a new story.

    Removes YAML files, output, and checkpoint. Preserves web_config.json.
    """
    if state.status == "running":
        return jsonify({"ok": False, "error": "Cannot reset while generation is running"}), 400

    _ensure_workspace()
    removed = []
    # Remove story files
    for role, filename in FILE_ROLES.items():
        path = os.path.join(WORKSPACE_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
            removed.append(filename)
    # Remove output and checkpoint
    for extra in ["full_story.md", "checkpoint.yaml"]:
        path = os.path.join(WORKSPACE_DIR, extra)
        if os.path.exists(path):
            os.remove(path)
            removed.append(extra)

    state.reset()

    return jsonify({"ok": True, "removed": removed})


@app.route("/api/parse-yaml")
def api_parse_yaml():
    """Parse uploaded YAML files and return a summary of loaded data.

    Returns character names/roles, chapter/scene counts, locations,
    heritage groups, validation results, and other key metadata.
    """
    _ensure_workspace()
    result = {"ok": True, "outline": None, "characters": None, "locations": None, "validation": []}

    outline_raw = char_raw = loc_raw = ""
    outline_data = char_data = loc_data = None

    # --- Outline ---
    outline_path = os.path.join(WORKSPACE_DIR, FILE_ROLES["outline"])
    if os.path.exists(outline_path):
        try:
            with open(outline_path, "r", encoding="utf-8") as f:
                outline_raw = f.read()
            data = _yaml.safe_load(outline_raw) or {}
            outline_data = data
            if not isinstance(data, dict):
                raise ValueError(f"Expected a YAML mapping at the top level, got {type(data).__name__}")
            chapters = data.get("chapters") or []
            if not isinstance(chapters, list):
                chapters = []
            scene_list = []
            for ch in chapters:
                if not isinstance(ch, dict):
                    continue
                ch_num = ch.get("chapter_number", "?")
                scenes = ch.get("scenes") or []
                if not isinstance(scenes, list):
                    scenes = []
                for sc in scenes:
                    if not isinstance(sc, dict):
                        continue
                    sc_num = sc.get("scene_number", "?")
                    sc_title = sc.get("title", "")
                    scene_list.append({
                        "id": str(sc_num),
                        "chapter": ch_num,
                        "title": sc_title or f"Ch{ch_num} Sc{sc_num}",
                        "setting": sc.get("setting", ""),
                        "characters": sc.get("characters_present", sc.get("characters", [])),
                    })
            result["outline"] = {
                "story_title": data.get("story_title", "Untitled"),
                "world": data.get("world", ""),
                "total_chapters": len(chapters),
                "total_scenes": len(scene_list),
                "chapters": [
                    {
                        "number": ch.get("chapter_number", i + 1) if isinstance(ch, dict) else i + 1,
                        "title": ch.get("title", "Untitled") if isinstance(ch, dict) else "Untitled",
                        "scenes": len(ch.get("scenes") or []) if isinstance(ch, dict) else 0,
                    }
                    for i, ch in enumerate(chapters)
                ],
                "scenes": scene_list,
                "style_directives": data.get("style_directives", ""),
                "anti_patterns": data.get("anti_patterns") or [],
                "narrative_hooks": [
                    (h.get("hook", h.get("name", str(h))) if isinstance(h, dict) else str(h))
                    for h in (data.get("narrative_hooks") or [])
                ],
                "overall_arc": data.get("overall_arc") or {},
            }
        except Exception as e:
            result["outline"] = {"error": str(e)}

    # --- Characters ---
    char_path = os.path.join(WORKSPACE_DIR, FILE_ROLES["characters"])
    if os.path.exists(char_path):
        try:
            with open(char_path, "r", encoding="utf-8") as f:
                char_raw = f.read()
            data = _yaml.safe_load(char_raw) or {}
            char_data = data
            chars = data.get("characters", data)
            if not isinstance(chars, dict):
                chars = {}
            char_list = []
            for cid, cdata in chars.items():
                if not isinstance(cdata, dict):
                    continue
                char_list.append({
                    "id": cid,
                    "name": cdata.get("Name") or cdata.get("name", cid),
                    "role": cdata.get("role", ""),
                    "vibe": cdata.get("vibe", ""),
                    "heritage": cdata.get("heritage", []),
                    "has_catchphrase": bool(cdata.get("catchphrase") or cdata.get("catchphrases")),
                    "has_secret": bool(cdata.get("secret")),
                    "has_relationships": bool(cdata.get("relationships")),
                    "has_evolution": bool(cdata.get("evolution")),
                })
            heritage = data.get("heritage", {})
            heritage_list = []
            if isinstance(heritage, dict):
                for hid, hdata in heritage.items():
                    if isinstance(hdata, dict):
                        heritage_list.append({
                            "id": hid,
                            "label": hdata.get("label", hid),
                        })
            result["characters"] = {
                "total": len(char_list),
                "characters": char_list,
                "heritage_groups": heritage_list,
            }
        except Exception as e:
            result["characters"] = {"error": str(e)}

    # --- Locations ---
    loc_path = os.path.join(WORKSPACE_DIR, FILE_ROLES["locations"])
    if os.path.exists(loc_path):
        try:
            with open(loc_path, "r", encoding="utf-8") as f:
                loc_raw = f.read()
            data = _yaml.safe_load(loc_raw) or {}
            loc_data = data
            locs = data.get("setting", data.get("locations", data))
            if not isinstance(locs, dict):
                locs = {}
            loc_list = []
            for lid, ldata in locs.items():
                if isinstance(ldata, dict):
                    loc_list.append({
                        "id": lid,
                        "type": ldata.get("type", ""),
                        "description": (ldata.get("description", "")[:80] + "...")
                            if len(ldata.get("description", "")) > 80
                            else ldata.get("description", ""),
                    })
                elif isinstance(ldata, str):
                    loc_list.append({"id": lid, "type": "", "description": ldata[:80]})
            result["locations"] = {"total": len(loc_list), "locations": loc_list}
        except Exception as e:
            result["locations"] = {"error": str(e)}

    # --- Validation ---
    try:
        vresults = _validate_all(
            outline_raw, outline_data,
            char_raw, char_data,
            loc_raw, loc_data,
        )
        result["validation"] = [v.to_dict() for v in vresults]
    except Exception as e:
        result["validation"] = [{"level": "error", "source": "validator",
                                  "field": "(internal)", "line": None,
                                  "message": f"Validator error: {e}",
                                  "suggestion": None}]

    return jsonify(result)


@app.route("/api/start", methods=["POST"])
def api_start():
    """Start story generation."""
    data = request.get_json(force=True) if request.is_json else {}
    resume = data.get("resume", False)

    cfg = _load_web_config()
    cfg["resume"] = resume

    ok, message = _start_generation(cfg)
    status_code = 200 if ok else 400
    return jsonify({"ok": ok, "message": message}), status_code


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Request graceful stop of generation."""
    _lazy_imports()

    if state.status != "running":
        return jsonify({"ok": False, "message": "Not currently running"})

    _story_stopper()
    state.emit("log", {"message": "Stop requested by user", "level": "warn"})
    return jsonify({"ok": True, "message": "Stop requested"})


@app.route("/api/ollama-health")
def api_ollama_health():
    """Ping the Ollama server to check connectivity and list models."""
    cfg = _load_web_config()
    host = _normalize_host(cfg.get("host", ""))
    if not host:
        return jsonify({"ok": False, "error": "No host configured"})

    try:
        resp = _requests.get(f"{host}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [
            m.get("name", "") for m in data.get("models", [])
        ]
        return jsonify({"ok": True, "models": models})
    except _requests.ConnectionError:
        return jsonify({"ok": False, "error": "Connection refused"})
    except _requests.Timeout:
        return jsonify({"ok": False, "error": "Timeout"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/events")
def api_events():
    """SSE endpoint for real-time progress updates."""
    def stream():
        q = state.subscribe()
        try:
            # Send initial heartbeat
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except queue.Empty:
                    # Heartbeat to keep connection alive
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except GeneratorExit:
            pass
        finally:
            state.unsubscribe(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/output")
def api_output():
    """Get the full generated output text."""
    output_path = os.path.join(WORKSPACE_DIR, "full_story.md")
    if not os.path.exists(output_path):
        return jsonify({"text": "", "exists": False})

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            text = f.read()
        return jsonify({"text": text, "exists": True})
    except OSError as e:
        return jsonify({"text": "", "exists": False, "error": str(e)})


@app.route("/api/download")
def api_download():
    """Download the output .md file."""
    output_path = os.path.join(WORKSPACE_DIR, "full_story.md")
    if not os.path.exists(output_path):
        return jsonify({"ok": False, "error": "No output file yet"}), 404

    return send_file(
        output_path,
        mimetype="text/markdown",
        as_attachment=True,
        download_name="novel_output.md",
    )


@app.route("/api/delete-file/<role>", methods=["POST"])
def api_delete_file(role):
    """Delete a single workspace file by role."""
    if role not in FILE_ROLES:
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400
    path = os.path.join(WORKSPACE_DIR, FILE_ROLES[role])
    if os.path.exists(path):
        os.remove(path)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "File not found"}), 404


# ---------------------------------------------------------------------------
# Consult routes
# ---------------------------------------------------------------------------

@app.route("/api/consult", methods=["POST"])
def api_consult():
    """Start an AI consultation analysis and stream results as SSE.

    Runs in a background thread so the analysis continues even if the
    initiating browser disconnects.  Any device can reconnect via
    /api/consult-results (snapshot) or /api/consult-events (live stream).
    """
    # If already running, don't start a new one — just attach a subscriber
    if consult_state._thread is None or not consult_state._thread.is_alive():
        consult_state.reset()

        def worker():
            from .consult import get_analysis_passes, build_pass_prompt
            cfg = _load_web_config()
            host = _normalize_host(cfg.get("host", ""))
            model = cfg.get("model", "gemma3:12b")
            # Consult passes use num_ctx=16384 on large YAML — needs a generous
            # floor regardless of the standard generation timeout setting.
            timeout = max(int(cfg.get("timeout", 900)), 1800)

            if not host:
                consult_state.emit("consult_error", {
                    "message": "No Ollama host configured"
                })
                return

            files = {}
            for role in ("outline", "characters", "locations"):
                path = os.path.join(WORKSPACE_DIR, FILE_ROLES.get(role, f"{role}.yaml"))
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            files[role] = f.read()
                    except OSError:
                        pass

            passes = get_analysis_passes(files)
            if not passes:
                consult_state.emit("consult_error", {
                    "message": (
                        "No YAML files available for analysis. "
                        "Upload your story files first."
                    )
                })
                return

            consult_state.emit("consult_start", {"total_passes": len(passes)})

            for idx, (pass_name, pass_cfg) in enumerate(passes, 1):
                label = pass_cfg["label"]
                emoji = pass_cfg["emoji"]

                consult_state.emit("pass_start", {
                    "pass": pass_name,
                    "label": label,
                    "emoji": emoji,
                    "index": idx,
                    "total": len(passes),
                })
                state.emit("model_active", {"model": "consult", "name": model})

                system_prompt, user_prompt = build_pass_prompt(pass_name, files)

                url = f"{host}/api/generate"
                payload = {
                    "model": model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": True,
                    "options": {
                        "num_ctx": 16384,
                        "temperature": 0.4,
                        "top_p": 0.9,
                    },
                }

                t_start = time.time()
                done_data = None

                try:
                    resp = _requests.post(
                        url, json=payload, timeout=timeout, stream=True
                    )
                    resp.raise_for_status()

                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except ValueError:
                            continue
                        token = chunk.get("response", "")
                        if token:
                            consult_state.emit("pass_chunk", {
                                "pass": pass_name,
                                "chunk": token,
                            })
                        if chunk.get("done"):
                            done_data = chunk
                            break

                except Exception as e:
                    state.emit("model_active", {"model": "idle", "name": ""})
                    consult_state.emit("pass_error", {
                        "pass": pass_name,
                        "message": str(e),
                    })
                    continue

                elapsed = time.time() - t_start
                stats = {"elapsed": round(elapsed, 1)}
                if done_data:
                    eval_count = done_data.get("eval_count", 0)
                    eval_dur = done_data.get("eval_duration", 0)
                    prompt_eval = done_data.get("prompt_eval_count", 0)
                    if eval_dur and eval_count:
                        stats["toks_per_s"] = round(
                            eval_count / (eval_dur / 1e9), 1
                        )
                    if eval_count:
                        stats["eval_tokens"] = eval_count
                    if prompt_eval:
                        stats["prompt_tokens"] = prompt_eval

                consult_state.emit("pass_done", {
                    "pass": pass_name,
                    "stats": stats,
                })
                state.emit("model_active", {"model": "idle", "name": ""})

            consult_state.emit("consult_done", {})

        t = threading.Thread(target=worker, daemon=True, name="novel-consult")
        t.start()
        consult_state._thread = t

    # Subscribe atomically with snapshot to avoid duplicate chunks
    q, snap = consult_state.subscribe_with_snapshot()

    def stream():
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"

            # Replay accumulated pass text captured at subscribe time
            for name in ("characters", "outline", "locations", "crossref"):
                p = snap["passes"].get(name)
                if not p:
                    continue
                yield (
                    f"data: {json.dumps({'type': 'pass_restore', 'pass': name, 'label': p['label'], 'emoji': p['emoji'], 'text': p['text'], 'status': p['status'], 'stats': p.get('stats'), 'error': p.get('error')})}\n\n"
                )

            # If already finished, send terminal event and stop
            if snap["status"] == "completed":
                yield f"data: {json.dumps({'type': 'consult_done'})}\n\n"
                return
            if snap["status"] == "error":
                yield f"data: {json.dumps({'type': 'consult_error', 'message': snap.get('error', '')})}\n\n"
                return

            # Stream live events from background thread
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                    if event["type"] in ("consult_done", "consult_error"):
                        break
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

        except GeneratorExit:
            pass
        finally:
            consult_state.unsubscribe(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/consult-results")
def api_consult_results():
    """Return the cached consult results snapshot for reconnection.

    Safe to call from any device at any time, even while analysis is running.
    Returns accumulated text for each completed or in-progress pass.
    """
    return jsonify(consult_state.snapshot())


@app.route("/api/consult-clear", methods=["POST"])
def api_consult_clear():
    """Clear cached consult results."""
    if consult_state._thread is not None and consult_state._thread.is_alive():
        return jsonify({"ok": False, "error": "Analysis still running"}), 400
    consult_state.reset()
    return jsonify({"ok": True})


@app.route("/api/consult-apply", methods=["POST"])
def api_consult_apply():
    """Generate a corrected YAML file for a completed analysis pass (SSE).

    Streams the proposed fixed YAML from the LLM.  The client can review
    the result in an editable textarea before saving.
    """
    data = request.get_json(force=True)
    role = data.get("role", "")

    if role not in ("outline", "characters", "locations"):
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400

    snap = consult_state.snapshot()
    pass_data = snap["passes"].get(role)
    if not pass_data or pass_data.get("status") != "done":
        return jsonify({"ok": False, "error": "Pass not completed"}), 400

    analysis_text = pass_data["text"]

    yaml_path = os.path.join(WORKSPACE_DIR, FILE_ROLES[role])
    if not os.path.exists(yaml_path):
        return jsonify({"ok": False, "error": "YAML file not found in workspace"}), 404

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            original_yaml = f.read()
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    def stream():
        from .consult import build_fix_prompt
        cfg = _load_web_config()
        host = _normalize_host(cfg.get("host", ""))
        model = cfg.get("model", "gemma3:12b")
        # Same floor as analysis passes — fix generation also uses num_ctx=16384.
        timeout = max(int(cfg.get("timeout", 900)), 1800)

        if not host:
            yield f"data: {json.dumps({'type': 'fix_error', 'message': 'No Ollama host configured'})}\n\n"
            return

        system_prompt, user_prompt = build_fix_prompt(role, original_yaml, analysis_text)

        url = f"{host}/api/generate"
        payload = {
            "model": model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": True,
            "options": {
                "num_ctx": 16384,
                "temperature": 0.3,
            },
        }

        try:
            resp = _requests.post(url, json=payload, timeout=timeout, stream=True)
            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError:
                    continue
                token = chunk.get("response", "")
                if token:
                    yield f"data: {json.dumps({'type': 'fix_chunk', 'chunk': token})}\n\n"
                if chunk.get("done"):
                    yield f"data: {json.dumps({'type': 'fix_done'})}\n\n"
                    break

        except GeneratorExit:
            pass
        except Exception as e:
            yield f"data: {json.dumps({'type': 'fix_error', 'message': str(e)})}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/consult-save", methods=["POST"])
def api_consult_save():
    """Save a proposed YAML fix back to workspace.

    Validates the YAML before writing it.  This replaces the existing
    file in the workspace, which then takes effect on the next generation run.
    """
    _ensure_workspace()
    data = request.get_json(force=True)
    role = data.get("role", "")
    content = data.get("content", "")

    if role not in FILE_ROLES:
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400
    if not content.strip():
        return jsonify({"ok": False, "error": "Content is empty"}), 400
    if len(content) > 5 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Content too large (>5MB)"}), 400

    # Validate YAML syntax before saving
    try:
        _yaml.safe_load(content)
    except _yaml.YAMLError as e:
        return jsonify({"ok": False, "error": f"Invalid YAML: {e}"}), 400

    dest = os.path.join(WORKSPACE_DIR, FILE_ROLES[role])
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)

    return jsonify({
        "ok": True,
        "filename": FILE_ROLES[role],
        "size": len(content.encode("utf-8")),
    })


# ---------------------------------------------------------------------------
# Memory routes
# ---------------------------------------------------------------------------

@app.route("/api/memory", methods=["GET"])
def api_memory_get():
    """Return the story memory from the current checkpoint.

    Includes story_memory (facts, actions, commitments, characters),
    last_completed_chapter/scene, and a truncated story_so_far snippet.
    Returns empty memory if no checkpoint exists yet.
    """
    checkpoint_path = os.path.join(WORKSPACE_DIR, "checkpoint.yaml")
    if not os.path.exists(checkpoint_path):
        return jsonify({
            "ok": True,
            "exists": False,
            "last_completed_chapter": None,
            "last_completed_scene": None,
            "story_so_far_snippet": "",
            "story_memory": {
                "characters": {},
                "facts": [],
                "actions": [],
                "commitments": [],
                "used_imagery": [],
            },
        })

    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            cp = _yaml.safe_load(f) or {}
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    memory = cp.get("story_memory") or {}
    if not isinstance(memory, dict):
        memory = {}

    story_so_far = cp.get("story_so_far", "")
    snippet = story_so_far[:300] + ("…" if len(story_so_far) > 300 else "")

    return jsonify({
        "ok": True,
        "exists": True,
        "last_completed_chapter": cp.get("last_completed_chapter"),
        "last_completed_scene": cp.get("last_completed_scene"),
        "story_so_far_snippet": snippet,
        "story_memory": {
            "characters": memory.get("characters") or {},
            "facts": memory.get("facts") or [],
            "actions": memory.get("actions") or [],
            "commitments": memory.get("commitments") or [],
            "used_imagery": memory.get("used_imagery") or [],
        },
    })


@app.route("/api/memory", methods=["POST"])
def api_memory_post():
    """Save updated story memory back to checkpoint.

    Accepts a partial story_memory dict (facts, actions, commitments,
    characters) and merges it into the existing checkpoint.  The checkpoint
    must already exist — this endpoint is for editing, not initialisation.
    """
    checkpoint_path = os.path.join(WORKSPACE_DIR, "checkpoint.yaml")
    if not os.path.exists(checkpoint_path):
        return jsonify({"ok": False, "error": "No checkpoint found — start generation first"}), 404

    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            cp = _yaml.safe_load(f) or {}
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not read checkpoint: {e}"}), 500

    data = request.get_json(force=True)
    new_memory = data.get("story_memory")
    if not isinstance(new_memory, dict):
        return jsonify({"ok": False, "error": "story_memory must be a dict"}), 400

    # Merge — replace only the sections provided
    existing = cp.get("story_memory") or {}
    if not isinstance(existing, dict):
        existing = {}
    for key in ("facts", "actions", "commitments", "characters", "used_imagery"):
        if key in new_memory:
            existing[key] = new_memory[key]
    cp["story_memory"] = existing

    try:
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            _yaml.dump(cp, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not write checkpoint: {e}"}), 500

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------

def run_server(host="0.0.0.0", port=8080):
    """Start the Flask development server.

    Args:
        host: Bind address (0.0.0.0 for LAN access).
        port: Port number.
    """
    _ensure_workspace()

    print(f"\n{'=' * 60}")
    print(f"  Novel Builder — Web UI")
    print(f"  http://{host}:{port}")
    if host == "0.0.0.0":
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            print(f"  LAN: http://{local_ip}:{port}")
        except Exception:
            pass
    print(f"  Workspace: {os.path.abspath(WORKSPACE_DIR)}")
    print(f"{'=' * 60}\n")

    app.run(host=host, port=port, threaded=True, debug=False)
