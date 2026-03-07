"""Checkpoint read/write, resume logic, and story memory management."""

import os
import re
from datetime import datetime

from .yaml_io import load_yaml_optional, save_yaml


_CHECKPOINT_FILE = "checkpoint.yaml"
_MAX_RECENT_SCENES = 3
_MAX_MEMORY_CHARACTERS = 20
_RECENT_ALWAYS_INJECT = 5  # always-inject memory from last N scenes
_COMPRESSION_INTERVAL = 5  # compress story_so_far every N scenes
_MAX_IMAGERY_PER_LOCATION = 20  # max used-imagery phrases per location
_MAX_IMAGERY_PER_CHARACTER = 10  # max used-imagery phrases per character
_MAX_IMAGERY_GLOBAL = 15  # max unkeyed used-imagery phrases

# --- Deduplication config for actions/commitments ---
_DEDUP_JACCARD_THRESHOLD = 0.25  # minimum overlap ratio to consider a duplicate
_DEDUP_LOOKBACK = 30             # how many recent entries to compare against

# Stop-words for deduplication (includes routine-work verbs to avoid false misses)
_DEDUP_STOP_WORDS = {
    "the", "a", "an", "is", "was", "and", "or", "of", "to", "in", "for",
    "on", "it", "he", "she", "they", "with", "that", "this", "her", "his",
    "had", "has", "have", "but", "not", "are", "were", "will", "must",
    "begin", "begins", "beginning", "continue", "continues", "continuing",
    "complete", "completes", "completing", "start", "starts", "starting",
    "finish", "finishes", "finishing", "ensure", "ensures", "maintain",
    "maintains", "until", "end", "before", "after", "during", "all",
    "any", "each", "every", "more", "some", "their", "its", "be", "do",
    "does", "did", "if", "as", "at", "by", "up", "my", "our", "your",
    "i", "we", "you", "me", "him", "them", "day", "shift", "time",
    "work", "task", "tasks", "assigned", "process", "properly", "rest",
    "scene", "narrative", "details", "noted", "noted", "throughout",
}


def _dedup_words(text):
    """Extract set of crude-stemmed content words for Jaccard deduplication."""
    tokens = re.sub(r"[^\w\s]", "", text.lower()).split()
    return {t[:6] for t in tokens if t not in _DEDUP_STOP_WORDS and len(t) >= 3}


def _is_near_duplicate(new_detail, existing_entries):
    """Return True if new_detail is too similar to any recent entry (Jaccard >= threshold)."""
    new_words = _dedup_words(new_detail)
    if len(new_words) < 2:
        return False
    for entry in existing_entries[-_DEDUP_LOOKBACK:]:
        existing_words = _dedup_words(entry.get("detail", ""))
        if not existing_words:
            continue
        overlap = len(new_words & existing_words)
        union = len(new_words | existing_words)
        if union > 0 and overlap / union >= _DEDUP_JACCARD_THRESHOLD:
            return True
    return False


