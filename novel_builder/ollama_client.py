"""Ollama API calls with retry logic and model routing."""

import threading
import time

import requests


class OllamaError(Exception):
    """Raised when Ollama API call fails after all retries."""
    pass


class _OllamaWatchdog:
    """Monitor Ollama model liveness during generation via /api/ps polling.

    Runs in a daemon thread.  If the model disappears from /api/ps (or the
    server becomes unreachable) for several consecutive checks, closes the
    HTTP response to unblock the streaming read.
    """

    POLL_INTERVAL = 30   # seconds between /api/ps checks
    MISS_THRESHOLD = 3   # consecutive misses before aborting

    def __init__(self, host, model, response, emit_callback=None):
        self._host = host
        self._model = model
        self._response = response
        self._emit = emit_callback
        self._abort = threading.Event()
        self._model_gone = False
        self._start_time = time.time()
        self._last_token_time = time.time()
        self._token_count = 0
        self._first_token = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    # -- public API --------------------------------------------------------

    def start(self):
        self._thread.start()

    def stop(self):
        self._abort.set()
        self._thread.join(timeout=5)

    def record_token(self):
        """Notify the watchdog that a token was received."""
        self._last_token_time = time.time()
        self._token_count += 1
        if not self._first_token:
            self._first_token = True
            elapsed = self._fmt(time.time() - self._start_time)
            self._log(
                f"First token after {elapsed} (model load + prompt eval)",
            )

    @property
    def model_confirmed_gone(self):
        return self._model_gone

    # -- internals ---------------------------------------------------------

    def _log(self, msg, level="info"):
        if self._emit:
            try:
                self._emit("log", message=f"[Ollama] {msg}", level=level)
            except Exception:
                pass

    @staticmethod
    def _fmt(seconds):
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s" if m else f"{s}s"

    def _is_model_active(self):
        """Poll /api/ps.  Returns True / False / None (unknown)."""
        try:
            resp = requests.get(f"{self._host}/api/ps", timeout=10)
            if not resp.ok:
                return None
            for m in resp.json().get("models", []):
                name = m.get("model", "") or m.get("name", "")
                if name == self._model:
                    return True
            return False
        except Exception:
            return None

    def _run(self):
        misses = 0
        while not self._abort.wait(self.POLL_INTERVAL):
            elapsed = self._fmt(time.time() - self._start_time)
            idle = time.time() - self._last_token_time

            status = self._is_model_active()

            if status is True:
                misses = 0
                if self._first_token:
                    self._log(
                        f"Model active -- {self._token_count} tokens, "
                        f"{elapsed} elapsed",
                    )
                else:
                    self._log(
                        f"Waiting for first token -- model active, "
                        f"{elapsed} elapsed",
                    )
                continue

            # Model missing or server unreachable
            misses += 1
            reason = ("not listed in /api/ps" if status is False
                      else "server unreachable")
            self._log(
                f"Model {reason} "
                f"(check {misses}/{self.MISS_THRESHOLD})",
                "warn",
            )

            if misses >= self.MISS_THRESHOLD and idle > 60:
                self._log(
                    f"Aborting request: {reason} for "
                    f"{misses} consecutive checks, no tokens for "
                    f"{self._fmt(idle)}",
                    "error",
                )
                self._model_gone = True
                try:
                    self._response.close()
                except Exception:
                    pass
                return


