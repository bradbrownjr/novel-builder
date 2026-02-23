"""Ollama API calls with retry logic and model routing."""

import time

import requests


class OllamaError(Exception):
    """Raised when Ollama API call fails after all retries."""
    pass


def call_ollama(host, model, system_prompt, user_prompt, timeout=900,
                temperature=0.85, num_ctx=12288):
    """Make a single streaming call to the Ollama /api/generate endpoint.

    Uses stream=True so the timeout applies per-chunk (not total generation
    time). This prevents false timeouts on long scenes where the model is
    actively generating but takes more than `timeout` seconds overall.

    Args:
        host: Ollama server URL.
        model: Model name.
        system_prompt: System message.
        user_prompt: User message.
        timeout: Per-chunk inactivity timeout in seconds.
        temperature: Sampling temperature.
        num_ctx: Context window size.

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

    try:
        response = requests.post(url, json=payload, timeout=timeout, stream=True)
        response.raise_for_status()

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
            if data.get("done"):
                break

        return "".join(chunks)

    except requests.exceptions.Timeout:
        raise OllamaError(f"Timed out waiting for response chunk after {timeout}s")
    except requests.exceptions.ConnectionError as e:
        raise OllamaError(f"Connection failed: {e}")
    except requests.exceptions.HTTPError as e:
        raise OllamaError(f"HTTP error: {e}")
    except Exception as e:
        raise OllamaError(f"Ollama API error: {e}")


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
    backoff_delays = [180, 300, 900, 1800, 3600]  # 3m, 5m, 15m, 30m, 60m — ~1h53m total patience

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            result = call_ollama(
                host, model, system_prompt, user_prompt,
                timeout=timeout, temperature=temperature, num_ctx=num_ctx,
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
                print(f"  Waiting {delay_str} before next attempt...")
                # Emit progress so the web UI shows retry status
                if _emit_callback:
                    _emit_callback("log", message=f"[Retry {attempt}/{retries}] Ollama error: {e}. Waiting {delay_str}...", level="warn")
                time.sleep(delay)
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
        "You are a precise literary assistant that extracts information "
        "ONLY from what is explicitly written in the scene text.\n\n"
        "RULES:\n"
        "- Use ONLY character names provided in the metadata. Do NOT swap, "
        "  confuse, or invent character names.\n"
        "- SUMMARY must describe what actually happened — not what might happen.\n"
        "- Extract only facts/actions/commitments that are NEW and clearly "
        "  stated in the text. If nothing new, write NONE.\n"
        "- Do NOT infer, speculate, or embellish. Stick to what the text says.\n"
        "- Keep extractions brief and specific.\n\n"
        "FORMAT (follow exactly — no extra text before or after):\n\n"
        "SUMMARY: <2-3 sentence summary of key events>\n"
        "NEW_CHARACTERS: <Full Name: brief role> or NONE\n"
        "NEW_FACTS: <one fact established in this scene> or NONE\n"
        "ACTIONS: <Character Name did what> or NONE\n"
        "COMMITMENTS: <Character Name will/must do what> or NONE\n\n"
        "IMPORTANT:\n"
        "- Always attribute actions/commitments to the CORRECT character "
        "  by name. Double-check against the character list.\n"
        "- Omit trivial details (e.g., 'character walked across room'). "
        "  Only extract plot-relevant facts, actions, and commitments.\n"
        "- Start your response with SUMMARY: — nothing else."
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
            "ACTIONS:, and COMMITMENTS: on separate lines."
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