def _sanitize_story_memory(memory):
    """Ensure story_memory has the correct structure (dict with typed fields).

    Defensive utility that coerces unexpected types (None, string, wrong
    collection) back to the expected container so downstream code never
    receives a string where it expects a dict or list.

    Args:
        memory: The story_memory value from a checkpoint state dict.

    Returns:
        A new dict with guaranteed-correct types for each key.
    """
    if not isinstance(memory, dict):
        print(f"Warning: story_memory was {type(memory).__name__!r}, resetting to empty dict.")
        memory = {}

    # characters must be a dict
    chars = memory.get("characters", {})
    if not isinstance(chars, dict):
        print(f"Warning: story_memory.characters was {type(chars).__name__!r} "
              f"(value: {str(chars)[:80]!r}) — discarding corrupt value.")
        chars = {}
    else:
        # Each character entry must itself be a dict
        bad = [k for k, v in chars.items() if not isinstance(v, dict)]
        if bad:
            print(f"Warning: story_memory.characters had {len(bad)} non-dict "
                  f"entries {bad[:3]} — removing them.")
            chars = {k: v for k, v in chars.items() if isinstance(v, dict)}
    memory["characters"] = chars

    # facts must be a list of dicts
    facts = memory.get("facts", [])
    if not isinstance(facts, list):
        print(f"Warning: story_memory.facts was {type(facts).__name__!r} "
              f"(value: {str(facts)[:80]!r}) — discarding corrupt value.")
        facts = []
    else:
        bad_count = sum(1 for f in facts if not isinstance(f, dict))
        if bad_count:
            print(f"Warning: story_memory.facts had {bad_count} non-dict entries — removing them.")
            facts = [f for f in facts if isinstance(f, dict)]
    memory["facts"] = facts

    # commitments must be a list of dicts
    commitments = memory.get("commitments", [])
    if not isinstance(commitments, list):
        print(f"Warning: story_memory.commitments was {type(commitments).__name__!r} "
              f"(value: {str(commitments)[:80]!r}) — discarding corrupt value.")
        commitments = []
    else:
        bad_count = sum(1 for c in commitments if not isinstance(c, dict))
        if bad_count:
            print(f"Warning: story_memory.commitments had {bad_count} non-dict entries — removing them.")
            commitments = [c for c in commitments if isinstance(c, dict)]
    memory["commitments"] = commitments

    # actions must be a list of dicts
    actions = memory.get("actions", [])
    if not isinstance(actions, list):
        print(f"Warning: story_memory.actions was {type(actions).__name__!r} "
              f"(value: {str(actions)[:80]!r}) — discarding corrupt value.")
        actions = []
    else:
        bad_count = sum(1 for a in actions if not isinstance(a, dict))
        if bad_count:
            print(f"Warning: story_memory.actions had {bad_count} non-dict entries — removing them.")
            actions = [a for a in actions if isinstance(a, dict)]
    memory["actions"] = actions

    # used_imagery must be a list of dicts
    imagery = memory.get("used_imagery", [])
    if not isinstance(imagery, list):
        print(f"Warning: story_memory.used_imagery was {type(imagery).__name__!r} "
              f"(value: {str(imagery)[:80]!r}) — discarding corrupt value.")
        imagery = []
    else:
        bad_count = sum(1 for i in imagery if not isinstance(i, dict))
        if bad_count:
            print(f"Warning: story_memory.used_imagery had {bad_count} non-dict entries — removing them.")
            imagery = [i for i in imagery if isinstance(i, dict)]
    memory["used_imagery"] = imagery

    return memory


def load_checkpoint(filepath=None):
    """Load checkpoint state from file.

    Args:
        filepath: Path to checkpoint file (default: checkpoint.yaml).

    Returns:
        Dict with checkpoint state, or empty dict if not found.
    """
    path = filepath or _CHECKPOINT_FILE
    state = load_yaml_optional(path)
    if state and "story_memory" in state:
        state["story_memory"] = _sanitize_story_memory(state["story_memory"])
    return state


def save_checkpoint(state, filepath=None):
    """Save checkpoint state to file.

    Args:
        state: Dict with checkpoint data.
        filepath: Path to write (default: checkpoint.yaml).
    """
    path = filepath or _CHECKPOINT_FILE
    state["timestamp"] = datetime.now().isoformat()
    save_yaml(path, state)


def should_resume(args, checkpoint):
    """Determine whether to resume from checkpoint.

    Args:
        args: Parsed CLI args (has .resume, .restart).
        checkpoint: Loaded checkpoint dict.

    Returns:
        True if generation should resume from checkpoint.
    """
    if not checkpoint:
        return False
    if args.restart:
        return False
    if args.resume:
        return True

    # Interactive prompt
    last_ch = checkpoint.get("last_completed_chapter", "?")
    last_sc = checkpoint.get("last_completed_scene", "?")
    print(f"\nCheckpoint found: last completed Chapter {last_ch}, "
          f"Scene {last_sc}.")
    answer = input("Resume from where you left off? [Y/n]: ").strip().lower()
    return answer != "n"


def init_state(config, output_file):
    """Create a fresh checkpoint state.

    Args:
        config: Loaded story config dict.
        output_file: Output markdown file path.

    Returns:
        New checkpoint state dict.
    """
    return {
        "story_title": config.get("story_title", "Untitled"),
        "output_file": output_file,
        "last_completed_chapter": 0,
        "last_completed_scene": None,
        "story_so_far": "",
        "recent_scenes": [],
        "character_appearances": {},
        "story_memory": {
            "characters": {},
            "facts": [],
            "actions": [],
            "commitments": [],
            "used_imagery": [],
        },
    }