def call_ollama(host, model, system_prompt, user_prompt, timeout=900,
                temperature=0.85, num_ctx=12288, emit_callback=None):
    """Make a single streaming call to the Ollama /api/generate endpoint.

    Uses stream=True with no read timeout to prevent false timeouts on
    slow hardware.  A background watchdog thread polls /api/ps to verify
    the model is still loaded and closes the connection if it detects the
    model has crashed or been evicted.

    Args:
        host: Ollama server URL.
        model: Model name.
        system_prompt: System message.
        user_prompt: User message.
        timeout: Connection timeout in seconds (read timeout is unlimited;
                 the watchdog monitors liveness instead).
        temperature: Sampling temperature.
        num_ctx: Context window size.
        emit_callback: Optional callable(event_type, **kwargs) for
            progress/log events (forwarded to the watchdog).

    Returns:
        Generated text string.

    Raises:
        OllamaError: If the API call fails.
    """
    import json as _json

    url = f"{host}/api/generate"
    payload = {
        "model": model,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": True,
        "options": {
            "num_ctx": num_ctx,
            "temperature": temperature,
            "top_p": 0.92,
            "presence_penalty": 0.2,
            "repeat_penalty": 1.15,
        },
    }

    watchdog = None
    try:
        # Connection timeout only; read timeout unlimited (watchdog
        # monitors model liveness via /api/ps instead).
        connect_timeout = min(timeout, 60)
        response = requests.post(
            url, json=payload, timeout=(connect_timeout, None), stream=True,
        )
        response.raise_for_status()

        # Start watchdog to monitor model via /api/ps
        watchdog = _OllamaWatchdog(host, model, response, emit_callback)
        watchdog.start()

        chunks = []
        for line in response.iter_lines(chunk_size=None):
            if not line:
                continue
            try:
                data = _json.loads(line)
            except ValueError:
                continue
            token = data.get("response", "")
            if token:
                chunks.append(token)
                watchdog.record_token()
            if data.get("done"):
                break

        return "".join(chunks)

    except requests.exceptions.Timeout:
        raise OllamaError(
            f"Connection to Ollama timed out after {min(timeout, 60)}s "
            f"(server may be down)"
        )
    except requests.exceptions.ConnectionError as e:
        if watchdog and watchdog.model_confirmed_gone:
            raise OllamaError(
                f"Model '{model}' is no longer active on the Ollama server "
                f"(verified via /api/ps polling)"
            )
        raise OllamaError(f"Connection failed: {e}")
    except requests.exceptions.HTTPError as e:
        raise OllamaError(f"HTTP error: {e}")
    except Exception as e:
        if watchdog and watchdog.model_confirmed_gone:
            raise OllamaError(
                f"Model '{model}' is no longer active on the Ollama server "
                f"(verified via /api/ps polling)"
            )
        raise OllamaError(f"Ollama API error: {e}")
    finally:
        if watchdog:
            watchdog.stop()


def _wait_for_ollama(host, max_wait, emit_callback=None):
    """Poll Ollama until it responds or *max_wait* seconds elapse.

    Checks every 15 seconds.  Returns as soon as the server answers
    /api/tags (even if no models are loaded yet), so subsequent retry
    attempts don't waste time sleeping after the server has recovered.
    """
    deadline = time.time() + max_wait
    poll_interval = 15
    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            resp = requests.get(f"{host}/api/tags", timeout=10)
            if resp.ok:
                if emit_callback:
                    emit_callback("log", message="[Ollama] Server is back online, retrying...", level="info")
                return
        except Exception:
            pass
    # Max wait elapsed -- fall through so the retry loop tries anyway


def unload_model(host, model, emit_callback=None):
    """Unload a model from Ollama memory by sending keep_alive=0.

    Used to free RAM/VRAM before switching to a different model
    (e.g., generation -> summary).  No-op if the model is not loaded
    or the server is unreachable.

    Args:
        host: Ollama server URL.
        model: Model name to unload.
        emit_callback: Optional callable for log events.
    """
    try:
        resp = requests.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": 0},
            timeout=15,
        )
        if resp.ok and emit_callback:
            emit_callback(
                "log",
                message=f"[Ollama] Unloaded '{model}' to free memory",
                level="info",
            )
    except Exception:
        pass  # Server down or model not loaded -- nothing to unload


