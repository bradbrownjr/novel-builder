"""Checkpoint read/write, resume logic, and story memory management."""

import os
from datetime import datetime

from .yaml_io import load_yaml_optional, save_yaml


_CHECKPOINT_FILE = "checkpoint.yaml"
_MAX_RECENT_SCENES = 3
_MAX_MEMORY_CHARACTERS = 20


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
            "commitments": [],
        },
    }


def update_after_scene(state, chapter_num, scene_id, summary,
                       extraction, present_char_ids):
    """Update checkpoint state after a scene completes.

    Args:
        state: Current checkpoint state dict (mutated in place).
        chapter_num: Chapter number just completed.
        scene_id: Scene ID just completed (e.g., "2.1").
        summary: AI-generated scene summary string.
        extraction: Dict with 'characters', 'facts', 'commitments' lists.
        present_char_ids: List of character IDs that appeared in the scene.
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
    _merge_story_memory(state, extraction, str(scene_id))


def _merge_story_memory(state, extraction, scene_id):
    """Merge extracted story memory from a scene into checkpoint state.

    Args:
        state: Checkpoint state (mutated).
        extraction: Dict with 'characters', 'facts', 'commitments'.
        scene_id: Scene ID string.
    """
    memory = _sanitize_story_memory(state.get("story_memory", {}))

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

    # Commitments
    for commitment in extraction.get("commitments", []):
        if commitment.strip():
            memory.setdefault("commitments", []).append({
                "scene": scene_id,
                "detail": commitment.strip(),
            })

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
    if not memory or (not memory["characters"] and not memory["facts"] and not memory["commitments"]):
        return {"characters": {}, "facts": [], "commitments": []}

    text_lower = text_to_scan.lower()
    relevant = {"characters": {}, "facts": [], "commitments": []}

    # Check remembered characters
    for char_id, char_data in memory["characters"].items():
        name = char_data.get("name", "")
        if (char_id in text_lower or
                (name and name.lower() in text_lower)):
            relevant["characters"][char_id] = char_data

    # For facts and commitments, include recent ones and keyword-matched
    for fact in memory["facts"][-10:]:  # last 10 facts
        detail = fact.get("detail", "")
        # Include if any word overlap with scene text
        words = set(detail.lower().split())
        scene_words = set(text_lower.split())
        if words & scene_words - {"the", "a", "an", "is", "was", "and", "or"}:
            relevant["facts"].append(fact)

    for commit in memory["commitments"][-10:]:
        detail = commit.get("detail", "")
        words = set(detail.lower().split())
        scene_words = set(text_lower.split())
        if words & scene_words - {"the", "a", "an", "is", "was", "and", "or"}:
            relevant["commitments"].append(commit)

    return relevant


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