def update_after_scene(state, chapter_num, scene_id, summary,
                       extraction, present_char_ids, known_names=None,
                       setting_id=None):
    """Update checkpoint state after a scene completes.

    Args:
        state: Current checkpoint state dict (mutated in place).
        chapter_num: Chapter number just completed.
        scene_id: Scene ID just completed (e.g., "2.1").
        summary: AI-generated scene summary string.
        extraction: Dict with 'characters', 'facts', 'commitments',
                    'used_imagery' lists.
        present_char_ids: List of character IDs that appeared in the scene.
        known_names: Optional iterable of known character names from
                     characters.yaml.  Used to block phantom extractions.
        setting_id: Optional location/setting ID for the scene, used to
                    key used-imagery entries to the correct location.
    """
    state["last_completed_chapter"] = chapter_num
    state["last_completed_scene"] = str(scene_id)

    # Update recent scenes (rolling window)
    recent = state.get("recent_scenes", [])
    recent.append({"scene": str(scene_id), "summary": summary})
    if len(recent) > _MAX_RECENT_SCENES:
        recent = recent[-_MAX_RECENT_SCENES:]
    state["recent_scenes"] = recent

    # Update story_so_far with the latest summary
    story_so_far = state.get("story_so_far", "")
    if story_so_far:
        state["story_so_far"] = f"{story_so_far} {summary}"
    else:
        state["story_so_far"] = summary

    # Track character appearances
    appearances = state.get("character_appearances", {})
    for char_id in present_char_ids:
        if char_id not in appearances:
            appearances[char_id] = []
        appearances[char_id].append(str(scene_id))
    state["character_appearances"] = appearances

    # Merge story memory
    _merge_story_memory(state, extraction, str(scene_id),
                        known_names=known_names, setting_id=setting_id,
                        present_char_ids=present_char_ids)

    # Increment compression counter
    state["_scenes_since_compress"] = state.get("_scenes_since_compress", 0) + 1


def _merge_story_memory(state, extraction, scene_id, known_names=None,
                        setting_id=None, present_char_ids=None):
    """Merge extracted story memory from a scene into checkpoint state.

    Args:
        state: Checkpoint state (mutated).
        extraction: Dict with 'characters', 'facts', 'commitments',
                    'used_imagery'.
        scene_id: Scene ID string.
        known_names: Optional iterable of known character name strings from
                     characters.yaml.  Any extracted character whose full name
                     or first name matches a known character is silently
                     discarded to prevent phantom entries.
        setting_id: Optional location/setting ID for keying used imagery.
        present_char_ids: Optional list of character IDs in the scene,
                          used to key character-scoped used imagery.
    """
    memory = _sanitize_story_memory(state.get("story_memory", {}))

    # Build a deduplication guard from known character names.
    # We block on full name OR first name so that e.g. "Elias Bloom" is
    # rejected when "Elias Thorne" is already a known character.
    _known_full = set()
    _known_first = set()
    if known_names:
        for n in known_names:
            nl = n.lower().strip()
            _known_full.add(nl)
            first = nl.split()[0] if nl else ""
            if first:
                _known_first.add(first)

    # New characters
    for char_entry in extraction.get("characters", []):
        # Parse "name: description" format
        if ":" in char_entry:
            name, desc = char_entry.split(":", 1)
            name = name.strip()
            desc = desc.strip()
        else:
            name = char_entry.strip()
            desc = ""

        # Reject phantom extractions that share a name with a known character
        name_lower = name.lower().strip()
        first_name = name_lower.split()[0] if name_lower else ""
        if name_lower in _known_full or first_name in _known_first:
            continue

        char_id = name.lower().replace(" ", "_").replace("'", "")

        if char_id in memory.get("characters", {}):
            # Update existing
            memory["characters"][char_id]["last_seen"] = scene_id
            if desc:
                existing_notes = memory["characters"][char_id].get("notes", "")
                memory["characters"][char_id]["notes"] = (
                    f"{existing_notes} {desc}".strip()
                    if existing_notes else desc
                )
        else:
            # Cap at max tracked characters
            if len(memory.get("characters", {})) < _MAX_MEMORY_CHARACTERS:
                if "characters" not in memory:
                    memory["characters"] = {}
                memory["characters"][char_id] = {
                    "name": name,
                    "introduced_scene": scene_id,
                    "description": desc,
                    "last_seen": scene_id,
                    "notes": "",
                }

    # Facts
    for fact in extraction.get("facts", []):
        if fact.strip():
            memory.setdefault("facts", []).append({
                "scene": scene_id,
                "detail": fact.strip(),
            })

    # Actions (with deduplication guard)
    for action in extraction.get("actions", []):
        if action.strip():
            existing = memory.get("actions", [])
            if not _is_near_duplicate(action.strip(), existing):
                memory.setdefault("actions", []).append({
                    "scene": scene_id,
                    "detail": action.strip(),
                })

    # Commitments (with deduplication guard)
    for commitment in extraction.get("commitments", []):
        if commitment.strip():
            existing = memory.get("commitments", [])
            if not _is_near_duplicate(commitment.strip(), existing):
                memory.setdefault("commitments", []).append({
                    "scene": scene_id,
                    "detail": commitment.strip(),
                })

    # Used imagery — distinctive descriptive phrases keyed to location/character
    _merge_used_imagery(
        memory, extraction.get("used_imagery", []),
        scene_id, setting_id, present_char_ids, known_names,
    )

    state["story_memory"] = memory