def call_ollama_with_retry(host, model, system_prompt, user_prompt,
                           timeout=900, retries=5, temperature=0.85,
                           num_ctx=12288, emit_callback=None):
    """Call Ollama with exponential backoff retry logic.

    Args:
        host: Ollama server URL.
        model: Model name.
        system_prompt: System message.
        user_prompt: User message.
        timeout: Request timeout in seconds.
        retries: Maximum number of attempts.
        temperature: Sampling temperature.
        num_ctx: Context window size.
        emit_callback: Optional callable(event_type, **kwargs) for progress logging.

    Returns:
        Generated text string.

    Raises:
        OllamaError: If all retry attempts fail.
    """
    _emit_callback = emit_callback
    # Generous backoff for scenarios like Docker pulling a 1GB+ upgrade
    # image (15+ min).  _wait_for_ollama polls during the wait and
    # resumes immediately once the server is back.
    backoff_delays = [300, 900, 1800, 3600, 3600]  # 5m, 15m, 30m, 60m, 60m

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            result = call_ollama(
                host, model, system_prompt, user_prompt,
                timeout=timeout, temperature=temperature, num_ctx=num_ctx,
                emit_callback=_emit_callback,
            )
            return result
        except OllamaError as e:
            last_error = e
            if attempt < retries:
                delay = backoff_delays[min(attempt - 1, len(backoff_delays) - 1)]
                mins = delay // 60
                secs = delay % 60
                delay_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                print(f"  [Retry {attempt}/{retries}] {e}")
                print(f"  Waiting up to {delay_str} for Ollama...")
                if _emit_callback:
                    _emit_callback("log", message=f"[Retry {attempt}/{retries}] {e}. Polling Ollama for up to {delay_str}...", level="warn")
                # Poll Ollama health during backoff -- retry as soon as
                # the server is reachable rather than sleeping the full delay.
                _wait_for_ollama(host, delay, _emit_callback)
            else:
                print(f"  [Failed] All {retries} attempts exhausted.")

    raise OllamaError(
        f"All {retries} attempts failed. Last error: {last_error}"
    )


def call_summary_model(host, model, text, timeout=300, scene_meta=None):
    """Call the summary model to summarize a scene and extract story memory.

    Uses a combined prompt that produces both a scene summary and
    extracted persistent details in a structured format.

    Args:
        host: Ollama server URL.
        model: Summary model name (e.g., gemma3:1b).
        text: The generated scene text to summarize.
        timeout: Request timeout.
        scene_meta: Optional dict with 'scene_id', 'title', 'characters'
                    (list of character names in the scene).

    Returns:
        Tuple of (summary_text, extraction_text).
        extraction_text contains structured memory data.
    """
    system_prompt = (
        "You are a precise story-continuity assistant. Your job is to extract "
        "information that matters for FUTURE scenes — not to recap what happened.\n\n"
        "RULES:\n"
        "- Use ONLY character names listed in the metadata. Do NOT swap, "
        "  confuse, or invent character names.\n"
        "- NEW_CHARACTERS is ONLY for genuinely new, previously unknown "
        "  characters NOT in the metadata character list. If a name is a "
        "  variant of a known character, do NOT add it — write NONE.\n"
        "- Do NOT combine parts of different characters' names into a new name.\n"
        "- SUMMARY: Capture the key PLOT EVENTS — what changed, what was "
        "  learned, what was decided, what shifted between characters. "
        "  Skip routine physical actions and setting descriptions.\n"
        "- NEW_FACTS: Only facts that future scenes need to stay consistent "
        "  (e.g., a secret revealed, a location discovered, a rule established, "
        "  an object acquired). NOT routine observations.\n"
        "- ACTIONS: Only consequential actions — decisions made, promises given, "
        "  confrontations, discoveries, betrayals. NOT 'walked across room' or "
        "  'poured coffee'.\n"
        "- COMMITMENTS: Promises, threats, obligations, or plans that must be \n"
        "  followed up in future scenes.\n"
        "- USED_IMAGERY: Distinctive descriptive phrases, vivid sensory details, \n"
        "  specific metaphors, or recurring images from this scene that would \n"
        "  feel repetitive if reused in a future scene at the same location or \n"
        "  describing the same character. Extract the EXACT memorable phrase, \n"
        "  prefixed with its subject (a character name or 'setting'). \n"
        "  Examples: 'setting: dust motes danced in shafts of light', \n"
        "  'Elias: weathered hands like old leather'. \n"
        "  Do NOT extract generic action ('walked across room') — only vivid \n"
        "  sensory/descriptive language that a reader would notice if repeated.\n"
        "- If nothing fits a category, write NONE for that category.\n"
        "- Do NOT infer or speculate. Only extract what the text explicitly states.\n\n"
        "FORMAT (follow exactly — no extra text before or after):\n\n"
        "SUMMARY: <2-3 sentences: what happened that matters for the story>\n"
        "NEW_CHARACTERS: <Full Name: brief role> or NONE\n"
        "NEW_FACTS: <one fact that future scenes need> or NONE\n"
        "ACTIONS: <Character Name did what (consequential only)> or NONE\n"
        "COMMITMENTS: <Character Name will/must do what> or NONE\n"
        "USED_IMAGERY: <subject: vivid phrase> or NONE\n\n"
        "Start your response with SUMMARY: — nothing else."
    )

    # Build user prompt with scene metadata for grounding
    meta_lines = []
    if scene_meta:
        if scene_meta.get("scene_id"):
            meta_lines.append(f"Scene: {scene_meta['scene_id']}")
        if scene_meta.get("title"):
            meta_lines.append(f"Title: {scene_meta['title']}")
        if scene_meta.get("characters"):
            meta_lines.append(f"Characters in scene: {', '.join(scene_meta['characters'])}")
        if scene_meta.get("setting"):
            meta_lines.append(f"Setting/location: {scene_meta['setting']}")
    meta_block = "\n".join(meta_lines)
    if meta_block:
        base_user_prompt = f"Scene metadata:\n{meta_block}\n\nScene text:\n\n{text}"
    else:
        base_user_prompt = f"Analyze this scene:\n\n{text}"
    user_prompt = base_user_prompt

    for format_attempt in range(2):
        result = call_ollama_with_retry(
            host, model, system_prompt, user_prompt,
            timeout=timeout, retries=2, temperature=0.3, num_ctx=8192,
        )
        summary, extraction = _parse_summary_response(result)

        if summary:  # Got a usable summary — extraction may be empty but that's OK
            return summary, extraction

        # Model ignored the format — retry with an explicit reminder
        user_prompt = (
            f"{base_user_prompt}\n\n"
            "IMPORTANT: Your previous response did not follow the required "
            "format. You MUST begin your response with 'SUMMARY:' followed "
            "by the summary text, then NEW_CHARACTERS:, NEW_FACTS:, "
            "ACTIONS:, COMMITMENTS:, and USED_IMAGERY: on separate lines."
        )

    # Both attempts produced no summary — return what we have
    return summary, extraction


