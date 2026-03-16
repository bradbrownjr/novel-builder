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
import traceback as _traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from flask import (
    Flask,
    Response,
    current_app,
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
CONSULT_CACHE_FILE = "consult_cache.json"
STYLE_PRESETS_FILE = "style_presets.yaml"
PROMPT_OVERRIDES_FILE = "prompt_overrides.yaml"

# Known YAML file roles and their standard names
FILE_ROLES = {
    "outline": "story_outline.yaml",
    "characters": "characters.yaml",
    "locations": "locations.yaml",
    "style": "custom_style.txt",
}


def _normalize_host(host):
    """Normalize an Ollama host string to a full URL.

    Accepts bare IPs (10.6.26.2), IP:port (10.6.26.2:11434),
    or full URLs (http://10.6.26.2:11434).  Mirrors the same
    normalization the CLI applies interactively.
    """
    if not host:
        return host
    host = host.strip().rstrip("/")
    if not host.startswith("http://") and not host.startswith("https://"):
        # Bare IP or IP:port  --  add scheme
        if ":" not in host:
            # No port either  --  add default Ollama port
            host = f"http://{host}:11434"
        else:
            host = f"http://{host}"
    return host


def _normalize_tts_host(host):
    """Normalize a TTS server URL.

    Accepts bare IPs (10.6.26.2), IP:port (10.6.26.2:8001),
    or full URLs (http://10.6.26.2:8001).  Unlike Ollama, there is
    no default port -- the URL must include the port if non-standard.
    """
    if not host:
        return host
    host = host.strip().rstrip("/")
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"http://{host}"
    return host


def _preprocess_tts_text(text):
    """Preprocess text for TTS to handle stutters and hesitations.

    Converts patterns like "H-hello" or "W-what" into forms that
    TTS engines pronounce as natural stutters rather than spelling
    out the leading letter.

    Examples:
        "H-hello"   -> "heh hello"
        "W-what"    -> "wuh what"
        "I-I don't" -> "I... I don't"
        "N-no"      -> "nuh no"
    """
    # Map leading consonants to phonetic stutter sounds
    _STUTTER_SOUNDS = {
        "b": "buh", "c": "kuh", "d": "duh", "f": "fuh", "g": "guh",
        "h": "heh", "j": "juh", "k": "kuh", "l": "luh", "m": "muh",
        "n": "nuh", "p": "puh", "q": "kuh", "r": "ruh", "s": "suh",
        "t": "tuh", "v": "vuh", "w": "wuh", "x": "ex", "y": "yuh",
        "z": "zuh",
    }

    def _replace_stutter(m):
        letter = m.group(1)
        word = m.group(2)
        lower = letter.lower()
        # Same letter repeated (I-I, I-I-I) -> ellipsis pause
        if lower == word.lower():
            return f"{letter}... {word}"
        sound = _STUTTER_SOUNDS.get(lower, lower)
        return f"{sound} {word}"

    # Match stutter pattern: single letter + hyphen + word where the
    # word starts with the same letter (case-insensitive).
    # This avoids false positives on normal hyphenated words like
    # "e-mail" or "co-worker" that don't share the leading letter.
    # Also match same-letter repetition like "I-I".
    def _is_stutter(m):
        letter = m.group(1).lower()
        word = m.group(2)
        # Same starting letter = stutter (H-hello, S-stop, I-I)
        if word[0].lower() == letter:
            return _replace_stutter(m)
        return m.group(0)  # Not a stutter, leave unchanged

    return re.sub(
        r"\b([A-Za-z])-([A-Za-z]{1,})\b",
        _is_stutter,
        text,
    )


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
        self.throughput = {"generation": None, "summary": None}
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
                entry = {
                    "time": time.time(),
                    "message": data.get("message", ""),
                    "level": data.get("level", "info"),
                }
                self.logs.append(entry)
                if len(self.logs) > 500:
                    self.logs = self.logs[-500:]
            elif event_type == "throughput":
                role = data.get("model_role")
                if role in self.throughput:
                    self.throughput[role] = {
                        "tok_per_min": data.get("tok_per_min", 0),
                        "updated_at": time.time(),
                    }

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
                "throughput": dict(self.throughput),
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
            self.throughput = {"generation": None, "summary": None}


state = GenerationState()


# ---------------------------------------------------------------------------
# Audiobook compilation state (server-side TTS  --  survives browser close)
# ---------------------------------------------------------------------------

class AudiobookState:
    """Thread-safe state for server-side audiobook compilation."""

    def __init__(self):
        self._lock = threading.Lock()
        self.status = "idle"  # idle | compiling | converting | completed | error | cancelled
        self.done = 0
        self.total = 0
        self.phase = ""  # "synthesizing" | "converting" | ""
        self.error = ""
        self.format = "mp3"
        self.output_file = ""  # path to completed file
        self._cancel = False
        self._thread = None

    def reset(self):
        with self._lock:
            self.status = "idle"
            self.done = 0
            self.total = 0
            self.phase = ""
            self.error = ""
            self.format = "mp3"
            self.output_file = ""
            self._cancel = False
            self._thread = None

    def snapshot(self):
        with self._lock:
            return {
                "status": self.status,
                "done": self.done,
                "total": self.total,
                "phase": self.phase,
                "error": self.error,
                "format": self.format,
                "has_file": bool(self.output_file and os.path.exists(self.output_file)),
                "file_size": (
                    os.path.getsize(self.output_file)
                    if self.output_file and os.path.exists(self.output_file)
                    else 0
                ),
            }


audiobook_state = AudiobookState()


# ---------------------------------------------------------------------------
# Consult state (AI analysis results  --  survives browser refresh)
# ---------------------------------------------------------------------------

class ConsultState:
    """Stores consultation analysis results server-side.

    Uses a subscriber queue pattern matching GenerationState so results
    persist across page refreshes and are accessible from any device.
    Fix generation also runs in a background thread and emits events
    through the same subscriber mechanism, ensuring progress survives
    page refreshes and is visible across devices.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.status = "idle"   # idle | running | completed | error
        self.passes = {}       # pass_name -> {label, emoji, text, status, stats, error}
        self.fixes = {}        # role -> {status, content} -- generated fix YAML
        self.error = None
        self._thread = None
        self._fix_thread = None
        self._fix_queue_roles = []  # ordered list of roles queued for fix generation
        self._fix_current = None    # role currently being generated
        self._event_queues = []
        self._stop_requested = False  # set by /api/consult-stop
        self._load_from_disk()

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
                self._stop_requested = False
            elif event_type == "consult_done":
                self.status = "completed"
            elif event_type == "consult_stopped":
                self.status = "stopped"
            elif event_type == "consult_error":
                self.status = "error"
                self.error = data.get("message", "")

            # Fix generation events
            elif event_type == "fix_start":
                role = data["role"]
                self.fixes[role] = {"status": "generating", "content": ""}
                self._fix_current = role
            elif event_type == "fix_chunk":
                role = data["role"]
                if role in self.fixes:
                    self.fixes[role]["content"] += data.get("chunk", "")
            elif event_type == "fix_done":
                role = data["role"]
                if role in self.fixes:
                    self.fixes[role]["status"] = "done"
                self._fix_current = None
            elif event_type == "fix_error":
                role = data["role"]
                if role in self.fixes:
                    self.fixes[role]["status"] = "error"
                self._fix_current = None
            elif event_type == "fix_queued":
                role = data["role"]
                if role not in self.fixes or self.fixes[role].get("status") != "generating":
                    self.fixes[role] = {"status": "queued", "content": ""}
            elif event_type == "all_fixes_done":
                self._fix_current = None
                self._fix_queue_roles = []

            # Persist to disk after meaningful state changes
            if event_type in ("pass_done", "pass_error",
                               "consult_done", "consult_error", "consult_stopped",
                               "fix_start", "fix_done", "fix_error",
                               "all_fixes_done"):
                self._persist()

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
        """Subscribe atomically with a snapshot -- prevents duplicate chunks.

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
                "fixes": {k: dict(v) for k, v in self.fixes.items()},
                "error": self.error,
                "is_alive": self._thread is not None and self._thread.is_alive(),
                "fix_alive": self._fix_thread is not None and self._fix_thread.is_alive(),
                "fix_current": self._fix_current,
                "fix_queue": list(self._fix_queue_roles),
            }
        return q, snapshot

    def unsubscribe(self, q):
        with self._lock:
            if q in self._event_queues:
                self._event_queues.remove(q)

    def set_fix(self, role, content, status="done"):
        """Store a generated fix for a role."""
        with self._lock:
            self.fixes[role] = {"status": status, "content": content}
            self._persist()

    def get_fix(self, role):
        """Retrieve stored fix content for a role."""
        with self._lock:
            return self.fixes.get(role, {}).get("content", "")

    def is_fix_running(self):
        """Check if fix generation is currently active."""
        with self._lock:
            return self._fix_thread is not None and self._fix_thread.is_alive()

    def snapshot(self):
        with self._lock:
            return {
                "status": self.status,
                "passes": {k: dict(v) for k, v in self.passes.items()},
                "fixes": {k: dict(v) for k, v in self.fixes.items()},
                "error": self.error,
                "is_alive": self._thread is not None and self._thread.is_alive(),
                "fix_alive": self._fix_thread is not None and self._fix_thread.is_alive(),
                "fix_current": self._fix_current,
                "fix_queue": list(self._fix_queue_roles),
            }

    def reset(self):
        with self._lock:
            self.status = "idle"
            self.passes = {}
            self.fixes = {}
            self.error = None
            self._fix_queue_roles = []
            self._fix_current = None
            self._stop_requested = False
        self._delete_cache()

    def request_stop(self):
        """Signal the analysis worker to stop after the current pass."""
        with self._lock:
            self._stop_requested = True

    def _persist(self):
        """Save current passes to disk for restart survival."""
        try:
            path = os.path.join(WORKSPACE_DIR, CONSULT_CACHE_FILE)
            data = {
                "status": self.status,
                "passes": {k: dict(v) for k, v in self.passes.items()},
                "fixes": {k: dict(v) for k, v in self.fixes.items()},
                "error": self.error,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def _load_from_disk(self):
        """Restore consult results from cache file on startup."""
        path = os.path.join(WORKSPACE_DIR, CONSULT_CACHE_FILE)
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.status = data.get("status", "idle")
            # A "running" status on disk means the server restarted while the
            # worker was active.  Treat it as stopped so the user can resume.
            if self.status == "running":
                self.status = "stopped"
            self.passes = data.get("passes", {})
            self.fixes = data.get("fixes", {})
            self.error = data.get("error")
            # Reset any stale "generating" or "queued" fixes from crash
            for role, fix_data in self.fixes.items():
                if fix_data.get("status") in ("generating", "queued"):
                    fix_data["status"] = "error"
                    fix_data["content"] = fix_data.get("content", "")
        except (json.JSONDecodeError, OSError):
            pass

    def _delete_cache(self):
        """Remove the cache file."""
        path = os.path.join(WORKSPACE_DIR, CONSULT_CACHE_FILE)
        try:
            os.remove(path)
        except OSError:
            pass


consult_state = ConsultState()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_workspace():
    """Create workspace directory if it doesn't exist."""
    os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _safe_filename(filename):
    """Sanitize a filename  --  no path traversal, no shell special chars."""
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
        "summary_model": "gemma3:4b",
        "retries": 3,
        "timeout": 900,
        # TTS (Speaches / Kokoro / Piper)
        "tts_host": "",
        "tts_model": "",
        "tts_narrator_voice": "",
        "tts_voice_map": {},
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
        summary_model=web_config.get("summary_model", "gemma3:4b"),
        retries=int(web_config.get("retries", 3)),
        timeout=int(web_config.get("timeout", 900)),
        num_ctx=int(web_config.get("generation_num_ctx", 8192)),
        output=os.path.join(WORKSPACE_DIR, "full_story.md"),
        quiet=True,  # Web UI handles display
        resume=web_config.get("resume", False),
        restart=not web_config.get("resume", False),
        dry_run=False,
        chapter=None,
        scene=None,
        # Always pin checkpoint to workspace so save and load agree
        checkpoint_path=os.path.join(WORKSPACE_DIR, "checkpoint.yaml"),
        # File paths  --  point to workspace
        outline=os.path.join(WORKSPACE_DIR, FILE_ROLES["outline"]),
        characters=os.path.join(WORKSPACE_DIR, FILE_ROLES["characters"]),
        locations=os.path.join(WORKSPACE_DIR, FILE_ROLES["locations"]),
    )

    # Validate required files exist
    if not os.path.exists(args.outline):
        return False, "Story outline file not uploaded"
    if not os.path.exists(args.characters):
        return False, "Characters file not uploaded"

    # Locations are optional  --  set to None if missing
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

    # Load prompt overrides if present
    overrides_path = os.path.join(WORKSPACE_DIR, PROMPT_OVERRIDES_FILE)
    if os.path.exists(overrides_path):
        try:
            with open(overrides_path, "r", encoding="utf-8") as f:
                prompt_overrides = _yaml.safe_load(f) or {}
            if prompt_overrides:
                config["_prompt_overrides"] = prompt_overrides
        except (OSError, _yaml.YAMLError):
            pass

    # Inject TTS voice map so prompt builder can add voice tagging instructions.
    # Merge tts_voice fields from characters.yaml with any manually saved voice
    # assignments.  yaml-defined voices take lower priority; saved config wins.
    yaml_voices = {}
    for char_id, char_data in config.get("characters", {}).items():
        if not isinstance(char_data, dict):
            continue
        voice = char_data.get("tts_voice", "")
        if voice:
            name = char_data.get("Name") or char_data.get("name", char_id)
            yaml_voices[name] = voice
    saved_voice_map = web_config.get("tts_voice_map") or {}
    merged_voice_map = {**yaml_voices, **saved_voice_map}
    if merged_voice_map:
        config["_tts_voice_map"] = merged_voice_map

    # Reset state and start
    state.reset()
    state.start_time = time.time()
    state.status = "running"

    def worker():
        try:
            _story_generator(config, args, event_callback=_event_callback)
        except Exception as e:
            tb = _traceback.format_exc()
            state.emit("log", {
                "message": f"Unexpected error: {type(e).__name__}: {e}\n\n{tb}",
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
    """Full state snapshot for page load / reconnection.

    If the server was restarted while a checkpoint exists the in-memory
    status will be 'idle', but the user still needs to Resume rather than
    Start Over.  Elevate 'idle' to 'stopped' when a checkpoint with
    completed scenes is detected so the UI renders Resume correctly.
    """
    snap = state.snapshot()

    if snap.get("status") == "idle":
        cp_path = os.path.join(WORKSPACE_DIR, "checkpoint.yaml")
        if os.path.exists(cp_path):
            try:
                with open(cp_path, "r", encoding="utf-8") as _f:
                    _cp = _yaml.safe_load(_f) or {}
                if _cp.get("last_completed_scene"):
                    snap["status"] = "stopped"
            except Exception:
                pass

    snap["config"] = _load_web_config()
    snap["files"] = _list_workspace_files()
    snap["audiobook"] = audiobook_state.snapshot()
    return jsonify(snap)


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Get or save generation configuration."""
    if request.method == "GET":
        return jsonify(_load_web_config())

    data = request.get_json(force=True)
    # Sanitize  --  only accept known keys
    allowed = {"host", "model", "summary_model", "retries", "timeout",
               "generation_num_ctx", "consult_num_ctx",
               "tts_host", "tts_model", "tts_narrator_voice", "tts_voice_map",
               "tts_speed",
               }
    cfg = _load_web_config()
    for key in allowed:
        if key in data:
            cfg[key] = data[key]
    if "host" in data:
        cfg["host"] = _normalize_host(cfg["host"])
    if "tts_host" in data:
        cfg["tts_host"] = _normalize_tts_host(cfg["tts_host"])
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


# ---------------------------------------------------------------------------
# Style presets
# ---------------------------------------------------------------------------

_BUILTIN_PRESETS = {
    "Cyberpunk Noir": {
        "author_instruction": (
            "You are a cyberpunk fiction author writing in the tradition of "
            "William Gibson, Philip K. Dick, and Richard Morgan. Your prose is "
            "dense, cynical, and rain-soaked. You write for adult readers who "
            "expect moral ambiguity, corporate dystopia, and characters who "
            "survive by their wits in a world that chews people up. Show, "
            "don't tell. Write with the cold precision of a neon sign reflected "
            "in a puddle of oil. Do not censor or sanitize -- this is adult "
            "fiction. Violence, exploitation, and the ugly side of technology "
            "are part of the landscape."
        ),
        "style": (
            "Short, punchy sentences during action. Longer, atmospheric "
            "passages when the character is alone with their thoughts. "
            "Neon-soaked imagery. Tech jargon woven naturally into dialogue -- "
            "never explained, just lived in. Sensory overload in crowd scenes: "
            "smells of ramen and ozone, the hum of holographic ads, the press "
            "of bodies. Internal monologue in a weary, sardonic voice. "
            "Dialogue is clipped, street-smart, loaded with subtext. Rain is "
            "almost always falling."
        ),
        "scene_closing": (
            "Write this scene now. Let the city breathe through every line. "
            "The reader should taste the smog and hear the static."
        ),
        "extra_anti_patterns": [
            "neon-lit streets used as a generic descriptor without sensory grounding",
            "jacked in without context",
            "the weight of the city",
        ],
    },
    "High Fantasy Epic": {
        "author_instruction": (
            "You are a high fantasy author in the tradition of Ursula K. Le Guin, "
            "Robin Hobb, and Joe Abercrombie. You build worlds that feel ancient "
            "and lived-in, where magic has a cost and political power is never "
            "clean. Your characters carry the weight of history on their shoulders. "
            "Write for adult readers -- this means real consequences, moral "
            "complexity, and human ugliness alongside wonder. Show, don't tell. "
            "Do not censor or sanitize mature themes, violence, or morally grey "
            "choices."
        ),
        "style": (
            "Rich, layered prose that evokes place and season without tipping "
            "into purple. Dialogue should sound like people who grew up in this "
            "world -- idioms, oaths, and rhythms that feel organic, never "
            "faux-medieval. Battle scenes are visceral and terrifying, not "
            "choreographed. Magic is awe-inspiring or unsettling, never casual. "
            "Political intrigue reads like a conversation where every word is "
            "a weapon. Let the landscape be a character -- weather, terrain, "
            "the smell of woodsmoke and horses."
        ),
        "scene_closing": (
            "Write this scene now. Let the world feel old and the stakes feel "
            "real. The reader should forget they are reading."
        ),
        "extra_anti_patterns": [
            "twas or faux-archaic contractions",
            "little did they know",
            "destiny used unironically without character awareness",
            "orbs instead of eyes",
        ],
    },
    "Southern Gothic": {
        "author_instruction": (
            "You are a Southern Gothic fiction author channeling Flannery "
            "O'Connor, Cormac McCarthy, and William Faulkner. You write about "
            "decay -- of families, of land, of the myths people tell themselves "
            "to survive. The heat is oppressive and so is the silence between "
            "what people say and what they mean. Write for adult readers. Do "
            "not flinch from violence, grotesquerie, moral rot, or the sacred "
            "tangled up with the profane. Show, don't tell. Write authentically "
            "without content filtering."
        ),
        "style": (
            "Long, winding sentences that mirror the heat and the slow decay "
            "of afternoon. Sensory details rooted in the land -- red clay, "
            "cicadas, the mineral smell of well water, rust on screen doors. "
            "Dialogue is laconic, loaded with what is left unsaid. Characters "
            "speak in idiom and implication. Violence, when it comes, is sudden "
            "and matter-of-fact. Religion and superstition bleed together. Let "
            "the grotesque sit alongside the tender without comment."
        ),
        "scene_closing": (
            "Write this scene now. Make the reader feel the humidity and the "
            "weight of family history pressing down on every room."
        ),
        "extra_anti_patterns": [
            "the South as a simple backdrop without texture",
            "bless your heart used as a punchline",
            "dark and stormy",
        ],
    },
    "Literary Realism": {
        "author_instruction": (
            "You are a contemporary literary fiction author in the tradition of "
            "Donna Tartt, Kazuo Ishiguro, and Rachel Cusk. You write about "
            "ordinary people navigating the gap between who they are and who "
            "they pretend to be. Every scene earns its place through character "
            "revelation or quiet tension. Write for adult readers -- this means "
            "emotional honesty, including uncomfortable truths about desire, "
            "regret, class, and the body. Show, don't tell. Do not sanitize "
            "the human experience."
        ),
        "style": (
            "Precise, controlled prose. Every detail is chosen -- the brand of "
            "cigarette, the specific shade of light through a window, the way "
            "someone holds a glass. Subtext drives every conversation. Interior "
            "life is rendered through concrete sensory detail, not abstract "
            "emotional labels. Pacing follows the character's attention -- what "
            "they notice reveals who they are. Humor is dry and situational, "
            "never telegraphed. Let silence do work."
        ),
        "scene_closing": (
            "Write this scene now. Trust the reader to feel what the character "
            "cannot say."
        ),
        "extra_anti_patterns": [
            "a wave of emotion",
            "tears streamed down",
            "heart pounding as emotional shorthand",
            "suddenly realized",
        ],
    },
    "Cosmic Horror": {
        "author_instruction": (
            "You are a cosmic horror author drawing on H.P. Lovecraft's sense "
            "of scale, Thomas Ligotti's philosophical dread, and Laird Barron's "
            "physicality. You write about the annihilating indifference of the "
            "universe and the fragility of human sanity when confronted with "
            "what should not exist. Write for adult readers -- psychological "
            "disintegration, body horror, existential despair, and the seductive "
            "pull of forbidden knowledge are all on the table. Show, don't tell. "
            "Do not censor or sanitize -- horror requires going to dark places."
        ),
        "style": (
            "Building dread through accumulation of wrong details -- geometry "
            "that does not resolve, sounds that have no source, smells with no "
            "earthly analogue. Academic or clinical narration that slowly frays "
            "at the edges. Long sentences that refuse to arrive at comfort. The "
            "horror is in what is almost perceived, almost understood. "
            "Descriptions of the unknowable should reach for synesthesia and "
            "contradiction rather than adjective stacking. Characters rationalize "
            "until they cannot. Let the landscape become hostile -- architecture, "
            "weather, even light itself turning wrong."
        ),
        "scene_closing": (
            "Write this scene now. The reader should feel the walls of reality "
            "thinning. Let wrongness accumulate until it becomes unbearable."
        ),
        "extra_anti_patterns": [
            "eldritch used more than once per chapter",
            "indescribable as a description -- describe it or show the failure to",
            "tentacles as generic shorthand for alien",
            "sanity slipping stated directly",
        ],
    },
    "Romantic Suspense": {
        "author_instruction": (
            "You are a romantic suspense author blending the tension craft of "
            "Tana French with the emotional intensity of Nora Roberts and the "
            "heat of a good thriller. Your stories are driven by two engines: "
            "who can you trust, and who do you want. Write for adult readers -- "
            "this means real danger, real desire, and the messy intersection of "
            "vulnerability and survival. Show, don't tell. Erotic tension and "
            "explicit scenes are written with the same care as action sequences. "
            "Do not censor or sanitize."
        ),
        "style": (
            "Tight, propulsive pacing in danger scenes -- short paragraphs, "
            "sharp verbs, the clock always ticking. In intimate scenes, slow "
            "down: texture of skin, catch of breath, the specific vulnerability "
            "of being seen by someone dangerous. Dual awareness: the character "
            "tracking threat vectors while also hyperaware of the love interest's "
            "proximity. Dialogue crackles with double meaning. Trust is the "
            "central currency -- every scene either builds or breaks it. "
            "Environmental details serve mood: locked rooms, storm light, the "
            "intimacy of shared confined spaces."
        ),
        "scene_closing": (
            "Write this scene now. Keep one hand on the knife and the other on "
            "the heartbeat."
        ),
        "extra_anti_patterns": [
            "electricity between them as the only chemistry metaphor",
            "chiseled jaw or smoldering eyes",
            "she did not know why she trusted him",
        ],
    },
    "Hardboiled Detective": {
        "author_instruction": (
            "You are a hardboiled detective fiction author in the lineage of "
            "Raymond Chandler, Dashiell Hammett, and Walter Mosley. Your "
            "narrator has seen too much and drinks accordingly. The city is a "
            "character -- corrupt, beautiful, and indifferent. Write for adult "
            "readers. Violence is quick and has consequences. Sex exists. People "
            "lie for a living. Show, don't tell. Do not censor or sanitize."
        ),
        "style": (
            "First person, past tense, with a narrator whose voice is the whole "
            "show. Similes that land like a fist -- original, concrete, one per "
            "scene max. Dialogue is 60 percent of every scene. Descriptions are "
            "selective: one perfect detail per character, per room. The plot is "
            "a maze but the prose is a straight line. Wit is bone-dry and "
            "delivered deadpan. Every character the narrator meets is assessed "
            "in two sentences -- what they look like and what that tells you "
            "about how they will betray you."
        ),
        "scene_closing": (
            "Write this scene now. Keep the voice consistent and the whiskey "
            "metaphorical."
        ),
        "extra_anti_patterns": [
            "dame used unironically in a modern setting",
            "it was a dark and stormy night",
            "legs described as going all the way up",
        ],
    },
    "Vonnegut Absurdist": {
        "author_instruction": (
            "You are a fiction author channeling Kurt Vonnegut -- darkly funny, "
            "deceptively simple, and quietly furious about the human condition. "
            "You write short, declarative sentences that land like punchlines to "
            "jokes nobody asked for. You treat the absurd as ordinary and the "
            "ordinary as absurd. You are kind to your characters even when you "
            "are destroying them. Write for adult readers. War, cruelty, sex, "
            "bureaucratic evil, and the cosmic indifference of the universe are "
            "all fair game. Do not censor or sanitize -- Vonnegut never did. "
            "Show, don't tell, except when telling is funnier."
        ),
        "style": (
            "Short paragraphs. Short sentences. Sometimes a sentence is its own "
            "paragraph. So it goes. Deadpan delivery of devastating information. "
            "Dark humor threaded through tragedy without undercutting either. "
            "Characters are introduced with a brief, offhand biography that "
            "makes them immediately human. Sci-fi concepts, if present, are "
            "described matter-of-factly, as though explaining a toaster. "
            "Repetition of key phrases as structural rhythm. Asides to the "
            "reader are permitted if they feel earned. Sentimentality is allowed "
            "only when it arrives unexpectedly after something terrible. "
            "The narrator has opinions and is not hiding them."
        ),
        "scene_closing": (
            "Write this scene now. Be funny about something that isn't funny. "
            "Be kind about something that doesn't deserve it."
        ),
        "extra_anti_patterns": [
            "flowery descriptions longer than two sentences",
            "dramatic irony that explains itself",
            "characters who monologue their emotions",
            "wry smile as the only humor indicator",
        ],
    },
}


def _migrate_preset_value(val):
    """Migrate old string-only preset format to structured dict."""
    if isinstance(val, str):
        return {"style": val}
    if isinstance(val, dict):
        return val
    return {}


def _strip_code_fences(text):
    """Remove markdown code fences (```yaml / ```) wrapping LLM output."""
    import re
    stripped = text.strip()
    # Match optional language tag: ```yaml or just ```
    stripped = re.sub(r'^```[a-zA-Z]*\s*\n', '', stripped)
    stripped = re.sub(r'\n```\s*$', '', stripped)
    return stripped.strip()


def _load_style_presets():
    """Load style_presets.yaml from workspace. Seeds built-in presets on first run."""
    path = os.path.join(WORKSPACE_DIR, STYLE_PRESETS_FILE)
    if not os.path.exists(path):
        # Seed built-in presets on first run
        import copy
        seeded = {"active": None, "presets": copy.deepcopy(_BUILTIN_PRESETS)}
        _save_style_presets(seeded)
        return seeded
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
        raw = data.get("presets") or {}
        presets = {k: _migrate_preset_value(v) for k, v in raw.items()}
        # Merge in any new built-in presets the user doesn't have yet
        import copy
        changed = False
        for name, builtin in _BUILTIN_PRESETS.items():
            if name not in presets:
                presets[name] = copy.deepcopy(builtin)
                changed = True
        result = {"active": data.get("active"), "presets": presets}
        if changed:
            _save_style_presets(result)
        return result
    except (OSError, _yaml.YAMLError):
        return {"active": None, "presets": {}}


def _save_style_presets(data):
    """Save style_presets.yaml to workspace."""
    _ensure_workspace()
    path = os.path.join(WORKSPACE_DIR, STYLE_PRESETS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


@app.route("/api/style-presets", methods=["GET"])
def api_style_presets_get():
    """Return all style presets, the active preset name, and defaults."""
    from .prompt_builder import DEFAULT_SYSTEM_OPENING, DEFAULT_SCENE_CLOSING
    data = _load_style_presets()
    return jsonify({
        "ok": True,
        "active": data["active"],
        "presets": data["presets"],
        "defaults": {
            "author_instruction": DEFAULT_SYSTEM_OPENING,
            "scene_closing": DEFAULT_SCENE_CLOSING,
        },
    })


def _deploy_preset(preset_data):
    """Write a preset's fields to custom_style.txt and prompt_overrides.yaml."""
    _ensure_workspace()
    # Style -> custom_style.txt
    style = (preset_data.get("style") or "").strip()
    dest = os.path.join(WORKSPACE_DIR, FILE_ROLES["style"])
    if style:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(style)
    elif os.path.exists(dest):
        os.remove(dest)

    # Author instruction, scene closing, extra anti-patterns -> prompt_overrides.yaml
    overrides = {}
    ai = (preset_data.get("author_instruction") or "").strip()
    sc = (preset_data.get("scene_closing") or "").strip()
    eap = preset_data.get("extra_anti_patterns") or []
    if isinstance(eap, str):
        eap = [p.strip() for p in eap.split("\n") if p.strip()]
    if ai:
        overrides["system_opening"] = ai
    if sc:
        overrides["scene_closing"] = sc
    if eap:
        overrides["extra_anti_patterns"] = eap

    ov_path = os.path.join(WORKSPACE_DIR, PROMPT_OVERRIDES_FILE)
    if overrides:
        with open(ov_path, "w", encoding="utf-8") as f:
            _yaml.dump(overrides, f, allow_unicode=True, default_flow_style=False)
    elif os.path.exists(ov_path):
        os.remove(ov_path)


def _undeploy_preset():
    """Clear custom_style.txt and prompt_overrides.yaml."""
    for path in (
        os.path.join(WORKSPACE_DIR, FILE_ROLES["style"]),
        os.path.join(WORKSPACE_DIR, PROMPT_OVERRIDES_FILE),
    ):
        if os.path.exists(path):
            os.remove(path)


@app.route("/api/style-presets", methods=["POST"])
def api_style_presets_post():
    """Create or update a preset. If activate=True, also deploys it."""
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    activate = bool(body.get("activate", False))
    if not name:
        return jsonify({"ok": False, "error": "Name required"}), 400

    preset_data = {
        "author_instruction": body.get("author_instruction", ""),
        "style": body.get("style", ""),
        "scene_closing": body.get("scene_closing", ""),
        "extra_anti_patterns": body.get("extra_anti_patterns", []),
    }

    data = _load_style_presets()
    data["presets"][name] = preset_data
    if activate:
        data["active"] = name
        _deploy_preset(preset_data)
    _save_style_presets(data)
    return jsonify({"ok": True, "name": name, "active": data["active"]})


@app.route("/api/style-presets/<name>", methods=["DELETE"])
def api_style_presets_delete(name):
    """Delete a named preset. Clears deployed files if it was active."""
    data = _load_style_presets()
    if name not in data.get("presets", {}):
        return jsonify({"ok": False, "error": "Preset not found"}), 404
    del data["presets"][name]
    if data.get("active") == name:
        data["active"] = None
        _undeploy_preset()
    _save_style_presets(data)
    return jsonify({"ok": True})


@app.route("/api/style-presets/<name>/activate", methods=["POST"])
def api_style_presets_activate(name):
    """Activate a preset: deploy its fields to the appropriate files."""
    data = _load_style_presets()
    if name not in data.get("presets", {}):
        return jsonify({"ok": False, "error": "Preset not found"}), 404
    preset_data = data["presets"][name]
    data["active"] = name
    _deploy_preset(preset_data)
    _save_style_presets(data)
    return jsonify({"ok": True, "active": name})


@app.route("/api/style-presets/deactivate", methods=["POST"])
def api_style_presets_deactivate():
    """Deactivate the active preset, clearing deployed files."""
    data = _load_style_presets()
    if data.get("active"):
        data["active"] = None
        _undeploy_preset()
        _save_style_presets(data)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Prompt overrides
# ---------------------------------------------------------------------------

@app.route("/api/prompt-overrides", methods=["GET"])
def api_prompt_overrides_get():
    """Return current prompt overrides from workspace."""
    path = os.path.join(WORKSPACE_DIR, PROMPT_OVERRIDES_FILE)
    if not os.path.exists(path):
        return jsonify({"ok": True, "overrides": {}})
    try:
        with open(path, "r", encoding="utf-8") as f:
            overrides = _yaml.safe_load(f) or {}
        return jsonify({"ok": True, "overrides": overrides})
    except (OSError, _yaml.YAMLError) as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/prompt-overrides", methods=["POST"])
def api_prompt_overrides_post():
    """Save prompt overrides to workspace. Empty overrides removes the file."""
    body = request.get_json(force=True)
    overrides = body.get("overrides", {}) or {}
    _ensure_workspace()
    path = os.path.join(WORKSPACE_DIR, PROMPT_OVERRIDES_FILE)
    # Only non-empty values count
    non_empty = {k: v for k, v in overrides.items()
                 if v and (not isinstance(v, list) or v)}
    if non_empty:
        with open(path, "w", encoding="utf-8") as f:
            _yaml.dump(non_empty, f, allow_unicode=True, default_flow_style=False)
    else:
        if os.path.exists(path):
            os.remove(path)
    return jsonify({"ok": True})


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

    # Remove compiled audiobook files
    for ab_name in ["audiobook.mp3", "audiobook.m4b", "audiobook_chapters.json"]:
        ab_path = os.path.join(WORKSPACE_DIR, ab_name)
        if os.path.exists(ab_path):
            os.remove(ab_path)
            removed.append(ab_name)
    audiobook_state.reset()

    # Clear consult cache file and in-memory state
    consult_cache_path = os.path.join(WORKSPACE_DIR, "consult_cache.json")
    if os.path.exists(consult_cache_path):
        os.remove(consult_cache_path)
        removed.append("consult_cache.json")
    consult_state.reset()

    # Clear character voice assignments -- they belong to the story, not the server
    try:
        cfg = _load_web_config()
        if cfg.get("tts_voice_map"):
            cfg["tts_voice_map"] = {}
            _save_web_config(cfg)
    except Exception:
        pass

    state.reset()

    return jsonify({"ok": True, "removed": removed})


@app.route("/api/reset-generation", methods=["POST"])
def api_reset_generation():
    """Clear checkpoint and output only, preserving YAML story files and consult results.

    Use this to rerun generation from scratch without losing the AI Consult
    analysis or your uploaded story files.
    """
    if state.status == "running":
        return jsonify({"ok": False, "error": "Cannot reset while generation is running"}), 400

    _ensure_workspace()
    removed = []
    for filename in ["checkpoint.yaml", "full_story.md"]:
        path = os.path.join(WORKSPACE_DIR, filename)
        if os.path.exists(path):
            os.remove(path)
            removed.append(filename)

    # Remove compiled audiobook files
    for ab_name in ["audiobook.mp3", "audiobook.m4b", "audiobook_chapters.json"]:
        ab_path = os.path.join(WORKSPACE_DIR, ab_name)
        if os.path.exists(ab_path):
            os.remove(ab_path)
            removed.append(ab_name)
    audiobook_state.reset()

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
                "pov_character": data.get("pov_character", ""),
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
                    "gender": cdata.get("gender", ""),
                    "vibe": cdata.get("vibe", ""),
                    "heritage": cdata.get("heritage", []),
                    "has_catchphrase": bool(cdata.get("catchphrase") or cdata.get("catchphrases")),
                    "has_secret": bool(cdata.get("secret")),
                    "has_relationships": bool(cdata.get("relationships")),
                    "has_evolution": bool(cdata.get("evolution")),
                    "tts_voice": cdata.get("tts_voice", ""),
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
    state.emit("log", {"message": "Stop requested by user", "level": "warn", "time": time.time()})
    return jsonify({"ok": True, "message": "Stop requested"})


@app.route("/api/consult-stop", methods=["POST"])
def api_consult_stop():
    """Request graceful stop of the running consultation analysis.

    The worker checks the stop flag between passes.  The current pass
    will complete before stopping, so the response may take a moment
    to appear in the UI.
    """
    is_running = (
        consult_state._thread is not None
        and consult_state._thread.is_alive()
    )
    if not is_running:
        return jsonify({"ok": False, "message": "Consult is not running"})

    consult_state.request_stop()
    state.emit("log", {
        "message": "[Consult] Stop requested by user -- will pause after current pass",
        "level": "warn",
        "time": time.time(),
    })
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


@app.route("/api/ollama-unload", methods=["POST"])
def api_ollama_unload():
    """Unload the active model from Ollama VRAM by setting keep_alive=0.

    Sends a minimal generate request with keep_alive=0, which signals
    Ollama to evict the model from GPU memory after the current request
    completes. Use this to recover from a hung or stalled generation.
    """
    cfg = _load_web_config()
    host = _normalize_host(cfg.get("host", ""))
    model = (request.get_json(force=True) or {}).get("model") or cfg.get("model", "")

    if not host:
        return jsonify({"ok": False, "error": "No Ollama host configured"}), 400
    if not model:
        return jsonify({"ok": False, "error": "No model name provided"}), 400

    try:
        resp = _requests.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=15,
        )
        resp.raise_for_status()
        state.emit("log", {
            "message": f"Unloaded model '{model}' from Ollama VRAM",
            "level": "warn",
            "time": __import__('time').time(),
        })
        return jsonify({"ok": True, "message": f"Model '{model}' unloaded from Ollama"})
    except _requests.ConnectionError:
        return jsonify({"ok": False, "error": "Ollama connection refused"}), 502
    except _requests.Timeout:
        return jsonify({"ok": False, "error": "Ollama did not respond in time"}), 504
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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


_MARKER_STRIP_RE = re.compile(
    r"<!--\s*(?:/?scene:[\d.]+|chapter:\d+|speaker:[^>]*|/speaker:[^>]*)\s*-->",
    re.IGNORECASE,
)


@app.route("/api/download")
def api_download():
    """Download the output .md file with all HTML comment markers stripped."""
    output_path = os.path.join(WORKSPACE_DIR, "full_story.md")
    if not os.path.exists(output_path):
        return jsonify({"ok": False, "error": "No output file yet"}), 404

    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Strip scene/chapter/speaker markers, data-tts spans, and collapse excess blank lines
    content = _MARKER_STRIP_RE.sub("", content)
    content = re.sub(r'<span\s+data-tts="[^"]*">|</span>', "", content)
    content = re.sub(r"\n{3,}", "\n\n", content).strip() + "\n"

    return current_app.response_class(
        content,
        mimetype="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="novel_output.md"'},
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

    Body (optional):
        {"passes": ["outline", "crossref"]}  -- retry only specific passes.
        If omitted, runs all applicable passes from scratch.
    """
    # If already running, don't start a new one  --  just attach a subscriber
    if consult_state._thread is None or not consult_state._thread.is_alive():
        body = request.get_json(silent=True) or {}
        requested_passes = body.get("passes")  # None = run all
        resume = body.get("resume", False)

        # Full run clears everything; selective retry preserves completed passes;
        # resume continues from where a stopped analysis left off.
        if requested_passes is not None:
            # Clear only the passes being retried
            with consult_state._lock:
                for pname in requested_passes:
                    consult_state.passes.pop(pname, None)
                consult_state.status = "running"
                consult_state.error = None
                consult_state._stop_requested = False
        elif resume and consult_state.status in ("stopped", "error"):
            # Resume: keep completed passes intact, run only incomplete ones
            with consult_state._lock:
                consult_state.status = "running"
                consult_state.error = None
                consult_state._stop_requested = False
        else:
            consult_state.reset()

        _resume_mode = resume and requested_passes is None

        # Log the moment the analysis was requested so the user has a timestamp.
        if _resume_mode:
            _req_label = "resuming from stopped"
        elif requested_passes:
            _req_label = "retrying: " + ", ".join(requested_passes)
        else:
            _req_label = "full analysis"
        state.emit("log", {
            "message": f"[Consult] Analysis requested ({_req_label})",
            "level": "info",
            "time": time.time(),
        })

        def worker():
            from .consult import get_analysis_passes, build_pass_prompt, build_story_context
            cfg = _load_web_config()
            host = _normalize_host(cfg.get("host", ""))
            model = cfg.get("model", "gemma3:12b")
            # Consult passes can need a large context window for full YAML
            # analysis.  Default 32768; configurable via Settings tab.
            timeout = max(int(cfg.get("timeout", 900)), 1800)
            retries = int(cfg.get("retries", 3))
            consult_ctx = int(cfg.get("consult_num_ctx", 32768))

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

            # Build story-specific context so the consultant evaluates content
            # against the author's declared intent, not generic fiction norms.
            _outline_data = {}
            if files.get("outline"):
                try:
                    _outline_data = _yaml.safe_load(files["outline"]) or {}
                except _yaml.YAMLError:
                    pass
            _po_data = {}
            _po_path = os.path.join(WORKSPACE_DIR, "prompt_overrides.yaml")
            if os.path.exists(_po_path):
                try:
                    with open(_po_path, "r", encoding="utf-8") as _f:
                        _po_data = _yaml.safe_load(_f) or {}
                except (OSError, _yaml.YAMLError):
                    pass
            story_ctx = build_story_context(_outline_data, _po_data)

            all_passes = get_analysis_passes(files)

            # Determine which passes to run based on mode
            if requested_passes is not None:
                passes = [(n, c) for n, c in all_passes if n in requested_passes]
            elif _resume_mode:
                # Resume: skip passes that are already completed
                with consult_state._lock:
                    done = {n for n, p in consult_state.passes.items() if p.get("status") == "done"}
                passes = [(n, c) for n, c in all_passes if n not in done]
            else:
                passes = all_passes
            if not passes:
                consult_state.emit("consult_error", {
                    "message": (
                        "No YAML files available for analysis. "
                        "Upload your story files first."
                    )
                })
                state.emit("log", {
                    "message": "[Consult] No YAML files found -- analysis aborted.",
                    "level": "error",
                    "time": time.time(),
                })
                return

            worker_start = time.time()
            pass_labels = ", ".join(c["label"] for _, c in passes)
            state.emit("log", {
                "message": (
                    f"[Consult] Starting {len(passes)}-pass analysis "
                    f"with model {model} (ctx {consult_ctx}): {pass_labels}"
                ),
                "level": "info",
                "time": time.time(),
            })
            consult_state.emit("consult_start", {"total_passes": len(passes)})

            for idx, (pass_name, pass_cfg) in enumerate(passes, 1):
                label = pass_cfg["label"]
                emoji = pass_cfg["emoji"]

                # Check stop flag before starting this pass
                if consult_state._stop_requested:
                    state.emit("log", {
                        "message": f"[Consult] Stop acknowledged -- {len(passes) - idx + 1} pass(es) skipped",
                        "level": "warn",
                        "time": time.time(),
                    })
                    break

                consult_state.emit("pass_start", {
                    "pass": pass_name,
                    "label": label,
                    "emoji": emoji,
                    "index": idx,
                    "total": len(passes),
                })
                state.emit("model_active", {"model": "consult", "name": model})
                state.emit("log", {
                    "message": f"[Consult] Pass {idx}/{len(passes)}: {label} -- started",
                    "level": "info",
                    "time": time.time(),
                })

                system_prompt, user_prompt = build_pass_prompt(pass_name, files, story_context=story_ctx)

                url = f"{host}/api/generate"
                payload = {
                    "model": model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": True,
                    "options": {
                        "num_ctx": consult_ctx,
                        "temperature": 0.4,
                        "top_p": 0.9,
                    },
                }

                t_start = time.time()
                done_data = None
                backoff = [60, 180, 300, 600, 900]

                for attempt in range(1, retries + 1):
                    try:
                        resp = _requests.post(
                            url, json=payload,
                            timeout=(30, None),
                            stream=True
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

                        # Success -- break out of retry loop
                        break

                    except Exception as e:
                        if attempt < retries:
                            delay = backoff[min(attempt - 1, len(backoff) - 1)]
                            consult_state.emit("pass_chunk", {
                                "pass": pass_name,
                                "chunk": (
                                    f"\n\n[Retry {attempt}/{retries}] "
                                    f"{e} -- retrying in {delay}s...\n\n"
                                ),
                            })
                            state.emit("log", {
                                "message": (
                                    f"[Consult {label}] Retry {attempt}/{retries}: "
                                    f"{e}. Waiting {delay}s..."
                                ),
                                "level": "warn",
                            })
                            time.sleep(delay)
                        else:
                            state.emit("model_active", {"model": "idle", "name": ""})
                            consult_state.emit("pass_error", {
                                "pass": pass_name,
                                "message": str(e),
                            })
                            state.emit("log", {
                                "message": (
                                    f"[Consult] Pass {idx}/{len(passes)}: {label} "
                                    f"-- failed after {retries} attempts: {e}"
                                ),
                                "level": "error",
                                "time": time.time(),
                            })
                            done_data = None
                            break

                if done_data is None:
                    # Pass failed after all retries -- already emitted pass_error
                    state.emit("model_active", {"model": "idle", "name": ""})
                    continue

                elapsed = time.time() - t_start
                stats = {"elapsed": round(elapsed, 1)}
                eval_count = 0
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

                _log_parts = [f"[Consult] Pass {idx}/{len(passes)}: {label} -- done in {round(elapsed, 1)}s"]
                if eval_count:
                    _log_parts.append(f"{eval_count} tokens")
                if stats.get("toks_per_s"):
                    _log_parts.append(f"{stats['toks_per_s']} tok/s")
                state.emit("log", {
                    "message": " -- ".join(_log_parts),
                    "level": "info",
                    "time": time.time(),
                })

            # If loop exited due to stop request, emit stopped rather than done
            if consult_state._stop_requested:
                consult_state.emit("consult_stopped", {})
                state.emit("log", {
                    "message": "[Consult] Analysis paused -- Resume Analysis to continue remaining passes",
                    "level": "warn",
                    "time": time.time(),
                })
            else:
                total_elapsed = round(time.time() - worker_start, 1)
                consult_state.emit("consult_done", {})
                state.emit("log", {
                    "message": f"[Consult] Analysis complete -- {total_elapsed}s total",
                    "level": "info",
                    "time": time.time(),
                })

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
            if snap["status"] == "stopped":
                yield f"data: {json.dumps({'type': 'consult_stopped'})}\n\n"
                return

            # Stream live events from background thread
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                    if event["type"] in ("consult_done", "consult_error", "consult_stopped"):
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
    if consult_state.is_fix_running():
        return jsonify({"ok": False, "error": "Fix generation still running"}), 400
    consult_state.reset()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Story Concept Builder (AI-assisted YAML generation from ideas)
# ---------------------------------------------------------------------------

_concept_state = {"thread": None, "text": "", "status": "idle", "error": None}
_concept_lock = threading.Lock()
_concept_subs = []


@app.route("/api/concept", methods=["POST"])
def api_concept():
    """Generate story YAML files from a user's story idea via SSE."""
    from .concept import build_concept_prompt

    data = request.get_json(silent=True) or {}
    idea = (data.get("idea") or "").strip()
    if not idea:
        return jsonify({"ok": False, "error": "No story idea provided"}), 400

    with _concept_lock:
        t = _concept_state.get("thread")
        if t is not None and t.is_alive():
            pass  # Allow reconnection to existing run
        else:
            _concept_state["text"] = ""
            _concept_state["status"] = "running"
            _concept_state["error"] = None

            cfg = _load_web_config()
            host = _normalize_host(cfg.get("host", ""))
            model = cfg.get("model", "gemma3:12b")
            consult_ctx = int(cfg.get("consult_num_ctx", 32768))

            if not host:
                return jsonify({"ok": False, "error": "No Ollama host configured"}), 400

            system_prompt, user_prompt = build_concept_prompt(idea)

            def worker():
                url = f"{host}/api/generate"
                payload = {
                    "model": model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": True,
                    "options": {
                        "num_ctx": consult_ctx,
                        "temperature": 0.7,
                        "top_p": 0.9,
                    },
                }
                state.emit("model_active", {"model": "consult", "name": model})
                state.emit("log", {
                    "message": f"[Concept] Building story concept with {model}",
                    "level": "info",
                    "time": time.time(),
                })
                try:
                    resp = _requests.post(
                        url, json=payload,
                        timeout=(30, None),
                        stream=True,
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
                            with _concept_lock:
                                _concept_state["text"] += token
                            for q in list(_concept_subs):
                                try:
                                    q.put_nowait({"type": "chunk", "text": token})
                                except Exception:
                                    pass
                        if chunk.get("done"):
                            break
                    with _concept_lock:
                        _concept_state["status"] = "done"
                    for q in list(_concept_subs):
                        try:
                            q.put_nowait({"type": "done"})
                        except Exception:
                            pass
                    state.emit("log", {
                        "message": "[Concept] Story concept generation complete",
                        "level": "info",
                        "time": time.time(),
                    })
                except Exception as e:
                    with _concept_lock:
                        _concept_state["status"] = "error"
                        _concept_state["error"] = str(e)
                    for q in list(_concept_subs):
                        try:
                            q.put_nowait({"type": "error", "message": str(e)})
                        except Exception:
                            pass
                    state.emit("log", {
                        "message": f"[Concept] Error: {e}",
                        "level": "error",
                        "time": time.time(),
                    })
                finally:
                    state.emit("model_active", {"model": "idle", "name": ""})

            t = threading.Thread(target=worker, daemon=True, name="concept-builder")
            t.start()
            _concept_state["thread"] = t

    # Subscribe to events
    q = queue.Queue()
    _concept_subs.append(q)

    def stream():
        try:
            with _concept_lock:
                if _concept_state["text"]:
                    yield f"data: {json.dumps({'type': 'snapshot', 'text': _concept_state['text']})}\n\n"
                if _concept_state["status"] == "done":
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return
                if _concept_state["status"] == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': _concept_state.get('error', '')})}\n\n"
                    return

            while True:
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                    if ev["type"] in ("done", "error"):
                        break
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except GeneratorExit:
            pass
        finally:
            if q in _concept_subs:
                _concept_subs.remove(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/concept/result")
def api_concept_result():
    """Return the current concept builder result snapshot."""
    with _concept_lock:
        return jsonify({
            "status": _concept_state["status"],
            "text": _concept_state["text"],
            "error": _concept_state.get("error"),
        })


@app.route("/api/concept/save", methods=["POST"])
def api_concept_save():
    """Save a generated YAML file to the workspace.

    Expects JSON: {"role": "outline|characters|locations", "content": "..."}
    """
    _ensure_workspace()

    data = request.get_json(silent=True) or {}
    role = data.get("role", "").strip()
    content = data.get("content", "")
    if not role or not content.strip():
        return jsonify({"ok": False, "error": "Missing role or content"}), 400

    if role not in FILE_ROLES:
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400

    # Validate YAML before saving
    import yaml
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        return jsonify({"ok": False, "error": f"Invalid YAML: {e}"}), 400

    fname = FILE_ROLES[role]
    path = os.path.join(WORKSPACE_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    state.emit("log", {
        "message": f"[Concept] Saved {fname}",
        "level": "info",
        "time": time.time(),
    })
    return jsonify({"ok": True, "filename": fname})


# ---------------------------------------------------------------------------
# Voice Casting (AI-assisted TTS voice recommendations)
# ---------------------------------------------------------------------------

_voice_cast_state = {"thread": None, "text": "", "status": "idle", "error": None}
_voice_cast_lock = threading.Lock()
_voice_cast_subs = []


@app.route("/api/voice-cast", methods=["POST"])
def api_voice_cast():
    """Run AI voice casting and stream recommendations as SSE.

    Sends character data + voice catalog to the LLM and streams back
    per-character voice recommendations with explanations.
    """
    from .consult import build_voice_casting_prompt
    from .voice_catalog import get_catalog_summary

    with _voice_cast_lock:
        t = _voice_cast_state.get("thread")
        if t is not None and t.is_alive():
            pass  # Allow reconnection -- just subscribe to existing run
        else:
            # Start new voice casting run
            _voice_cast_state["text"] = ""
            _voice_cast_state["status"] = "running"
            _voice_cast_state["error"] = None

            cfg = _load_web_config()
            host = _normalize_host(cfg.get("host", ""))
            model = cfg.get("summary_model", "gemma3:4b")
            cast_ctx = int(cfg.get("consult_num_ctx", cfg.get("generation_num_ctx", 8192)))
            timeout_s = max(int(cfg.get("timeout", 900)), 1800)

            if not host:
                return jsonify({"ok": False, "error": "No Ollama host configured"}), 400

            # Load characters YAML
            char_path = os.path.join(WORKSPACE_DIR, FILE_ROLES.get("characters", "characters.yaml"))
            if not os.path.exists(char_path):
                return jsonify({"ok": False, "error": "No characters.yaml found"}), 400
            with open(char_path, "r", encoding="utf-8") as f:
                char_raw = f.read()

            # Strip existing tts_voice assignments so the model does
            # genuine casting instead of echoing the author's old picks.
            try:
                char_parsed = _yaml.safe_load(char_raw) or {}
                chars = char_parsed.get("characters", char_parsed)
                if isinstance(chars, dict):
                    for cdata in chars.values():
                        if isinstance(cdata, dict):
                            cdata.pop("tts_voice", None)
                    char_yaml = _yaml.dump(
                        {"characters": chars} if "characters" in char_parsed else chars,
                        default_flow_style=False, allow_unicode=True,
                    )
                else:
                    char_yaml = char_raw
            except Exception:
                char_yaml = char_raw

            catalog_text = get_catalog_summary()

            # Load outline for POV/narrator context (best-effort)
            outline_context = {}
            outline_path = os.path.join(WORKSPACE_DIR, FILE_ROLES.get("outline", "story_outline.yaml"))
            if os.path.exists(outline_path):
                try:
                    with open(outline_path, "r", encoding="utf-8") as f:
                        outline_data = _yaml.safe_load(f.read()) or {}
                    outline_context["pov_character"] = outline_data.get("pov_character", "")
                    arc = outline_data.get("overall_arc") or {}
                    outline_context["pov"] = arc.get("pov", "")
                except Exception:
                    pass

            pov_log = outline_context.get("pov_character", "")
            if pov_log:
                state.emit("log", {
                    "message": f"[Voice Cast] First-person POV detected: narrator = {pov_log}",
                    "level": "info",
                    "time": time.time(),
                })
            else:
                state.emit("log", {
                    "message": "[Voice Cast] No pov_character set -- narrator will be cast independently",
                    "level": "info",
                    "time": time.time(),
                })

            # Get available voices from TTS server (best-effort)
            available = []
            tts_host = _normalize_tts_host(cfg.get("tts_host", ""))
            tts_model = cfg.get("tts_model", "")
            if tts_host:
                eps = []
                if tts_model:
                    eps.append(f"/v1/audio/voices?model={tts_model}")
                eps.extend(["/v1/audio/voices", "/v1/voices"])
                for ep in eps:
                    try:
                        resp = _requests.get(f"{tts_host}{ep}", timeout=5)
                        if not resp.ok:
                            continue
                        data = resp.json()
                        raw = (
                            data if isinstance(data, list)
                            else data.get("voices", data.get("data", []))
                        )
                        if isinstance(raw, list):
                            for v in raw:
                                if isinstance(v, str):
                                    available.append(v)
                                elif isinstance(v, dict):
                                    available.append(
                                        v.get("id") or v.get("name")
                                        or v.get("voice_id") or str(v)
                                    )
                            if available:
                                break
                    except Exception:
                        continue

            system_prompt, user_prompt = build_voice_casting_prompt(
                char_yaml, catalog_text, sorted(available), outline_context
            )

            pov_name = outline_context.get("pov_character", "")
            pov_desc = outline_context.get("pov", "")
            state.emit("log", {
                "message": (
                    f"[Voice Cast] Outline context: pov_character={pov_name!r}, "
                    f"pov={pov_desc!r}"
                ),
                "level": "info",
                "time": time.time(),
            })

            def worker():
                url = f"{host}/api/generate"
                payload = {
                    "model": model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": True,
                    "options": {
                        "num_ctx": cast_ctx,
                        "temperature": 0.4,
                        "top_p": 0.9,
                    },
                }
                state.emit("model_active", {"model": "consult", "name": model})
                state.emit("log", {
                    "message": f"[Voice Cast] Starting voice casting with {model}",
                    "level": "info",
                    "time": time.time(),
                })
                try:
                    resp = _requests.post(
                        url, json=payload,
                        timeout=(30, None),
                        stream=True,
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
                            with _voice_cast_lock:
                                _voice_cast_state["text"] += token
                            for q in list(_voice_cast_subs):
                                try:
                                    q.put_nowait({"type": "chunk", "text": token})
                                except Exception:
                                    pass
                        if chunk.get("done"):
                            break
                    with _voice_cast_lock:
                        _voice_cast_state["status"] = "done"
                    for q in list(_voice_cast_subs):
                        try:
                            q.put_nowait({"type": "done"})
                        except Exception:
                            pass
                    state.emit("log", {
                        "message": "[Voice Cast] Voice casting complete",
                        "level": "info",
                        "time": time.time(),
                    })
                except Exception as e:
                    with _voice_cast_lock:
                        _voice_cast_state["status"] = "error"
                        _voice_cast_state["error"] = str(e)
                    for q in list(_voice_cast_subs):
                        try:
                            q.put_nowait({"type": "error", "message": str(e)})
                        except Exception:
                            pass
                    state.emit("log", {
                        "message": f"[Voice Cast] Error: {e}",
                        "level": "error",
                        "time": time.time(),
                    })
                finally:
                    state.emit("model_active", {"model": "idle", "name": ""})

            t = threading.Thread(target=worker, daemon=True, name="voice-cast")
            t.start()
            _voice_cast_state["thread"] = t

    q = queue.Queue()

    def stream():
        try:
            # Subscribe and snapshot atomically so no token can land in
            # both the snapshot and the queue (which would duplicate text
            # at the tail of the streamed output).
            with _voice_cast_lock:
                _voice_cast_subs.append(q)
                snapshot_text = _voice_cast_state["text"]
                snapshot_status = _voice_cast_state["status"]
                snapshot_error = _voice_cast_state.get("error", "")
            # Yield outside the lock so the worker is not blocked.
            if snapshot_text:
                yield f"data: {json.dumps({'type': 'snapshot', 'text': snapshot_text})}\n\n"
            if snapshot_status == "done":
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            if snapshot_status == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': snapshot_error})}\n\n"
                return

            while True:
                try:
                    ev = q.get(timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                    if ev["type"] in ("done", "error"):
                        break
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except GeneratorExit:
            pass
        finally:
            if q in _voice_cast_subs:
                _voice_cast_subs.remove(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/voice-cast/result")
def api_voice_cast_result():
    """Return the current voice casting result snapshot."""
    with _voice_cast_lock:
        return jsonify({
            "status": _voice_cast_state["status"],
            "text": _voice_cast_state["text"],
            "error": _voice_cast_state.get("error"),
        })


@app.route("/api/voice-cast/correct", methods=["POST"])
def api_voice_cast_correct():
    """Request AI correction for specific voice casting violations.

    Sends a concise, targeted prompt to the summary model describing each
    violation and asks only for corrected assignments.

    Body:
        {"violations": [{"char_id": str, "char_name": str,
                          "assigned_voice": str, "reason": str}]}
    Returns:
        {"ok": True, "assignments": {char_id: voice_id}, "raw": str}
    """
    from .consult import build_voice_correction_prompt
    from .voice_catalog import get_catalog_summary

    data = request.get_json(force=True) or {}
    violations = data.get("violations", [])
    if not violations:
        return jsonify({"ok": True, "assignments": {}, "raw": ""})

    cfg = _load_web_config()
    host = _normalize_host(cfg.get("host", ""))
    if not host:
        return jsonify({"ok": False, "error": "No Ollama host configured"}), 400

    model = cfg.get("summary_model", "gemma3:4b")
    cast_ctx = int(cfg.get("consult_num_ctx", cfg.get("generation_num_ctx", 8192)))
    catalog_text = get_catalog_summary()
    system_p, user_p = build_voice_correction_prompt(violations, catalog_text)

    payload = {
        "model": model,
        "system": system_p,
        "prompt": user_p,
        "stream": False,
        "options": {"num_ctx": cast_ctx, "temperature": 0.2},
    }

    try:
        resp = _requests.post(
            f"{host}/api/generate", json=payload, timeout=(30, 120)
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    # Parse the YAML assignments block from the response
    assignments = {}
    yaml_match = re.search(r"```yaml\s*\n([\s\S]*?)```", raw)
    if yaml_match:
        try:
            block = _yaml.safe_load(yaml_match.group(1)) or {}
            chars = block.get("characters", block)
            if isinstance(chars, dict):
                for cid, cdata in chars.items():
                    if isinstance(cdata, dict) and cdata.get("tts_voice"):
                        assignments[str(cid)] = str(cdata["tts_voice"])
                    elif isinstance(cdata, str):
                        assignments[str(cid)] = cdata
        except Exception:
            pass

    state.emit("log", {
        "message": f"[Voice Cast] Correction: fixed {len(assignments)} assignment(s)",
        "level": "info",
        "time": time.time(),
    })
    return jsonify({"ok": True, "assignments": assignments, "raw": raw})


@app.route("/api/voice-catalog")
def api_voice_catalog():
    """Return the full voice catalog as a JSON dict."""
    from .voice_catalog import KOKORO_VOICES
    return jsonify({"ok": True, "voices": KOKORO_VOICES})


@app.route("/api/consult-apply", methods=["POST"])
def api_consult_apply():
    """Start background fix generation for one or more analysis passes.

    Runs fix generation in a background thread so it persists across
    browser refreshes and is visible from any device.  Multiple roles
    are processed sequentially to avoid overloading the LLM.

    Body:
        {"role": "characters"}  -- single role
        {"roles": ["characters", "outline"]}  -- multiple roles (sequential)
    """
    data = request.get_json(force=True)

    # Accept either a single role or a list of roles
    roles = data.get("roles", [])
    if not roles:
        single = data.get("role", "")
        if single:
            roles = [single]

    valid_roles = ("outline", "characters", "locations", "crossref")
    for r in roles:
        if r not in valid_roles:
            return jsonify({"ok": False, "error": f"Unknown role: {r}"}), 400

    # Validate all requested passes are completed
    snap = consult_state.snapshot()
    for r in roles:
        pass_data = snap["passes"].get(r)
        if not pass_data or pass_data.get("status") != "done":
            return jsonify({"ok": False, "error": f"Pass '{r}' not completed"}), 400

    # If fix generation is already running, reject
    if consult_state.is_fix_running():
        return jsonify({"ok": False, "error": "Fix generation already in progress"}), 409

    # Mark all as queued
    for r in roles:
        consult_state.emit("fix_queued", {"role": r})

    def fix_worker(fix_roles):
        from .consult import build_fix_prompt, build_crossref_fix_prompt, build_story_context
        cfg = _load_web_config()
        host = _normalize_host(cfg.get("host", ""))
        model = cfg.get("model", "gemma3:12b")
        consult_ctx = int(cfg.get("consult_num_ctx", 32768))
        retries = int(cfg.get("retries", 3))

        if not host:
            for r in fix_roles:
                consult_state.emit("fix_error", {
                    "role": r,
                    "message": "No Ollama host configured",
                })
            consult_state.emit("all_fixes_done", {})
            return

        # Load story-specific context once for all fix passes.
        _outline_path = os.path.join(WORKSPACE_DIR, FILE_ROLES.get("outline", "story_outline.yaml"))
        _outline_data = {}
        if os.path.exists(_outline_path):
            try:
                with open(_outline_path, "r", encoding="utf-8") as _f:
                    _outline_data = _yaml.safe_load(_f) or {}
            except (OSError, _yaml.YAMLError):
                pass
        _po_data = {}
        _po_path = os.path.join(WORKSPACE_DIR, "prompt_overrides.yaml")
        if os.path.exists(_po_path):
            try:
                with open(_po_path, "r", encoding="utf-8") as _f:
                    _po_data = _yaml.safe_load(_f) or {}
            except (OSError, _yaml.YAMLError):
                pass
        story_ctx = build_story_context(_outline_data, _po_data)

        total = len(fix_roles)
        for idx, role in enumerate(fix_roles, 1):
            consult_state.emit("fix_start", {"role": role, "index": idx, "total": total})
            state.emit("model_active", {"model": "consult", "name": f"{model} (fix: {role})"})
            fix_start_time = time.time()
            state.emit("log", {
                "message": f"[Consult] Generating fix {idx}/{total}: {role}...",
                "level": "info",
                "time": time.time(),
            })

            snap_inner = consult_state.snapshot()
            analysis_text = snap_inner["passes"].get(role, {}).get("text", "")

            # Load YAML files from workspace
            files = {}
            roles_needed = [role] if role != "crossref" else ["outline", "characters", "locations"]
            for rr in roles_needed:
                yaml_path = os.path.join(WORKSPACE_DIR, FILE_ROLES.get(rr, ""))
                if os.path.exists(yaml_path):
                    try:
                        with open(yaml_path, "r", encoding="utf-8") as f:
                            files[rr] = f.read()
                    except OSError:
                        pass

            if role != "crossref" and role not in files:
                consult_state.emit("fix_error", {"role": role, "message": "YAML file not found"})
                state.emit("model_active", {"model": "idle", "name": ""})
                continue

            if role == "crossref":
                system_prompt, user_prompt = build_crossref_fix_prompt(files, analysis_text, story_context=story_ctx)
            else:
                system_prompt, user_prompt = build_fix_prompt(role, files[role], analysis_text, story_context=story_ctx)

            url = f"{host}/api/generate"
            payload = {
                "model": model,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": True,
                "options": {
                    "num_ctx": consult_ctx,
                    "temperature": 0.3,
                },
            }

            accumulated = ""
            backoff = [60, 180, 300, 600, 900]
            success = False

            for attempt in range(1, retries + 1):
                try:
                    resp = _requests.post(url, json=payload, timeout=(30, None), stream=True)
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
                            accumulated += token
                            consult_state.emit("fix_chunk", {"role": role, "chunk": token})
                        if chunk.get("done"):
                            success = True
                            break

                    if not success:
                        # Stream ended without done flag -- treat as success
                        success = True
                    break

                except Exception as e:
                    if attempt < retries:
                        delay = backoff[min(attempt - 1, len(backoff) - 1)]
                        note = f"\n[Retry {attempt}/{retries}] {e} -- retrying in {delay}s...\n"
                        accumulated += note
                        consult_state.emit("fix_chunk", {"role": role, "chunk": note})
                        state.emit("log", {
                            "message": f"[Consult fix {role}] Retry {attempt}/{retries}: {e}. Waiting {delay}s...",
                            "level": "warn",
                            "time": time.time(),
                        })
                        time.sleep(delay)
                    else:
                        consult_state.emit("fix_error", {"role": role, "message": str(e)})
                        state.emit("log", {
                            "message": f"[Consult fix {role}] Failed: {e}",
                            "level": "error",
                            "time": time.time(),
                        })
                        state.emit("model_active", {"model": "idle", "name": ""})
                        success = False
                        break

            if success:
                consult_state.emit("fix_done", {"role": role})
                _fix_elapsed = round(time.time() - fix_start_time, 1)
                state.emit("log", {
                    "message": f"[Consult] Fix generated for {role} in {_fix_elapsed}s ({len(accumulated)} chars)",
                    "level": "info",
                    "time": time.time(),
                })

            state.emit("model_active", {"model": "idle", "name": ""})

        consult_state.emit("all_fixes_done", {})
        state.emit("log", {
            "message": f"[Consult] All fix generation complete ({len(fix_roles)} role(s))",
            "level": "info",
            "time": time.time(),
        })

    with consult_state._lock:
        consult_state._fix_queue_roles = list(roles)

    t = threading.Thread(target=fix_worker, args=(roles,), daemon=True, name="novel-consult-fix")
    t.start()
    consult_state._fix_thread = t

    return jsonify({"ok": True, "roles": roles, "message": f"Fix generation started for {len(roles)} pass(es)"})


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

    # Strip markdown code fences the LLM may have wrapped the YAML in
    content = _strip_code_fences(content)

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


@app.route("/api/consult-mark-applied", methods=["POST"])
def api_consult_mark_applied():
    """Mark one or more fix roles as applied so the UI stops prompting to apply.

    Called by the client after applyAllFixes() successfully saves each file.
    Sets fix status to 'applied' so _refreshGenAllBtn no longer shows the button.
    """
    data = request.get_json(force=True)
    roles = data.get("roles", [])
    valid = ("outline", "characters", "locations", "crossref")
    for role in roles:
        if role in valid:
            existing = consult_state.get_fix(role)
            consult_state.set_fix(role, existing, status="applied")
    return jsonify({"ok": True})


@app.route("/api/consult-save-fix", methods=["POST"])
def api_consult_save_fix():
    """Persist the user-edited fix content back to consult cache.

    This is called when the user edits the proposed fix textarea so
    the edits survive page refreshes.
    """
    data = request.get_json(force=True)
    role = data.get("role", "")
    content = data.get("content", "")

    if role not in ("outline", "characters", "locations", "crossref"):
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400

    consult_state.set_fix(role, content)
    return jsonify({"ok": True})


@app.route("/api/consult-download-fix/<role>")
def api_consult_download_fix(role):
    """Download the proposed fix YAML as a file."""
    content = consult_state.get_fix(role)
    if not content:
        return jsonify({"ok": False, "error": "No fix available"}), 404

    filename = FILE_ROLES.get(role, f"{role}_fix.yaml")
    return Response(
        content,
        mimetype="text/yaml",
        headers={
            "Content-Disposition": f"attachment; filename=\"fixed_{filename}\"",
        },
    )


@app.route("/api/consult-original/<role>")
def api_consult_original(role):
    """Return the original YAML content for diff comparison."""
    if role not in FILE_ROLES:
        return jsonify({"ok": False, "error": f"Unknown role: {role}"}), 400

    yaml_path = os.path.join(WORKSPACE_DIR, FILE_ROLES[role])
    if not os.path.exists(yaml_path):
        return jsonify({"ok": False, "error": "File not found"}), 404

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"ok": True, "content": content, "filename": FILE_ROLES[role]})
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
    must already exist  --  this endpoint is for editing, not initialisation.
    """
    checkpoint_path = os.path.join(WORKSPACE_DIR, "checkpoint.yaml")
    if not os.path.exists(checkpoint_path):
        return jsonify({"ok": False, "error": "No checkpoint found  --  start generation first"}), 404

    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            cp = _yaml.safe_load(f) or {}
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not read checkpoint: {e}"}), 500

    data = request.get_json(force=True)
    new_memory = data.get("story_memory")
    if not isinstance(new_memory, dict):
        return jsonify({"ok": False, "error": "story_memory must be a dict"}), 400

    # Merge  --  replace only the sections provided
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
# TTS (Text-to-Speech) routes -- Speaches / Kokoro / Piper
# ---------------------------------------------------------------------------

@app.route("/api/tts/health")
def api_tts_health():
    """Check TTS server connectivity and list available models."""
    host = request.args.get("host", "").strip()
    if not host:
        cfg = _load_web_config()
        host = cfg.get("tts_host", "")
    host = _normalize_tts_host(host)
    if not host:
        return jsonify({"ok": False, "error": "No TTS host configured"})

    try:
        resp = _requests.get(f"{host}/v1/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [
            m.get("id", "") for m in data.get("data", [])
            if m.get("id")
        ]
        return jsonify({"ok": True, "models": models})
    except _requests.ConnectionError:
        return jsonify({"ok": False, "error": "Connection refused"})
    except _requests.Timeout:
        return jsonify({"ok": False, "error": "Timeout"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/tts/voices")
def api_tts_voices():
    """Discover available voices for a TTS model.

    Tries several common endpoints (Speaches / OpenAI-compatible),
    returns whatever voice list the server exposes.  Falls back
    gracefully so the UI can offer a text input instead.

    Returns enriched voice data with descriptions from the voice
    catalog when available.
    """
    from .voice_catalog import enrich_voice_list

    host = request.args.get("host", "").strip()
    model = request.args.get("model", "").strip()
    if not host:
        cfg = _load_web_config()
        host = cfg.get("tts_host", "")
        if not model:
            model = cfg.get("tts_model", "")
    host = _normalize_tts_host(host)
    if not host:
        return jsonify({"ok": False, "voices": [], "error": "No TTS host"})

    endpoints = []
    if model:
        endpoints.append(f"/v1/audio/voices?model={model}")
    endpoints.extend(["/v1/audio/voices", "/v1/voices"])

    for ep in endpoints:
        try:
            resp = _requests.get(f"{host}{ep}", timeout=5)
            if not resp.ok:
                continue
            data = resp.json()
            raw = (
                data if isinstance(data, list)
                else data.get("voices", data.get("data", []))
            )
            if not isinstance(raw, list):
                continue
            voices = []
            for v in raw:
                if isinstance(v, str):
                    voices.append(v)
                elif isinstance(v, dict):
                    vid = (
                        v.get("id")
                        or v.get("name")
                        or v.get("voice_id")
                        or str(v)
                    )
                    voices.append(vid)
            if voices:
                enriched = enrich_voice_list(sorted(voices))
                return jsonify({"ok": True, "voices": enriched})
        except Exception:
            continue

    return jsonify({
        "ok": False,
        "voices": [],
        "error": "Voice listing not available -- type voice names manually",
    })


@app.route("/api/tts/speak", methods=["POST"])
def api_tts_speak():
    """Generate speech audio from text via the TTS server.

    Proxies the request to the Speaches-compatible /v1/audio/speech
    endpoint and streams the MP3 response back to the browser.
    """
    cfg = _load_web_config()
    data = request.get_json(force=True)

    host = _normalize_tts_host(data.get("host") or cfg.get("tts_host", ""))
    model = data.get("model") or cfg.get("tts_model", "")
    voice = data.get("voice") or cfg.get("tts_narrator_voice", "")
    text = data.get("text", "").strip()
    speed = float(data.get("speed", 1.0))

    if not host:
        return jsonify({"ok": False, "error": "No TTS host configured"}), 400
    if not model:
        return jsonify({"ok": False, "error": "No TTS model selected"}), 400
    if not voice:
        return jsonify({"ok": False, "error": "No voice selected"}), 400
    if not text:
        return jsonify({"ok": False, "error": "No text provided"}), 400

    text = _preprocess_tts_text(text)

    try:
        resp = _requests.post(
            f"{host}/v1/audio/speech",
            json={
                "model": model,
                "input": text,
                "voice": voice,
                "speed": speed,
                "response_format": "mp3",
            },
            timeout=120,
            stream=True,
        )
        resp.raise_for_status()
        return Response(
            resp.iter_content(chunk_size=4096),
            mimetype="audio/mpeg",
            headers={"Content-Type": "audio/mpeg"},
        )
    except _requests.ConnectionError:
        return jsonify({"ok": False, "error": "TTS server connection refused"}), 502
    except _requests.Timeout:
        return jsonify({"ok": False, "error": "TTS request timed out"}), 504
    except _requests.HTTPError as e:
        return jsonify({"ok": False, "error": f"TTS server error: {e}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/tts/segments", methods=["POST"])
def api_tts_segments():
    """Segment scene text into narration/dialogue blocks.

    Parses inline <span data-tts="Name"> tags produced by the generation
    model.  Falls back to treating the entire text as narration if no
    spans are found.

    Returns a list of paragraph-level segments, each attributed to
    a character (for dialogue) or left as narration.
    """
    from .tts import parse_span_segments

    data = request.get_json(force=True)
    text = data.get("text", "")

    segments = parse_span_segments(text)
    if not segments:
        segments = [{"type": "narration", "text": text, "character": None}]

    return jsonify({"ok": True, "segments": segments})


# ---------------------------------------------------------------------------
# Server-side audiobook compilation
# ---------------------------------------------------------------------------

def _parse_chapters_for_audio(text):
    """Parse full_story.md into chapters with scene text.

    Returns: [{title: str, scenes: [str, ...]}, ...]
    """
    chapter_re = re.compile(r"<!--\s*chapter:\d+\s*-->")
    scene_re = re.compile(
        r"<!--\s*scene:[\d.]+\s*-->([\s\S]*?)<!--\s*/scene:[\d.]+\s*-->"
    )
    heading_re = re.compile(r"^#+\s+(.+)", re.MULTILINE)

    blocks = chapter_re.split(text)
    chapters = []
    for block in blocks:
        if not block.strip():
            continue
        title_m = heading_re.search(block)
        title = title_m.group(1).strip() if title_m else "Chapter"
        scene_matches = scene_re.findall(block)
        scenes = [s.strip() for s in scene_matches if s.strip()]
        if not scenes:
            fallback = heading_re.sub("", block).strip()
            if fallback:
                scenes.append(fallback)
        if scenes:
            chapters.append({"title": title, "scenes": scenes})
    return chapters


def _compile_audiobook_worker(fmt, cfg, story_title, chapters, voice_map,
                              narrator_voice, pov_character, tts_host,
                              tts_model, tts_speed):
    """Background worker for server-side audiobook compilation."""
    from .tts import parse_span_segments
    import json as _json_mod

    mp3_path = os.path.join(WORKSPACE_DIR, "audiobook.mp3")
    chapters_json_path = os.path.join(WORKSPACE_DIR, "audiobook_chapters.json")

    try:
        # If M4B requested and MP3 + chapter metadata already cached, skip synthesis
        if fmt == "m4b" and os.path.exists(mp3_path) and os.path.exists(chapters_json_path):
            try:
                with open(chapters_json_path, "r", encoding="utf-8") as f:
                    cached_chapters = _json_mod.load(f)
                state.emit("log", {
                    "message": "Audiobook: using cached MP3, skipping synthesis",
                    "level": "info",
                })
                _convert_mp3_to_m4b(mp3_path, cached_chapters, story_title or "Audiobook")
                audiobook_state.status = "completed"
                audiobook_state.phase = ""
                state.emit("log", {"message": "Audiobook: M4B ready for download", "level": "info"})
                state.emit("audiobook_progress", audiobook_state.snapshot())
                return
            except Exception as e:
                state.emit("log", {
                    "message": f"Audiobook: cached chapter data invalid ({e}), re-synthesizing",
                    "level": "warn",
                })

        # Build segment list
        all_segments = []
        if story_title:
            all_segments.append({
                "seg": {"type": "title", "text": story_title + " . . .", "character": None},
                "chapter_idx": 0,
            })

        for ci, chapter in enumerate(chapters):
            if chapter["title"]:
                all_segments.append({
                    "seg": {"type": "title", "text": chapter["title"] + " . . .", "character": None},
                    "chapter_idx": ci,
                })
            for scene_text in chapter["scenes"]:
                segs = parse_span_segments(scene_text)
                if not segs:
                    segs = [{"type": "narration", "text": scene_text, "character": None}]
                for seg in segs:
                    all_segments.append({"seg": seg, "chapter_idx": ci})

        total = len(all_segments)
        audiobook_state.total = total
        audiobook_state.phase = "synthesizing"
        state.emit("log", {
            "message": f"Audiobook: synthesizing {total} segments as {fmt.upper()}",
            "level": "info",
        })
        state.emit("audiobook_progress", audiobook_state.snapshot())

        # Resolve voice for each segment
        def get_voice(seg):
            if seg.get("character"):
                if pov_character and seg["character"] == pov_character:
                    return narrator_voice
                if seg["character"] in voice_map:
                    return voice_map[seg["character"]]
            return narrator_voice

        # Synthesize each segment and write MP3 bytes to disk
        chapter_byte_offsets = [None] * len(chapters)
        cumulative_bytes = 0

        with open(mp3_path, "wb") as mp3_file:
            for i, entry in enumerate(all_segments):
                if audiobook_state._cancel:
                    audiobook_state.status = "cancelled"
                    state.emit("log", {"message": "Audiobook compilation cancelled", "level": "warn"})
                    state.emit("audiobook_progress", audiobook_state.snapshot())
                    return

                seg = entry["seg"]
                ci = entry["chapter_idx"]
                if chapter_byte_offsets[ci] is None:
                    chapter_byte_offsets[ci] = cumulative_bytes

                voice = get_voice(seg)
                text = _preprocess_tts_text(seg.get("text", "").strip())
                if not text:
                    audiobook_state.done = i + 1
                    continue

                try:
                    resp = _requests.post(
                        f"{tts_host}/v1/audio/speech",
                        json={
                            "model": tts_model,
                            "input": text,
                            "voice": voice,
                            "speed": tts_speed,
                            "response_format": "mp3",
                        },
                        timeout=120,
                        stream=True,
                    )
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=8192):
                        mp3_file.write(chunk)
                        cumulative_bytes += len(chunk)
                except Exception as e:
                    state.emit("log", {
                        "message": f"Audiobook: segment {i + 1}/{total} failed: {e}",
                        "level": "warn",
                    })

                audiobook_state.done = i + 1
                if (i + 1) % 10 == 0 or i + 1 == total:
                    state.emit("audiobook_progress", audiobook_state.snapshot())

        state.emit("log", {
            "message": f"Audiobook: synthesis complete -- {cumulative_bytes / 1024 / 1024:.1f} MB MP3",
            "level": "info",
        })

        # Build chapter list and save for re-use
        chapter_list = []
        for ci, chapter in enumerate(chapters):
            if chapter_byte_offsets[ci] is not None:
                chapter_list.append({
                    "title": chapter["title"],
                    "byte_offset": chapter_byte_offsets[ci],
                })
        try:
            with open(chapters_json_path, "w", encoding="utf-8") as f:
                _json_mod.dump(chapter_list, f)
        except Exception:
            pass

        # Convert to M4B if requested
        if fmt == "m4b":
            _convert_mp3_to_m4b(mp3_path, chapter_list, story_title or "Audiobook")
        else:
            audiobook_state.output_file = mp3_path

        audiobook_state.status = "completed"
        audiobook_state.phase = ""
        state.emit("log", {
            "message": f"Audiobook: {fmt.upper()} ready for download",
            "level": "info",
        })
        state.emit("audiobook_progress", audiobook_state.snapshot())

    except Exception as e:
        audiobook_state.status = "error"
        audiobook_state.error = str(e)
        state.emit("log", {
            "message": f"Audiobook compilation error: {e}",
            "level": "error",
        })
        state.emit("audiobook_progress", audiobook_state.snapshot())


def _probe_duration_ms(ffmpeg_path, audio_path):
    """Get audio duration in milliseconds using ffprobe (or ffmpeg fallback)."""
    import subprocess

    # Try ffprobe first (faster, more precise)
    ffprobe = ffmpeg_path.replace("ffmpeg", "ffprobe")
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(float(r.stdout.strip()) * 1000)
    except Exception:
        pass

    # Fallback: parse ffmpeg stderr
    try:
        r = subprocess.run(
            [ffmpeg_path, "-i", audio_path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        for line in r.stderr.splitlines():
            if "Duration:" in line:
                part = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = part.split(":")
                return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
    except Exception:
        pass
    return 0


def _inject_nero_chapters(m4b_path, chapters_ms):
    """Inject Nero-style chapter markers into an M4B file.

    Nero chapters are stored in moov.udta.chpl and are widely supported by
    audiobook players.  Unlike QuickTime chapter tracks, they do NOT create
    an extra stream (no SubtitleHandler text track) which avoids the
    'source files deleted/moved' error in some players.

    Args:
        m4b_path: Path to M4B file (modified in-place).
        chapters_ms: [{title: str, start_ms: int}, ...]
    """
    import struct

    if not chapters_ms:
        return

    with open(m4b_path, "rb") as f:
        data = bytearray(f.read())

    # -- Build chpl atom --
    payload = bytearray()
    payload += struct.pack("B", 1)          # version 1
    payload += b"\x00\x00\x00"              # flags
    payload += b"\x00\x00\x00\x00"          # reserved (version-1 field)
    payload += struct.pack(">I", len(chapters_ms))
    for ch in chapters_ms:
        ts = ch["start_ms"] * 10_000        # ms -> 100ns units
        title = ch["title"].encode("utf-8")[:255]
        payload += struct.pack(">q", ts)
        payload += struct.pack("B", len(title))
        payload += title
    chpl_atom = struct.pack(">I", len(payload) + 8) + b"chpl" + bytes(payload)

    # -- Find moov atom --
    pos = 0
    moov_pos = moov_size = None
    while pos < len(data) - 8:
        atom_sz = struct.unpack(">I", data[pos:pos + 4])[0]
        atom_nm = bytes(data[pos + 4:pos + 8])
        if atom_sz == 1:
            atom_sz = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
        elif atom_sz == 0:
            atom_sz = len(data) - pos
        if atom_sz < 8:
            break
        if atom_nm == b"moov":
            moov_pos = pos
            moov_size = atom_sz
        pos += atom_sz
    if moov_pos is None:
        raise ValueError("moov atom not found")

    # -- Find udta inside moov --
    scan = moov_pos + 8
    moov_end = moov_pos + moov_size
    udta_pos = udta_size = None
    while scan < moov_end - 8:
        s = struct.unpack(">I", data[scan:scan + 4])[0]
        n = bytes(data[scan + 4:scan + 8])
        if s < 8:
            break
        if n == b"udta":
            udta_pos = scan
            udta_size = s
            break
        scan += s

    if udta_pos is not None:
        # Remove existing chpl if present
        inner = udta_pos + 8
        while inner < udta_pos + udta_size - 8:
            s2 = struct.unpack(">I", data[inner:inner + 4])[0]
            if s2 < 8:
                break
            if bytes(data[inner + 4:inner + 8]) == b"chpl":
                del data[inner:inner + s2]
                udta_size -= s2
                moov_size -= s2
                struct.pack_into(">I", data, udta_pos, udta_size)
                struct.pack_into(">I", data, moov_pos, moov_size)
                break
            inner += s2

        # Append chpl at end of udta
        ins = udta_pos + udta_size
        data[ins:ins] = chpl_atom
        udta_size += len(chpl_atom)
        moov_size += len(chpl_atom)
        struct.pack_into(">I", data, udta_pos, udta_size)
        struct.pack_into(">I", data, moov_pos, moov_size)
    else:
        # Create udta containing chpl at end of moov
        udta = struct.pack(">I", len(chpl_atom) + 8) + b"udta" + chpl_atom
        ins = moov_pos + moov_size
        data[ins:ins] = udta
        moov_size += len(udta)
        struct.pack_into(">I", data, moov_pos, moov_size)

    with open(m4b_path, "wb") as f:
        f.write(data)


def _convert_mp3_to_m4b(mp3_path, chapter_list, book_title):
    """Convert MP3 to M4B (AAC in MP4) with Nero chapter markers.

    Two-step process:
      1. FFmpeg transcodes MP3 to AAC in MP4 container (no chapter input,
         so no spurious text track is created -- single audio stream).
      2. Python injects Nero chapters directly into moov.udta.chpl.

    The M4B is created WITHOUT +faststart (moov at end of file) so that
    chapter injection doesn't require stco offset fixups.
    """
    import shutil
    import subprocess

    audiobook_state.phase = "converting"
    state.emit("audiobook_progress", audiobook_state.snapshot())
    state.emit("log", {"message": "Audiobook: converting to M4B...", "level": "info"})

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        audiobook_state.status = "error"
        audiobook_state.error = "FFmpeg is not installed. Install it with: sudo apt install ffmpeg"
        return

    m4b_path = os.path.join(WORKSPACE_DIR, "audiobook.m4b")

    try:
        # Step 1: transcode to AAC -- no chapter metadata input, no extra streams
        cmd = [
            ffmpeg_path,
            "-i", mp3_path,
            "-c:a", "aac",
            "-b:a", "128k",
            "-metadata", f"title={book_title}",
            "-metadata", "album=Audiobook",
            "-y", m4b_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            audiobook_state.status = "error"
            audiobook_state.error = f"FFmpeg conversion failed: {result.stderr[-500:]}"
            return

        # Step 2: calculate chapter times and inject Nero chapters
        if chapter_list:
            duration_ms = _probe_duration_ms(ffmpeg_path, mp3_path)
            total_bytes = os.path.getsize(mp3_path)
            chapters_ms = []
            for ch in chapter_list:
                start_ms = (
                    int(ch["byte_offset"] / total_bytes * duration_ms)
                    if total_bytes else 0
                )
                chapters_ms.append({"title": ch["title"], "start_ms": start_ms})

            _inject_nero_chapters(m4b_path, chapters_ms)
            state.emit("log", {
                "message": f"Audiobook: injected {len(chapters_ms)} Nero chapters",
                "level": "info",
            })

        audiobook_state.output_file = m4b_path

    except subprocess.TimeoutExpired:
        audiobook_state.status = "error"
        audiobook_state.error = "FFmpeg conversion timed out"
    except Exception as e:
        audiobook_state.status = "error"
        audiobook_state.error = f"M4B conversion error: {e}"


@app.route("/api/tts/compile", methods=["POST"])
def api_tts_compile():
    """Start server-side audiobook compilation."""
    if audiobook_state._thread is not None and audiobook_state._thread.is_alive():
        return jsonify({"ok": False, "error": "Audiobook compilation already running"}), 400

    data = request.get_json(force=True) if request.is_json else {}
    fmt = data.get("format", "m4b")
    if fmt not in ("mp3", "m4b"):
        fmt = "m4b"

    # Read the story output
    output_path = os.path.join(WORKSPACE_DIR, "full_story.md")
    if not os.path.exists(output_path):
        return jsonify({"ok": False, "error": "No story output found. Generate the story first."}), 404

    with open(output_path, "r", encoding="utf-8") as f:
        story_text = f.read()

    chapters = _parse_chapters_for_audio(story_text)
    if not chapters:
        return jsonify({"ok": False, "error": "No chapters/scenes found in output"}), 400

    # Load TTS config
    cfg = _load_web_config()
    tts_host = _normalize_tts_host(cfg.get("tts_host", ""))
    tts_model = cfg.get("tts_model", "")
    narrator_voice = cfg.get("tts_narrator_voice", "")
    tts_speed = float(cfg.get("tts_speed", 1.0))

    if not tts_host or not tts_model or not narrator_voice:
        return jsonify({"ok": False, "error": "Configure TTS host, model and narrator voice first"}), 400

    # Build voice map from YAML + saved config
    voice_map = {}
    outline_path = os.path.join(WORKSPACE_DIR, FILE_ROLES["outline"])
    char_path = os.path.join(WORKSPACE_DIR, FILE_ROLES["characters"])

    story_title = ""
    pov_character = ""

    if os.path.exists(outline_path):
        try:
            with open(outline_path, "r", encoding="utf-8") as f:
                outline = _yaml.safe_load(f) or {}
            story_title = outline.get("story_title", "")
            pov_character = outline.get("pov_character", "")
        except Exception:
            pass

    if os.path.exists(char_path):
        try:
            with open(char_path, "r", encoding="utf-8") as f:
                char_data = _yaml.safe_load(f) or {}
            chars = char_data.get("characters", char_data)
            if isinstance(chars, dict):
                for cid, cval in chars.items():
                    if isinstance(cval, dict) and cval.get("tts_voice"):
                        name = cval.get("Name") or cval.get("name", cid)
                        voice_map[name] = cval["tts_voice"]
        except Exception:
            pass

    # Saved voice map from web config overrides YAML
    saved_map = cfg.get("tts_voice_map") or {}
    voice_map.update(saved_map)

    # Reset state and start worker
    audiobook_state.reset()
    audiobook_state.status = "compiling"
    audiobook_state.format = fmt

    thread = threading.Thread(
        target=_compile_audiobook_worker,
        args=(fmt, cfg, story_title, chapters, voice_map, narrator_voice,
              pov_character, tts_host, tts_model, tts_speed),
        daemon=True,
        name="audiobook-compile",
    )
    thread.start()
    audiobook_state._thread = thread

    return jsonify({"ok": True, "message": f"Audiobook compilation started ({fmt.upper()})"})


@app.route("/api/tts/compile-status")
def api_tts_compile_status():
    """Get current audiobook compilation progress."""
    return jsonify(audiobook_state.snapshot())


@app.route("/api/tts/compile-cancel", methods=["POST"])
def api_tts_compile_cancel():
    """Cancel a running audiobook compilation."""
    if audiobook_state._thread is None or not audiobook_state._thread.is_alive():
        return jsonify({"ok": False, "error": "No compilation running"}), 400
    audiobook_state._cancel = True
    return jsonify({"ok": True, "message": "Cancellation requested"})


@app.route("/api/tts/compile-download")
def api_tts_compile_download():
    """Download the compiled audiobook file."""
    snap = audiobook_state.snapshot()
    if not snap["has_file"]:
        return jsonify({"ok": False, "error": "No audiobook file available"}), 404

    path = audiobook_state.output_file
    ext = os.path.splitext(path)[1]  # .mp3 or .m4b
    mimetype = "audio/mp4" if ext == ".m4b" else "audio/mpeg"

    # Get story title for filename
    story_title = "audiobook"
    outline_path = os.path.join(WORKSPACE_DIR, FILE_ROLES["outline"])
    if os.path.exists(outline_path):
        try:
            with open(outline_path, "r", encoding="utf-8") as f:
                outline = _yaml.safe_load(f) or {}
            story_title = outline.get("story_title", "audiobook") or "audiobook"
        except Exception:
            pass

    safe_title = "".join(
        c if c.isalnum() or c in " _-" else "_" for c in story_title
    ).strip() or "audiobook"

    return send_file(
        path,
        mimetype=mimetype,
        as_attachment=True,
        download_name=f"{safe_title}{ext}",
    )


# ---------------------------------------------------------------------------
# Text analysis
# ---------------------------------------------------------------------------

# Common English stop words filtered from text analysis results
_STOP_WORDS = frozenset(
    "a an the and but or nor for yet so is am are was were be been being "
    "have has had do does did will would shall should may might can could "
    "i me my mine myself you your yours yourself he him his himself she her "
    "hers herself it its itself we us our ours ourselves they them their "
    "theirs themselves what which who whom this that these those to of in "
    "for on with at by from as into through during before after above below "
    "between out off over under again further then once here there where "
    "when how why all each every both few more most other some such no not "
    "only own same than too very just about up if also back even still also "
    "well much now new like one two way get go got know see make take come "
    "think look want give use find tell ask seem feel try leave call need "
    "become keep let begin show hear play run move live believe bring happen "
    "must write provide sit stand lose pay meet include continue set learn "
    "change lead understand watch follow stop create speak read allow add "
    "spend grow open walk win offer remember love consider appear buy wait "
    "serve die send expect build stay fall cut reach kill remain".split()
)

_STRIP_HTML_RE = re.compile(r"<[^>]+>")
_STRIP_MARKER_RE = re.compile(
    r"<!--\s*(?:/?scene:[\d.]+|chapter:\d+|speaker:[^>]*|/speaker:[^>]*)\s*-->",
    re.IGNORECASE,
)
_WORD_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


def _analyze_text(text: str, top_n: int = 80):
    """Analyze text for most common words and phrases (bigrams/trigrams).

    Returns dict with 'words' and 'phrases' lists sorted by frequency.
    """
    import collections

    # Strip HTML tags and scene markers
    clean = _STRIP_HTML_RE.sub(" ", text)
    clean = _STRIP_MARKER_RE.sub(" ", clean)
    # Strip markdown headers
    clean = re.sub(r"^#{1,6}\s.*$", "", clean, flags=re.MULTILINE)

    tokens = _WORD_TOKEN_RE.findall(clean.lower())
    # Filter stop words and very short tokens
    filtered = [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]

    # Single word counts
    word_counts = collections.Counter(filtered)
    words = [{"word": w, "count": c} for w, c in word_counts.most_common(top_n)]

    # Bigrams and trigrams (phrases)
    bigrams = collections.Counter()
    trigrams = collections.Counter()
    for i in range(len(filtered) - 1):
        bigrams[f"{filtered[i]} {filtered[i + 1]}"] += 1
    for i in range(len(filtered) - 2):
        trigrams[f"{filtered[i]} {filtered[i + 1]} {filtered[i + 2]}"] += 1

    # Merge bigrams and trigrams, keep only phrases appearing 2+ times
    phrases = {}
    for phrase, cnt in bigrams.items():
        if cnt >= 2:
            phrases[phrase] = cnt
    for phrase, cnt in trigrams.items():
        if cnt >= 2:
            phrases[phrase] = cnt
    sorted_phrases = sorted(phrases.items(), key=lambda x: -x[1])[:top_n]
    phrase_list = [{"phrase": p, "count": c} for p, c in sorted_phrases]

    return {
        "words": words,
        "phrases": phrase_list,
        "total_words": len(tokens),
        "unique_words": len(set(tokens)),
    }


@app.route("/api/text-analysis")
def api_text_analysis():
    """Analyze the generated story text for word and phrase frequency."""
    output_path = os.path.join(WORKSPACE_DIR, "full_story.md")
    if not os.path.exists(output_path):
        return jsonify({"ok": False, "error": "No output file found."})

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)})

    if not text.strip():
        return jsonify({"ok": False, "error": "Output file is empty."})

    result = _analyze_text(text)
    result["ok"] = True
    return jsonify(result)


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
    print(f"  Novel Builder  --  Web UI")
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