def _merge_used_imagery(memory, raw_imagery, scene_id, setting_id,
                        present_char_ids, known_names):
    """Parse and store used-imagery entries from a scene extraction.

    Each raw entry is expected in "subject: phrase" format where subject
    is either 'setting' (keyed to the location) or a character name
    (keyed to a character ID).  Entries that can't be parsed are stored
    with scope '_global'.

    Caps are enforced per-location, per-character, and globally — oldest
    entries are evicted when the cap is exceeded.

    Args:
        memory: story_memory dict (mutated).
        raw_imagery: List of raw imagery strings from extraction.
        scene_id: Scene ID string.
        setting_id: Location/setting ID for the scene, or None.
        present_char_ids: List of character IDs in the scene, or None.
        known_names: Iterable of known character name strings, or None.
    """
    if not raw_imagery:
        return

    imagery_list = memory.setdefault("used_imagery", [])

    # Build a name→char_id lookup for matching imagery subjects
    _name_to_id = {}
    if known_names and present_char_ids:
        # known_names and present_char_ids come from the same characters dict
        # but known_names is all characters while present_char_ids is scene-specific.
        # We accept matches against present characters for keying.
        pass
    if present_char_ids:
        for cid in present_char_ids:
            _name_to_id[cid.lower()] = cid
            # Also add the first part as a short-name match
            parts = cid.split("_")
            if parts:
                _name_to_id[parts[0].lower()] = cid
    if known_names:
        for name in known_names:
            nl = name.lower().strip()
            # Try to find the matching char_id from present_char_ids
            first = nl.split()[0] if nl else ""
            for cid in (present_char_ids or []):
                cid_first = cid.split("_")[0].lower() if cid else ""
                if first and (first == cid_first or nl.replace(" ", "_") == cid.lower()):
                    _name_to_id[nl] = cid
                    if first:
                        _name_to_id[first] = cid
                    break

    for raw in raw_imagery:
        raw = raw.strip()
        if not raw or raw.upper() == "NONE":
            continue

        # Parse "subject: phrase" format
        scope_type = "_global"
        scope_id = ""
        phrase = raw

        if ":" in raw:
            subject, rest = raw.split(":", 1)
            subject = subject.strip()
            rest = rest.strip()
            if rest:  # Only use the split if there's actually a phrase after ':'
                phrase = rest
                subject_lower = subject.lower()

                if subject_lower in ("setting", "location", "place", "environment"):
                    scope_type = "setting"
                    scope_id = setting_id or "_unkeyed"
                elif subject_lower in _name_to_id:
                    scope_type = "character"
                    scope_id = _name_to_id[subject_lower]
                else:
                    # Unknown subject — try fuzzy match against known names
                    matched = False
                    for name_key, cid in _name_to_id.items():
                        if subject_lower in name_key or name_key in subject_lower:
                            scope_type = "character"
                            scope_id = cid
                            matched = True
                            break
                    if not matched:
                        scope_type = "_global"
                        scope_id = ""

        # Deduplicate: skip if this exact phrase (case-insensitive) already exists
        phrase_lower = phrase.lower()
        if any(e.get("detail", "").lower() == phrase_lower for e in imagery_list):
            continue

        imagery_list.append({
            "scene": scene_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "detail": phrase,
        })

    # Enforce per-scope caps — evict oldest entries when over limit
    _enforce_imagery_caps(imagery_list)

    memory["used_imagery"] = imagery_list