def _parse_summary_response(text):
    """Parse the structured response from the summary model.

    Args:
        text: Raw response text.

    Returns:
        Tuple of (summary, extraction_dict).
    """
    summary = ""
    extraction = {
        "characters": [],
        "facts": [],
        "actions": [],
        "commitments": [],
        "used_imagery": [],
    }

    lines = text.strip().split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        upper = line.upper()
        if upper.startswith("SUMMARY:"):
            summary = line[len("SUMMARY:"):].strip()
            current_section = "summary"
        elif upper.startswith("NEW_CHARACTERS:"):
            content = line[len("NEW_CHARACTERS:"):].strip()
            if content.upper() != "NONE" and content:
                extraction["characters"].append(content)
            current_section = "characters"
        elif upper.startswith("NEW_FACTS:"):
            content = line[len("NEW_FACTS:"):].strip()
            if content.upper() != "NONE" and content:
                extraction["facts"].append(content)
            current_section = "facts"
        elif upper.startswith("ACTIONS:"):
            content = line[len("ACTIONS:"):].strip()
            if content.upper() != "NONE" and content:
                extraction["actions"].append(content)
            current_section = "actions"
        elif upper.startswith("COMMITMENTS:"):
            content = line[len("COMMITMENTS:"):].strip()
            if content.upper() != "NONE" and content:
                extraction["commitments"].append(content)
            current_section = "commitments"
        elif upper.startswith("USED_IMAGERY:") or upper.startswith("USED IMAGERY:"):
            content = line.split(":", 1)[1].strip() if ":" in line[13:] else line[13:].strip()
            # Re-parse: the header is "USED_IMAGERY:" and the content may
            # itself contain "subject: phrase" so split carefully.
            content = line[len("USED_IMAGERY:"):].strip() if upper.startswith("USED_IMAGERY:") else line[len("USED IMAGERY:"):].strip()
            if content.upper() != "NONE" and content:
                extraction["used_imagery"].append(content)
            current_section = "used_imagery"
        elif current_section == "summary":
            summary += " " + line
        elif current_section in extraction:
            if line.upper() != "NONE" and line.startswith("- "):
                extraction[current_section].append(line[2:].strip())
            elif line.upper() != "NONE" and line:
                extraction[current_section].append(line)

    # Fallback: if parsing fails, treat the whole thing as summary
    if not summary:
        summary = text.strip()[:500]

    return summary, extraction