def _enforce_imagery_caps(imagery_list):
    """Evict oldest used-imagery entries when per-scope caps are exceeded.

    Modifies the list in place.

    Args:
        imagery_list: List of used_imagery dicts.
    """
    # Group by (scope_type, scope_id)
    from collections import defaultdict
    groups = defaultdict(list)
    for idx, entry in enumerate(imagery_list):
        key = (entry.get("scope_type", "_global"), entry.get("scope_id", ""))
        groups[key].append(idx)

    to_remove = set()
    for (stype, sid), indices in groups.items():
        if stype == "setting":
            cap = _MAX_IMAGERY_PER_LOCATION
        elif stype == "character":
            cap = _MAX_IMAGERY_PER_CHARACTER
        else:
            cap = _MAX_IMAGERY_GLOBAL

        if len(indices) > cap:
            # Remove oldest (lowest indices)
            excess = indices[:len(indices) - cap]
            to_remove.update(excess)

    if to_remove:
        for idx in sorted(to_remove, reverse=True):
            imagery_list.pop(idx)


def _clear_scene_memory(state, scene_id):
    """Remove story memory entries that were extracted from a specific scene.

    Called before re-merging extraction after a scene regeneration, so
    stale or hallucinated entries from the previous version are wiped
    and replaced with fresh ones rather than accumulated.

    Args:
        state: Checkpoint state (mutated).
        scene_id: Scene ID string whose extracted memory should be cleared.
    """
    scene_id = str(scene_id)
    memory = state.get("story_memory", {})
    if not memory:
        return

    # Remove list-based entries (facts, actions, commitments, used_imagery) from this scene
    for key in ("facts", "actions", "commitments", "used_imagery"):
        entries = memory.get(key, [])
        memory[key] = [e for e in entries if str(e.get("scene", "")) != scene_id]

    # Remove extracted minor characters first seen in this scene
    chars = memory.get("characters", {})
    memory["characters"] = {
        k: v for k, v in chars.items()
        if str(v.get("introduced_scene", "")) != scene_id
    }

    state["story_memory"] = memory


def get_relevant_memory(state, text_to_scan):
    """Get story memory entries relevant to the current scene.

    Scans scene text for references to remembered characters, locations,
    or topics.

    Args:
        state: Checkpoint state dict.
        text_to_scan: Scene events/notes text to scan for references.

    Returns:
        Dict with 'characters', 'facts', 'commitments' relevant to scene.
    """
    memory = _sanitize_story_memory(state.get("story_memory", {}))
    all_empty = (
        not memory.get("characters")
        and not memory.get("facts")
        and not memory.get("actions")
        and not memory.get("commitments")
        and not memory.get("used_imagery")
    )
    if not memory or all_empty:
        return {"characters": {}, "facts": [], "actions": [], "commitments": []}

    text_lower = text_to_scan.lower()
    relevant = {"characters": {}, "facts": [], "actions": [], "commitments": []}

    # Stopwords to exclude from keyword matching
    _STOP_WORDS = {
        "the", "a", "an", "is", "was", "and", "or", "of", "to", "in",
        "for", "on", "it", "he", "she", "they", "with", "that", "this",
        "her", "his", "had", "has", "have", "but", "not", "are", "were",
    }
    scene_words = set(text_lower.split()) - _STOP_WORDS

    # Track scene IDs of recent scenes for always-inject
    recent = state.get("recent_scenes", [])
    recent_scene_ids = {r["scene"] for r in recent[-_RECENT_ALWAYS_INJECT:]}

    # Check remembered characters
    for char_id, char_data in memory["characters"].items():
        name = char_data.get("name", "")
        if (char_id in text_lower or
                (name and name.lower() in text_lower)):
            relevant["characters"][char_id] = char_data

    def _match_or_recent(entry):
        """Return True if entry keyword-matches scene text or is recent."""
        if entry.get("scene") in recent_scene_ids:
            return True
        detail = entry.get("detail", "")
        words = set(detail.lower().split()) - _STOP_WORDS
        return bool(words & scene_words)

    # Facts: keyword-matched from last 10
    for fact in memory.get("facts", [])[-10:]:
        if _match_or_recent(fact):
            relevant["facts"].append(fact)

    # Actions: always-inject recent, keyword-match older
    for action in memory.get("actions", [])[-10:]:
        if _match_or_recent(action):
            relevant["actions"].append(action)

    # Commitments: always-inject recent, keyword-match older
    for commit in memory.get("commitments", [])[-10:]:
        if _match_or_recent(commit):
            relevant["commitments"].append(commit)

    return relevant


def get_used_imagery(state, setting_id=None, char_ids=None):
    """Retrieve used-imagery phrases relevant to the current scene.

    Returns phrases that match the scene's setting and/or characters,
    plus a small window of recent global (unkeyed) phrases.  This is
    used to build the imagery-suppression block in the scene prompt.

    Args:
        state: Checkpoint state dict.
        setting_id: Current scene's location/setting ID, or None.
        char_ids: List of character IDs present in the scene, or None.

    Returns:
        Dict with 'setting' (list of phrases) and 'characters'
        (dict of char_id -> list of phrases).
    """
    memory = state.get("story_memory", {})
    imagery_list = memory.get("used_imagery", [])
    if not imagery_list:
        return {"setting": [], "characters": {}, "global": []}

    setting_phrases = []
    char_phrases = {}
    global_phrases = []

    char_set = set(char_ids or [])

    for entry in imagery_list:
        scope_type = entry.get("scope_type", "_global")
        scope_id = entry.get("scope_id", "")
        phrase = entry.get("detail", "")
        if not phrase:
            continue

        if scope_type == "setting":
            if setting_id and scope_id == setting_id:
                setting_phrases.append(phrase)
        elif scope_type == "character":
            if scope_id in char_set:
                char_phrases.setdefault(scope_id, []).append(phrase)
        else:
            global_phrases.append(phrase)

    # Cap global to most recent entries
    if len(global_phrases) > _MAX_IMAGERY_GLOBAL:
        global_phrases = global_phrases[-_MAX_IMAGERY_GLOBAL:]

    return {
        "setting": setting_phrases,
        "characters": char_phrases,
        "global": global_phrases,
    }


def resumption_point(state, chapters):
    """Determine where to resume generation.

    Args:
        state: Checkpoint state dict.
        chapters: List of chapter dicts from config.

    Returns:
        Tuple of (chapter_index, scene_index) to start from.
        Both are 0-based indices into the chapter/scene lists.
    """
    last_ch = state.get("last_completed_chapter", 0)
    last_sc = str(state.get("last_completed_scene", ""))

    for ch_idx, chapter in enumerate(chapters):
        ch_num = chapter.get("chapter_number", ch_idx + 1)
        if ch_num < last_ch:
            continue
        if ch_num > last_ch:
            return ch_idx, 0

        # Same chapter — find the scene after the last completed one
        scenes = chapter.get("scenes", [])
        for sc_idx, scene in enumerate(scenes):
            sc_id = str(scene.get("scene_number", f"{ch_num}.{sc_idx + 1}"))
            if sc_id == last_sc:
                # Start from the next scene
                if sc_idx + 1 < len(scenes):
                    return ch_idx, sc_idx + 1
                else:
                    # Chapter complete, move to next
                    if ch_idx + 1 < len(chapters):
                        return ch_idx + 1, 0
                    else:
                        return len(chapters), 0  # All done

    return 0, 0  # Start from beginning


def should_compress(state):
    """Check whether story_so_far should be compressed.

    Returns True every _COMPRESSION_INTERVAL scenes and when the
    accumulated text exceeds 1500 characters (the prompt builder's
    truncation threshold).  The counter is stored in the checkpoint
    so it survives restarts.
    """
    counter = state.get("_scenes_since_compress", 0)
    story = state.get("story_so_far", "")
    return counter >= _COMPRESSION_INTERVAL and len(story) > 1500


def compress_story_so_far(state, host, summary_model):
    """Compress story_so_far via the summary model into a tighter recap.

    Replaces the raw concatenation of per-scene summaries with a
    coherent, compressed narrative summary.  Resets the compression
    counter on success.

    Args:
        state: Checkpoint state dict (mutated in place).
        host: Ollama host URL.
        summary_model: Model name for summarization.

    Returns:
        True if compression succeeded, False otherwise.
    """
    from .ollama_client import call_ollama

    story = state.get("story_so_far", "")
    if not story or len(story) < 800:
        return False

    system_prompt = (
        "You are a precise literary assistant. "
        "Compress the following story-so-far summary into a single, "
        "coherent recap of 4-6 sentences. Preserve every character "
        "name, key action, unresolved commitment, and plot development. "
        "Do NOT add any information not present in the input. "
        "Output ONLY the compressed summary — nothing else."
    )

    try:
        compressed = call_ollama(
            host=host,
            model=summary_model,
            system_prompt=system_prompt,
            user_prompt=story,
            timeout=300,
        )
        compressed = compressed.strip()
        if compressed and len(compressed) < len(story):
            old_len = len(story)
            state["story_so_far"] = compressed
            state["_scenes_since_compress"] = 0
            print(f"    Story-so-far compressed: {old_len} → {len(compressed)} chars")
            return True
        else:
            print("    Compression did not reduce size — skipping.")
            return False
    except Exception as e:
        print(f"    Warning: story_so_far compression failed — {e}")
        return False
